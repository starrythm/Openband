"""Build 0–100% ring assets and a sample 212 × 520 layout preview."""
from math import cos, radians, sin
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
RING_DIR = ROOT / "watch/src/common/quota-rings"
SIZE = 120
SCALE = 4


def render_ring(percent):
    center = SIZE * SCALE / 2
    radius = 53.5 * SCALE
    weight = 8.5 * SCALE
    image = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE))
    draw = ImageDraw.Draw(image)
    outer = radius + weight / 2
    box = (center - outer, center - outer, center + outer, center + outer)
    draw.ellipse(box, fill="#08160e", outline="#1b3728", width=round(weight))
    if percent:
        sweep = 360 * percent / 100
        mask = Image.new("L", image.size)
        arc = ImageDraw.Draw(mask)
        arc.arc(box, start=-90, end=sweep - 90, fill=255, width=round(weight))
        if percent < 100:
            for degrees in (0, sweep):
                polar = radians(degrees - 90)
                x = center + cos(polar) * radius
                y = center + sin(polar) * radius
                cap = weight / 2
                arc.ellipse((x - cap, y - cap, x + cap, y + cap), fill=255)
        gradient = Image.linear_gradient("L").resize(image.size, Image.Resampling.BILINEAR)
        ink = ImageOps.colorize(gradient, "#75ffae", "#31d872").convert("RGBA")
        image.paste(ink, (0, 0), mask)
    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def render_preview():
    # This preview uses sample data, not a device capture.
    scale = 2
    width, height = 212 * scale, 520 * scale
    screen = Image.new("RGB", (width, height), "#000000")
    draw = ImageDraw.Draw(screen)
    fonts = Path("C:/Windows/Fonts")

    def label(value, y, size, color, bold=False):
        font = ImageFont.truetype(str(fonts / ("msyhbd.ttc" if bold else "msyh.ttc")), size * scale)
        draw.text((width // 2, y * scale), value, font=font, fill=color, anchor="mm")

    label("Codex 额度", 45, 22, "#dcf6e7", True)
    for y, title, value, reset in (
        (66, "五小时", 68, "重置 06/12 16:00"),
        (225, "每周", 81, "重置 06/16 09:30"),
    ):
        ring = Image.open(RING_DIR / f"{value}.png").resize((240, 240), Image.Resampling.LANCZOS)
        screen.paste(ring, (92, y * scale), ring)
        label(title, y + 40, 17, "#a4ceb4", True)
        label(f"{value}%", y + 72, 34, "#effff5", True)
        label(reset, y + 135, 17, "#aac9b6")
    draw.line((100, 774, 324, 774), fill="#2a4937", width=2)
    label("额度", 412, 18, "#9ec1ab")
    label("1,234", 446, 35, "#79ffae", True)

    matte = Image.new("RGB", (width + 44, height + 44), "#151d19")
    capsule = Image.new("L", (width, height))
    ImageDraw.Draw(capsule).rounded_rectangle((0, 0, width - 1, height - 1), radius=width // 2, fill=255)
    matte.paste(screen, (22, 22), capsule)
    matte.save(ROOT / "quota-preview.png", optimize=True)


if __name__ == "__main__":
    RING_DIR.mkdir(parents=True, exist_ok=True)
    for value in range(101):
        render_ring(value).save(RING_DIR / f"{value}.png", optimize=True)
    render_preview()
