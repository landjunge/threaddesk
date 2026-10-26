"""Generate package identity from the exact checkout at build time."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def write_build_info(root: Path) -> dict:
    tree = ast.parse((root / "src/threaddesk/__init__.py").read_text(encoding="utf-8"))
    version = next(
        ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    )

    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

    identity = {
        "version": version,
        "source_commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain=v1", "--untracked-files=normal")),
        "build_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    }
    target = root / "src/threaddesk/_build_info.json"
    target.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    return identity


if __name__ == "__main__":
    print(json.dumps(write_build_info(Path(__file__).resolve().parents[1])))
