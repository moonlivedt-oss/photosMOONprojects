"""Нарезка и раскладка: заготовки, метки в имени файла («Космос [ic tokyo]»), имена кусков, запись."""
import os
import re
import shutil

import картинки as K
from PIL import Image

from окно.общее import LIB, clean_name, procs, unique

# Разделы, которых пока нет на диске: папка создаётся при первом сохранении в неё.
PLANNED = ["08 Градиенты", "09 Эффекты и частицы", "10 Рамки и орнаменты", "11 Аватары",
           "12 Медали и достижения", "13 Экраны ошибок и пустоты"]

# имя, настройки нарезки, раздел по умолчанию
PRESETS = [
    ("Лист 4x3 (обводка уже есть)", dict(mode="grid", fon="auto", obv=0, pad=6, size=256, fmt="webp"), "04 Иконки"),
    ("Наклейки (добавить белую обводку)", dict(mode="grid", fon="auto", obv=8, pad=6, size=256, fmt="webp"), "02 Наклейки"),
    ("Иконки (автопоиск рисунков)", dict(mode="auto", fon="auto", obv=0, pad=6, size=256, fmt="webp"), "04 Иконки"),
    ("Частицы на чёрном фоне", dict(mode="auto", fon="ostavit", obv=0, pad=6, size=256, fmt="webp"), "09 Эффекты и частицы"),
    ("Фон или иллюстрация целиком", dict(mode="whole", fon="ostavit", obv=0, pad=0, size=1920, fmt="webp"), "01 Фоны"),
    ("Логотип в ICO", dict(mode="whole", fon="ostavit", obv=0, pad=0, size=0, fmt="ico"), "05 Логотипы"),
]


def process(path, o):
    """Исходник + настройки -> (лист, готовые картинки, рамки на листе)."""
    im = K.load(path)
    if o["mode"] == "whole":
        out = K.remove_bg(im) if o["fon"] == "ubrat" else im
        if o["size"] and max(out.size) > o["size"]:
            k = o["size"] / max(out.size)
            out = out.resize((round(out.width * k), round(out.height * k)), Image.LANCZOS)
        return im, [out], []
    setka = (o["cols"], o["rows"]) if o["mode"] == "grid" else None
    pieces, boxes = K.cut(im, setka, o["size"], o["fon"], o["obv"], o["pad"] / 100)
    return im, pieces, boxes


# ---------------------------------------------------------------- раскладка по метке в имени файла
# Кнопка «Имена» в Промпты.html даёт имя вида «Космос [ic tokyo]» или «bg-cozy-lofi-study [bd mocha]»:
# вид картинки и палитра. По ним окно само выбирает нарезку и папку, а 12 имён кусков листа берёт
# из самой страницы промптов (так имя файла остаётся коротким).
PROMPTS = os.path.join(LIB, "Промпты.html")
TAG = re.compile(r"^(.*?)\s*\[([a-z]{2}) ([a-z]+)\]$")
GRID = dict(mode="grid", cols=4, rows=3, fon="auto", obv=0, pad=6, size=256, fmt="webp")


def whole(size, fmt="webp"):
    return dict(mode="whole", cols=4, rows=3, fon="ostavit", obv=0, pad=0, size=size, fmt=fmt)


# вид: (папка, нарезка). {set} - набор (лист), {pal} - папка палитры.
ROUTES = {
    "ic": ("04 Иконки/{set}/{pal}", GRID),
    "st": ("02 Наклейки/{set}/{pal}", GRID),
    "po": ("03 Маскоты/{set}", GRID),
    "md": ("12 Медали и достижения/{set}/{pal}", GRID),
    "av": ("11 Аватары/{set}/{pal}", GRID),
    "ma": ("03 Маскоты/Новый стиль", whole(1024)),
    "sc": ("06 Иллюстрации/Онбординг", whole(1024)),
    "sp": ("06 Иллюстрации/Заставки", whole(1920)),
    "bd": ("01 Фоны/Ночные сцены/{pal}", whole(1920)),
    "bl": ("01 Фоны/Светлые/{pal}", whole(1920)),
    "pa": ("07 Паттерны и текстуры/{pal}", whole(0)),
    "gr": ("08 Градиенты/{pal}", whole(1920)),
    "em": ("13 Экраны ошибок и пустоты/{pal}", whole(768)),
    "es": ("13 Экраны ошибок и пустоты/{set}/{pal}", GRID),
    "so": ("06 Иллюстрации/Онбординг", dict(GRID, cols=3, rows=2)),
    "me": ("12 Медали и достижения/{pal}", whole(512)),
    "aa": ("11 Аватары/{pal}", whole(512)),
    "fx": ("09 Эффекты и частицы/{pal}", dict(GRID, rows=4)),
    "fr": ("10 Рамки и орнаменты/{pal}", whole(1920)),
    "lo": ("05 Логотипы", whole(0, "ico")),
    "co": ("06 Иллюстрации/Обложки", whole(1920)),
}
STOP = set("a an the of with and in on at to for from by under over near into its is no very that".split())
_prompts = {"mt": None, "pals": {}, "sets": {}}


