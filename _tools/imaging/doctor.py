"""Доктор библиотеки: битые, пустые, обрезанные, с остатками фона и каймой."""
import os

import numpy as np
from PIL import Image, ImageFilter

from imaging.cutting import label
from imaging.editing import _lum
from imaging.files import LIB, upright

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
