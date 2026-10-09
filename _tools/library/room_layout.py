"""Расстановка мебели в комнате (без Qt): её делят 3D-комната окна, сцена в Blender, командная строка и
сервер MCP. Размеры - в сантиметрах; у моделей Poly Haven - настоящие (dimensions_mm), у простых - по разделу."""

import random

from library import unreal as U

# размер по умолчанию (самая большая сторона, см), когда у модели нет настоящих размеров
DEFAULT_CM = {
    "Кровати": 210,
    "Диваны": 210,
    "Стулья и кресла": 90,
    "Столы": 130,
    "Шкафы и полки": 180,
    "Кухня и посуда": 90,
    "Ванная": 150,
    "Свет": 150,
    "Техника": 70,
    "Декор": 50,
    "Растения": 90,
    "Стены, двери, окна": 220,
    "Инструменты": 40,
    "Хозяйство и уборка": 50,
    "Спорт и хобби": 40,
    "Одежда и аксессуары": 35,
    "Мелочи": 45,
}


def size_cm(a):
    dims = a.get("dimensions_mm")
    if dims and max(dims) > 0:
        return max(10.0, max(dims) / 10)
    return DEFAULT_CM.get(a.get("section") or U.home_section(a), 80)


def footprint(a, s):
    """Сколько места модель занимает на полу (см): у Poly Haven - настоящие ширина и глубина
    (dimensions_mm: x, y - пол, z - высота), у простых моделей - самая большая сторона, с запасом."""
    dims = a.get("dimensions_mm")
    if dims and len(dims) == 3 and max(dims[:2]) > 0:
        return max(20.0, max(dims[0], dims[1]) / 10)
    return s


def layout(models, seed=None):
    """Расстановка рядами от задней стены. -> (items, ширина, глубина) в см."""
    order = list(models)
    if seed is not None:
        random.Random(seed).shuffle(order)
    if seed is None:  # по умолчанию крупное - к задней стене
        order.sort(key=lambda a: -size_cm(a))
    sizes = [size_cm(a) for a in order]
    area = sum((footprint(a, s) + 50) ** 2 for a, s in zip(order, sizes))
    w = max(380.0, min(1400.0, (area**0.5) * 1.15))
    items, x, z, row = [], -w / 2 + 30, None, 0.0
    for a, s in zip(order, sizes):
        fp = footprint(a, s)
        if z is None:
            z = 0.0
        if x + fp > w / 2 - 30 and x > -w / 2 + 30:  # ряд кончился
            z += row + 50
            x, row = -w / 2 + 30, 0.0
        items.append({"a": a, "x": x + fp / 2, "z": z + fp / 2, "size": s})
        x += fp + 50
        row = max(row, fp)
    d = max(380.0, z + row + 120)
    for it in items:  # z считался от задней стены
        it["z"] = -d / 2 + 20 + it["z"]
    return items, w, d
