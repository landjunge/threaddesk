from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent.parent
datas = collect_data_files("threaddesk")
hiddenimports = collect_submodules("uvicorn") + collect_submodules("webview")

a = Analysis(
    [str(ROOT / "packaging" / "desktop_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name="ThreadDesk", console=False,
    )
    app_files = COLLECT(
        exe, a.binaries, a.datas, strip=False, upx=True, name="ThreadDesk",
    )
    app = BUNDLE(
        app_files,
        name="ThreadDesk.app",
        bundle_identifier="de.netzwerkpunkt.threaddesk",
        info_plist={"NSHighResolutionCapable": True},
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas,
        name="ThreadDesk", console=False, strip=False, upx=True,
    )
