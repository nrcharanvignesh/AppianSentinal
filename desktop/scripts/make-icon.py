"""Generate the Windows app icon.

electron-builder embeds build/icon.ico via rcedit (win.signAndEditExecutable).
Without this file the installed app ships the default Electron atom icon.

    python desktop/scripts/make-icon.py

ponytail: flat geometric placeholder; replace build/icon.ico with real brand
artwork when design provides it - nothing else needs to change.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "build" / "icon.ico"

# Rendered at 1024 then downsampled, so small sizes stay clean.
CANVAS = 1024
SIZES = [16, 24, 32, 48, 64, 128, 256]

BACKGROUND = (17, 24, 39, 255)
SHIELD = (99, 179, 237, 255)
NOTCH = (17, 24, 39, 255)


def build_master() -> Image.Image:
    """Draw a dark rounded square carrying a light sentinel shield."""
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, CANVAS - 1, CANVAS - 1),
        radius=int(CANVAS * 0.22),
        fill=BACKGROUND,
    )

    # Shield: straight shoulders, tapered point. Readable down to 16px.
    left, right = CANVAS * 0.26, CANVAS * 0.74
    top, waist, tip = CANVAS * 0.22, CANVAS * 0.56, CANVAS * 0.80
    draw.polygon(
        [
            (left, top),
            (right, top),
            (right, waist),
            (CANVAS * 0.50, tip),
            (left, waist),
        ],
        fill=SHIELD,
    )

    # Centre notch keeps the mark from reading as a plain blob.
    draw.polygon(
        [
            (CANVAS * 0.50, CANVAS * 0.34),
            (CANVAS * 0.62, CANVAS * 0.46),
            (CANVAS * 0.50, CANVAS * 0.64),
            (CANVAS * 0.38, CANVAS * 0.46),
        ],
        fill=NOTCH,
    )
    return image


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    master = build_master()
    master.save(OUTPUT_PATH, format="ICO", sizes=[(size, size) for size in SIZES])
    print(f"[SUCCESS] wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
