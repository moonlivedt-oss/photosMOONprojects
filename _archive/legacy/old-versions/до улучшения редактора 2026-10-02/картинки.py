#!/usr/bin/env python3
# ============================================================
#  Инструменты библиотеки картинок. Нужны Pillow и numpy: pip install pillow numpy
#
#  python картинки.py нарезать лист.png [ещё.png ...] [ключи]
#      Лист с несколькими рисунками -> отдельные квадратные картинки.
#      Рисунки ищутся сами (по пустому месту между ними), порядок - по строкам.
#      --setka 4x3        резать строго на 4 столбца и 3 строки (как в cpp-docs-panel)
#      --razmer 256       сторона результата в px (0 - не менять)
#      --format webp      webp | png
#      --imena a,b,c      имена по порядку (иначе <лист>_01, _02 ...)
#      --fon auto         auto | ubrat | ostavit - убрать однотонный фон (auto: если он есть)
#      --obvodka 0        белая обводка в px, как у наклеек (после удаления фона)
#      --otstup 0.06      поля вокруг рисунка (доля стороны)
#      --out папка        куда класть (иначе "<лист> - нарезка" рядом с листом)
#
#  python картинки.py конвертировать файлы/папки [--v webp|png|jpg|ico] [--max 1920] [--zamenit]
#      Перевод формата и уменьшение. ico - сразу 16..256 px в одном файле.
#      --zamenit удаляет исходник после удачной конвертации.
#
#  python картинки.py дубли [папка]
#      Ищет одинаковые картинки (тот же рисунок в другом размере или формате),
#      оставляет самую крупную, остальные ПЕРЕНОСИТ в "_дубли" (не удаляет).
#
#  python картинки.py галерея
#      Пересобирает Галерея.html по всем картинкам библиотеки.
# ============================================================
import argparse
import html
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".ico", ".svg", ".avif")
INBOX = "00 Входящие"      # неразобранное: в галерею и в поиск дублей не попадает


def images_in(root):
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith("_") and x != INBOX)
        for f in sorted(files):
            if f.lower().endswith(EXT) and not f.startswith("_"):
                out.append(os.path.join(d, f))
    return out


ORIENT = 274                            # тег EXIF «как повернуть при показе»


def upright(im):
    """Картинка так, как её показывают просмотрщик Windows и браузер: с поворотом по EXIF.
    Некоторые jpg хранят пиксели боком и флаг «поверни»; без этого они видны лёжа."""
    try:
        if im.getexif().get(ORIENT, 1) != 1:
            return ImageOps.exif_transpose(im)
    except Exception:
        pass
    return im


def size_of(path):
    """Размер картинки с учётом поворота по EXIF, без чтения пикселей."""
    with Image.open(path) as im:
        w, h = im.size
        try:
            if im.getexif().get(ORIENT, 1) in (5, 6, 7, 8):
                w, h = h, w
        except Exception:
            pass
    return w, h


def load(path):
    # with: у многокадровых (gif, анимированный webp) Pillow держит файл открытым после load(),
    # и Windows не даёт его потом перенести или убрать в корзину
    with Image.open(path) as im:
        im.load()
        return upright(im).convert("RGBA")


def is_animated(path):
    """Многокадровая картинка: сжатие и чистка взяли бы только первый кадр."""
    try:
        with Image.open(path) as im:
            return bool(getattr(im, "is_animated", False))
    except Exception:
        return False


