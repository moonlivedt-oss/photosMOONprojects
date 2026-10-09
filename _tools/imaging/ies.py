"""IES-профили света (LM-63-2002) и их превью «пятно на стене».
Профили рисуются формулами, поэтому свои и без лицензий. Unreal: Point/Spot Light -> IES Texture."""

import json
import os

import numpy as np
from PIL import Image

V = np.linspace(0, 180, 181)  # вертикальный угол: 0 - прямо вниз, 180 - вверх
H = np.arange(0, 361, 15)  # горизонтальный: 0 - к стене (для несимметричных)


def smooth(x, a, b):
    """0 до a, 1 после b, плавно между."""
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def gauss(x, mu, s):
    return np.exp(-0.5 * ((x - mu) / s) ** 2)


# имя -> (описание, функция (v, h) -> сила света 0..1); h - None у симметричных
PROFILES = {
    "Широкий конус": (
        "Мягкий широкий свет вниз, край растушёван - общий свет комнаты",
        lambda v, h: np.cos(np.radians(np.minimum(v, 90))) ** 1.5 * (1 - smooth(v, 55, 80)),
    ),
    "Узкий луч": (
        "Яркое узкое пятно со слабым ореолом - акцент на предмет, сцена",
        lambda v, h: gauss(v, 0, 7) + 0.08 * gauss(v, 0, 25),
    ),
    "Прожектор с кольцом": (
        "Пятно и светлое кольцо вокруг - как у дешёвого фонарика",
        lambda v, h: gauss(v, 0, 9) + 0.45 * gauss(v, 24, 4) + 0.05 * (1 - smooth(v, 30, 60)),
    ),
    "Кольца": (
        "Несколько колец, расходящихся от центра - декоративные бра",
        lambda v, h: (0.55 + 0.45 * np.cos(np.radians(v) * 14)) * (1 - smooth(v, 40, 75)),
    ),
    "Даунлайт с резким краем": (
        "Ровное пятно с чёткой границей - встроенный потолочный светильник",
        lambda v, h: 1 - smooth(v, 28, 32),
    ),
    "Лампочка": (
        "Почти во все стороны, сверху тень цоколя - голая лампа накаливания",
        lambda v, h: 0.85 + 0.15 * np.cos(np.radians(v)) - 0.85 * smooth(v, 140, 175),
    ),
    "Вверх и вниз": (
        "Два луча - вверх и вниз по стене: настенное бра «цилиндр»",
        lambda v, h: gauss(v, 0, 16) + gauss(v, 180, 16) * 0.9,
    ),
    "Уличный фонарь": (
        "Крылья в стороны (batwing): ровно освещает дорогу, под фонарём не слепит",
        lambda v, h: (0.35 + 0.65 * gauss(v, 62, 14)) * (1 - smooth(v, 78, 88)),
    ),
    "Полосы": (
        "Полосатый свет, как сквозь решётку или жалюзи",
        lambda v, h: (0.25 + 0.75 * (np.sin(np.radians(v) * 30) > 0)) * (1 - smooth(v, 50, 80)),
    ),
    "Мягкий ореол": (
        "Тусклое широкое свечение без пятна - свеча, ночник, магический огонь",
        lambda v, h: 0.6 + 0.4 * np.sin(np.radians(v)) - 0.3 * smooth(v, 150, 180),
    ),
    "Настенный омыватель": (
        "Свет, вытянутый в одну сторону - подсветка стены снизу (wall washer)",
        lambda v, h: gauss(v, 35, 18) * (0.15 + 0.85 * np.cos(np.radians(h) / 2) ** 4),
    ),
    "Овальное пятно": (
        "Вытянутый луч - фары, подсветка картины, коридор",
        lambda v, h: gauss(v, 0, 8 + 12 * np.abs(np.cos(np.radians(h)))),
    ),
}
ASYM = {"Настенный омыватель", "Овальное пятно"}
PEAK = 1500.0  # кандел в самой яркой точке


def table(name):
    """-> (горизонтальные углы, матрица [h][v] в канделах)."""
    fn = PROFILES[name][1]
    if name in ASYM:
        hh = H
        m = np.array([fn(V, float(h)) for h in hh])
    else:
        hh = np.array([0])
        m = np.array([fn(V, None)])
    m = np.clip(np.nan_to_num(m), 0, None)
    return hh, m / max(m.max(), 1e-9) * PEAK


