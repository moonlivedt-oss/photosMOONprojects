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
import json
import os
import shutil
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

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


def load(path):
    im = Image.open(path)
    im.load()
    return im.convert("RGBA")


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
            c, r = L * i // n, L // (2 * n)
            win = prof[c - r:c + r]
            res.append(c - r + int(np.flatnonzero(win == win.min()).mean()))
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


def save(im, path, fmt):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if fmt == "webp":
        im.save(path, "WEBP", quality=90, method=6, alpha_quality=90)
    elif fmt in ("jpg", "jpeg"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, (0, 0), im)
        bg.save(path, "JPEG", quality=90, optimize=True)
    elif fmt == "ico":
        side = max(im.size)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(side, 16)]
        sq.save(path, "ICO", sizes=sizes)
    else:
        im.save(path, "PNG", optimize=True)


def cut(im, setka=None, razmer=256, fon="auto", obvodka=0, otstup=0.06):
    """Режет лист на квадратные картинки. setka - (столбцы, строки) или None (автопоиск).
    Возвращает (картинки, их рамки на листе). Общая часть для командной строки и окна."""
    _, uniform = border_color(im)
    has_alpha = np.asarray(im.getchannel("A")).min() < 250
    removed = fon == "ubrat" or (fon == "auto" and uniform and not has_alpha)
    if removed:
        im = remove_bg(im)
    mask = object_mask(im, removed)
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
        pieces, _ = cut(load(src), setka, a.razmer, a.fon, a.obvodka, a.otstup)
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
        im = load(src)
        if a.max and max(im.size) > a.max and a.v != "ico":
            k = a.max / max(im.size)
            im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
        dst = os.path.splitext(src)[0] + "." + a.v
        save(im, dst, a.v)
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
            im = Image.open(f)
            im.load()
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
            shutil.move(x[0], dst)
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
function stem(it){return it.file.split("/").pop().replace(/\\.[^.]+$/,"")}
(function(){var fs=$("fs"),ft=$("ft"),c={};fs.innerHTML='<option value="">Все разделы</option>';
 D.sections.forEach(function(s){fs.innerHTML+='<option>'+s.name+'</option>';s.groups.forEach(function(g){g.items.forEach(function(it){var k=stem(it);c[k]=(c[k]||0)+1})})});
 ft.innerHTML='<option value="">Все темы</option>';Object.keys(c).sort().forEach(function(k){if(c[k]>=3)ft.innerHTML+='<option>'+k+'</option>'})})();
function card(it,sub){var i=shown.length;shown.push(it);var d=document.createElement("div");d.className="it";
 d.innerHTML='<div class="th"><img loading="lazy" src="'+enc(it.file)+'"></div><div class="cap" title="'+it.file+'">'+(sub||it.name)+' <span>'+it.info+'</span></div><button class="cp">Путь</button>';
 d.onclick=function(){open(i)};d.lastChild.onclick=function(e){e.stopPropagation();copy(abs(it),this)};return d}
function draw(){var q=$("q").value.trim().toLowerCase(),fsec=$("fs").value,ft=$("ft").value,nav=$("nav");m.innerHTML="";shown=[];nav.innerHTML="";
 function ok(s,g,it){return(!fsec||s.name===fsec)&&(!ft||stem(it)===ft)&&(!q||(s.name+" "+g.name+" "+it.file).toLowerCase().indexOf(q)>=0)}
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
    secs = {}
    for f in images_in(LIB):
        rel = os.path.relpath(f, LIB).replace("\\", "/")
        parts = rel.split("/")
        if len(parts) < 2:
            continue
        sec, grp = parts[0], "/".join(parts[1:-1])
        info = "%d КБ" % max(1, os.path.getsize(f) // 1024)
        if not f.lower().endswith(".svg"):
            try:
                with Image.open(f) as im:
                    info = "%dx%d, %s" % (im.width, im.height, info)
            except Exception:
                pass
        secs.setdefault(sec, {}).setdefault(grp, []).append(
            {"file": rel, "name": html.escape(parts[-1]), "info": info, "t": int(os.path.getmtime(f))})
    data = {"sections": [{"name": html.escape(s), "groups": [{"name": html.escape(g), "items": secs[s][g]} for g in sorted(secs[s])]}
                         for s in sorted(secs)], "built": time.strftime("%d.%m.%Y %H:%M"), "root": LIB}
    js = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    with open(os.path.join(LIB, "Галерея.html"), "w", encoding="utf-8") as fh:
        fh.write(PAGE.replace("/*DATA*/null", js))
    # Что уже есть в библиотеке: папка -> имена файлов. Промпты.html по этому списку прячет готовые карточки.
    have = {}
    for f in images_in(LIB):
        have.setdefault(os.path.basename(os.path.dirname(f)), []).append(os.path.splitext(os.path.basename(f))[0])
    with open(os.path.join(LIB, "_инструменты", "готово.js"), "w", encoding="utf-8") as fh:
        fh.write("window.HAVE = " + json.dumps(have, ensure_ascii=False) + ";\n")
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
    k.add_argument("--v", default="webp", choices=["webp", "png", "jpg", "ico"])
    k.add_argument("--max", type=int, default=0)
    k.add_argument("--zamenit", action="store_true")
    d = sub.add_parser("дубли")
    d.add_argument("papka", nargs="?")
    sub.add_parser("галерея")
    a = p.parse_args()
    {"нарезать": cmd_cut, "конвертировать": cmd_convert, "дубли": cmd_dupes, "галерея": cmd_gallery}[a.cmd](a)


if __name__ == "__main__":
    main()
