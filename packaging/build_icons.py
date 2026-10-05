"""Build macOS .icns and Windows .ico from brand/mark.svg."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MARK = ROOT / "brand" / "mark.svg"
ICNS = ROOT / "brand" / "ThreadDesk.icns"
ICO = ROOT / "brand" / "ThreadDesk.ico"

ICONSET_SIZES = (
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
)
ICO_SIZES = ((16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))


def rasterize_mark(dest: Path, size: int = 1024) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["qlmanage", "-t", "-s", str(size), "-o", str(dest), str(MARK)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    produced = dest / f"{MARK.name}.png"
    if not produced.is_file():
        raise RuntimeError("qlmanage hat keine PNG-Vorschau erzeugt.")
    return produced


def build() -> tuple[Path, Path]:
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        source = rasterize_mark(work)
        master = Image.open(source).convert("RGBA")
        iconset = work / "ThreadDesk.iconset"
        iconset.mkdir()
        for edge, name in ICONSET_SIZES:
            master.resize((edge, edge), Image.Resampling.LANCZOS).save(iconset / name)
        subprocess.check_call(["iconutil", "-c", "icns", "-o", str(ICNS), str(iconset)])
        master.save(ICO, format="ICO", sizes=list(ICO_SIZES))
    return ICNS, ICO


if __name__ == "__main__":
    icns, ico = build()
    print(icns)
    print(ico)
