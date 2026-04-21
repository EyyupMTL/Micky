"""Generate a multi-res .ico from the app logo colors."""
from pathlib import Path
from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]


def make(out: Path) -> None:
    imgs = []
    for sz in SIZES:
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Rounded square background
        r = max(4, sz // 6)
        d.rounded_rectangle([(0, 0), (sz - 1, sz - 1)], r, fill=(14, 17, 22, 255))
        # Mic capsule
        cx, cy = sz / 2, sz * 0.45
        w = sz * 0.28
        h = sz * 0.40
        d.rounded_rectangle(
            [(cx - w / 2, cy - h / 2), (cx + w / 2, cy + h / 2)],
            int(w / 2),
            fill=(138, 255, 193, 255),
        )
        # Arc cradle (approximated with a wider shape)
        arc_w = sz * 0.52
        arc_h = sz * 0.34
        d.arc(
            [(cx - arc_w / 2, cy - arc_h / 2), (cx + arc_w / 2, cy + arc_h / 2 + sz * 0.25)],
            start=20,
            end=160,
            fill=(138, 255, 193, 255),
            width=max(2, sz // 22),
        )
        # Stem + base
        stem_y = cy + h / 2 + sz * 0.03
        d.line([(cx, stem_y), (cx, stem_y + sz * 0.13)], fill=(138, 255, 193, 255), width=max(2, sz // 22))
        base_y = stem_y + sz * 0.14
        d.line(
            [(cx - sz * 0.12, base_y), (cx + sz * 0.12, base_y)],
            fill=(138, 255, 193, 255),
            width=max(2, sz // 22),
        )
        imgs.append(img)
    imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES])


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "assets" / "micky.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    make(out)
    print("wrote", out)
