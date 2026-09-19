"""Generate the Windows app icon from the supplied brand artwork.

electron-builder embeds build/icon.ico via rcedit (win.signAndEditExecutable).
Without this file the installed app ships the default Electron atom icon.

    python desktop/scripts/make-icon.py

"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

INPUT_PATH = Path(__file__).resolve().parents[2] / "icon.png"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "build" / "icon.ico"

SIZES = [16, 24, 32, 48, 64, 128, 256]

def build_master() -> Image.Image:
    """Load the square source used by Electron and the rendered workbench."""
    if not INPUT_PATH.is_file():
        raise FileNotFoundError(f"brand icon is missing: {INPUT_PATH}")
    with Image.open(INPUT_PATH) as source:
        image = source.convert("RGBA")
    if image.width != image.height:
        raise ValueError("brand icon must be square")
    return image


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    master = build_master()
    master.save(OUTPUT_PATH, format="ICO", sizes=[(size, size) for size in SIZES])
    print(f"[SUCCESS] wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