def ies_text(name):
    hh, m = table(name)

    def rows(vals):
        vals = ["%g" % round(float(x), 2) for x in vals]
        return "\n".join(" ".join(vals[i : i + 10]) for i in range(0, len(vals), 10))

    out = [
        "IESNA:LM-63-2002",
        "[TEST] generated",
        "[MANUFAC] Moon image library",
        f"[LUMCAT] {translit(name)}",
        f"[LUMINAIRE] {translit(PROFILES[name][0])}",
        "TILT=NONE",
        # ламп, люмен (-1 = абсолютная фотометрия), множитель, углов по вертикали и горизонтали,
        # тип C, единицы - метры, размеры светящей части
        f"1 -1 1 {len(V)} {len(hh)} 1 2 0.05 0.05 0",
        "1 1 100",
        rows(V),
        rows(hh),
    ]
    out += [rows(r) for r in m]
    return "\n".join(out) + "\n"


def preview(name, w=384, h=384):
    """Пятно на стене: источник в 0.4 м от стены у верхнего края, светит вниз."""
    hh, m = table(name)
    x = np.linspace(-2.2, 2.2, w)
    z = np.linspace(0.6, -3.8, h)
    X, Z = np.meshgrid(x, z)
    D = 0.4
    r = np.sqrt(X * X + D * D + Z * Z)
    v = np.degrees(np.arccos(np.clip(-Z / r, -1, 1)))
    hdeg = (np.degrees(np.arctan2(X, D)) + 360) % 360
    vi = np.clip(v, 0, 180)
    if len(hh) == 1:
        cd = np.interp(vi, V, m[0])
    else:
        # билинейно по двум углам
        hf = hdeg / 15.0
        h0 = np.floor(hf).astype(int) % (len(hh) - 1)
        t = hf - np.floor(hf)
        a = np.array([np.interp(vi.ravel(), V, m[i]) for i in range(len(hh))])
        idx = np.arange(vi.size)
        cd = ((1 - t.ravel()) * a[h0.ravel(), idx] + t.ravel() * a[h0.ravel() + 1, idx]).reshape(vi.shape)
    e = cd * (D / r) / (r * r)
    e = e / np.percentile(e, 99.7)
    lum = 1 - np.exp(-1.6 * e)
    warm = np.array([255, 214, 160]) / 255.0
    wall = np.array([28, 26, 34]) / 255.0
    img = wall + lum[..., None] * (warm - wall * 0.6)
    img = np.clip(img, 0, 1) ** (1 / 1.2)
    return Image.fromarray((img * 255).astype(np.uint8), "RGB")


def write_all(root):
    """Все профили: root/<имя>/<имя>.ies + preview.webp + asset.json. -> [папки]."""
    out = []
    for name, (desc, _fn) in PROFILES.items():
        d = os.path.join(root, "Свои профили", name)
        os.makedirs(d, exist_ok=True)
        fn = "IES_" + translit(name).replace(" ", "_") + ".ies"  # имя ассета в Unreal - латиницей
        with open(os.path.join(d, fn), "w", encoding="ascii", newline="\r\n") as fh:
            fh.write(ies_text(name))
        preview(name).save(os.path.join(d, "preview.webp"), quality=90)
        meta = {
            "id": "ies-" + translit(name).lower().replace(" ", "-"),
            "name": name,
            "kind": "ies",
            "theme": "Свои профили",
            "source": "Сгенерировано библиотекой",
            "url": "",
            "license": "свой, без ограничений",
            "authors": [],
            "tags": ["свет", "ies"],
            "description": desc,
            "main": [fn],
            "res": "",
            "added": "",
            "size": os.path.getsize(os.path.join(d, fn)),
        }
        with open(os.path.join(d, "asset.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
        out.append(d)
    return out


TR = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        [
            "a",
            "b",
            "v",
            "g",
            "d",
            "e",
            "e",
            "zh",
            "z",
            "i",
            "y",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "r",
            "s",
            "t",
            "u",
            "f",
            "h",
            "ts",
            "ch",
            "sh",
            "sch",
            "",
            "y",
            "",
            "e",
            "yu",
            "ya",
        ],
    )
)


def translit(s):
    """Внутри .ies - только ASCII: старые программы спотыкаются о кириллицу."""
    out = "".join((TR[c.lower()].capitalize() if c.isupper() else TR[c]) if c.lower() in TR else c for c in s)
    return out.replace("«", '"').replace("»", '"')
