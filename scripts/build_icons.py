"""Derive native icons from the approved mark; do not redesign the brand."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path


def main() -> None:
    import cairosvg
    from PIL import Image

    root = Path(__file__).resolve().parents[1]
    source = (root / "brand/mark.svg").read_bytes()
    output = root / "build/icons"
    output.mkdir(parents=True, exist_ok=True)
    png = cairosvg.svg2png(bytestring=source, output_width=1024, output_height=1024)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    assert image.size == (1024, 1024) and image.getpixel((0, 0))[3] == 0
    image.save(output / "icon.png")
    image.save(output / "icon.ico", format="ICO", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    image.save(output / "icon.icns", format="ICNS")
    evidence = {"source": "brand/mark.svg", "source_sha256": hashlib.sha256(source).hexdigest()}
    for name in ("icon.png", "icon.ico", "icon.icns"):
        assert (output / name).stat().st_size > 0
        evidence[name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
    (output / "icons.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("Native icons generated from brand/mark.svg")


if __name__ == "__main__":
    main()
