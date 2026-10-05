"""Create a source-commit receipt and checksum for one CI build artifact."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
_VERSION = re.compile(r'(?m)^__version__\s*=\s*"([^"]+)"\s*$')


def package_version(root: Path | None = None) -> str:
    """The one product version, read from ``threaddesk.__version__``."""
    text = ((root or ROOT) / "src" / "threaddesk" / "__init__.py").read_text(encoding="utf-8")
    found = _VERSION.findall(text)
    if len(found) != 1 or not found[0].strip():
        raise ValueError("package version missing")
    return found[0]


def source_commit(root: Path | None = None) -> str:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root or ROOT, text=True
    ).strip()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError("source commit missing")
    return commit


def macos_release_version(product_version: str) -> str:
    """Derive Apple's three numeric fields; preserve the full product label separately."""
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:(?:a|b|rc)[0-9]+)?", product_version)
    if match is None:
        raise ValueError("Unsupported product version for macOS bundle")
    return ".".join(str(int(part)) for part in match.groups())


def bundle_settings(root: Path | None = None) -> dict[str, object]:
    """macOS bundle fields for the tree being built. No second version literal."""
    app_version = package_version(root)
    commit = source_commit(root)
    return {
        "version": app_version,
        "macos_version": macos_release_version(app_version),
        "source_commit": commit,
        "info_plist": {
            "NSHighResolutionCapable": True,
            "CFBundleVersion": macos_release_version(app_version),
            "ThreadDeskProductVersion": app_version,
            "ThreadDeskSourceCommit": commit,
        },
    }


def write_macos_info_plist(path: Path, settings: dict[str, object]) -> None:
    """Write the same version fields the spec passes into PyInstaller's BUNDLE."""
    payload = {
        "CFBundleDisplayName": "ThreadDesk",
        "CFBundleName": "ThreadDesk",
        "CFBundleIdentifier": "de.netzwerkpunkt.threaddesk",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": settings["macos_version"],
        "NSHighResolutionCapable": True,
    }
    payload.update(settings["info_plist"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    artifact = args.artifact
    if artifact.is_symlink() or not artifact.is_file() or artifact.suffix not in {".exe", ".dmg"}:
        parser.error("Expected one native application artifact")
    digest = hashlib.sha256()
    with artifact.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    identity = bundle_settings(ROOT)
    result = {
        "application": "ThreadDesk", "version": identity["version"],
        "source_commit": identity["source_commit"],
        "workflow_run": os.environ.get("GITHUB_RUN_ID", "local-build"),
        "file": artifact.name, "bytes": artifact.stat().st_size, "sha256": digest.hexdigest(),
        "system": platform.system(), "architecture": platform.machine(), "python": platform.python_version(),
        "build_tools": {name: version(name) for name in ("pyinstaller", "pywebview")},
        "status": "unpublished release candidate; native user-device acceptance remains separate",
    }
    Path(str(artifact) + ".sha256").write_text(f"{digest.hexdigest()}  {artifact.name}\n", encoding="utf-8")
    Path(str(artifact) + ".build.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
