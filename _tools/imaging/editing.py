"""Правка по рецепту: цвет (adj) и список шагов (ops) - одинаково для превью и полного размера."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from imaging.cutting import add_outline, remove_bg, to_square
from imaging.encoding import encode, has_alpha, is_art, trim
from imaging.files import fmt_of, hex_rgb, load

# Правка - это рецепт: цвет (adj) и список шагов (ops). Окно показывает его на уменьшенной копии
# (scale < 1), а сохранение применяет тот же рецепт к полному размеру. Размеры в шагах (обводка,
# длинная сторона) заданы для полного размера, обрезка - долями (0..1) от текущей картинки.
ADJ = [("bright", "Яркость"), ("contrast", "Контраст"), ("sat", "Насыщенность"),
       ("hue", "Оттенок"), ("warm", "Тепло"), ("shadows", "Тени"), ("highlights", "Света"),
       ("sharp", "Резкость"), ("opacity", "Прозрачность")]
ADJ_RANGE = {"hue": (-180, 180), "opacity": (0, 100)}      # остальные - -100..100


def adjust(im, bright=0, contrast=0, sat=0, hue=0, warm=0, shadows=0, highlights=0, sharp=0, opacity=0, scale=1.0):
    """Цветокоррекция с сохранением прозрачности. Значения -100..100, hue - градусы, opacity 0..100
    (насколько прозрачнее). sharp > 0 - резче, < 0 - размытие; радиус зависит от scale, чтобы
    превью на уменьшенной копии выглядело как полный размер. Контраст считается от средней
    яркости только видимых пикселей - прозрачный фон (обычно чёрный под альфой) его не сбивает."""
    if not (bright or contrast or sat or hue or warm or shadows or highlights or sharp or opacity):
        return im
    im = im.convert("RGBA")
    alpha = im.getchannel("A")
    rgb = im.convert("RGB")
    if hue:
        h, s, v = rgb.convert("HSV").split()
        h = h.point(lambda x: (x + round(hue * 256 / 360)) % 256)
        rgb = Image.merge("HSV", (h, s, v)).convert("RGB")
    if bright:
        rgb = ImageEnhance.Brightness(rgb).enhance(1 + bright / 100)
    if contrast:
        a = np.asarray(rgb).astype(np.float32)
        vis = np.asarray(alpha) > 40
        mean = _lum(a[vis]).mean() if vis.any() else _lum(a).mean()
        a = (a - mean) * (1 + contrast / 100) + mean
        rgb = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    if sat:
        rgb = ImageEnhance.Color(rgb).enhance(1 + sat / 100)
    if shadows or highlights:                   # тени - тёмная половина, света - светлая, плавно
        a = np.asarray(rgb).astype(np.float32)
        y = _lum(a)[..., None] / 255
        lift = shadows / 100 * 80 * (1 - y) ** 2 + highlights / 100 * 80 * y ** 2
        rgb = Image.fromarray(np.clip(a + lift, 0, 255).astype(np.uint8), "RGB")
    if warm:                                    # теплее - краснее и желтее, холоднее - синее
        a = np.asarray(rgb).astype(np.int16)
        k = warm * 0.35
        a[..., 0] += int(k)
        a[..., 2] -= int(k)
        rgb = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    if sharp > 0:
        rgb = rgb.filter(ImageFilter.UnsharpMask(max(0.6, 2 * scale), round(sharp * 2.5), 2))
    if opacity:
        alpha = alpha.point(lambda v: round(v * (1 - opacity / 100)))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    if sharp < 0:                               # размытие с учётом прозрачности - без тёмного ореола
        out = out.convert("RGBa").filter(ImageFilter.GaussianBlur(-sharp / 100 * 8 * scale)).convert("RGBA")
    return out


def apply_edits(im, ops, adj=None, scale=1.0, info=None):
    """Рецепт правки -> картинка. Цвет правится первым: так белая обводка наклейки остаётся белой.
    scale - во сколько раз im меньше полного размера (превью). После уменьшения («resize») превью
    считается сразу в полном размере, если тот не больше копии, - так мелкий результат виден чётко.
    info (dict) получает итоговый scale."""
    im = adjust(im.convert("RGBA"), **(adj or {}), scale=scale)
    for o in ops:
        if o.get("off"):                        # шаг выключен галкой в окне правки
            continue
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
            im = add_outline(im, max(1, round(o["px"] * scale)), o.get("color", "#ffffff"))
        elif k == "square":
            im = to_square(im, o.get("pad", 0.06), (0, 0, 0, 0))
        elif k == "resize":
            if scale < 1 and o["size"] <= max(im.size):
                scale = 1.0                     # превью дальше - в полном размере
            side = max(1, round(o["size"] * scale))
            f = side / max(im.size)
            im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.LANCZOS)
        elif k == "angle":                      # свободный поворот (выровнять горизонт), deg - по часовой
            w0, h0 = im.size
            im = im.convert("RGBa").rotate(-o["deg"], Image.BICUBIC, expand=True).convert("RGBA")   # RGBa: без тёмной каймы
            if o.get("fit"):                    # срезать прозрачные клинья по углам
                im = im.crop(_inner_box(im.size, w0, h0, o["deg"]))
        elif k == "fill":                       # подложить сплошной цвет под прозрачное
            base = Image.new("RGBA", im.size, hex_rgb(o.get("color", "#ffffff")) + (255,))
            base.alpha_composite(im)
            im = base
        elif k == "pad":                        # поля вокруг: доля длинной стороны, прозрачные или цветом
            m = round(max(im.size) * o.get("k", 0.1))
            fill = hex_rgb(o["color"]) + (255,) if o.get("color") else (0, 0, 0, 0)
            big = Image.new("RGBA", (im.width + 2 * m, im.height + 2 * m), fill)
            big.alpha_composite(im, (m, m))
            im = big
        elif k == "recolor":
            im = recolor(im, o["colors"], o.get("k", 1.0))
        elif k == "defringe":
            im = defringe(im, max(0, round(o.get("px", 1) * max(scale, 0.5))))
        elif k == "brush":
            im = brush(im, o["mode"], o["r"], o["pts"])
        elif k == "shadow":                     # rel: размеры - доли длинной стороны (одинаково на всех файлах)
            u = max(im.size) if o.get("rel") else scale
            im = shadow(im, o["dx"] * u, o["dy"] * u, max(0.5, o["blur"] * u), o.get("a", 0.45),
                        o.get("color", "#000000"))
        elif k == "glow":
            u = max(im.size) if o.get("rel") else scale
            im = shadow(im, 0, 0, max(0.5, o["r"] * u), o.get("a", 0.8), o.get("color", "#ffffff"), spread=True)
        elif k == "round":
            im = round_corners(im, o["rad"])
        elif k == "center":                     # квадрат из середины (аватар, превью)
            side = min(im.size)
            x, y = (im.width - side) // 2, (im.height - side) // 2
            im = im.crop((x, y, x + side, y + side))
    if info is not None:
        info["scale"] = scale
    return im


def _inner_box(size, w, h, deg):
    """Самый большой прямоугольник с пропорцией w:h внутри картинки w×h, повёрнутой на deg
    (size - размер холста после поворота с expand). Без прозрачных клиньев по углам."""
    a = math.radians(abs(deg) % 180)
    if a > math.pi / 2:
        a = math.pi - a
    sin, cos = math.sin(a), math.cos(a)
    long_, short = max(w, h), min(w, h)
    if short <= 2 * sin * cos * long_ or abs(sin - cos) < 1e-10:
        x = 0.5 * short
        wr, hr = (x / sin, x / cos) if w >= h else (x / cos, x / sin)
    else:
        c2 = cos * cos - sin * sin
        wr, hr = (w * cos - h * sin) / c2, (h * cos - w * sin) / c2
    W, H = size
    x0, y0 = (W - wr) / 2, (H - hr) / 2
    return (max(0, math.ceil(x0)), max(0, math.ceil(y0)), min(W, math.floor(x0 + wr)), min(H, math.floor(y0 + hr)))


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
    if rad > 2:                                 # мягкий край кисти, без лесенки
        m = m.filter(ImageFilter.GaussianBlur(min(2.0, rad * 0.15)))
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
    ss = 4                                      # маска вчетверо крупнее и вниз - гладкий край без лесенки
    r = max(1, round(rad * min(im.size) * ss))
    m = Image.new("L", (im.width * ss, im.height * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width * ss - 1, im.height * ss - 1), r, fill=255)
    m = m.resize(im.size, Image.BOX)
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
