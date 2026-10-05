import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'scripts/verify_release.py'
spec = importlib.util.spec_from_file_location('verify_release', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def artifacts(root):
    for name in ('ThreadDesk-Windows.exe', 'ThreadDesk-macOS.dmg', 'ThreadDesk-macOS-AppleSilicon.dmg'):
        body = ('synthetic-' + name).encode()
        digest = hashlib.sha256(body).hexdigest()
        (root / name).write_bytes(body)
        (root / (name + '.sha256')).write_text(f'{digest}  {name}\n')
        (root / (name + '.build.json')).write_text(json.dumps({
            'version': '0.1.1rc1',
            'source_commit': 'tested-commit', 'file': name, 'bytes': len(body), 'sha256': digest,
            'system': 'Windows' if name.endswith('.exe') else 'Darwin',
            'architecture': 'arm64' if 'AppleSilicon' in name else ('AMD64' if name.endswith('.exe') else 'x86_64')}))


def test_release_matches_tested_commit_and_all_platforms(tmp_path):
    artifacts(tmp_path)
    module.verify(tmp_path, 'tested-commit')


@pytest.mark.parametrize('damage', ['commit', 'bytes', 'missing', 'architecture', 'version'])
def test_release_rejects_wrong_commit_damaged_or_missing_download(tmp_path, damage):
    artifacts(tmp_path)
    name = 'ThreadDesk-macOS.dmg'
    if damage == 'bytes':
        (tmp_path / name).write_bytes(b'damaged')
    elif damage == 'missing':
        (tmp_path / name).unlink()
    else:
        receipt = tmp_path / (name + '.build.json')
        data = json.loads(receipt.read_text())
        if damage == 'commit':
            data['source_commit'] = 'wrong'
        elif damage == 'version':
            data['version'] = ''
        else:
            data['architecture'] = 'wrong'
        receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        module.verify(tmp_path, 'tested-commit')