def write_atomic(path, data, encoding=None):
    """Запись через временный файл: браузер или второй поток не увидят файл наполовину,
    а сбой посреди записи не оставит пустышку вместо старого."""
    tmp = "%s.tmp%d-%d" % (path, os.getpid(), threading.get_ident())     # у каждого потока свой
    with open(tmp, "w" if encoding else "wb", **({"encoding": encoding} if encoding else {})) as fh:
        fh.write(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------- фон
def border_color(im):
    a = np.asarray(im.convert("RGB")).astype(int)
    b = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    med = np.median(b, 0)
    uniform = (np.abs(b - med).max(1) < 24).mean() > 0.85
    return med, uniform


def remove_bg(im, tol=38):
    """Убирает однотонный фон, связанный с краями (внутренние белые детали остаются)."""
    rgb = np.asarray(im.convert("RGB")).astype(int)
    bg, _ = border_color(im)
    cand = (np.abs(rgb - bg).max(2) <= tol).astype(np.uint8) * 255
    m = Image.fromarray(cand, "L").copy()   # copy: иначе буфер только для чтения и заливка уходит в копию
    px, (w, h) = m.load(), m.size
    for x in range(w):
        for y in (0, h - 1):
            if px[x, y] == 255:
                ImageDraw.floodfill(m, (x, y), 128)
    for y in range(h):
        for x in (0, w - 1):
            if px[x, y] == 255:
                ImageDraw.floodfill(m, (x, y), 128)
    keep = (np.asarray(m) != 128).astype(np.uint8) * 255
    soft = Image.fromarray(keep, "L").filter(ImageFilter.GaussianBlur(0.8))
    old = np.asarray(im.getchannel("A")).astype(np.uint16)
    out = im.copy()
    out.putalpha(Image.fromarray((old * np.asarray(soft) // 255).astype(np.uint8), "L"))
    return out


def add_outline(im, px):
    if px <= 0:
        return im
    pad = px + 2
    big = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    big.paste(im, (pad, pad), im)
    m = big.getchannel("A").point(lambda v: 255 if v > 100 else 0)
    left = px
    while left > 0:                       # MaxFilter большого размера медленный - наращиваем шагами
        step = min(left, 5)
        m = m.filter(ImageFilter.MaxFilter(2 * step + 1))
        left -= step
    m = m.filter(ImageFilter.GaussianBlur(0.8))
    white = Image.new("RGBA", big.size, (255, 255, 255, 0))
    white.putalpha(m)
    white.alpha_composite(big)
    return white


# ---------------------------------------------------------------- поиск рисунков на листе
def object_mask(im, bg_removed):
    if bg_removed or np.asarray(im.getchannel("A")).min() < 250:
        return np.asarray(im.getchannel("A")) > 40
    rgb = np.asarray(im.convert("RGB")).astype(int)
    bg, _ = border_color(im)
    return np.abs(rgb - bg).max(2) > 38


def find_pieces(mask):
    """Возвращает список (bbox, маска куска) в полном размере, по строкам."""
    H, W = mask.shape
    k = max(1, max(H, W) // 400)
    small = Image.fromarray((mask * 255).astype(np.uint8), "L").resize((W // k, H // k), Image.BOX)
    s = np.asarray(small) > 20
    gap = max(1, round(max(s.shape) * 0.012))
    grown = Image.fromarray((s * 255).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(2 * gap + 1))
    lab = grown.point(lambda v: 255 if v else 0)
    px = lab.load()
    arr = np.asarray(lab)
    n = 0
    for y, x in zip(*np.nonzero(arr == 255)):
        if px[int(x), int(y)] != 255:
            continue
        n += 1
        if n > 250:
            break
        ImageDraw.floodfill(lab, (int(x), int(y)), n)
    L = np.asarray(lab)
    comps = []
    for i in range(1, min(n, 250) + 1):
        ys, xs = np.nonzero((L == i) & s)
        if len(xs):
            comps.append({"ids": {i}, "box": [xs.min(), ys.min(), xs.max() + 1, ys.max() + 1]})
    if not comps:
        return []
    area = lambda c: (c["box"][2] - c["box"][0]) * (c["box"][3] - c["box"][1])
    med = float(np.median([area(c) for c in comps]))
    big = [c for c in comps if area(c) >= 0.2 * med] or comps
    for c in comps:                         # мелочь (искорки, звёздочки) - к ближайшему крупному
        if c in big:
            continue
        cx, cy = (c["box"][0] + c["box"][2]) / 2, (c["box"][1] + c["box"][3]) / 2
        t = min(big, key=lambda b: ((b["box"][0] + b["box"][2]) / 2 - cx) ** 2 + ((b["box"][1] + b["box"][3]) / 2 - cy) ** 2)
        t["ids"] |= c["ids"]
        t["box"] = [min(t["box"][0], c["box"][0]), min(t["box"][1], c["box"][1]),
                    max(t["box"][2], c["box"][2]), max(t["box"][3], c["box"][3])]
    big.sort(key=lambda c: c["box"][1])
    rows, cur = [], []
    for c in big:
        if cur and (c["box"][1] + c["box"][3]) / 2 > max(b["box"][3] for b in cur):
            rows.append(cur)
            cur = []
        cur.append(c)
    rows.append(cur)
    out = []
    for r in rows:
        for c in sorted(r, key=lambda c: c["box"][0]):
            m = Image.fromarray((np.isin(L, list(c["ids"])) * 255).astype(np.uint8), "L")
            m = np.asarray(m.filter(ImageFilter.MaxFilter(3)).resize((W, H), Image.NEAREST)) > 0
            x0, y0, x1, y1 = c["box"]
            out.append(((x0 * k, y0 * k, min(W, x1 * k + k), min(H, y1 * k + k)), m))
    return out


def grid_pieces(mask, cols, rows):
    H, W = mask.shape

    def cuts(n, axis):
        prof = mask.sum(axis=axis)
        L = len(prof)
        res = [0]
        for i in range(1, n):
            c, r = L * i // n, max(1, L // (2 * n))      # max: у крошечного листа окно поиска было пустым
            a = max(0, c - r)
            win = prof[a:max(a + 1, c + r)]
            res.append(a + int(np.flatnonzero(win == win.min()).mean()) if len(win) else c)
        return res + [L]

    xs, ys = cuts(cols, 0), cuts(rows, 1)
    # Каждая связная область целиком уходит в ту ячейку, где её середина: рисунок, вылезший
    # за линию сетки, не обрезается, а кусок соседа не попадает в кадр.
    k = max(1, max(H, W) // 600)
    w, h = W // k, H // k
    small = np.asarray(Image.fromarray((mask * 255).astype(np.uint8), "L").resize((w, h), Image.BOX)) > 127
    L, n = label(small)
    grid = (np.searchsorted(np.array(ys[1:-1]) / k, np.arange(h), side="right")[:, None] * cols
            + np.searchsorted(np.array(xs[1:-1]) / k, np.arange(w), side="right")[None, :])
    py, px = np.nonzero(L)
    lab = L[py, px]
    x0, y0 = np.full(n + 1, w), np.full(n + 1, h)
    x1, y1 = np.zeros(n + 1, int), np.zeros(n + 1, int)
    np.minimum.at(x0, lab, px), np.minimum.at(y0, lab, py)
    np.maximum.at(x1, lab, px), np.maximum.at(y1, lab, py)
    home = grid[np.minimum((y0 + y1) // 2, h - 1), np.minimum((x0 + x1) // 2, w - 1)]
    # Мелочь (искорки, оторвавшийся край обводки) идёт в клетку ближайшего крупного рисунка, а не туда,
    # где её середина: иначе верх головы из нижнего ряда торчит полоской под рисунком верхнего.
    area = np.bincount(lab, minlength=n + 1)
    big = np.flatnonzero(area >= 0.02 * w * h / (cols * rows))
    big = big[big > 0]
    if len(big):
        for i in np.flatnonzero((area > 0) & (area < 0.02 * w * h / (cols * rows))):
            if i == 0:
                continue
            gx = np.maximum(0, np.maximum(x0[big] - x1[i], x0[i] - x1[big]))
            gy = np.maximum(0, np.maximum(y0[big] - y1[i], y0[i] - y1[big]))
            home[i] = home[big[int(np.argmin(gx * gx + gy * gy))]]
    stuck = (x1 - x0 > 1.4 * w / cols) | (y1 - y0 > 1.4 * h / rows)     # слиплось с соседом - режем по линии
    own = np.where(stuck[L], grid, home[L])
    sm = stuck[L] & (L > 0)
    if sm.any():
        # Слипшиеся соседи обычно касаются только тонкой обводкой: сжимаем, чтобы перемычка исчезла,
        # раздаём части по клеткам, а потом наращиваем метки обратно до исходного контура.
        er = np.asarray(Image.fromarray((sm * 255).astype(np.uint8), "L").filter(ImageFilter.MinFilter(7))) > 0
        Le, ne = label(er)
        if ne:
            ey, ex = np.nonzero(Le)
            el = Le[ey, ex]
            ex0, ey0 = np.full(ne + 1, w), np.full(ne + 1, h)
            ex1, ey1 = np.zeros(ne + 1, int), np.zeros(ne + 1, int)
            np.minimum.at(ex0, el, ex), np.minimum.at(ey0, el, ey)
            np.maximum.at(ex1, el, ex), np.maximum.at(ey1, el, ey)
            ehome = grid[np.minimum((ey0 + ey1) // 2, h - 1), np.minimum((ex0 + ex1) // 2, w - 1)]
            ebig = (ex1 - ex0 > 1.4 * w / cols) | (ey1 - ey0 > 1.4 * h / rows)
            g = Le.copy()
            for _ in range(10):
                pad = np.pad(g, 1)
                nb = np.max([pad[1 + dy:h + 1 + dy, 1 + dx:w + 1 + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=0)
                fill = sm & (g == 0) & (nb > 0)
                if not fill.any():
                    break
                g[fill] = nb[fill]
            part = np.where((g > 0) & ~ebig[g], ehome[g], grid)
            own = np.where(sm, part, own)
    out = []
    for r in range(rows):
        for c in range(cols):
            m = small & (own == r * cols + c)
            if not m.any():
                out.append(((xs[c], ys[r], xs[c + 1], ys[r + 1]), None))
                continue
            my, mx = np.nonzero(m)
            box = (max(0, (mx.min() - 2) * k), max(0, (my.min() - 2) * k), min(W, (mx.max() + 3) * k), min(H, (my.max() + 3) * k))
            grown = np.asarray(Image.fromarray((m * 255).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(5))) > 0
            grown &= ~(small & (own != r * cols + c))        # запас по краю, но без пикселей соседа
            full = Image.fromarray((grown * 255).astype(np.uint8), "L").resize((W, H), Image.NEAREST)
            out.append((box, np.asarray(full) > 0))
    return out


def label(s):
    """Связные области булевой маски -> (карта номеров с 1, их количество)."""
    lab = Image.fromarray(np.where(s, -1, 0).astype(np.int32)).copy()   # copy: см. remove_bg
    px, n = lab.load(), 0
    for y, x in zip(*np.nonzero(s)):
        if px[int(x), int(y)] == -1:
            n += 1
            ImageDraw.floodfill(lab, (int(x), int(y)), n)
    return np.asarray(lab), n


def to_square(im, pad, fill):
    a = np.asarray(im.getchannel("A"))
    ys, xs = np.nonzero(a > 8)
    if len(xs):
        im = im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    w, h = im.size
    side = int(max(w, h) * (1 + 2 * pad)) or 1
    canvas = Image.new("RGBA", (side, side), fill)
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    return canvas


def has_alpha(im):
    return (
        im.mode in ("RGBA", "LA", "PA") and np.asarray(im.getchannel("A")).min() < 255
    )


# подложка для форматов без прозрачности (jpg): имя, подпись, цвет
MATTES = [
    ("white", "Белая", (255, 255, 255)),
    ("dark", "Тёмная, как окно", (20, 20, 28)),
    ("black", "Чёрная", (0, 0, 0)),
]


def matte_rgb(m):
    """Цвет подложки: имя из MATTES или "#rrggbb"."""
    for name, _t, rgb in MATTES:
        if m == name:
            return rgb
    if isinstance(m, str) and m.startswith("#") and len(m) == 7:
        return tuple(int(m[i:i + 2], 16) for i in (1, 3, 5))
    return 255, 255, 255


def encode(im, fmt, quality=90, lossless=False, speed=None, sharp=False, matte="white"):
    """Картинка -> байты файла. quality 1..100; lossless - без потерь (webp, png; для png это без
    уменьшения палитры). speed - для подбора качества: быстрее и чуть хуже сжато.
    sharp - цвет без прореживания (avif 4:4:4, jpg без субдискретизации): у иконок и наклеек
    иначе мылятся контуры. matte - подложка вместо прозрачности для jpg."""
    buf = io.BytesIO()
    im = im if im.mode in ("RGB", "RGBA") else im.convert("RGBA")
    if fmt == "webp":
        if lossless:
            im.save(
                buf,
                "WEBP",
                lossless=True,
                quality=100,
                method=speed if speed is not None else 6,
                exact=False,
            )
        else:
            im.save(
                buf,
                "WEBP",
                quality=quality,
                method=speed if speed is not None else 6,
                alpha_quality=min(100, quality + 5),
            )
    elif fmt == "avif":
        im.save(
            buf,
            "AVIF",
            quality=100 if lossless else quality,
            speed=speed if speed is not None else 6,
            subsampling="4:4:4" if sharp or lossless else "4:2:0",
        )
    elif fmt in ("jpg", "jpeg"):
        if has_alpha(im):
            bg = Image.new("RGB", im.size, matte_rgb(matte))
            bg.paste(im, (0, 0), im)
            im = bg
        im.convert("RGB").save(
            buf, "JPEG", quality=quality, optimize=True, progressive=True,
            subsampling=0 if sharp else 2,
        )
    elif fmt == "ico":
        side = max(im.size)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(
            im, ((side - im.width) // 2, (side - im.height) // 2), im.convert("RGBA")
        )
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(side, 16)]
        sq.save(buf, "ICO", sizes=sizes)
    else:
        if not lossless and quality < 100:
            # png с потерями: палитра до 256 цветов, как у pngquant (заметно легче для иконок и наклеек)
            colors = max(16, min(256, int(quality * 2.56)))
            im = im.convert("RGBA").quantize(
                colors,
                method=Image.Quantize.FASTOCTREE,
                dither=Image.Dither.FLOYDSTEINBERG,
            )
        im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def save(im, path, fmt, quality=90, lossless=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if fmt == "png" and quality == 90 and not lossless:
        lossless = True  # по умолчанию png без потерь, как раньше
    data = encode(im, fmt, quality, lossless)
    with open(path, "wb") as fh:
        fh.write(data)


# ---------------------------------------------------------------- размер
FITS = [
    ("fit", "Вписать (без обрезки)"),
    ("fill", "Заполнить (обрезать края)"),
    ("square", "Квадрат с полями"),
]


def resize(im, size, fit="fit", height=0):
    """size - длинная сторона (или ширина, если задана height). Меньшие картинки не увеличиваются,
    кроме "fill" и "square" с точным размером."""
    if not size:
        if fit == "square":
            side = max(im.size)
            sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            sq.paste(
                im.convert("RGBA"), ((side - im.width) // 2, (side - im.height) // 2)
            )
            return sq
        return im
    w, h = (size, height) if height else (size, size)
    if fit == "fill":
        return ImageOps.fit(im, (w, h), Image.LANCZOS)
    if fit == "square":
        im = im.convert("RGBA")
        im.thumbnail((w, h), Image.LANCZOS)
        sq = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sq.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
        return sq
    if im.width <= w and im.height <= h:
        return im
    k = min(w / im.width, h / im.height)
    return im.resize(
        (max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS
    )


# ---------------------------------------------------------------- качество на глаз
def _box(x, k=8):
    c = np.pad(x, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def _planes(im, side=1024):
    """Яркость, два цветовых канала (YCbCr поверх серого) и прозрачность - массивы одного размера."""
    im = im.convert("RGBA")
    if max(im.size) > side:
        im = im.copy()
        im.thumbnail((side, side), Image.BOX)
    g = Image.new("RGBA", im.size, (128, 128, 128, 255))
    g.alpha_composite(im)
    y, cb, cr = (np.asarray(c, dtype=float) for c in g.convert("YCbCr").split())
    return y, cb, cr, np.asarray(im.getchannel("A"), dtype=float)


def _drift(d):
    """Оценка 0..1 по разнице каналов: средний сдвиг и самые заметные места (контуры).
    Подобрано на библиотеке: расползшийся цвет на контурах наклеек «0.99» не проходит, фото проходят."""
    return 1 - (d.mean() / 250 + np.percentile(d, 99.5) / 2500)


def ssim(a, b):
    """Похожесть двух картинок 0..1: SSIM по яркости, сдвиг цвета и прозрачности - берётся худшее.
    Одна яркость не видит расползшийся цвет на контурах (так первым портятся webp, jpg и avif).
    0.99 - разницы на глаз не видно."""
    pa, pb = _planes(a), _planes(b)
    if pa[0].shape != pb[0].shape or min(pa[0].shape) < 8:
        return 1.0 if pa[0].shape == pb[0].shape else 0.0
    score = _ssim_y(pa[0], pb[0])
    score = min(score, _drift(np.hypot(pa[1] - pb[1], pa[2] - pb[2])))
    if pa[3].min() < 255 or pb[3].min() < 255:
        score = min(score, _drift(np.abs(pa[3] - pb[3])))
    return float(score)


def _ssim_y(x, y):
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = _box(x), _box(y)
    vx, vy, cxy = _box(x * x) - mx * mx, _box(y * y) - my * my, _box(x * y) - mx * my
    m = ((2 * mx * my + c1) * (2 * cxy + c2)) / (
        (mx * mx + my * my + c1) * (vx + vy + c2)
    )
    return float(m.mean())


TARGETS = [
    (0.990, "Разницы не видно"),
    (0.980, "Почти без разницы"),
    (0.965, "Сильнее сжать"),
]


def auto_quality(im, fmt, target=0.99, sharp=False, matte="white"):
    """Самое низкое качество, при котором картинка на глаз не отличается (поиск делением пополам)."""
    if fmt not in ("webp", "avif", "jpg", "jpeg", "png"):
        return 90
    fast = {"webp": 3, "avif": 9}.get(fmt)
    ref = flat(im, matte) if fmt in ("jpg", "jpeg") else im     # jpg сравниваем с картинкой на той же подложке
    lo, hi = 30, 95
    if fmt == "png":
        lo, hi = 20, 100  # для png "качество" - число цветов палитры
    while hi - lo > 4:
        mid = (lo + hi) // 2
        out = Image.open(io.BytesIO(encode(im, fmt, mid, speed=fast, sharp=sharp, matte=matte)))
        if ssim(ref, out) >= target:
            hi = mid
        else:
            lo = mid
    return hi


# ---------------------------------------------------------------- сжатие файла
KINDS = [
    ("auto", "Определить само"),
    ("photo", "Фото, фон, иллюстрация"),
    ("art", "Иконка, наклейка, рисунок"),
]
BEST = "best"                                   # формат «самый лёгкий»: пробуем несколько, берём меньший


def flat(im, matte="white"):
    """Картинка без прозрачности на подложке - так её увидят в jpg."""
    if not has_alpha(im):
        return im.convert("RGB")
    bg = Image.new("RGB", im.size, matte_rgb(matte))
    bg.paste(im, (0, 0), im.convert("RGBA"))
    return bg


def is_art(im):
    """Рисунок (иконка, наклейка, плоская графика): есть прозрачность или мало цветов.
    Таким вредно прореживание цвета, и им часто выгоднее сжатие без потерь."""
    if has_alpha(im):
        return True
    small = im.convert("RGB")
    small.thumbnail((256, 256), Image.NEAREST)
    return small.getcolors(2048) is not None


def trim(im, alpha=8):
    """Срезает прозрачные поля по краям. Возвращает (картинка, срезано ли)."""
    if not has_alpha(im):
        return im, False
    box = im.getchannel("A").point(lambda v: 255 if v > alpha else 0).getbbox()
    if not box or box == (0, 0) + im.size:
        return im, False
    return im.crop(box), True


def _one(im, fmt, o, sharp):
    """Один формат: байты и сведения. Без потерь / ручное качество / подбор на глаз."""
    matte, target = o.get("matte", "white"), o.get("target", 0.99)
    if o.get("lossless") and fmt in ("webp", "png", "avif"):
        return encode(im, fmt, 100, True, sharp=True), dict(fmt=fmt, q=100, lossless=True)
    if o.get("q"):
        q = o["q"]
        return encode(im, fmt, q, fmt == "png" and q >= 100, sharp=sharp, matte=matte), dict(fmt=fmt, q=q)
    q = auto_quality(im, fmt, target, sharp, matte)
    data, info = encode(im, fmt, q, sharp=sharp, matte=matte), dict(fmt=fmt, q=q)
    if sharp and fmt == "webp":                 # рисунку webp без потерь часто легче и точнее
        ll = encode(im, "webp", 100, True)
        if len(ll) <= len(data):
            data, info = ll, dict(fmt=fmt, q=100, lossless=True)
    return data, info


def best_formats(im, art):
    """Кандидаты для «самого лёгкого»: у прозрачных нет jpg, у фото нет png-палитры."""
    out = ["webp", "avif"]
    if art:
        out.append("png")
    if not has_alpha(im):
        out.append("jpg")
    return out


def _fit_budget(im, fmt, o, sharp, kb):
    """Влезть в kb: сначала понижаем качество, не хватает - уменьшаем размер."""
    limit, matte, cur = kb * 1024, o.get("matte", "white"), im
    for _k in range(8):
        lo, hi = (16, 100) if fmt == "png" else (35, 95)     # ниже - каша; лучше уменьшить размер
        got = None
        while lo <= hi:
            mid = (lo + hi) // 2
            data = encode(cur, fmt, mid, sharp=sharp, matte=matte)
            if len(data) <= limit:
                got, lo = (data, mid), mid + 1
            else:
                hi = mid - 1
        if got:
            return got[0], dict(fmt=fmt, q=got[1], budget=True, scaled=cur.size if cur is not im else None)
        cur = cur.resize((max(1, round(cur.width * 0.8)), max(1, round(cur.height * 0.8))), Image.LANCZOS)
    q = 16 if fmt == "png" else 35
    data = encode(cur, fmt, q, sharp=sharp, matte=matte)
    return data, dict(fmt=fmt, q=q, budget=True, scaled=cur.size, over=len(data) > limit)


def compress(im, o):
    """im + настройки -> (байты, сведения). Настройки o:
    fmt - webp/avif/png/jpg/ico или "best" (попробовать несколько и взять самый лёгкий);
    q - качество (0 - подобрать на глаз до target), lossless; size, fit - размер;
    kind - auto/photo/art (рисунку - цвет без прореживания); trim - срезать прозрачные поля;
    budget - не больше стольких КБ; matte - подложка для jpg.
    Сведения: fmt, q, lossless, sharp, trimmed, size (итоговый размер), budget/scaled/over."""
    trimmed = False
    if o.get("trim"):
        im, trimmed = trim(im)
    im = resize(im, o.get("size", 0), o.get("fit", "fit"))
    kind = o.get("kind", "auto")
    art = is_art(im) if kind == "auto" else kind == "art"
    fmt = o["fmt"]
    if fmt == "ico":
        data, info = encode(im, "ico"), dict(fmt="ico", q=100)
    elif fmt == BEST:
        data, info = min((_one(im, f, o, art) for f in best_formats(im, art)), key=lambda t: len(t[0]))
    else:
        data, info = _one(im, fmt, o, art)
    kb = o.get("budget", 0)
    if kb and len(data) > kb * 1024 and info["fmt"] != "ico":
        data, info = _fit_budget(im, info["fmt"], o, art, kb)
    info.update(sharp=art, trimmed=trimmed, size=info.get("scaled") or im.size)
    return data, info


def to_svg(im):
    """Контуры: рисунок -> svg (vtracer). Годится для плоских значков и наклеек, у фото выйдет каша.
    Без vtracer - ImportError (ставится: py -3.14 -m pip install vtracer)."""
    import vtracer
    im = im.convert("RGBA")
    if max(im.size) > 1024:
        im = im.copy()
        im.thumbnail((1024, 1024), Image.LANCZOS)
    # через файлы и без параметров: в сборке vtracer под Python 3.14 и строковый вывод,
    # и любой именованный параметр роняют процесс (проверено 2026-10-02, vtracer 0.6.15)
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.png"), os.path.join(d, "out.svg")
        im.save(src, "PNG")
        vtracer.convert_image_to_svg_py(src, dst)     # параметры по умолчанию: цвет, сплайны, слои
        with open(dst, "rb") as fh:
            return fh.read()


# ---------------------------------------------------------------- правка
# Правка - это рецепт: цвет (adj) и список шагов (ops). Окно показывает его на уменьшенной копии
# (scale < 1), а сохранение применяет тот же рецепт к полному размеру. Размеры в шагах (обводка,
# длинная сторона) заданы для полного размера, обрезка - долями (0..1) от текущей картинки.
ADJ = [("bright", "Яркость"), ("contrast", "Контраст"), ("sat", "Насыщенность"),
       ("hue", "Оттенок"), ("warm", "Тепло")]


def adjust(im, bright=0, contrast=0, sat=0, hue=0, warm=0):
    """Цветокоррекция с сохранением прозрачности. bright/contrast/sat/warm - -100..100, hue - градусы."""
    if not (bright or contrast or sat or hue or warm):
        return im
    from PIL import ImageEnhance
    im = im.convert("RGBA")
    alpha = im.getchannel("A")
    rgb = im.convert("RGB")
    if hue:
        h, s, v = rgb.convert("HSV").split()
        h = h.point(lambda x: (x + round(hue * 256 / 360)) % 256)
        rgb = Image.merge("HSV", (h, s, v)).convert("RGB")
    for name, val in (("bright", bright), ("contrast", contrast), ("sat", sat)):
        if val:
            cls = {"bright": ImageEnhance.Brightness, "contrast": ImageEnhance.Contrast,
                   "sat": ImageEnhance.Color}[name]
            rgb = cls(rgb).enhance(1 + val / 100)
    if warm:                                    # теплее - краснее и желтее, холоднее - синее
        a = np.asarray(rgb).astype(np.int16)
        k = warm * 0.35
        a[..., 0] += int(k)
        a[..., 2] -= int(k)
        rgb = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def apply_edits(im, ops, adj=None, scale=1.0):
    """Рецепт правки -> картинка. Цвет правится первым: так белая обводка наклейки остаётся белой."""
    im = adjust(im.convert("RGBA"), **(adj or {}))
    for o in ops:
        k = o["op"]
        if k == "rotate":                       # deg: 90 - по часовой
            im = im.transpose({90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
                               270: Image.Transpose.ROTATE_90}[o["deg"] % 360])
        elif k == "flip":
            im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT if o["dir"] == "h" else Image.Transpose.FLIP_TOP_BOTTOM)
        elif k == "crop":
            x0, y0, x1, y1 = o["box"]
            w, h = im.size
            box = (int(round(x0 * w)), int(round(y0 * h)), int(round(x1 * w)), int(round(y1 * h)))
            box = (max(0, box[0]), max(0, box[1]), min(w, max(box[0] + 1, box[2])), min(h, max(box[1] + 1, box[3])))
            im = im.crop(box)
        elif k == "trim":
            im = trim(im)[0]
        elif k == "nobg":
            im = remove_bg(im, o.get("tol", 38))
        elif k == "outline":
            im = add_outline(im, max(1, round(o["px"] * scale)))
        elif k == "square":
            im = to_square(im, o.get("pad", 0.06), (0, 0, 0, 0))
        elif k == "resize":
            side = max(1, round(o["size"] * scale))
            f = side / max(im.size)
            im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.LANCZOS)
        elif k == "recolor":
            im = recolor(im, o["colors"], o.get("k", 1.0))
        elif k == "defringe":
            im = defringe(im, max(0, round(o.get("px", 1) * max(scale, 0.5))))
        elif k == "brush":
            im = brush(im, o["mode"], o["r"], o["pts"])
        elif k == "shadow":
            im = shadow(im, o["dx"] * scale, o["dy"] * scale, max(0.5, o["blur"] * scale), o.get("a", 0.45),
                        o.get("color", "#000000"))
        elif k == "glow":
            im = shadow(im, 0, 0, max(0.5, o["r"] * scale), o.get("a", 0.8), o.get("color", "#ffffff"), spread=True)
        elif k == "round":
            im = round_corners(im, o["rad"])
        elif k == "center":                     # квадрат из середины (аватар, превью)
            side = min(im.size)
            x, y = (im.width - side) // 2, (im.height - side) // 2
            im = im.crop((x, y, x + side, y + side))
    return im


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def recolor(im, colors, k=1.0):
    """Перекраска в палитру (градиентная карта): тёмное -> самый тёмный цвет палитры, светлое -> самый
    светлый, между ними - по порядку. Яркость растягивается по самой картинке, чтобы палитра
    использовалась вся. k - сила (0..1), прозрачность не трогается."""
    im = im.convert("RGBA")
    pal = sorted((hex_rgb(c) for c in colors), key=lambda c: _lum(np.array(c, float)))
    if len(pal) < 2:
        return im
    a = np.asarray(im).astype(np.float32)
    lum = _lum(a[..., :3])
    solid = a[..., 3] > 40
    lo, hi = (np.percentile(lum[solid], (2, 98)) if solid.any() else (0, 255))
    if hi - lo < 60:                            # почти одноцветный рисунок - растягивать нечего
        lo, hi = 0, 255
    t = np.clip((lum - lo) / max(1.0, hi - lo), 0, 1) * (len(pal) - 1)
    i = np.minimum(t.astype(int), len(pal) - 2)
    f = (t - i)[..., None]
    p = np.array(pal, np.float32)
    mapped = p[i] * (1 - f) + p[i + 1] * f
    out = a.copy()
    out[..., :3] = a[..., :3] * (1 - k) + mapped * k
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def _blur(x, r):
    """Среднее по квадрату (2r+1)^2 того же размера, что и x (края продолжаются)."""
    p = np.pad(x, ((r + 1, r), (r + 1, r)), mode="edge")
    c = p.cumsum(0).cumsum(1)
    n = 2 * r + 1
    return (c[n:, n:] - c[:-n, n:] - c[n:, :-n] + c[:-n, :-n]) / (n * n)


def defringe(im, px=1):
    """Убрать светлую (или тёмную) кайму после удаления фона: край прозрачности сжимается на px,
    а полупрозрачные пиксели края берут цвет соседнего плотного рисунка вместо цвета старого фона."""
    im = im.convert("RGBA")
    if not has_alpha(im):
        return im
    alpha = im.getchannel("A")
    if px:
        alpha = alpha.filter(ImageFilter.MinFilter(2 * px + 1))
    a = np.asarray(im).astype(np.float32)
    solid = (a[..., 3] >= 230).astype(np.float32)
    w = _blur(solid, 3)
    out = a.copy()
    edge = (a[..., 3] < 230) & (w > 0.01)
    for c in range(3):
        bled = _blur(a[..., c] * solid, 3) / np.maximum(w, 1e-6)
        out[..., c] = np.where(edge, bled, a[..., c])
    res = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")
    res.putalpha(alpha)
    return res


def brush(im, mode, r, pts):
    """Мазок кистью: mode "erase" - стереть до прозрачного, "restore" - вернуть (после «убрать фон»
    цвет под прозрачностью сохраняется). r - радиус долей длинной стороны, pts - точки долями."""
    im = im.convert("RGBA")
    w, h = im.size
    rad = max(1, round(r * max(w, h)))
    m = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(m)
    xy = [(x * w, y * h) for x, y in pts]
    if len(xy) > 1:
        d.line(xy, fill=255, width=2 * rad, joint="curve")
    for x, y in xy:
        d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=255)
    a = np.asarray(im.getchannel("A")).astype(np.int16)
    mk = np.asarray(m).astype(np.int16)
    a = np.minimum(a, 255 - mk) if mode == "erase" else np.maximum(a, mk)
    out = im.copy()
    out.putalpha(Image.fromarray(a.astype(np.uint8), "L"))
    return out


def shadow(im, dx, dy, blur, opacity, color="#000000", spread=False):
    """Тень (или свечение при spread и нулевом сдвиге) из формы рисунка; холст расширяется, чтобы она влезла."""
    im = im.convert("RGBA")
    m = int(blur * 3 + max(abs(dx), abs(dy))) + 2
    big = Image.new("RGBA", (im.width + 2 * m, im.height + 2 * m), (0, 0, 0, 0))
    sh = im.getchannel("A")
    if spread:                                  # свечение: форма чуть шире, потом размыта
        sh = sh.filter(ImageFilter.MaxFilter(3))
    mask = Image.new("L", big.size, 0)
    mask.paste(sh, (m + round(dx), m + round(dy)))
    mask = mask.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(min(255, v * opacity * (1.6 if spread else 1))))
    layer = Image.new("RGBA", big.size, hex_rgb(color) + (0,))
    layer.putalpha(mask)
    big.alpha_composite(layer)
    big.alpha_composite(im, (m, m))
    # лишний запас срезаем, но место самой картинки (и её прозрачные поля) сохраняем
    box = big.getchannel("A").point(lambda v: 255 if v > 2 else 0).getbbox() or (m, m, m + im.width, m + im.height)
    box = (min(box[0], m), min(box[1], m), max(box[2], m + im.width), max(box[3], m + im.height))
    return big.crop(box)


def round_corners(im, rad):
    """Скругление углов: rad - доля короткой стороны (0.5 - круг или «таблетка»)."""
    im = im.convert("RGBA")
    r = max(1, round(rad * min(im.size)))
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width - 1, im.height - 1), r, fill=255)
    a = np.minimum(np.asarray(im.getchannel("A")), np.asarray(m))
    out = im.copy()
    out.putalpha(Image.fromarray(a.astype(np.uint8), "L"))
    return out


EDITABLE = ("png", "jpg", "webp", "avif", "bmp", "gif")


def edit_format(path, im):
    """В каком формате сохранить правку: как было, кроме случаев, когда исходный формат не годится."""
    f = fmt_of(path)
    if f in ("bmp", "gif"):
        return "png"
    if f == "jpg" and has_alpha(im):           # фон убран - jpg прозрачность не хранит
        return "webp"
    return f


def encode_edit(im, fmt):
    """Сохранение правки без заметных потерь: png и рисунки в webp - без потерь, остальное - 92."""
    art = is_art(im)
    if fmt == "png":
        return encode(im, "png", 100, True)
    if fmt == "webp" and art:
        return encode(im, "webp", 100, True)
    return encode(im, fmt, 92 if fmt != "avif" else 90, sharp=art)


def job_edit(path, o):
    """Файл + рецепт -> (байты, формат, размер). Для сохранения по ядрам."""
    im = apply_edits(load(path), o.get("ops", []), o.get("adj"))
    fmt = edit_format(path, im)
    return encode_edit(im, fmt), fmt, im.size


# ---------------------------------------------------------------- доктор библиотеки
ART = ("02 Наклейки", "03 Маскоты", "04 Иконки", "11 Аватары", "12 Медали и достижения")
IMPORTED = ("Kenney", "Hero Patterns")         # чужие наборы: рисунок во всю клетку - так задумано
PROBLEMS = [("broken", "Не открывается"), ("empty", "Пустая или почти прозрачная"), ("small", "Слишком мелкая"),
            ("bg", "Фон не убран"), ("edge", "Рисунок обрезан краем"), ("neighbor", "Кусок соседа у края"),
            ("fringe", "Светлая кайма")]


def doctor_check(path, art=None):
    """Что не так с картинкой: [код из PROBLEMS]. Читается уменьшенная копия - быстро.
    art - рисунок с прозрачным фоном (иначе по разделу: наклейки, иконки, маскоты...)."""
    rel = os.path.relpath(path, LIB) if path.startswith(LIB) else path
    imported = any(x in rel for x in IMPORTED)
    if art is None:
        art = rel.split(os.sep)[0] in ART and not imported
    try:
        with Image.open(path) as im:
            size = im.size
            im.draft("RGB", (256, 256))
            im = upright(im).convert("RGBA")
        im.thumbnail((192, 192))
    except Exception:
        return ["broken"]
    if imported:                                # детали интерфейса из чужих наборов мелкие и полупустые нарочно
        return []
    out = []
    if max(size) < 64 and not path.lower().endswith(".ico"):
        out.append("small")
    a = np.asarray(im.getchannel("A"))
    if a.min() == 255:
        if art:
            out.append("bg")
        return out
    solid = a > 128
    if solid.mean() < 0.015:
        return out + ["empty"]
    if not art:
        return out
    border = np.concatenate([solid[0], solid[-1], solid[:, 0], solid[:, -1]])
    if border.mean() > 0.04:
        out.append("edge")
    lab, n = label(solid)
    if n > 1:
        areas = np.bincount(lab.ravel())[1:]
        big = areas.max()
        edge_ids = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
        if any(areas[i - 1] < 0.06 * big for i in edge_ids):
            out.append("neighbor")
    rgb = np.asarray(im.convert("RGB")).astype(float)
    semi = (a > 40) & (a < 220)
    # плотный край рисунка (пиксели рядом с прозрачным): если он сам светлый - это задуманная обводка наклейки
    near = np.asarray(Image.fromarray((~solid * 255).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(5))) > 0
    ring = (a >= 230) & near
    if semi.sum() > 40 and ring.sum() > 20:
        ls, lr = _lum(rgb[semi]).mean(), _lum(rgb[ring]).mean()
        thin = semi.sum() < 1.2 * ring.sum()        # кайма - узкая полоска; широкий ореол - это задуманное свечение
        if thin and ls > 150 and lr < 150 and ls > lr + 70:
            out.append("fringe")
    return out


def job_doctor(path, _o=None):
    return doctor_check(path)


# ---------------------------------------------------------------- атлас и svg-спрайт
def _ids(paths):
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
    for i, (p, name) in enumerate(zip(paths, _ids(paths))):
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
    js = {"frames": {k: {"frame": {"x": x, "y": y, "w": w, "h": h}} for k, (x, y, w, h) in frames.items()},
          "meta": {"image": sheet_name, "size": {"w": size[0], "h": size[1]}, "scale": 1}}
    css = [".sprite{display:inline-block;background:url('%s') no-repeat}" % sheet_name]
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
    import re
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
            box = "0 0 %s %s" % (w.group(1) if w else 100, h.group(1) if h else 100)
        out.append('<symbol id="%s" viewBox="%s">%s</symbol>' % (css_id(name), box, body.strip()))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def job_svg(path, o):
    im = load(path)
    return to_svg(trim(im)[0] if o.get("trim") else im)


# ---------------------------------------------------------------- задачи для параллельных процессов
# Выполняются в отдельных процессах (окно раздаёт файлы по ядрам), поэтому на входе и выходе -
# только простые данные: путь, словарь настроек, байты.
def job_compress(path, o):
    """Файл -> (байты или None, сведения)."""
    if o.get("fmt") == "clean":
        return clean(path), dict(fmt=fmt_of(path), clean=True)
    if o.get("fmt") == "svg":
        return to_svg(load(path)), dict(fmt="svg")
    return compress(load(path), o)


def job_image(im, o):
    """Уже открытая картинка (кусок листа) -> (байты, сведения)."""
    return compress(im, o)


RETINA = (("", 1), ("@2x", 2), ("@3x", 3))


def job_export(path, o):
    """Выгрузка одного файла -> [(хвост имени, формат, байты)]. o как у compress, плюс
    retina - набор name / name@2x / name@3x (size - для @1x; не задан - треть исходника)."""
    im = load(path)
    if o.get("fmt") == "svg":
        return [("", "svg", to_svg(trim(im)[0] if o.get("trim") else im))]
    fmt = o.get("fmt") or fmt_of(path)
    if fmt not in ("webp", "avif", "png", "jpg", "ico", BEST):
        fmt = "png"
    q = o.get("q", 0)
    base = dict(o, fmt=fmt, q=q, lossless=q >= 100)
    if not o.get("retina"):
        data, info = compress(im, base)
        return [("", info["fmt"], data)]
    if o.get("trim"):
        im = trim(im)[0]
    side = o.get("size") or max(1, max(im.size) // 3)
    out, last = [], None
    for tail, k in RETINA:
        data, info = compress(im, dict(base, size=side * k, trim=False))
        if tuple(info["size"]) == last:          # исходник меньше - крупнее не будет, копию не пишем
            break
        last = tuple(info["size"])
        out.append((tail, info["fmt"], data))
    return out


def job_variant(path, o):
    """Для сравнения форматов: байты, сведения и оценка похожести на исходник (score)."""
    src = load(path)
    data, info = compress(src, o)
    out = Image.open(io.BytesIO(data))
    out.load()
    ref = resize(trim(src)[0] if o.get("trim") else src, o.get("size", 0), o.get("fit", "fit"))
    if info["fmt"] == "jpg":
        ref = flat(ref, o.get("matte", "white"))
    info["score"] = ssim(ref, out) if out.size == ref.size else None
    return data, info


def fmt_of(path):
    e = os.path.splitext(path)[1][1:].lower()
    return {"jpeg": "jpg"}.get(e, e)


def clean(path):
    """Чистка без потерь: метаданные прочь, png пережат с максимальным сжатием, jpg - с теми же таблицами.
    Возвращает байты, если вышло меньше, иначе None."""
    f = fmt_of(path)
    with Image.open(path) as src:
        if getattr(src, "is_animated", False):     # пересохранение оставило бы один кадр
            return None
        src.load()
        buf = io.BytesIO()
        keep = {}                               # из метаданных оставляем только поворот, иначе картинка ляжет набок
        o = src.getexif().get(ORIENT, 1)
        if o != 1:
            ex = Image.Exif()
            ex[ORIENT] = o
            keep = {"exif": ex.tobytes()}
        if f == "png":
            im = (
                src
                if src.mode in ("RGB", "RGBA", "P", "L", "LA")
                else src.convert("RGBA")
            )
            im.save(buf, "PNG", optimize=True, compress_level=9, **keep)
        elif f == "jpg":
            src.save(buf, "JPEG", quality="keep", optimize=True, progressive=True, **keep)
        elif f == "webp" and src.info.get("lossless"):
            src.save(buf, "WEBP", lossless=True, method=6, quality=100, **keep)
        else:
            return None
    data = buf.getvalue()
    return data if len(data) < os.path.getsize(path) else None


# ---------------------------------------------------------------- набор значков и лист превью
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
        if os.path.exists(p):              # не затирать: у нескольких картинок свой favicon
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
    sheet = Image.new(
        "RGBA", (cols * (cell + pad) + pad, rows * (cell + cap + pad) + pad), bg
    )
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
            sheet.alpha_composite(
                im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2)
            )
        except Exception:
            pass
        name = os.path.splitext(os.path.basename(p))[0]
        while d.textlength(name, font=font) > cell and len(name) > 4:
            name = name[:-2]
        d.text((x + cell / 2, y + cell + 6), name, fill=fg, font=font, anchor="ma")
    return sheet


def cut(im, setka=None, razmer=256, fon="auto", obvodka=0, otstup=0.06, boxes=None):
    """Режет лист на квадратные картинки. setka - (столбцы, строки) или None (автопоиск);
    boxes - рамки, поправленные руками (тогда сетка и автопоиск не нужны).
    Возвращает (картинки, их рамки на листе). Общая часть для командной строки и окна."""
    _, uniform = border_color(im)
    has_alpha = np.asarray(im.getchannel("A")).min() < 250
    removed = fon == "ubrat" or (fon == "auto" and uniform and not has_alpha)
    if removed:
        im = remove_bg(im)
    mask = object_mask(im, removed)
    if boxes:
        pieces = [(tuple(int(v) for v in b), mask) for b in boxes]
    else:
        pieces = grid_pieces(mask, *setka) if setka else find_pieces(mask)
    fill = (0, 0, 0, 0)
    if not removed and not has_alpha:
        bg, _ = border_color(im)
        fill = tuple(int(v) for v in bg) + (255,)
    out = []
    for box, m in pieces:
        piece = im.crop(box)
        if m is not None and (removed or has_alpha):
            sub = m[box[1]:box[3], box[0]:box[2]]
            al = np.asarray(piece.getchannel("A")) * sub
            piece.putalpha(Image.fromarray(al.astype(np.uint8), "L"))
        if not (removed or has_alpha):
            pm = mask[box[1]:box[3], box[0]:box[2]]
            ys, xs = np.nonzero(pm)
            if len(xs):
                piece = piece.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
            sq = Image.new("RGBA", (max(piece.size),) * 2, fill)
            sq.paste(piece, ((sq.width - piece.width) // 2, (sq.height - piece.height) // 2))
            piece = sq
        else:
            piece = add_outline(piece, obvodka)
        piece = to_square(piece, otstup, fill)
        if razmer:
            piece = piece.resize((razmer, razmer), Image.LANCZOS)
        out.append(piece)
    return out, [tuple(int(v) for v in p[0]) for p in pieces]


def cmd_cut(a):
    names = [x.strip() for x in a.imena.split(",")] if a.imena else []
    setka = tuple(int(v) for v in a.setka.lower().replace("х", "x").split("x")) if a.setka else None
    for src in a.files:
        try:
            pieces, _ = cut(load(src), setka, a.razmer, a.fon, a.obvodka, a.otstup)
        except Exception as e:              # битый лист не обрывает всю пачку
            print("%s: не получилось - %s" % (os.path.basename(src), e))
            continue
        stem = os.path.splitext(os.path.basename(src))[0]
        out = a.out or os.path.join(os.path.dirname(os.path.abspath(src)), stem + " - нарезка")
        print("%s: найдено %d" % (os.path.basename(src), len(pieces)))
        for i, piece in enumerate(pieces):
            name = names[i] if i < len(names) else "%s_%02d" % (stem, i + 1)
            p = os.path.join(out, name + "." + a.format)
            save(piece, p, a.format)
            print("  ->", p)


def cmd_convert(a):
    files = []
    for f in a.files:
        files += images_in(f) if os.path.isdir(f) else [f]
    for src in files:
        if src.lower().endswith((".svg", "." + a.v)):
            continue
        if is_animated(src):
            print("%s: анимация - пропущено (сохранился бы один кадр)" % os.path.basename(src))
            continue
        dst = os.path.splitext(src)[0] + "." + a.v
        try:
            im = load(src)
            if a.max and max(im.size) > a.max and a.v != "ico":
                k = a.max / max(im.size)
                im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
            save(im, dst, a.v)
        except Exception as e:
            print("%s: не получилось - %s" % (os.path.basename(src), e))
            continue
        print("%s -> %s  (%d КБ -> %d КБ)" % (os.path.basename(src), os.path.basename(dst),
                                             os.path.getsize(src) // 1024, os.path.getsize(dst) // 1024))
        if a.zamenit:
            os.remove(src)


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


def cmd_dupes(a):
    root = os.path.abspath(a.papka or LIB)
    feats = []
    for f in images_in(root):
        if f.lower().endswith(".svg"):
            continue
        try:
            with Image.open(f) as im:
                im.load()
                im = upright(im).copy()     # copy: файл закрывается, картинка остаётся
        except Exception:
            continue
        w, h = im.size
        r, v = signature(im)
        feats.append((f, r, v, (w * h, os.path.getsize(f))))
    gone, moved = set(), 0
    for i, (f, r, v, q) in enumerate(feats):
        if f in gone:
            continue
        grp = [feats[i]] + [x for x in feats[i + 1:] if x[0] not in gone
                            and abs(x[1] - r) / r < SAME_RATIO and np.abs(x[2] - v).mean() < SAME_DIFF]
        if len(grp) < 2:
            continue
        grp.sort(key=lambda x: x[3], reverse=True)
        print("оставлено:", os.path.relpath(grp[0][0], root))
        for x in grp[1:]:
            gone.add(x[0])
            dst = os.path.join(root, "_дубли", os.path.relpath(x[0], root))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.move(x[0], dst)
            except OSError as e:            # файл открыт в другой программе
                print("   не перенесено:", os.path.relpath(x[0], root), "-", e)
                continue
            moved += 1
            print("   в _дубли:", os.path.relpath(x[0], root))
    print("Перенесено в _дубли: %d" % moved if moved else "Дублей нет.")


# ---------------------------------------------------------------- галерея
PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Библиотека картинок</title>
<style>
:root{--bg:#15151c;--card:#1f1f29;--fg:#e8e6f0;--dim:#9a98a8;--acc:#9d8cff;--chk:#2a2a36}
:root[data-theme=light]{--bg:#f4f3f8;--card:#fff;--fg:#1d1c24;--dim:#6b6978;--acc:#6a55e0;--chk:#e6e4ee}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);padding:12px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--chk)}
h1{font-size:17px;margin:0 12px 0 0}input{flex:1;min-width:180px;padding:7px 10px;border-radius:8px;border:1px solid var(--chk);background:var(--card);color:var(--fg)}
button{padding:6px 10px;border-radius:8px;border:1px solid var(--chk);background:var(--card);color:var(--fg);cursor:pointer}
nav{display:flex;gap:6px;flex-wrap:wrap;padding:8px 16px}nav a{color:var(--acc);text-decoration:none;font-size:13px}
section{padding:4px 16px 12px}h2{font-size:16px;margin:14px 0 4px}h3{font-size:13px;color:var(--dim);margin:10px 0 6px;font-weight:500}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--sz,130px),1fr));gap:10px}
#sz{flex:0 0 110px;min-width:0;padding:0;accent-color:var(--acc)}h2 span{color:var(--dim);font-weight:400;font-size:13px}
#up{position:fixed;right:16px;bottom:16px;z-index:3;display:none}
.it{background:var(--card);border-radius:10px;overflow:hidden;cursor:zoom-in}
.th{aspect-ratio:1;display:flex;align-items:center;justify-content:center;background:repeating-conic-gradient(var(--chk) 0 25%,transparent 0 50%) 0 0/16px 16px}
.th img{max-width:92%;max-height:92%}.cap{padding:5px 8px;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.cap span{color:var(--dim)}
#big{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;flex-direction:column;align-items:center;justify-content:center;z-index:5;padding:16px}
#big img{max-width:100%;max-height:82vh;background:repeating-conic-gradient(#333 0 25%,#222 0 50%) 0 0/16px 16px}#big p{color:#ddd;margin:10px 0 0;text-align:center}
select{padding:6px 8px;border-radius:8px;border:1px solid var(--chk);background:var(--card);color:var(--fg)}
.it{position:relative}.cp{position:absolute;top:6px;right:6px;font-size:11px;padding:3px 7px;opacity:0;transition:opacity .12s}.it:hover .cp,.cp:focus{opacity:1}
:root[data-pv=light] .th,:root[data-pv=light] #big img{background:#fff}:root[data-pv=dark] .th,:root[data-pv=dark] #big img{background:#000}
#big button{margin-top:8px}
</style></head><body>
<header><h1>Библиотека картинок</h1><input id="q" placeholder="Поиск по названию...">
<select id="fs" title="Раздел"></select><select id="ft" title="Тема оформления"></select>
<select id="so" title="Порядок"><option value="name">По разделам</option><option value="new">Сначала новые</option></select>
<input id="sz" type="range" min="80" max="280" value="130" title="Размер плиток">
<button id="pv" title="Фон под картинками">Фон: шахматка</button><button id="th">Тема</button><span id="n" style="color:var(--dim)"></span></header>
<nav id="nav"></nav><main id="m"></main><div id="big"><img id="bi"><p id="bp"></p><button id="bc">Копировать путь</button></div>
<button id="up" title="Наверх">Наверх</button>
<script>
var D=/*DATA*/null,m=document.getElementById("m"),shown=[],cur=0,BS=String.fromCharCode(92),R=document.documentElement;
function $(i){return document.getElementById(i)}
function get(k){try{return localStorage.getItem(k)}catch(e){return null}}function put(k,v){try{localStorage.setItem(k,v)}catch(e){}}
if(get("gth"))R.dataset.theme=get("gth");
$("th").onclick=function(){var t=R.dataset.theme==="light"?"dark":"light";R.dataset.theme=t;put("gth",t)};
var PV=["chk","light","dark"],PVN={chk:"шахматка",light:"светлый",dark:"тёмный"};
function pv(v){R.dataset.pv=v;$("pv").textContent="Фон: "+PVN[v];put("gpv",v)}
pv(PVN[get("gpv")]?get("gpv"):"chk");$("pv").onclick=function(){pv(PV[(PV.indexOf(R.dataset.pv)+1)%3])};
function enc(p){return p.split("/").map(encodeURIComponent).join("/")}
function abs(it){return D.root+BS+it.file.split("/").join(BS)}
function copy(t,el){var o=el.textContent;function ok(){el.textContent="Скопировано";setTimeout(function(){el.textContent=o},900)}
 function fb(){var a=document.createElement("textarea");a.value=t;document.body.appendChild(a);a.select();document.execCommand("copy");a.remove();ok()}
 if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(t).then(ok,fb);else fb()}
function un(t){var a=document.createElement("textarea");a.innerHTML=t;return a.value}
function stem(it){return it.file.split("/").pop().replace(/\\.[^.]+$/,"")}
(function(){var fs=$("fs"),ft=$("ft"),c={};fs.innerHTML='<option value="">Все разделы</option>';
 D.sections.forEach(function(s){fs.innerHTML+='<option>'+s.name+'</option>';s.groups.forEach(function(g){g.items.forEach(function(it){var k=stem(it);c[k]=(c[k]||0)+1})})});
 ft.innerHTML='<option value="">Все темы</option>';Object.keys(c).sort().forEach(function(k){if(c[k]>=3)ft.innerHTML+='<option>'+k+'</option>'})})();
function card(it,sub){var i=shown.length;shown.push(it);var d=document.createElement("div");d.className="it";
 d.innerHTML='<div class="th"><img loading="lazy" src="'+enc(it.file)+'"></div><div class="cap" title="'+it.file+'">'+(sub||it.name)+' <span>'+it.info+'</span></div><button class="cp">Путь</button>';
 d.onclick=function(){open(i)};d.lastChild.onclick=function(e){e.stopPropagation();copy(abs(it),this)};return d}
function draw(){var q=$("q").value.trim().toLowerCase(),fsec=$("fs").value,ft=$("ft").value,nav=$("nav");m.innerHTML="";shown=[];nav.innerHTML="";
 function ok(s,g,it){return(!fsec||un(s.name)===fsec)&&(!ft||stem(it)===ft)&&(!q||(s.name+" "+g.name+" "+it.file).toLowerCase().indexOf(q)>=0)}
 if($("so").value==="new"){var all=[];D.sections.forEach(function(s){s.groups.forEach(function(g){g.items.forEach(function(it){if(ok(s,g,it))all.push(it)})})});
  all.sort(function(a,b){return b.t-a.t});var sec=document.createElement("section"),gr=document.createElement("div");gr.className="grid";
  all.forEach(function(it){gr.appendChild(card(it,it.file.split("/").slice(-2).join(" / ")))});sec.appendChild(gr);m.appendChild(sec)}
 else D.sections.forEach(function(s,si){var sec=document.createElement("section"),any=0;sec.id="s"+si;sec.innerHTML="<h2>"+s.name+"</h2>";
  s.groups.forEach(function(g){var items=g.items.filter(function(it){return ok(s,g,it)});if(!items.length)return;any+=items.length;
   if(g.name){var h=document.createElement("h3");h.textContent=g.name;sec.appendChild(h)}
   var gr=document.createElement("div");gr.className="grid";items.forEach(function(it){gr.appendChild(card(it))});sec.appendChild(gr)});
  if(any){sec.firstChild.innerHTML=s.name+" <span>"+any+"</span>";m.appendChild(sec);var a=document.createElement("a");a.href="#s"+si;a.textContent=s.name+" ("+any+")";nav.appendChild(a)}});
 $("n").textContent=shown.length+" шт., собрано "+D.built}
function open(i){cur=(i+shown.length)%shown.length;var it=shown[cur];$("bi").src=enc(it.file);$("bp").textContent=it.file+"  -  "+it.info;$("big").style.display="flex"}
$("big").onclick=function(){this.style.display="none"};$("bc").onclick=function(e){e.stopPropagation();copy(abs(shown[cur]),this)};
document.onkeydown=function(e){var q=$("q");
 if($("big").style.display!=="flex"){if(e.key==="/"&&document.activeElement!==q){e.preventDefault();q.focus()}
  else if(e.key==="Escape"&&document.activeElement===q){q.value="";draw();q.blur()}return}
 if(e.key==="Escape")$("big").style.display="none";if(e.key==="ArrowRight")open(cur+1);if(e.key==="ArrowLeft")open(cur-1)};
function sz(v){R.style.setProperty("--sz",v+"px");$("sz").value=v;put("gsz",v)}sz(+get("gsz")||130);$("sz").oninput=function(){sz(this.value)};
window.onscroll=function(){$("up").style.display=scrollY>600?"block":"none"};$("up").onclick=function(){scrollTo({top:0,behavior:"smooth"})};
$("q").placeholder="Поиск по названию...  ( / )";
$("q").oninput=$("fs").onchange=$("ft").onchange=$("so").onchange=draw;draw();
</script></body></html>"""


def cmd_gallery(_a=None):
    secs, files = {}, []
    for f in images_in(LIB):
        rel = os.path.relpath(f, LIB).replace("\\", "/")
        parts = rel.split("/")
        if len(parts) < 2:
            continue
        try:
            st = os.stat(f)                 # файл могли перенести, пока шла сборка
        except OSError:
            continue
        files.append(f)
        sec, grp = parts[0], "/".join(parts[1:-1])
        info = "%d КБ" % max(1, st.st_size // 1024)
        if not f.lower().endswith(".svg"):
            try:
                info = "%dx%d, %s" % (size_of(f) + (info,))
            except Exception:
                pass
        secs.setdefault(sec, {}).setdefault(grp, []).append(
            {"file": rel, "name": html.escape(parts[-1]), "info": info, "t": int(st.st_mtime)})
    data = {"sections": [{"name": html.escape(s), "groups": [{"name": html.escape(g), "items": secs[s][g]} for g in sorted(secs[s])]}
                         for s in sorted(secs)], "built": time.strftime("%d.%m.%Y %H:%M"), "root": LIB}
    js = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    write_atomic(os.path.join(LIB, "Галерея.html"), PAGE.replace("/*DATA*/null", js), "utf-8")
    # Что уже есть в библиотеке: папка -> имена файлов. Промпты.html по этому списку прячет готовые карточки.
    have = {}
    for f in files:
        have.setdefault(os.path.basename(os.path.dirname(f)), []).append(os.path.splitext(os.path.basename(f))[0])
    write_atomic(os.path.join(LIB, "_инструменты", "готово.js"),
                 "window.HAVE = " + json.dumps(have, ensure_ascii=False) + ";\n", "utf-8")
    total = sum(len(v) for s in secs.values() for v in s.values())
    print("Галерея: %d картинок" % total)
    for s in sorted(secs):
        print("  %s: %d" % (s, sum(len(v) for v in secs[s].values())))


def main():
    p = argparse.ArgumentParser(description="Инструменты библиотеки картинок")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("нарезать")
    c.add_argument("files", nargs="+")
    c.add_argument("--setka")
    c.add_argument("--razmer", type=int, default=256)
    c.add_argument("--format", default="webp", choices=["webp", "png"])
    c.add_argument("--imena")
    c.add_argument("--fon", default="auto", choices=["auto", "ubrat", "ostavit"])
    c.add_argument("--obvodka", type=int, default=0)
    c.add_argument("--otstup", type=float, default=0.06)
    c.add_argument("--out")
    k = sub.add_parser("конвертировать")
    k.add_argument("files", nargs="+")
    k.add_argument("--v", default="webp", choices=["webp", "avif", "png", "jpg", "ico"])
    k.add_argument("--max", type=int, default=0)
    k.add_argument("--zamenit", action="store_true")
    d = sub.add_parser("дубли")
    d.add_argument("papka", nargs="?")
    sub.add_parser("галерея")
    a = p.parse_args()
    {"нарезать": cmd_cut, "конвертировать": cmd_convert, "дубли": cmd_dupes, "галерея": cmd_gallery}[a.cmd](a)


if __name__ == "__main__":
    main()
