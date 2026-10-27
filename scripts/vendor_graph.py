"""Explicit, integrity-verified maintenance build of offline graph assets.

Normal application startup reads only the committed local artifacts. This
command requires npm/Node solely to rebuild the fixed worker supervisor.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
from pathlib import Path
import subprocess
import tarfile

from vendor_ui import download

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src/threaddesk/ui/static"
PACKAGES = (
    ("sigma", "4.0.3", "package/dist/sigma.min.js", "sigma-4.0.3.min.js"),
    ("graphology", "0.26.0", "package/dist/graphology.umd.min.js", "graphology-0.26.0.min.js"),
)
LICENSES = (("graphology-layout-forceatlas2", "0.10.1"),
            ("graphology-utils", "2.5.2"), ("events", "3.3.0"))


def package(name, version):
    metadata_url = f"https://registry.npmjs.org/{name}/{version}"
    metadata = json.loads(download(metadata_url, 1_000_000))
    if metadata.get("name") != name or metadata.get("version") != version or metadata.get("license") != "MIT":
        raise ValueError("Unexpected graph package identity or license")
    archive = download(metadata["dist"]["tarball"], 20_000_000)
    algorithm, digest = metadata["dist"]["integrity"].split("-", 1)
    if algorithm != "sha512" or not hmac.compare_digest(hashlib.sha512(archive).digest(), base64.b64decode(digest, validate=True)):
        raise ValueError("Graph package checksum mismatch")
    return metadata, archive


def main():
    prepared, records, licenses = {}, [], []
    for name, version, member, filename in (*PACKAGES, *((name, version, None, None) for name, version in LICENSES)):
        metadata, archive = package(name, version)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as contents:
            if member:
                info = contents.getmember(member)
                if not info.isfile() or info.size > 2_000_000:
                    raise ValueError("Unexpected graph script")
                body = contents.extractfile(info).read()
                prepared[filename] = body
            else:
                body = b""
            license_text = None
            for candidate in ("package/LICENSE", "package/LICENSE.txt", "package/LICENSE.md"):
                try:
                    info = contents.getmember(candidate)
                except KeyError:
                    continue
                if not info.isfile() or info.size > 100_000:
                    raise ValueError("Unexpected graph license")
                license_text = contents.extractfile(info).read().decode()
                break
            if license_text is None:
                raise ValueError("Graph package license missing")
        records.append({"package": name, "version": version, "license": "MIT",
                        "tarball": metadata["dist"]["tarball"], "integrity": metadata["dist"]["integrity"],
                        **({"file": filename, "sha256": hashlib.sha256(body).hexdigest()} if filename else {})})
        licenses.append(f"{name} {version}\n\n{license_text.strip()}\n")
    build = ROOT / "scripts/graph-worker"
    subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=build, check=True)
    subprocess.run([str(build / "node_modules/.bin/esbuild"), "entry.js", "--bundle", "--minify",
                    "--format=iife", f"--outfile={DEST / 'forceatlas2-0.10.1.min.js'}"], cwd=build, check=True)
    worker = DEST / "forceatlas2-0.10.1.min.js"
    records.append({"file": worker.name, "sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
                    "build": "scripts/graph-worker/entry.js", "esbuild": "0.25.12",
                    "lock_sha256": hashlib.sha256((build / 'package-lock.json').read_bytes()).hexdigest()})
    for filename, body in prepared.items():
        (DEST / filename).write_bytes(body)
    (DEST / "graph-vendor.json").write_text(json.dumps(records, indent=2) + "\n")
    (DEST / "GRAPH-VENDOR-LICENSES.txt").write_text("\n\n".join(licenses))
    print(json.dumps({"artifacts": [record for record in records if record.get('file')]}))


if __name__ == "__main__":
    main()
