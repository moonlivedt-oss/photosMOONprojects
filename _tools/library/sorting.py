"""Нарезка и раскладка: заготовки, метки в имени файла («Космос [ic tokyo]»), имена кусков, запись."""
import os
import re
import shutil

from PIL import Image

import imaging as K
from imaging import neural
from library.common import CLOSING, LIB, archive, clean_name, log_error, procs, short, unique
from library.prompts import set_name
from library.tagging import tag_saved

# Разделы, которых пока нет на диске: папка создаётся при первом сохранении в неё.
PLANNED = ["08 Градиенты", "09 Эффекты и частицы", "10 Рамки и орнаменты", "11 Аватары",
           "12 Медали и достижения", "13 Экраны ошибок и пустоты"]

# имя, настройки нарезки, раздел по умолчанию
PRESETS = [
    ("Лист 4x3 (обводка уже есть)", dict(mode="grid", bg_mode="auto", obv=0, pad=6, size=256, fmt="webp"), "04 Иконки"),
    ("Наклейки (добавить белую обводку)", dict(mode="grid", bg_mode="auto", obv=8, pad=6, size=256, fmt="webp"), "02 Наклейки"),
    ("Иконки (автопоиск рисунков)", dict(mode="auto", bg_mode="auto", obv=0, pad=6, size=256, fmt="webp"), "04 Иконки"),
    ("Частицы на чёрном фоне", dict(mode="auto", bg_mode="keep", obv=0, pad=6, size=256, fmt="webp"), "09 Эффекты и частицы"),
    ("Фон или иллюстрация целиком", dict(mode="whole", bg_mode="keep", obv=0, pad=0, size=1920, fmt="webp"), "01 Фоны"),
    ("Логотип в ICO", dict(mode="whole", bg_mode="keep", obv=0, pad=0, size=0, fmt="ico"), "05 Логотипы"),
]


def process(path, o):
    """Исходник + настройки -> (лист, готовые картинки, рамки на листе)."""
    im = K.load(path)
    rec = o.get("recipe")                   # правка кусков: рецепт из редактора (убрать фон, обводка...)
    if o["mode"] == "whole":
        out = {"remove": K.remove_bg, "ai": neural.remove_bg_ai}.get(o["bg_mode"], lambda a: a)(im)
        if rec:
            out = K.apply_edits(out, rec.get("ops", []), rec.get("adj"))
        if o["size"] and max(out.size) > o["size"]:
            k = o["size"] / max(out.size)
            out = out.resize((round(out.width * k), round(out.height * k)), Image.LANCZOS)
        return im, [out], []
    grid = (o["cols"], o["rows"]) if o["mode"] == "grid" else None
    pieces, boxes = K.cut(im, grid, o["size"], o["bg_mode"], o["obv"], o["pad"] / 100, boxes=o.get("boxes"))
    if rec:                                 # обводка и тень расширяют кусок - снова под нужную сторону
        pieces = [K.resize(K.apply_edits(p, rec.get("ops", []), rec.get("adj")), o["size"]) if o["size"]
                  else K.apply_edits(p, rec.get("ops", []), rec.get("adj")) for p in pieces]
    return im, pieces, boxes


# Кнопка «Имена» в Prompts.html даёт имя вида «Космос [ic tokyo]» или «bg-cozy-lofi-study [bd mocha]»:
# вид картинки и палитра. По ним окно само выбирает нарезку и папку, а 12 имён кусков листа берёт
# из самой страницы промптов (так имя файла остаётся коротким).
PROMPTS = os.path.join(LIB, "Prompts.html")
TAG = re.compile(r"^(.*?)\s*\[([a-z]{2}) ([a-z]+)\]$")
GRID = dict(mode="grid", cols=4, rows=3, bg_mode="auto", obv=0, pad=6, size=256, fmt="webp")


def whole(size, fmt="webp"):
    return dict(mode="whole", cols=4, rows=3, bg_mode="keep", obv=0, pad=0, size=size, fmt=fmt)


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
STOP = set(["a", "an", "the", "of", "with", "and", "in", "on", "at", "to", "for", "from", "by", "under", "over", "near", "into", "its", "is", "no", "very", "that"])
_prompts = {"mt": None, "pals": {}, "sets": {}}


def js_slug(s, n=3):
    """Как slug() в Prompts.html: первые слова без служебных, через дефис."""
    w = [x for x in re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split() if x not in STOP]
    return "-".join(w[:n])


def prompt_data():
    """Палитры и имена кусков листов из Prompts.html (перечитывается, когда страница меняется)."""
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
        text = stem             # лист назван списком имён (кнопка «Имена» в Prompts.html) - берём их
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
    same = (o["mode"] == "whole" and o["bg_mode"] in ("auto", "keep") and len(pieces) == 1 and not o.get("recipe")
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
    names = list(names) + [""] * (len(pieces) - len(names))       # имён меньше - куски не теряются
    try:
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
    except Exception as e:
        e.saved = saved                 # что успело записаться - чтобы Ctrl+Z мог это убрать
        raise
    return saved


def sort_files(items, sigs, keep_src, squeeze, say=None, tagger=None):
    """Нарезать и разложить пачку: items = [(лист, настройки, папка)]. Куски, что уже есть в библиотеке
    или уже встречались в этой же пачке, пропускаются. say(текст) - ход работы (из фонового потока);
    tagger - ставить подсказанные метки (library.tagging.Tagger).
    Возвращает (шаги для Ctrl+Z, сохранено, пропущено повторов, [(лист, ошибка)], {папки})."""
    steps, total, skipped, bad, where, seen = [], 0, 0, [], set(), []
    for n, (f, o, dest) in enumerate(items):
        if CLOSING.is_set():
            break
        if say:
            say("Режу %d из %d: %s" % (n + 1, len(items), os.path.basename(f)))
        try:
            _im, pieces, _b = process(f, dict(o))
            names = default_names(f, len(pieces))
            keep = []
            for i, pc in enumerate(pieces):
                if sigs.find(pc):
                    continue
                sg = K.signature(pc)
                if any(K.same_sig(sg, x) for x in seen):        # тот же рисунок на соседнем листе пачки
                    continue
                seen.append(sg)
                keep.append(i)
            skipped += len(pieces) - len(keep)
            try:
                saved = store(f, o, [pieces[i] for i in keep], [names[i] for i in keep], dest, squeeze)
            except Exception as e:
                steps += [("new", x) for x in getattr(e, "saved", [])]
                raise
            total += len(saved)
            if tagger and saved:
                try:
                    tag_saved(saved, tagger.suggest([pieces[i] for i in keep]))
                except Exception as e:
                    log_error(f"метки для {os.path.basename(f)}: {e}")
            steps += [("new", x) for x in saved]
            where.add(short(dest))
            if keep_src:
                steps.append(("move", f, archive(f)))
        except Exception as e:
            bad.append((f, str(e)))
    return steps, total, skipped, bad, where
