"""Generate the synthetic UI screenshot used by tests and manual demos."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "sample_ui.png"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def make_sample(path: Path = OUT) -> Path:
    width, height = 1280, 800
    image = Image.new("RGB", (width, height), (247, 248, 250))
    draw = ImageDraw.Draw(image)

    # Header bar
    draw.rectangle([0, 0, width, 88], fill=(30, 58, 138))
    draw.text((48, 26), "Settings", font=_font(30, bold=True), fill=(255, 255, 255))

    # Sidebar
    draw.rectangle([0, 88, 280, height], fill=(241, 243, 247))
    for index, label in enumerate(["General", "Appearance", "Notifications", "Privacy"]):
        y = 130 + index * 52
        draw.text((40, y), label, font=_font(20), fill=(54, 57, 63))
        if index == 1:
            draw.rectangle([20, y - 8, 260, y + 30], fill=(219, 228, 255))
            draw.text((40, y), label, font=_font(20, bold=True), fill=(30, 58, 138))

    # Content card
    draw.rounded_rectangle([330, 140, 1210, 470], radius=16, fill=(255, 255, 255), outline=(229, 231, 235), width=2)
    draw.text((370, 180), "Appearance", font=_font(26, bold=True), fill=(24, 24, 27))
    draw.text((370, 228), "Choose how the application looks on this device.", font=_font(18), fill=(82, 82, 91))

    # Theme options
    for index, label in enumerate(["Light", "Dark", "System"]):
        x = 370 + index * 210
        selected = index == 1
        draw.rounded_rectangle(
            [x, 290, x + 180, 400],
            radius=12,
            fill=(30, 41, 59) if selected else (249, 250, 251),
            outline=(37, 99, 235) if selected else (209, 213, 219),
            width=3 if selected else 2,
        )
        draw.text(
            (x + 24, 344),
            label,
            font=_font(20, bold=selected),
            fill=(255, 255, 255) if selected else (55, 65, 81),
        )

    # Buttons
    draw.rounded_rectangle([330, 600, 490, 652], radius=10, fill=(37, 99, 235))
    draw.text((376, 614), "Save", font=_font(19, bold=True), fill=(255, 255, 255))
    draw.rounded_rectangle([510, 600, 690, 652], radius=10, fill=(255, 255, 255), outline=(209, 213, 219), width=2)
    draw.text((560, 614), "Cancel", font=_font(19), fill=(55, 65, 81))

    # Status label
    draw.ellipse([330, 700, 348, 718], fill=(22, 163, 74))
    draw.text((360, 696), "All changes saved", font=_font(17), fill=(75, 85, 99))

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


if __name__ == "__main__":
    print(make_sample())
