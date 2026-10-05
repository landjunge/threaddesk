from pathlib import Path
import importlib.util
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path.cwd()
_provenance_path = ROOT / "scripts" / "package_provenance.py"
_provenance_spec = importlib.util.spec_from_file_location(
    "thread_desk_package_provenance", _provenance_path
)
_provenance = importlib.util.module_from_spec(_provenance_spec)
_provenance_spec.loader.exec_module(_provenance)
_bundle = _provenance.bundle_settings(ROOT)
datas = collect_data_files("threaddesk")
hiddenimports = collect_submodules("uvicorn") + collect_submodules("webview")
icons = ROOT / "build" / "icons"
icon = icons / ("icon.icns" if sys.platform == "darwin" else "icon.ico")
if not icon.is_file():
    raise RuntimeError("Generate the application icons first: python scripts/build_icons.py")

# Include application resources only, never the repository or a user workspace.
resource_root = (ROOT / "src" / "threaddesk").resolve()
for source, destination in datas:
    path = Path(source)
    if path.is_symlink() or not path.resolve().is_relative_to(resource_root):
        raise RuntimeError("Unexpected resource outside the application package")
    if path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".tdbundle", ".env"}:
        raise RuntimeError("Runtime data is not a distributable application resource")

a = Analysis(
    [str(ROOT / "packaging" / "desktop_entry.py")],
    pathex=[str(ROOT / "src")], binaries=[], datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ThreadDesk", console=False)
    app_files = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name="ThreadDesk")
    app = BUNDLE(
        app_files, name="ThreadDesk.app", icon=str(icon),
        bundle_identifier="de.netzwerkpunkt.threaddesk",
        version=_bundle["macos_version"],
        info_plist=_bundle["info_plist"],
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, name="ThreadDesk", icon=str(icon),
        console=False, strip=False, upx=True,
    )
