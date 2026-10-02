"""Create a source-commit receipt and checksum for one CI build artifact."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess


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
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result = {
        "application": "ThreadDesk", "version": version("threaddesk"),
        "source_commit": commit, "workflow_run": os.environ.get("GITHUB_RUN_ID", "local-build"),
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
