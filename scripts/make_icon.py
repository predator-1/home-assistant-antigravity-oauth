"""Render the integration icon (original artwork, no third-party marks).

.tmp/havenv/bin/python scripts/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "custom_components" / "antigravity" / "brand"
S = 2048  # supersampled canvas


def render() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # Rounded square with a vertical indigo-to-violet gradient.
    gradient = Image.new("RGBA", (S, S))
    top, bottom = (58, 76, 214), (146, 72, 222)
    for y in range(S):
        t = y / (S - 1)
        gradient.paste(
            (*tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True)), 255), (0, y, S, y + 1)
        )
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=S // 5, fill=255)
    img.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    # Ground line and a soft shadow: the object floats above it.
    draw.rounded_rectangle((S * 0.22, S * 0.82, S * 0.78, S * 0.85), radius=S // 60, fill=(255, 255, 255, 140))
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((S * 0.37, S * 0.755, S * 0.63, S * 0.795), fill=(20, 10, 60, 120))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(S // 80)))
    # Floating orb with an orbit ring.
    cx, cy, r = S * 0.5, S * 0.38, S * 0.16
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=white)
    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        (cx - r * 1.9, cy - r * 0.55, cx + r * 1.9, cy + r * 0.55), outline=white, width=S // 45
    )
    ring = ring.rotate(-18, center=(cx, cy), resample=Image.Resampling.BICUBIC)
    # Inside the orb the ring's back half is hidden and its front half is drawn in violet.
    orb = Image.new("L", (S, S), 0)
    ImageDraw.Draw(orb).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    upper = Image.new("L", (S, S), 0)
    ImageDraw.Draw(upper).rectangle((0, 0, S, cy), fill=255)
    alpha = ring.getchannel("A")
    hidden = Image.composite(orb, Image.new("L", (S, S), 0), upper)
    outside = Image.composite(Image.new("L", (S, S), 0), alpha, orb)
    front = Image.composite(alpha, Image.new("L", (S, S), 0), Image.composite(Image.new("L", (S, S), 0), orb, hidden))
    white_ring = Image.new("RGBA", (S, S), white)
    white_ring.putalpha(outside)
    violet_ring = Image.new("RGBA", (S, S), (98, 74, 218, 255))
    violet_ring.putalpha(front)
    img.alpha_composite(white_ring)
    img.alpha_composite(violet_ring)
    # Upward chevrons under the orb.
    for i, y in enumerate((0.69, 0.625)):
        w = S * (0.07 - i * 0.012)
        yy = S * y
        draw.line(
            [(cx - w, yy + w * 0.6), (cx, yy), (cx + w, yy + w * 0.6)],
            fill=(255, 255, 255, 255 - i * 80),
            width=S // 55,
            joint="curve",
        )
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = render()
    big.resize((512, 512), Image.Resampling.LANCZOS).save(OUT / "icon@2x.png", optimize=True)
    big.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "icon.png", optimize=True)


if __name__ == "__main__":
    main()
