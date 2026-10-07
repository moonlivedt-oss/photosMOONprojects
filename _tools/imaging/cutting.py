"""Нарезка листа: удаление фона, обводка, поиск рисунков на листе."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from imaging.files import hex_rgb


def border_color(im):
    a = np.asarray(im.convert("RGB")).astype(int)
    b = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    med = np.median(b, 0)
    uniform = (np.abs(b - med).max(1) < 24).mean() > 0.85
    return med, uniform


def remove_bg(im, tol=38):
    """Убирает однотонный фон, связанный с краями (внутренние белые детали остаются).
    У картинки с прозрачностью цвет фона берётся только с плотных пикселей края: под прозрачным
    часто лежит чёрный, и без этого заливка съедала бы тёмную обводку рисунка."""
    im = im.convert("RGBA")
    rgb = np.asarray(im.convert("RGB")).astype(int)
    alpha = np.asarray(im.getchannel("A"))
    clear = alpha < 16
    if clear.any():
        edge = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]]) >= 16
        if edge.mean() < 0.05:                  # края уже прозрачные - убирать нечего
            return im
        b = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])[edge]
        bg = np.median(b, 0)
    else:
        bg, _ = border_color(im)
    cand = ((np.abs(rgb - bg).max(2) <= tol) | clear).astype(np.uint8) * 255
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


def add_outline(im, px, color="#ffffff"):
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
    white = Image.new("RGBA", big.size, hex_rgb(color) + (0,))
    white.putalpha(m)
    white.alpha_composite(big)
    return white


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
        ys, xs = np.nonzero((i == L) & s)
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


def cut(im, grid=None, size=256, bg_mode="auto", outline=0, pad=0.06, boxes=None):
    """Режет лист на квадратные картинки -> (картинки, их рамки на листе).
    grid - (столбцы, строки) или None (автопоиск); boxes - рамки, поправленные руками.
    bg_mode - auto | remove | keep; outline - белая обводка в px; pad - поля, доля стороны."""
    _, uniform = border_color(im)
    has_alpha = np.asarray(im.getchannel("A")).min() < 250
    removed = bg_mode == "remove" or (bg_mode == "auto" and uniform and not has_alpha)
    if removed:
        im = remove_bg(im)
    mask = object_mask(im, removed)
    if boxes:
        pieces = [(tuple(int(v) for v in b), mask) for b in boxes]
    else:
        pieces = grid_pieces(mask, *grid) if grid else find_pieces(mask)
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
            piece = add_outline(piece, outline)
        piece = to_square(piece, pad, fill)
        if size:
            piece = piece.resize((size, size), Image.LANCZOS)
        out.append(piece)
    return out, [tuple(int(v) for v in p[0]) for p in pieces]
