"""Видно ли иконку или наклейку на фоне: контраст по WCAG (отношение яркостей, от 1 до 21).
Для значков и элементов интерфейса WCAG 2.1 требует хотя бы 3:1 (критерий 1.4.11), для текста - 4.5:1.
Вердикт: «хорошо» - силуэт почти везде читается от 3:1, «так себе» - только от 2:1 (видно, но бледно),
иначе «плохо видно».

Силуэт глаз находит по краю рисунка, но край - не только самый внешний пиксель: у наклейки белая обводка
на белом фоне сливается, а тёмный контур рисунка сразу за ней виден. Поэтому для каждой точки края берётся
самый контрастный пиксель рядом с ней внутри рисунка (на глубине до ~8% размера рисунка)."""

import numpy as np
from PIL import Image, ImageFilter

from imaging.files import hex_rgb, load

SIDE = 256
GOOD, OK = 3.0, 2.0  # WCAG для значков - 3:1; ниже 2:1 силуэт почти теряется
SHARE = 0.75  # такая доля края должна читаться
# фоны «на всякий случай», если у картинки нет своей палитры
DEFAULT_BGS = [("Белый", "#ffffff"), ("Тёмная тема", "#1e1e24")]


def _lin(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def luminance(rgb):
    """Относительная яркость WCAG; rgb - массив (..., 3) 0..255."""
    lin = _lin(np.asarray(rgb, np.float64))
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def ratio(l1, l2):
    hi, lo = np.maximum(l1, l2), np.minimum(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _erode(mask, r):
    pad = np.pad(mask, r, constant_values=False)
    out = mask.copy()
    h, w = mask.shape
    for dy in (-r, 0, r):
        for dx in (-r, 0, r):
            out &= pad[r + dy : r + dy + h, r + dx : r + dx + w]
    return out


def prepare(im, side=SIDE):
    """Картинка -> {lum, solid, ring, depth} или None (нет прозрачного фона - это фон или фото)."""
    im = im.convert("RGBA")
    im.thumbnail((side, side))
    a = np.asarray(im, np.float32)
    solid = a[..., 3] > 128
    if not solid.any() or solid.all() or (a[..., 3] < 16).mean() < 0.02:
        return None
    r = max(1, side // 128)
    ring = solid & ~_erode(solid, r)
    if ring.sum() < 12:
        ring = solid
    depth = max(2, round(0.08 * np.sqrt(solid.sum())))
    return dict(lum=luminance(a[..., :3]).astype(np.float32), solid=solid, ring=ring, depth=depth)


def measure(prep, bg_hex):
    """Насколько силуэт читается на фоне -> (доля края от 3:1, типичный контраст края, обводка сливается,
    доля края от 2:1)."""
    lb = float(luminance(np.array(hex_rgb(bg_hex), np.float64)))
    rat = np.where(prep["solid"], ratio(prep["lum"], lb), 1.0)
    # самый контрастный пиксель рядом (MaxFilter по десятым долям контраста - уложить в 8 бит)
    q = Image.fromarray(np.clip(rat * 10, 0, 255).astype(np.uint8), "L")
    near = np.asarray(q.filter(ImageFilter.MaxFilter(2 * prep["depth"] + 1)), np.float32) / 10
    edge, outer = near[prep["ring"]], rat[prep["ring"]]
    share3, share2 = float((edge >= GOOD).mean()), float((edge >= OK).mean())
    lost = float((outer >= GOOD).mean()) < 0.5 and share3 >= SHARE
    return share3, float(np.median(edge)), lost, share2


def verdict(share, soft=0.0):
    """share - доля края от 3:1 (WCAG для значков), soft - от 2:1 (видно, но бледно)."""
    return "хорошо" if share >= SHARE else "так себе" if max(share, soft) >= SHARE else "плохо видно"


def check(path, bgs):
    """Картинка на фонах bgs [(имя, #цвет)] -> {"bgs": [{name, color, share, ratio, verdict, note}], "worst": ...}
    или None (у картинки нет прозрачного фона - это фон или фото, проверять нечего)."""
    prep = prepare(load(path))
    if prep is None:
        return None
    out = []
    for name, color in bgs:
        share, med, lost, soft = measure(prep, color)
        item = dict(name=name, color=color, share=round(share, 2), ratio=round(med, 1), verdict=verdict(share, soft))
        if lost:
            item["note"] = "обводка сливается с фоном, рисунок виден"
        out.append(item)
    return dict(bgs=out, worst=min(out, key=lambda x: (x["share"], x["ratio"])))
