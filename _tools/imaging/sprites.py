"""Атласы, svg-спрайты, наборы значков программы и листы превью."""

import json
import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from imaging.encoding import resize, save, to_svg, trim
from imaging.files import load


def frame_ids(paths):
    """Имена кадров: имя файла, повторы - с номером."""
    seen, out = {}, []
    for p in paths:
        s = os.path.splitext(os.path.basename(p))[0]
        seen[s] = seen.get(s, 0) + 1
        out.append(s if seen[s] == 1 else "%s-%d" % (s, seen[s]))
    return out


def atlas(paths, cell=128, pad=2, cols=0):
    """Спрайт-лист: все картинки в сетке клеток cell x cell. -> (картинка, {имя: [x, y, w, h]})."""
    n = len(paths)
    cols = cols or max(1, int(np.ceil(np.sqrt(n))))
    rows = (n + cols - 1) // cols
    step = cell + 2 * pad
    sheet = Image.new("RGBA", (cols * step, rows * step), (0, 0, 0, 0))
    frames = {}
    for i, (p, name) in enumerate(zip(paths, frame_ids(paths))):
        try:
            im = load(p)
        except Exception:
            continue
        im.thumbnail((cell, cell), Image.LANCZOS)
        x = (i % cols) * step + pad + (cell - im.width) // 2
        y = (i // cols) * step + pad + (cell - im.height) // 2
        sheet.alpha_composite(im, (x, y))
        frames[name] = [x, y, im.width, im.height]
    return sheet, frames


def atlas_files(sheet_name, frames, size):
    """JSON (как у TexturePacker: frames/meta) и CSS (класс на кадр) для атласа."""
    js = {
        "frames": {k: {"frame": {"x": x, "y": y, "w": w, "h": h}} for k, (x, y, w, h) in frames.items()},
        "meta": {"image": sheet_name, "size": {"w": size[0], "h": size[1]}, "scale": 1},
    }
    css = [f".sprite{{display:inline-block;background:url('{sheet_name}') no-repeat}}"]
    for k, (x, y, w, h) in frames.items():
        css.append(".sprite-%s{width:%dpx;height:%dpx;background-position:-%dpx -%dpx}" % (css_id(k), w, h, x, y))
    return json.dumps(js, ensure_ascii=False, indent=1), "\n".join(css) + "\n"


def css_id(s):
    """Имя для css-класса и id: буквы, цифры и дефисы."""
    out = "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "x"


def svg_sprite(items):
    """[(имя, байты svg)] -> текст svg со <symbol id=...> для <use href="#имя">."""
    out = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none">']
    for name, data in items:
        text = data.decode("utf-8", "replace")
        m = re.search(r"<svg\b([^>]*)>(.*)</svg>", text, re.S)
        if not m:
            continue
        attrs, body = m.groups()
        vb = re.search(r'viewBox="([^"]+)"', attrs)
        if vb:
            box = vb.group(1)
        else:
            w = re.search(r'width="([\d.]+)', attrs)
            h = re.search(r'height="([\d.]+)', attrs)
            box = f"0 0 {w.group(1) if w else 100} {h.group(1) if h else 100}"
        out.append(f'<symbol id="{css_id(name)}" viewBox="{box}">{body.strip()}</symbol>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def job_svg(path, o):
    im = load(path)
    return to_svg(trim(im)[0] if o.get("trim") else im)


def icon_set(im, folder, stem):
    """Значок программы: .ico (16..256), png 256 и favicon 32 - всё, что обычно просит проект."""
    im = resize(im.convert("RGBA"), 0, "square")
    out = []
    for name, fmt, side in (
        (stem + ".ico", "ico", 256),
        (stem + "-256.png", "png", 256),
        ("favicon-32.png", "png", 32),
    ):
        p = os.path.join(folder, name)
        if os.path.exists(p):  # не затирать: у нескольких картинок свой favicon
            p = os.path.join(folder, stem + "-" + name)
        save(
            im.resize((side, side), Image.LANCZOS) if fmt == "png" else im,
            p,
            fmt,
            lossless=True,
        )
        out.append(p)
    return out


def _font(size):
    for f in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def contact_sheet(paths, cell=220, cols=0, dark=True):
    """Сетка картинок с подписями одной картинкой - для README или чтобы показать набор."""
    n = len(paths)
    cols = cols or max(1, min(8, round((n * 1.6) ** 0.5)))
    rows = (n + cols - 1) // cols
    pad, cap = 14, 26
    bg = (21, 21, 28, 255) if dark else (244, 243, 248, 255)
    fg = (232, 230, 240) if dark else (29, 28, 36)
    sheet = Image.new("RGBA", (cols * (cell + pad) + pad, rows * (cell + cap + pad) + pad), bg)
    d = ImageDraw.Draw(sheet)
    font = _font(14)
    for i, p in enumerate(paths):
        x, y = pad + (i % cols) * (cell + pad), pad + (i // cols) * (cell + cap + pad)
        d.rounded_rectangle(
            (x, y, x + cell, y + cell),
            12,
            fill=(31, 31, 41, 255) if dark else (255, 255, 255, 255),
        )
        try:
            im = load(p)
            im.thumbnail((cell - 16, cell - 16), Image.LANCZOS)
            sheet.alpha_composite(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        except Exception:
            pass
        name = os.path.splitext(os.path.basename(p))[0]
        while d.textlength(name, font=font) > cell and len(name) > 4:
            name = name[:-2]
        d.text((x + cell / 2, y + cell + 6), name, fill=fg, font=font, anchor="ma")
    return sheet
