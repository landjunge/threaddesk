"""PyInstaller server-only bundle; must run from the ThreadDesk project root."""
from pathlib import Path
import subprocess
import sys
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path.cwd()
PACKAGE = ROOT / "src" / "threaddesk"
if not PACKAGE.is_dir():
    raise RuntimeError("Run this build with the ThreadDesk repository as cwd")
subprocess.run([sys.executable, str(ROOT / "scripts/write_build_info.py")], check=True)
datas = []
for item in PACKAGE.rglob("*"):
    if item.is_file() and not item.is_symlink() and item.suffix not in {".py", ".pyc", ".pyo"}:
        if item.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".tdbundle", ".env"}:
            raise RuntimeError("Unexpected runtime data in package: " + str(item))
        datas.append((str(item), str(item.parent.relative_to(ROOT / "src"))))

a = Analysis(
    [str(ROOT / "packaging" / "tauri" / "backend" / "server.py")],
    pathex=[str(ROOT / "src"), str(ROOT / "packaging" / "tauri" / "backend")],
    binaries=[], datas=datas,
    hiddenimports=collect_submodules("uvicorn"),
    hookspath=[], runtime_hooks=[], excludes=["webview"], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name="ThreadDeskServer",
    console=True, strip=False, upx=False, target_arch="x86_64",
)

