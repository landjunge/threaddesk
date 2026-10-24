"""Targeted discovery authority, completeness and original-preservation checks."""
from pathlib import Path
import os

from threaddesk.server_sync.discovery import SourceFile, discover_project


def write(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    return path


def test_full_tree_new_files_and_stable_exact_external_file_grant(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    write(root, 'readme.md', '# Project')
    external = write(tmp_path, 'documents/context.txt', 'original externally referenced context')
    unrelated = write(tmp_path, 'documents/unrelated.txt', 'must not be inventoried')
    first = discover_project(root, local_references=[str(external)])
    assert first.issues == []
    assert len(first.files) == 2
    mapped = [name for name in first.sources if name.startswith('_external/')]
    assert len(mapped) == 1 and first.sources[mapped[0]].read_bytes() == external.read_bytes()
    assert all(item.path != unrelated for item in first.sources.values())
    write(root, 'later/new.txt', 'newly added')
    second = discover_project(root, local_references=[str(external)])
    assert mapped[0] in second.sources and 'later/new.txt' in second.sources
    assert external.read_text() == 'original externally referenced context'
    assert str(tmp_path) not in str(first.files)


def test_server_references_cannot_authorize_external_reads_and_symlink_fifo_block(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    root.mkdir()
    external = write(tmp_path, 'outside.txt', 'private external bytes')
    write(root, 'note.txt', 'project')
    (root / 'linked.txt').symlink_to(external)
    os.mkfifo(root / 'pipe')
    write(root, '.env', 'TOKEN=must-not-transfer')
    reads = []
    original = SourceFile.read_bytes

    def recording_read(source):
        reads.append(source.path)
        return original(source)

    monkeypatch.setattr(SourceFile, 'read_bytes', recording_read)
    plan = discover_project(root, server_references=[str(external)])
    assert len(plan.files) == 1 and plan.files[0]['path'] == 'note.txt'
    assert len(plan.issues) >= 3
    assert external not in reads
    assert external.read_text() == 'private external bytes'


def test_static_python_js_html_css_and_manifests_resolve_inside_tree(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    write(root, 'main.py', 'from pathlib import Path\nimport utils\nDATA = (Path(__file__).parent / "data.json").read_text()\n')
    write(root, 'utils.py', 'VALUE = 1\n')
    write(root, 'data.json', '{}')
    write(root, 'main.js', 'import {x} from "./part";\nimport fs from "node:fs";\nconst a = require("./lib");\nnew URL("./image.png", import.meta.url);\n')
    write(root, 'part.ts', 'export const x = 1;')
    write(root, 'lib/index.js', 'module.exports = {};')
    write(root, 'image.png', 'synthetic asset')
    write(root, 'index.html', '<link rel="stylesheet" href="/style.css"><img src="image.png"><script src="main.js"></script><style>body{background:url(/image.png)}</style><script>import "./part.ts";</script>')
    write(root, 'style.css', 'body { background: url("image.png") }')
    write(root, 'README.md', '![asset](image.png) [Docs](index.html) [online link](https://example.com)')
    write(root, 'package.json', '{"main":"main.js","files":["lib/*","image.png"]}')
    write(root, 'site.webmanifest', '{"icons":[{"src":"image.png"}],"start_url":"index.html"}')
    plan = discover_project(root)
    assert plan.issues == []
    assert len(plan.files) == 12
    assert plan.limitations


def test_dynamic_missing_remote_and_unprovisioned_dependencies_fail_closed(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    write(root, 'main.py', 'import unknown_package\nopen(configured_path).read()\n__import__(chosen_module)\n')
    write(root, 'main.js', 'import "./missing";\nimport(runtimeName);\nfetch(dynamicUrl);\n')
    write(root, 'index.html', '<img src="https://example.com/image.png">')
    plan = discover_project(root)
    assert any('Python import' in issue for issue in plan.issues)
    assert any('dynamic' in issue for issue in plan.issues)
    assert any('Missing' in issue for issue in plan.issues)
    assert any('Remote dependency' in issue for issue in plan.issues)
    write(root, 'inline.html', '<style>body{background:url(missing-inline.png)}</style><script>import(dynamicModule)</script>')
    inline = discover_project(root)
    assert any(issue.startswith('inline.html:') and 'Missing' in issue for issue in inline.issues)
    assert any(issue.startswith('inline.html:') and 'dynamic' in issue for issue in inline.issues)


def test_granted_file_does_not_authorize_siblings_but_explicit_root_does(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    external = write(tmp_path, 'documents/context.md', '[Required data](data.txt)')
    other = write(tmp_path, 'documents/data.txt', 'needed')
    limited = discover_project(root, local_references=[external])
    assert any('unapproved dependency' in issue for issue in limited.issues)
    assert all(source.path != other for source in limited.sources.values())
    complete = discover_project(root, approved_roots={'documents': external.parent})
    assert complete.issues == []
    assert {source.path for source in complete.sources.values()} == {external, other}
    # A server's logical external path can refer to a pre-existing grant only.
    logical = next(name for name, source in complete.sources.items() if source.path == other)
    again = discover_project(root, approved_roots={'documents': external.parent}, server_references=[logical])
    assert again.issues == []


def test_vcs_and_case_collisions_are_reported_without_unsafe_manifest(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    write(root, '.git/config', 'private VCS data')
    write(root, 'A/first.txt', 'one')
    # On case-insensitive macOS, NFC/case aliases may refer to the same directory;
    # use composed/decomposed filenames only when filesystem supports distinction.
    write(root, 'safe.txt', 'public')
    plan = discover_project(root, server_references=['.git/config'])
    assert not any('.git' in name for name in plan.sources)
    assert plan.issues
    # Source module names are not credential containers; real key paths stay blocked.
    write(root, 'secrets.py', 'def public_function(): return 1')
    source = discover_project(root)
    assert source.issues == [] and 'secrets.py' in source.sources


def test_explicit_grants_never_follow_symlinks_or_key_directories(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    data = write(tmp_path, 'external/data.txt', 'context')
    (tmp_path / 'shortcut').symlink_to(data.parent, target_is_directory=True)
    forbidden = write(tmp_path, '.ssh/context.txt', 'private key folder')
    plan = discover_project(root, local_references=[tmp_path / 'shortcut/data.txt', forbidden])
    assert plan.files == [] and len(plan.issues) >= 1
    assert data.read_text() == 'context' and forbidden.read_text() == 'private key folder'


def test_literal_percent_paths_cannot_grant_decoded_private_file(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    decoded_private = write(tmp_path, 'private.txt', 'outside private bytes')
    literal = write(root, '%2e%2e/private.txt', 'literal project bytes')
    external_literal = write(tmp_path, 'documents/report%20final.txt', 'literal percent filename')
    decoded_space = write(tmp_path, 'documents/report final.txt', 'different unapproved file')
    punctuation = write(tmp_path, 'documents/query?tag#one.txt', 'literal punctuation filename')
    truncated = write(tmp_path, 'documents/query', 'unapproved URL-parsed alias')
    plan = discover_project(root, local_references=['%2e%2e/private.txt', str(external_literal), str(punctuation)])
    assert plan.issues == []
    paths = {source.path for source in plan.sources.values()}
    assert literal in paths and external_literal in paths and punctuation in paths
    assert decoded_private not in paths and decoded_space not in paths and truncated not in paths
    assert not any(source.read_bytes() in {b'outside private bytes', b'different unapproved file'} for source in plan.sources.values())
    # Without an existing literal mapping, encoded traversal never becomes a grant.
    empty = tmp_path / 'empty-project'
    empty.mkdir()
    rejected = discover_project(empty, local_references=['%2e%2e/private.txt'])
    assert rejected.files == [] and rejected.issues
    assert decoded_private.read_text() == 'outside private bytes'


def test_file_uris_and_html_asset_encoding_work_without_server_traversal_aliases(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    write(root, 'index.html', '<img src="image%20one.png">')
    write(root, 'image one.png', 'project image')
    external = write(tmp_path, 'documents/context one.txt', 'explicit file URI context')
    safe = discover_project(root, local_references=[external.as_uri()])
    assert safe.issues == []
    assert external in {source.path for source in safe.sources.values()}
    # An encoded alias cannot point at an already authorized outside file through
    # a server reference. It must use its actual, existing portable mapping.
    blocked = discover_project(root, local_references=[external.as_uri()],
                               server_references=['%2e%2e/documents/context%20one.txt'])
    assert any('Encoded traversal' in issue for issue in blocked.issues)
    assert len(blocked.files) == len(safe.files)
    write(root, 'nested/page.html', '<img src="%252e%252e/image%20one.png">')
    assert any('Encoded traversal' in issue for issue in discover_project(root).issues)


def test_exact_file_capacity_allows_filtered_entries_directories_and_duplicate_grants(tmp_path,monkeypatch):
    from threaddesk.server_sync import discovery
    monkeypatch.setattr(discovery,'MAX_FILES',4)
    root=tmp_path/'project';root.mkdir()
    first=write(root,'one.txt','one')
    write(root,'two.txt','two')
    write(root,'nested/three.txt','three')
    write(root,'nested/four.txt','four')
    (root/'empty').mkdir()
    write(root,'.git/config','ignored VCS')
    write(root,'.threaddesk-sync-conflicts/remote/old.copy','ignored recovery')
    write(root,'.td-sync-'+'a'*32,'ignored unpublished download')
    exact=discover_project(root,local_references=[first])
    assert len(exact.files)==4
    assert exact.issues==[]
    assert {f['path'] for f in exact.files}=={'one.txt','two.txt','nested/three.txt','nested/four.txt'}
    write(root,'additional.txt','one genuine file beyond capacity')
    overflow=discover_project(root,local_references=[first])
    assert len(overflow.files)==4
    assert any('exceeds inventory file limit' in issue for issue in overflow.issues)
