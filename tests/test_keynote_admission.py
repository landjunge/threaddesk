"""Conditional Keynote bytes, private-key rejection and pre-CAS publication."""
from copy import deepcopy
import base64
import hashlib
import io
import plistlib
import stat
import zipfile

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.file_formats import describe
from threaddesk.services.file_formats.keynote import inspect_keynote, KeynoteError, require_validated_keynote
from threaddesk.services.file_formats.keynote_wire import objects
from threaddesk.services.library_import import LibraryImporter, LibraryImportError, validate_received_filename
from threaddesk.services.library_files import LibraryFileService
from threaddesk.services.library_receive import LibraryReceiver
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


def vint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def field(number, value):
    return vint(number << 3 | (2 if isinstance(value, bytes) else 0)) + (
        vint(len(value)) + value if isinstance(value, bytes) else vint(value))


def iwa(*, keynote=True):
    # Minimal structural fixtures, deliberately not claimed as renderable decks.
    payload = field(2, field(1, 2)) + field(3, field(1, 1)) if keynote else field(15, field(1, 1))
    header = field(1, 1) + field(2, field(1, 1) + field(3, len(payload)))
    plain = vint(len(header)) + header + payload
    length = len(plain)
    literal = bytes([(length - 1) << 2]) if length < 61 else bytes([60 << 2, length - 1])
    compressed = vint(length) + literal + plain
    return b'\x00' + len(compressed).to_bytes(3, 'little') + compressed


def deck(*, nested=False, keynote=True, extra=None, fake_iwa=False, properties=None):
    members = {'Index/Document.iwa':b'not an iwa' if fake_iwa else iwa(keynote=keynote),
               'Index/Slide-1.iwa':iwa(),
               'Metadata/Properties.plist':properties if properties is not None else plistlib.dumps({'fileFormatVersion':'14.4.1',
                   'documentUUID':'42541D1C-A9DC-49A9-814C-7FC1338850A2'}),
               'Metadata/DocumentIdentifier':b'42541D1C-A9DC-49A9-814C-7FC1338850A2'}
    if nested:
        container = io.BytesIO()
        with zipfile.ZipFile(container, 'w') as archive:
            for name in list(members):
                if name.startswith('Index/'):
                    archive.writestr(name, members.pop(name))
        members['Index.zip'] = container.getvalue()
        members = {'Presentation.key/' + name:value for name, value in members.items()}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, value in members.items():
            archive.writestr(name, value)
        if extra:
            name, value, mode = extra
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, value)
    return output.getvalue()


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def core(request, tmp_path):
    return ThreadService(request.param(tmp_path / 'workspace'))


@pytest.mark.parametrize('nested', [False, True])
def test_real_wire_identity_is_required_before_import_and_preview(core, tmp_path, nested):
    source = tmp_path / 'files'
    source.mkdir()
    original = source / 'Presentation.key'
    payload = deck(nested=nested)
    original.write_bytes(payload)
    proof = inspect_keynote(original)
    assert proof['identity'] == 'keynote_iwa_zip_v1' and proof['sha256'] == hashlib.sha256(payload).hexdigest()
    importer = LibraryImporter(core.store)
    result = importer.import_tree(source)
    assert result['stored'] == 1 and not result['failed']
    record = importer._read_records()[0]
    assert record['content_validation'] == proof
    preview = LibraryFileService(core.store).preview(record['id'])
    assert preview['kind'] == 'metadata' and preview['can_open']
    assert preview['formats']['index'] is False and preview['formats']['preview'] is False
    assert original.read_bytes() == payload


@pytest.mark.parametrize('payload', [b'-----BEGIN PRIVATE KEY-----\nnot real key material', b'unknown bytes', deck(fake_iwa=True), deck(keynote=False),
    deck(extra=('../outside.txt', b'unsafe', stat.S_IFREG)), deck(extra=('Data/private.pem', b'not real', stat.S_IFREG)),
    deck(extra=('Data/link', b'/outside', stat.S_IFLNK))])
def test_key_suffix_never_bypasses_private_key_or_archive_guards(core, tmp_path, monkeypatch, payload):
    source = tmp_path / 'files'
    source.mkdir()
    (source / 'Unknown.key').write_bytes(payload)
    importer = LibraryImporter(core.store)
    calls = []
    monkeypatch.setattr(importer, '_publish_blob', lambda *args: calls.append(args))
    result = importer.import_tree(source)
    assert result['failed'] == 1 and result['stored'] == 0
    assert not calls and not importer._read_records()
    assert not list(importer.blobs.glob('*'))


def test_snapshot_detects_source_swap_between_hash_and_publication(core, tmp_path, monkeypatch):
    source = tmp_path / 'files'
    source.mkdir()
    original = source / 'Presentation.key'
    original.write_bytes(deck())
    importer = LibraryImporter(core.store)
    stored_match = importer._stored_match

    def change(relative, digest, size):
        result = stored_match(relative, digest, size)
        original.write_bytes(b'-----BEGIN PRIVATE KEY-----\nnot real')
        return result

    monkeypatch.setattr(importer, '_stored_match', change)
    result = importer.import_tree(source)
    assert result['failed'] == 1 and result['results'][0]['error'] == 'copy_checksum'
    assert not importer._read_records() and not list(importer.blobs.glob('*'))


