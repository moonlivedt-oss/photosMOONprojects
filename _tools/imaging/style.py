"""Манера рисунка в числах и «выбивается из набора»: цвета, обводка, заливка, детализация, прозрачность.
CLIP для этого не годится - он видит смысл (печенье круглое, как луна), а не манеру. Здесь - простые признаки,
которые можно назвать словами: «другие цвета», «нет светлой обводки», «больше мелких деталей»."""

import numpy as np
from PIL import Image

from imaging.files import load

SIDE = 192  # признаки считаются на уменьшенной копии - быстро и одинаково для любого размера

# признак -> (подпись «больше», подпись «меньше», наименьший разброс: разница меньше - не в счёт)
FEATURES = {
    "light": ("светлее остальных", "темнее остальных", 9.0),
    "chroma": ("ярче, насыщеннее", "бледнее, серее", 9.0),
    "hue_a": ("краснее (другой оттенок)", "зеленее (другой оттенок)", 9.0),
    "hue_b": ("желтее (другой оттенок)", "синее (другой оттенок)", 9.0),
    "fill": ("рисунок плотнее, меньше пустот", "рисунок реже, больше пустот", 0.1),
    "rim": ("светлее край (обводка)", "нет светлой обводки или она темнее", 10.0),
    "detail": ("больше мелких деталей", "проще, меньше деталей", 0.35),
    "colors": ("больше цветов", "меньше цветов", 2.0),
    "clear": ("больше прозрачного поля вокруг", "меньше прозрачного, нет фона-прозрачности", 0.12),
}
LIMIT = 4.0  # насколько далеко от остальных (в разбросах набора) - уже «выбивается»
MIN_SET = 6  # в наборе меньше - сравнивать не с чем


def _lab(rgb):
    """sRGB 0..255 -> CIE Lab (D65)."""
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.2126, 0.0193], [0.3576, 0.7152, 0.1192], [0.1805, 0.0722, 0.9505]])
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def features(im):
    """Признаки манеры одной картинки (PIL.Image) -> {имя: число} или None (пустая)."""
    im = im.convert("RGBA")
    im.thumbnail((SIDE, SIDE), Image.Resampling.LANCZOS)
    a = np.asarray(im, dtype=np.float32)
    alpha = a[..., 3]
    solid = alpha > 128
    if solid.sum() < 30:
        return None
    ys, xs = np.nonzero(solid)
    box = solid[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    lab = _lab(a[..., :3][solid])
    # край рисунка: непрозрачное, рядом с которым прозрачное (обводка наклейки) - если прозрачности нет, край кадра
    pad = np.pad(solid, 2, constant_values=False)
    inner = solid.copy()
    for dy in (-2, 0, 2):
        for dx in (-2, 0, 2):
            inner &= pad[2 + dy : 2 + dy + solid.shape[0], 2 + dx : 2 + dx + solid.shape[1]]
    ring = solid & ~inner
    rim = _lab(a[..., :3][ring])[:, 0].mean() if ring.any() else lab[:, 0].mean()
    gray = a[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)
    gy, gx = np.gradient(gray)
    grad = np.hypot(gx, gy)[inner] if inner.any() else np.zeros(1)
    q = (a[..., :3][solid] // 32).astype(np.int32)
    codes = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    share = np.bincount(codes, minlength=512) / len(codes)
    return {
        "light": float(lab[:, 0].mean()),
        "chroma": float(np.hypot(lab[:, 1], lab[:, 2]).mean()),
        "hue_a": float(lab[:, 1].mean()),
        "hue_b": float(lab[:, 2].mean()),
        "fill": float(box.mean()),
        "rim": float(rim),
        "detail": float(np.log1p((grad > 24).mean() * 100)),  # доля резких перепадов внутри рисунка
        "colors": float((share > 0.02).sum()),
        "clear": float((alpha < 16).mean()),
    }


def features_of(path):
    try:
        return features(load(path))
    except Exception:
        return None


def odd_ones(feats, limit=LIMIT):
    """feats: {ключ: признаки} одного набора -> {ключ: [(признак, оценка), ...]} - чем выбивается.
    Оценка - во сколько «разбросов» набора картинка дальше медианы (со знаком: больше или меньше)."""
    keys = [k for k, f in feats.items() if f]
    if len(keys) < MIN_SET:
        return {}
    out = {}
    for name, (_more, _less, floor) in FEATURES.items():
        v = np.array([feats[k][name] for k in keys])
        med = np.median(v)
        spread = max(1.4826 * np.median(np.abs(v - med)), floor)
        z = (v - med) / spread
        for k, s in zip(keys, z):
            if abs(s) >= limit:
                out.setdefault(k, []).append((name, round(float(s), 1)))
    for k in out:
        out[k].sort(key=lambda x: -abs(x[1]))
    return out


def reason(name, score):
    more, less, _f = FEATURES[name]
    return more if score > 0 else less