def js_slug(s, n=3):
    """Как slug() в Промпты.html: первые слова без служебных, через дефис."""
    w = [x for x in re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split() if x not in STOP]
    return "-".join(w[:n])


def set_name(title):
    """Как setName() в Промпты.html: «Интерфейс: основное» -> «Интерфейс - основное», «Новый год: лист» -> «Новый год»."""
    t = re.sub(r"\s*\(.*?\)", "", title)
    if re.match(r"^(Новый год|Хэллоуин|Весна|Лето|Осень|День рождения):", t):
        return t.split(":")[0]
    return t.replace(": ", " - ")


def prompt_data():
    """Палитры и имена кусков листов из Промпты.html (перечитывается, когда страница меняется)."""
    try:
        mt = os.path.getmtime(PROMPTS)
    except OSError:
        return {}, {}
    if _prompts["mt"] != mt:
        with open(PROMPTS, encoding="utf-8") as fh:
            text = fh.read()
        pals = dict(re.findall(r'^\s*\["(\w+)","([^"]+)","', text, re.M))
        sets = {}
        for m in re.finditer(r'\["([^"]+)",\s*(?:as\()?(sheet|zoo|poses|empties|scenes)\(\[(.*?)\](?:,\s*\[(.*?)\])?',
                             text, re.S):
            title, fn, a, b = m.groups()
            named = fn in ("poses", "empties", "scenes")        # у этих имена кусков заданы вторым списком
            items = re.findall(r'"([^"]*)"', b if named and b else a)
            names = items if named else [js_slug(x) for x in items]
            key = set_name(title)
            sets[key] = names
            sets[({"sheet": "ic", "zoo": "st", "poses": "po", "empties": "es", "scenes": "so"}[fn], key)] = names
        _prompts.update(mt=mt, pals=pals, sets=sets)
    return _prompts["pals"], _prompts["sets"]


def sheet_names(kind, text):
    _pals, sets = prompt_data()
    return sets.get((kind, text)) or sets.get(text)


def route(path):
    """Метка в имени файла -> dict(dest, o, names, text) или None."""
    m = TAG.match(os.path.splitext(os.path.basename(path))[0])
    if not m or m.group(2) not in ROUTES:
        return None
    text, kind, pal = m.groups()
    pals, _sets = prompt_data()
    tpl, o = ROUTES[kind]
    rel = tpl.format(set=clean_name(text), pal=clean_name(pals.get(pal, pal)))
    names = sheet_names(kind, text) if o["mode"] == "grid" and kind != "fx" else None
    return dict(dest=os.path.join(LIB, *rel.split("/")), o=dict(o), names=names, text=text)


def default_names(path, n, text=""):
    """Имена по порядку: из метки листа, список через запятую, общий префикс или имя листа."""
    stem = os.path.splitext(os.path.basename(path))[0]
    for src in (text.strip(), stem):
        m = TAG.match(src)
        if m:
            listed = sheet_names(m.group(2), m.group(1))
            if listed and len(listed) == n and (src == text.strip() or not text):
                return [clean_name(x) for x in listed]
            if src == text.strip():
                text = m.group(1)
            else:
                stem = m.group(1)
    if not text and stem.count(",") == n - 1 and n > 1:
        text = stem             # лист назван списком имён (кнопка «Имена» в Промпты.html) - берём их
    listed = [clean_name(x) for x in text.split(",")] if "," in text else []
    prefix = clean_name(text) if text and not listed else stem
    out = []
    for i in range(n):
        if i < len(listed) and listed[i]:
            out.append(listed[i])
        else:
            out.append(prefix if n == 1 else "%s_%02d" % (prefix, i + 1))
    return out


SQUEEZE = dict(q=0, target=0.99, kind="auto")     # сжатие при раскладке: качество на глаз


def store(path, o, pieces, names, dest, squeeze=False):
    """Пишет картинки в раздел. Нетронутый файл нужного формата копируется без пережатия.
    squeeze - сразу сжать с подбором качества (по ядрам), чтобы раздел «Тяжёлые» не копился."""
    os.makedirs(dest, exist_ok=True)
    same = (o["mode"] == "whole" and o["fon"] != "ubrat" and len(pieces) == 1
            and os.path.splitext(path)[1].lower() == "." + o["fmt"])
    if same:
        same = K.size_of(path) == pieces[0].size
    packed = [None] * len(pieces)
    if squeeze and not same and o["fmt"] in ("webp", "avif", "png", "jpg"):
        try:
            packed = [d for d, _i in procs().map(K.job_image, pieces, [dict(SQUEEZE, fmt=o["fmt"])] * len(pieces))]
        except Exception:
            packed = [None] * len(pieces)        # не вышло по ядрам - сохраним как обычно
    saved = []
    for im, name, data in zip(pieces, names, packed):
        p = unique(os.path.join(dest, (clean_name(name) or "без имени") + "." + o["fmt"]))
        if same:
            shutil.copy2(path, p)
        elif data is not None:
            with open(p, "wb") as fh:
                fh.write(data)
        else:
            K.save(im, p, o["fmt"])
        saved.append(p)
    return saved
