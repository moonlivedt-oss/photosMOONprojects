"""Отпечатки картинок (дубли, «уже есть») и коды главных цветов (поиск по цвету)."""
import numpy as np
from PIL import Image

from imaging.files import upright

SAME_RATIO, SAME_DIFF = 0.04, 3.5      # насколько похожи пропорции и уменьшенная копия у одинаковых картинок


def signature(im):
    """Отпечаток картинки: пропорции и копия 12x12 на сером (прозрачность не мешает сравнению)."""
    w, h = im.size
    im = im.convert("RGBA")
    g = Image.new("RGBA", im.size, (128, 128, 128, 255))
    g.alpha_composite(im)
    return w / h, np.asarray(g.convert("RGB").resize((12, 12), Image.BOX), dtype=float)


def same_sig(a, b):
    """Два отпечатка signature() - одна и та же картинка?"""
    return abs(a[0] - b[0]) / b[0] < SAME_RATIO and np.abs(a[1] - b[1]).mean() < SAME_DIFF


# Цвета для поиска по цвету: код, название, образец. Порядок - как в списке окна.
COLORS = [("r", "Красный", "#e5484d"), ("o", "Оранжевый", "#f08c3a"), ("y", "Жёлтый", "#f2c94c"),
          ("g", "Зелёный", "#4cb782"), ("c", "Бирюзовый", "#3cc7c7"), ("b", "Синий", "#4a7ef0"),
          ("v", "Фиолетовый", "#9d6cf0"), ("p", "Розовый", "#ef6fb0"), ("w", "Светлый", "#f2f0f7"),
          ("k", "Тёмный", "#202028")]


def colors(im):
    """Коды заметных цветов картинки (доля от 12% непрозрачных пикселей), например "vbk"."""
    im = im.convert("RGBA")
    im.thumbnail((48, 48))
    a = np.asarray(im.getchannel("A")) > 128
    if not a.any():
        return ""
    h, s, v = [np.asarray(x).astype(int)[a] for x in im.convert("RGB").convert("HSV").split()]
    code = np.full(h.shape, "", dtype="<U1")
    chroma = (s >= 50) & (v >= 60)
    hue = np.select([h < 11, h < 27, h < 45, h < 110, h < 140, h < 166, h < 215, h < 240], list("roygcbvp"), "r")
    code[chroma] = hue[chroma]
    code[~chroma & (v >= 170)] = "w"
    code[v < 60] = "k"
    out = ""
    for c, _n, _s in COLORS:
        if (code == c).mean() >= 0.12:
            out += c
    return out


def main_colors(path, n=6):
    """Главные цвета картинки (без прозрачных пикселей), от самого заметного: ["#rrggbb", ...]."""
    with Image.open(path) as im:
        im.draft("RGB", (128, 128))
        im = upright(im).convert("RGBA")
    im.thumbnail((96, 96))
    a = np.asarray(im)
    px = a[a[..., 3] > 128][:, :3]
    if not len(px):
        return []
    q = Image.fromarray(px.reshape(1, -1, 3).astype(np.uint8), "RGB").quantize(n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:3 * n]
    counts = sorted(q.getcolors() or [], reverse=True)
    return ["#{:02x}{:02x}{:02x}".format(*tuple(pal[3 * i:3 * i + 3])) for c, i in counts if c >= len(px) * 0.02]
