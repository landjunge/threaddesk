"""Explicit maintenance command: vendor two fixed UI dependencies.

Downloads package bytes but never executes install scripts. Normal startup
must not call this script or access the registry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
from pathlib import Path
import tarfile
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src/threaddesk/ui/static"
PACKAGES = (
    ("htmx.org", "2.0.4", "package/dist/htmx.min.js", "htmx.min.js"),
    ("alpinejs", "3.14.8", "package/dist/cdn.min.js", "alpine.min.js"),
)
# This exact release's npm archive omits its license. Keep the upstream text.
# https://github.com/alpinejs/alpine/blob/v3.14.8/LICENSE.md
# Upstream blob: c3cc2ddc7574d9a9ccc7004236e2e174a97e60d2
ALPINE_LICENSE = '''# MIT License

Copyright © 2019-2021 Caleb Porzio and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''


def download(url: str, maximum: int) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org" or parsed.username:
        raise ValueError("Unexpected registry URL")
    with urlopen(url, timeout=30) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Package response is too large")
    return data


def main() -> None:
    prepared, records, licenses = {}, [], []
    for name, version, member, filename in PACKAGES:
        metadata_url = f"https://registry.npmjs.org/{name}/{version}"
        metadata = json.loads(download(metadata_url, 1_000_000))
        if metadata.get("name") != name or metadata.get("version") != version:
            raise ValueError("Package identity mismatch")
        distribution = metadata["dist"]
        integrity = distribution["integrity"]
        algorithm, digest = integrity.split("-", 1)
        if algorithm != "sha512":
            raise ValueError("Expected SHA-512 package integrity")
        archive = download(distribution["tarball"], 20_000_000)
        if not hmac.compare_digest(hashlib.sha512(archive).digest(), base64.b64decode(digest, validate=True)):
            raise ValueError("Package integrity mismatch")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            source = package.getmember(member)
            if not source.isfile() or source.size > 2_000_000:
                raise ValueError("Invalid script member")
            body = package.extractfile(source).read()
            body.decode("utf-8")
            license_text = None
            for candidate in ("package/LICENSE", "package/LICENSE.txt", "package/LICENSE.md", "package/COPYING"):
                try:
                    item = package.getmember(candidate)
                except KeyError:
                    continue
                if not item.isfile() or item.size > 100_000:
                    raise ValueError("Invalid license member")
                license_text = package.extractfile(item).read().decode("utf-8")
                break
            if license_text is None and name == "alpinejs" and version == "3.14.8" and metadata.get("license") == "MIT":
                license_text = ALPINE_LICENSE
            if license_text is None:
                raise ValueError(f"License missing for {name}")
        prepared[filename] = body
        records.append({"package": name, "version": version, "metadata": metadata_url,
                        "tarball": distribution["tarball"], "integrity": integrity,
                        "file": filename, "sha256": hashlib.sha256(body).hexdigest()})
        licenses.append(f"{name} {version}\n{metadata_url}\n\n{license_text.strip()}\n")
    DEST.mkdir(parents=True, exist_ok=True)
    for filename, body in prepared.items():
        (DEST / filename).write_bytes(body)
    (DEST / "ui-vendor.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (DEST / "UI-VENDOR-LICENSES.txt").write_text("\n\n".join(licenses), encoding="utf-8")
    for record in records:
        print(record["file"], record["sha256"])


if __name__ == "__main__":
    main()