@pytest.mark.parametrize('valid', [False, True])
def test_receiver_checks_exact_key_bytes_before_cas_and_can_resume(core, valid):
    tid = core.create('Receiver').id
    body = deck() if valid else b'-----BEGIN PRIVATE KEY-----\nnot real'
    receiver = LibraryReceiver(core.store)
    args = {'action':'begin', 'transfer_id':'keynote-upload', 'filename':'Presentation.key',
            'thread_id':tid, 'size':len(body), 'sha256':hashlib.sha256(body).hexdigest()}
    receiver.call(args)
    receiver.call({'action':'append', 'transfer_id':'keynote-upload', 'offset':0, 'data_base64':base64.b64encode(body).decode()})
    restarted = LibraryReceiver(core.store)
    if valid:
        receipt = restarted.call({'action':'commit', 'transfer_id':'keynote-upload'})
        assert receipt['state'] == 'committed'
        assert LibraryImporter(core.store)._read_records()[0]['content_validation']['identity'] == 'keynote_iwa_zip_v1'
        assert restarted.call({'action':'commit', 'transfer_id':'keynote-upload'}) == receipt
    else:
        with pytest.raises(LibraryImportError):
            restarted.call({'action':'commit', 'transfer_id':'keynote-upload'})
        assert restarted.call({'action':'status', 'transfer_id':'keynote-upload'})['state'] == 'receiving'
        assert not list(restarted.importer.blobs.glob('*'))
        assert not restarted.importer._read_records()


def test_name_capabilities_and_open_are_conditionally_bound_to_bytes(core, tmp_path):
    for filename in ('credentials.key', 'id_rsa.key', 'secret.key', 'private.pem'):
        with pytest.raises(LibraryImportError):
            validate_received_filename(filename)
    validate_received_filename('Presentation.key')  # Name alone is not admission.
    capabilities = describe('Presentation.key')
    assert capabilities['content_validation_required'] and not capabilities['external_open']
    assert not capabilities['directory_package_supported']
    source = tmp_path / 'files'
    source.mkdir()
    original = source / 'Presentation.key'
    original.write_bytes(deck())
    importer = LibraryImporter(core.store)
    importer.import_tree(source)
    record = importer._read_records()[0]
    assert require_validated_keynote(record, original)['sha256'] == record['sha256']
    wrong = deepcopy(record)
    wrong['sha256'] = '0' * 64
    with pytest.raises(ManagementError) as invalid:
        require_validated_keynote(wrong, original)
    assert invalid.value.code == 'keynote_validation_required'
    renamed = {**record, 'content_validation':None}
    from threaddesk.services.library_files.preview import format_info
    assert format_info(renamed)['external_open'] is False


def test_iwa_limits_malformed_copies_and_zip_directory_budget(tmp_path, monkeypatch):
    from threaddesk.services.file_formats import keynote
    path = tmp_path / 'Presentation.key'
    path.write_bytes(deck())
    monkeypatch.setattr(keynote, 'MAX_ENTRIES', 2)
    with pytest.raises(KeynoteError) as limited:
        inspect_keynote(path)
    assert limited.value.code == 'keynote_limit'
    oversized = vint(17 * 1024 * 1024) + b'\x00A'
    with pytest.raises(KeynoteError):
        list(objects(b'\x00' + len(oversized).to_bytes(3, 'little') + oversized))


def test_directory_package_is_one_explicit_unsupported_item_without_fragment_import(core, tmp_path):
    source = tmp_path / 'files'
    package = source / 'Presentation.key'
    (package / 'Index').mkdir(parents=True)
    inner = package / 'Index' / 'Document.iwa'
    inner.write_bytes(iwa())
    importer = LibraryImporter(core.store)
    result = importer.import_tree(source)
    assert result['stored'] == 0 and result['failed'] == 1
    assert result['results'][0]['relative_path'] == 'Presentation.key'
    assert result['results'][0]['error'] == 'keynote_directory_package_unsupported'
    assert not importer._read_records() and inner.read_bytes() == iwa()
    from threaddesk.services.library_watch.scan import snapshot
    state = snapshot(source)
    assert state['files'] == ['Presentation.key']
    assert state['warnings'][0]['error'] == 'keynote_directory_package_unsupported'
    with pytest.raises(LibraryImportError) as unsupported:
        importer.import_tree(package)
    assert unsupported.value.code == 'keynote_directory_package_unsupported'


def test_false_central_directory_count_is_rejected_before_zip_allocations(tmp_path, monkeypatch):
    from threaddesk.services.file_formats import keynote
    body = bytearray(deck())
    offset = body.rfind(b'PK\x05\x06')
    body[offset + 8:offset + 12] = b'\x01\x00\x01\x00'
    path = tmp_path / 'Presentation.key'
    path.write_bytes(body)
    called = []
    monkeypatch.setattr(keynote.zipfile, 'ZipFile', lambda *a, **k: called.append(True))
    with pytest.raises(KeynoteError):
        inspect_keynote(path)
    assert not called


@pytest.mark.parametrize('properties', [b'<plist><dict><broken', plistlib.dumps({'fileFormatVersion':'14.4.1', 'documentUUID':3})])
def test_bad_metadata_is_isolated_and_does_not_block_neighbor(core, tmp_path, properties):
    source = tmp_path / 'files'
    source.mkdir()
    (source / 'Broken.key').write_bytes(deck(properties=properties))
    (source / 'Neighbor.txt').write_text('Normal content still imports')
    result = LibraryImporter(core.store).import_tree(source)
    assert result['stored'] == 1 and result['failed'] == 1
    rows = LibraryImporter(core.store)._read_records()
    assert len(rows) == 1 and rows[0]['filename'] == 'Neighbor.txt'
