"""Fail closed unless every native artifact matches this tested source commit."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(root: Path, commit: str) -> None:
    expected = {'ThreadDesk-Windows.exe', 'ThreadDesk-macOS.dmg', 'ThreadDesk-macOS-AppleSilicon.dmg'}
    if {p.name for p in root.iterdir()} != {name + suffix for name in expected for suffix in ('', '.sha256', '.build.json')}:
        raise ValueError('Missing or unexpected release files')
    for name in expected:
        path = root / name
        receipt = json.loads((root / (name + '.build.json')).read_text())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksum = (root / (name + '.sha256')).read_text().strip()
        arch = 'arm64' if 'AppleSilicon' in name else ('AMD64' if name.endswith('.exe') else 'x86_64')
        system = 'Windows' if name.endswith('.exe') else 'Darwin'
        if (receipt['source_commit'] != commit or receipt['file'] != name
                or receipt['sha256'] != digest or receipt['bytes'] != path.stat().st_size
                or receipt['architecture'] != arch or receipt['system'] != system
                or checksum != f'{digest}  {name}'):
            raise ValueError('Artifact receipt does not match: ' + name)
    print('All three native downloads match the tested source and checksums.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    verify(args.directory, args.commit)
