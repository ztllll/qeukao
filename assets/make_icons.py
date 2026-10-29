#!/usr/bin/env python3
"""Regenerate branded icons with Pillow and a local bold CJK font.

After changing icons, regenerate the checked-in Go resource (group ID 1):
  cd ~/go/pkg/mod/github.com/akavel/rsrc@v0.10.2
  GOPROXY=off GOFLAGS=-mod=mod go run . -arch amd64 -ico /path/to/assets/qeukao-client.ico -o /path/to/client/rsrc_windows_amd64.syso
No manifest: rsrc allocates group ID 1, followed by seven image IDs 2..8.
"""
import argparse
import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZES = (16, 24, 32, 48, 64, 128, 256)
ASSETS = Path(__file__).resolve().parent


def render(size, color, font_path):
    # Render each size independently: preserve the glyph's hinted small strokes.
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    inset = max(0, size // 32)
    draw.rounded_rectangle((inset, inset, size - 1 - inset, size - 1 - inset),
                           radius=max(3, size // 5), fill=color)
    font = ImageFont.truetype(str(font_path), round(size * 0.78))
    box = draw.textbbox((0, 0), "考", font=font)
    x = (size - (box[2] - box[0])) // 2 - box[0]
    y = (size - (box[3] - box[1])) // 2 - box[1]
    draw.text((x, y), "考", font=font, fill="white")
    if size >= 48:
        # A separate approval badge, omitted when the tray is too small.
        draw.ellipse((size * .72, size * .72, size * .98, size * .98), fill="white")
        draw.line([(size * .78, size * .85), (size * .83, size * .90),
                   (size * .93, size * .79)], fill=color, width=max(2, size // 45))
    return image


def write_ico(path, images):
    # ICO directory + independently rendered PNGs (Pillow's default resizes one image).
    data = []
    for image in images:
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        data.append(stream.getvalue())
    offset = 6 + 16 * len(images)
    result = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    for image, raw in zip(images, data):
        size = image.width % 256
        result.extend(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(raw), offset))
        offset += len(raw)
    path.write_bytes(result + b"".join(data))
    with Image.open(path) as check:
        assert check.ico.sizes() == {(s, s) for s in SIZES}
        for image in images:
            assert check.ico.getimage(image.size).tobytes() == image.tobytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path,
                        default=Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"))
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    for name, color in (("qeukao", "#b3261e"), ("qeukao-client", "#244d75")):
        images = [render(s, color, args.font) for s in SIZES]
        write_ico(ASSETS / (name + ".ico"), images)
        if name == "qeukao":
            images[-1].save(ASSETS / "qeukao.png")
        if args.preview_dir:
            args.preview_dir.mkdir(parents=True, exist_ok=True)
            for image in images:
                if image.width in (16, 32, 256):
                    image.save(args.preview_dir / ("%s-%d.png" % (name, image.width)))


if __name__ == "__main__":
    main()
