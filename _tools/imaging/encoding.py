"""Кодирование, размер, качество «на глаз» и сжатие файлов."""

import io
import os
import tempfile

import numpy as np
from PIL import Image, ImageOps

from imaging.files import ORIENT, fmt_of


def has_alpha(im):
    return im.mode in ("RGBA", "LA", "PA") and np.asarray(im.getchannel("A")).min() < 255


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
        return tuple(int(m[i : i + 2], 16) for i in (1, 3, 5))
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
            buf,
            "JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
            subsampling=0 if sharp else 2,
        )
    elif fmt == "ico":
        side = max(im.size)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im.convert("RGBA"))
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
        lossless = True
    data = encode(im, fmt, quality, lossless)
    with open(path, "wb") as fh:
        fh.write(data)


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
            sq.paste(im.convert("RGBA"), ((side - im.width) // 2, (side - im.height) // 2))
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
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)


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
    m = ((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))
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
    ref = flat(im, matte) if fmt in ("jpg", "jpeg") else im  # jpg сравниваем с картинкой на той же подложке
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


KINDS = [
    ("auto", "Определить само"),
    ("photo", "Фото, фон, иллюстрация"),
    ("art", "Иконка, наклейка, рисунок"),
]
BEST = "best"  # формат «самый лёгкий»: пробуем несколько, берём меньший


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
    if sharp and fmt == "webp":  # рисунку webp без потерь часто легче и точнее
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
        lo, hi = (16, 100) if fmt == "png" else (35, 95)  # ниже - каша; лучше уменьшить размер
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
        vtracer.convert_image_to_svg_py(src, dst)  # параметры по умолчанию: цвет, сплайны, слои
        with open(dst, "rb") as fh:
            return fh.read()


def clean(path):
    """Чистка без потерь: метаданные прочь, png пережат с максимальным сжатием, jpg - с теми же таблицами.
    Возвращает байты, если вышло меньше, иначе None."""
    f = fmt_of(path)
    with Image.open(path) as src:
        if getattr(src, "is_animated", False):  # пересохранение оставило бы один кадр
            return None
        src.load()
        buf = io.BytesIO()
        keep = {}  # из метаданных оставляем только поворот, иначе картинка ляжет набок
        o = src.getexif().get(ORIENT, 1)
        if o != 1:
            ex = Image.Exif()
            ex[ORIENT] = o
            keep = {"exif": ex.tobytes()}
        if f == "png":
            im = src if src.mode in ("RGB", "RGBA", "P", "L", "LA") else src.convert("RGBA")
            im.save(buf, "PNG", optimize=True, compress_level=9, **keep)
        elif f == "jpg":
            src.save(buf, "JPEG", quality="keep", optimize=True, progressive=True, **keep)
        elif f == "webp" and src.info.get("lossless"):
            src.save(buf, "WEBP", lossless=True, method=6, quality=100, **keep)
        else:
            return None
    data = buf.getvalue()
    return data if len(data) < os.path.getsize(path) else None
