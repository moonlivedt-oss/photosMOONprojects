"""Видно ли иконку или наклейку на фоне: контраст по WCAG (отношение яркостей, от 1 до 21).
Для значков и элементов интерфейса WCAG 2.1 требует хотя бы 3:1 (критерий 1.4.11), для текста - 4.5:1.
Смотрится край рисунка - полоска у границы с прозрачным: по силуэту глаз и находит значок. Светлая обводка
наклейки поэтому спасает её на тёмном фоне, а на белом - нет."""

import numpy as np

from imaging.files import hex_rgb, load

SIDE = 256
GOOD, OK = 3.0, 2.0  # WCAG для значков - 3:1; ниже 2:1 силуэт почти теряется
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


def edge_lum(im):
    """Яркости пикселей края рисунка (непрозрачное у границы с прозрачным) или None, если прозрачности нет."""
    im = im.convert("RGBA")
    im.thumbnail((SIDE, SIDE))
    a = np.asarray(im, np.float32)
    solid = a[..., 3] > 128
    if not solid.any() or solid.all() or (a[..., 3] < 16).mean() < 0.02:
        return None
    pad = np.pad(solid, 3, constant_values=False)
    inner = solid.copy()
    for dy in (-3, 0, 3):
        for dx in (-3, 0, 3):
            inner &= pad[3 + dy : 3 + dy + solid.shape[0], 3 + dx : 3 + dx + solid.shape[1]]
    ring = solid & ~inner
    if ring.sum() < 20:
        ring = solid
    return luminance(a[..., :3][ring])


def score(edge, bg_hex):
    """-> (доля края с контрастом >= 3:1, контраст «типичного» края - медиана)."""
    lb = float(luminance(np.array(hex_rgb(bg_hex), np.float64)))
    r = ratio(edge, lb)
    return float((r >= GOOD).mean()), float(np.median(r))


def verdict(share):
    return "хорошо" if share >= 0.8 else "так себе" if share >= 0.5 else "плохо видно"


def check(path, bgs):
    """Картинка на фонах bgs [(имя, #цвет)] -> {"bgs": [{name, color, share, ratio, verdict}], "worst": ...}
    или None (у картинки нет прозрачного фона - это фон или фото, проверять нечего)."""
    edge = edge_lum(load(path))
    if edge is None:
        return None
    out = []
    for name, color in bgs:
        share, med = score(edge, color)
        out.append(dict(name=name, color=color, share=round(share, 2), ratio=round(med, 1), verdict=verdict(share)))
    return dict(bgs=out, worst=min(out, key=lambda x: x["share"]))
