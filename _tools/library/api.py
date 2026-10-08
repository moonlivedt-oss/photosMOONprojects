"""Операции с библиотекой для ИИ-помощников и командной строки: найти, посмотреть, поставить метки,
переименовать, разложить, поправить, убрать фон, увеличить, нарезать лист, выгрузить в проект.

Каждая операция - функция с описанием и JSON-схемой параметров (TOOLS). Сервер mcp_server.py отдаёт
их помощникам (Claude, Cursor и др.), `cli.py api` - любой программе. Пути - относительно корня
библиотеки, через «/». Всё, что меняет файлы, метки или избранное, пишется в журнал: окно видит это
сразу и отменяет Ctrl+Z, помощник отменяет сам (undo). Удалённое помощником не стирается, а лежит
в _sources/_deleted. В настройках окна доступ на запись можно выключить (ai_write)."""

import io
import os
import shutil
import time

import numpy as np
from PIL import Image, ImageDraw

import imaging as K
import library.common as C
from imaging import clip, neural
from library import batch, db, journal, prompts, sorting
from library.semantic import SemIndex
from library.signatures import SigIndex
from library.tagging import Tagger

AGENT = {"who": "ИИ-помощник"}  # имя автора в журнале; сервер ставит имя клиента (Claude Code и т. п.)
TOOLS = {}
MAX_VIEW = 36  # картинок на одном листе просмотра


class ApiError(Exception):
    """Понятная ошибка для помощника: что не так и как исправить."""


class Picture:
    """Картинка в ответе: сервер отдаёт её помощнику как изображение, командная строка - файлом."""

    def __init__(self, im, text=""):
        self.im, self.text = im, text

    def png(self):
        buf = io.BytesIO()
        self.im.save(buf, "PNG", optimize=True)
        return buf.getvalue()


def tool(name, desc, props=None, required=(), write=False):
    def deco(fn):
        TOOLS[name] = dict(
            fn=fn,
            desc=desc,
            write=write,
            schema={"type": "object", "properties": props or {}, "required": list(required)},
        )
        return fn

    return deco


def write_allowed():
    return C.load_cfg().get("ai_write", True)


def call(name, args=None):
    """Выполнить операцию по имени. -> результат (dict/list/Picture) или ApiError."""
    t = TOOLS.get(name)
    if not t:
        raise ApiError(f"Нет операции «{name}». Список - tools.")
    if t["write"] and not write_allowed():
        raise ApiError(
            "Изменять библиотеку помощникам запрещено в окне (ИИ-помощники -> «Только чтение»). "
            "Искать и смотреть можно."
        )
    args = dict(args or {})
    known = t["schema"]["properties"]
    extra = [k for k in args if k not in known]
    if extra:
        raise ApiError(f"Лишние параметры: {', '.join(extra)}. Есть: {', '.join(known) or 'нет'}.")
    missing = [k for k in t["schema"]["required"] if k not in args]
    if missing:
        raise ApiError(f"Не хватает параметров: {', '.join(missing)}.")
    return t["fn"](**args)


# ---------------------------------------------------------------- пути
def rel(p):
    """Путь для помощника: от корня библиотеки, через «/»."""
    return key(p).replace(os.sep, "/")


def key(p):
    """Путь для базы: как у окна (от корня, через обратную косую черту в Windows)."""
    return os.path.relpath(p, C.LIB)


def absolute(path, must_exist=True, inside=True):
    """Путь от помощника (относительный от корня библиотеки или полный) -> полный путь."""
    if not isinstance(path, str) or not path.strip():
        raise ApiError("Пустой путь.")
    p = os.path.normpath(path if os.path.isabs(path) else os.path.join(C.LIB, path.replace("/", os.sep)))
    if inside:
        try:
            r = key(p)
        except ValueError:
            r = ".."
        if r.startswith(".."):
            raise ApiError(f"«{path}» - не из библиотеки ({C.LIB}).")
    if must_exist and not os.path.exists(p):
        hint = ""
        base = os.path.splitext(os.path.basename(p))[0].lower()
        near = [rel(f) for f in K.images_in(C.LIB) if len(base) > 2 and base in os.path.basename(f).lower()][:5]
        if near:
            hint = " Похожие по имени: " + "; ".join(near)
        raise ApiError(f"Нет файла «{path}».{hint}")
    return p


def images(paths, limit=200):
    if isinstance(paths, str):
        paths = [paths]
    if not paths:
        raise ApiError("Не задано ни одной картинки (paths).")
    if len(paths) > limit:
        raise ApiError(f"Слишком много за раз: {len(paths)}, можно до {limit}.")
    out = [absolute(p) for p in paths]
    for p in out:
        if not os.path.isfile(p) or not p.lower().endswith(K.EXT):
            raise ApiError(f"«{rel(p)}» - не картинка.")
    return out


def folder_path(folder, create=False):
    """Папка внутри библиотеки (не служебная, не входящие)."""
    p = absolute(folder, must_exist=not create)
    r = rel(p)
    if r == "." or any(part.startswith("_") for part in r.split("/")) or r.split("/")[0] == K.INBOX:
        raise ApiError(f"«{folder}» - служебная папка или корень. Нужен раздел, например «04 Иконки/Космос».")
    if create:
        os.makedirs(p, exist_ok=True)
    elif not os.path.isdir(p):
        raise ApiError(f"«{folder}» - не папка.")
    return p


def item(p, score=None, favs=None):
    """Сведения о картинке для списка."""
    st = os.stat(p)
    out = dict(
        path=rel(p),
        name=os.path.splitext(os.path.basename(p))[0],
        folder=rel(os.path.dirname(p)),
        format=K.fmt_of(p),
        kb=round(st.st_size / 1024, 1),
    )
    try:
        if not p.lower().endswith(".svg"):
            out["width"], out["height"] = K.size_of(p)
    except Exception:
        pass
    r = key(p)
    tags = db.tags_of(r)
    if tags:
        out["tags"] = tags
    if r in (favs if favs is not None else db.favs()):
        out["favorite"] = True
    if score is not None:
        out["score"] = round(score, 4)
    return out


def record(text, steps):
    jid = journal.record(AGENT["who"], text, steps)
    return {"journal_id": jid, "undo": "undo(id=%d) или Ctrl+Z в окне" % jid} if jid else {}


# ---------------------------------------------------------------- индексы (общие с окном через базу)
_shared = {"queries": {}, "tagger": None}


def sem_index(update=True):
    s = SemIndex(C.LIB)
    if not s.ok:
        return s
    s._queries = _shared["queries"]
    if update:
        s.refresh()
    return s


def sig_index():
    s = SigIndex(C.LIB)
    s.refresh()
    return s


def tagger(sem):
    t = _shared["tagger"]
    if t is None:
        t = _shared["tagger"] = Tagger(sem)
    t.sem, t.bias = sem, None
    return t


# ---------------------------------------------------------------- обзор
RULES = """Как устроена библиотека:
- разделы по ТИПАМ картинок, а не по проектам: 01 Фоны, 02 Наклейки, 03 Маскоты, 04 Иконки, 05 Логотипы,
  06 Иллюстрации, 07 Паттерны и текстуры, 10 Рамки и орнаменты...; наборы - <раздел>/<набор>/<палитра>/;
- имена картинок короткие, по смыслу (английские slug или русские слова), без номеров версий;
- метки - строчными, «е» вместо «ё», без #; несколько слов можно («для сайта»);
- 00 Входящие - неразобранные листы: cut_sheet режет их и раскладывает, исходник уходит в _sources;
- папки на «_» служебные (оригиналы до правки и сжатия, удалённое) - их не трогать;
- каждое изменение отменяется: undo (последнее своё) или Ctrl+Z в окне;
- перед правкой полезно посмотреть результат: edit(mode="preview"), cut_sheet(preview=true)."""


@tool(
    "overview",
    "Обзор библиотеки: разделы с числом картинок и подпапками, частые метки, умные папки, "
    "входящие, какие нейросети есть, правила раскладки. Начинать работу с него.",
)
def overview():
    secs = []
    for name in sorted(os.listdir(C.LIB)):
        p = os.path.join(C.LIB, name)
        if not os.path.isdir(p) or name.startswith((".", "_")) or name == K.INBOX:
            continue
        subs = sorted(d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d)) and not d.startswith("_"))
        secs.append(
            dict(path=name, images=len(K.images_in(p)), subfolders=subs[:40], more_subfolders=max(0, len(subs) - 40))
        )
    tags = db.all_tags().most_common(60)
    try:
        inbox = [os.path.basename(f) for f in C.inbox_files()]
    except OSError:
        inbox = []
    return dict(
        root=C.LIB,
        version=C.VERSION,
        images=sum(s["images"] for s in secs),
        sections=secs,
        top_tags={t: n for t, n in tags},
        favorites=len(db.favs()),
        smart_folders=[dict(name=n, query=q, color=c, semantic=s) for n, q, c, s in db.smart_folders()],
        inbox=inbox,
        models=dict(
            semantic_search=clip.available(),
            remove_background=neural.bg_available(),
            upscale=neural.upscale_available(),
        ),
        colors={c: n for c, n, _h in K.COLORS},
        write_allowed=write_allowed(),
        rules=RULES,
    )


@tool(
    "list_folder",
    "Что лежит в папке библиотеки: подпапки (с числом картинок) и картинки.",
    {
        "folder": {"type": "string", "description": "папка от корня, например «04 Иконки/Космос»; пусто - корень"},
        "limit": {"type": "integer", "default": 100},
        "offset": {"type": "integer", "default": 0},
    },
)
def list_folder(folder="", limit=100, offset=0):
    p = absolute(folder) if folder else C.LIB
    if not os.path.isdir(p):
        raise ApiError(f"«{folder}» - не папка.")
    dirs, files = [], []
    for name in sorted(os.listdir(p)):
        f = os.path.join(p, name)
        if name.startswith((".", "_")):
            continue
        if os.path.isdir(f):
            dirs.append(dict(path=rel(f), images=len(K.images_in(f))))
        elif C.is_image(name):
            files.append(f)
    favs = db.favs()
    return dict(
        folder=rel(p) if p != C.LIB else "",
        subfolders=dirs,
        total_images=len(files),
        images=[item(f, favs=favs) for f in files[offset : offset + limit]],
    )


# ---------------------------------------------------------------- поиск
@tool(
    "search",
    "Найти картинки. query - слова (все должны встретиться в пути, имени, метках или заметке; "
    "«-слово» исключает) или описание по смыслу («уютная ночная улица», «грустный кот»; по-русски и "
    "по-английски; одно слово лучше по-английски - «owl», а не «сова» - или фразой). semantic: auto - по словам, а если ничего - по смыслу; true - только по смыслу; "
    "false - только по словам. Фильтры: color, tag, folder, favorites.",
    {
        "query": {"type": "string", "default": ""},
        "semantic": {"type": "string", "enum": ["auto", "true", "false"], "default": "auto"},
        "color": {"type": "string", "description": "код цвета: r o y g c b v p w k (см. overview.colors)"},
        "tag": {"type": "string"},
        "folder": {"type": "string", "description": "искать только в этой папке"},
        "favorites": {"type": "boolean", "default": False},
        "sort": {"type": "string", "enum": ["relevance", "name", "new", "size"], "default": "relevance"},
        "limit": {"type": "integer", "default": 40},
        "offset": {"type": "integer", "default": 0},
    },
)
def search(
    query="", semantic="auto", color=None, tag=None, folder=None, favorites=False, sort="relevance", limit=40, offset=0
):
    semantic = str(semantic).lower()
    base = K.images_in(folder_path(folder) if folder else C.LIB)
    favs = db.favs()
    if favorites:
        base = [p for p in base if key(p) in favs]
    if tag:
        tagged = set(db.with_tag(db.clean_tag(tag)))
        base = [p for p in base if key(p) in tagged]
    tokens = query.lower().replace("ё", "е").split()
    minus = [t[1:] for t in tokens if t.startswith("-") and len(t) > 1]
    words = [t.lstrip("#") for t in tokens if not t.startswith("-")]
    scores, mode, files = {}, "all", base
    if words and semantic != "true":
        extra = db.search_text()

        def hit(p):
            r = key(p)
            s = r.lower().replace("ё", "е") + " " + extra.get(r, "")
            return all(w in s for w in words) and not any(w in s for w in minus)

        files, mode = [p for p in base if hit(p)], "words"
    if words and (semantic == "true" or (semantic == "auto" and not files)):
        sem = sem_index()
        if not sem.ready():
            if semantic == "true":
                raise ApiError("Поиск по смыслу недоступен: нет моделей (py -3.14 _tools/get_models.py clip).")
        else:
            keep = set(base)
            ranked = [(p, s) for p, s in sem.rank(" ".join(words), top=300) if p in keep][:100]
            ranked = [(p, s) for p, s in ranked if not any(w in rel(p).lower() for w in minus)]
            files, scores, mode = [p for p, _s in ranked], dict(ranked), "meaning"
    elif minus and not words:
        files = [p for p in base if not any(w in rel(p).lower() for w in minus)]
    if color:
        sigs = sig_index()
        files = [p for p in files if sigs.has_color(p, color)]
    if sort == "name" or (sort == "relevance" and mode != "meaning"):
        files.sort(key=lambda p: rel(p).lower())
    elif sort == "new":
        files.sort(key=os.path.getmtime, reverse=True)
    elif sort == "size":
        files.sort(key=os.path.getsize, reverse=True)
    out = dict(
        total=len(files), mode=mode, items=[item(p, scores.get(p), favs) for p in files[offset : offset + limit]]
    )
    if mode == "meaning" and semantic == "auto":
        out["note"] = "По словам ничего не нашлось - показано по смыслу."
    if not files:
        out["note"] = "Ничего. Попробуйте другие слова, semantic=true или overview (какие есть разделы и метки)."
    return out


@tool(
    "similar",
    "Похожие картинки: by=meaning - по смыслу (CLIP), by=look - по виду (тот же рисунок, "
    "другой размер или палитра). path может быть и файлом не из библиотеки (только meaning).",
    {
        "path": {"type": "string"},
        "by": {"type": "string", "enum": ["meaning", "look"], "default": "meaning"},
        "limit": {"type": "integer", "default": 20},
    },
    ["path"],
)
def similar(path, by="meaning", limit=20):
    p = absolute(path, inside=False)
    if by == "look":
        sigs = sig_index()
        found = sigs.similar(p, limit)
    else:
        sem = sem_index()
        if not sem.ready():
            raise ApiError("Нет моделей поиска по смыслу (py -3.14 _tools/get_models.py clip).")
        if sem._rel(p) not in sem.data:
            sem.embed_file(p)
        found = sem.similar(p, limit)
    favs = db.favs()
    return dict(path=path, by=by, items=[item(f, favs=favs) for f in found])


# ---------------------------------------------------------------- сведения и просмотр
@tool(
    "info",
    "Всё о картинке: размер, формат, вес, прозрачность, рисунок или фото, главные цвета, метки, "
    "заметка, избранное, куда выгружалась, дата.",
    {"path": {"type": "string"}},
    ["path"],
)
def info(path):
    p = images(path)[0]
    out = item(p)
    out["modified"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))
    if not p.lower().endswith(".svg"):
        im = K.load(p)
        out.update(
            alpha=bool(K.has_alpha(im)),
            kind="art" if K.is_art(im) else "photo",
            animated=K.is_animated(p),
            colors=K.main_colors(p),
        )
    note = db.note_of(key(p))
    if note:
        out["note"] = note
    ex = db.exports_of(key(p))
    if ex:
        out["exported_to"] = [d for d, _t in ex]
    return out


def checker(size, cell=12):
    a = (np.indices((size[1], size[0])) // cell).sum(0) % 2
    g = np.where(a[..., None] == 1, np.uint8(66), np.uint8(40)).repeat(3, -1)
    return Image.fromarray(g, "RGB").convert("RGBA")


def on_checker(im):
    """Прозрачное - на шахматке: так помощник видит, где фон убран."""
    if not K.has_alpha(im):
        return im.convert("RGB")
    base = checker(im.size)
    base.alpha_composite(im)
    return base.convert("RGB")


def sheet(ims, labels, cell=176, mark=None):
    """Лист превью с номерами: помощник ссылается на картинки по номеру."""
    n = len(ims)
    cols = max(1, min(6, round((n * 1.5) ** 0.5 + 0.5)))
    rows = (n + cols - 1) // cols
    pad, cap = 10, 22
    out = Image.new("RGB", (cols * (cell + pad) + pad, rows * (cell + cap + pad) + pad), (21, 21, 28))
    d = ImageDraw.Draw(out)
    font = K.sprites._font(13)
    for i, (im, label) in enumerate(zip(ims, labels)):
        x, y = pad + (i % cols) * (cell + pad), pad + (i // cols) * (cell + cap + pad)
        tile = checker((cell, cell))
        if im is not None:
            im = im.copy()
            im.thumbnail((cell - 8, cell - 8), Image.LANCZOS)
            tile.alpha_composite(im.convert("RGBA"), ((cell - im.width) // 2, (cell - im.height) // 2))
        out.paste(tile.convert("RGB"), (x, y))
        if mark and mark[i]:
            d.rectangle((x, y, x + cell - 1, y + cell - 1), outline=(240, 190, 80), width=3)
            d.text((x + cell - 6, y + 6), mark[i], fill=(240, 190, 80), font=font, anchor="ra")
        d.rounded_rectangle((x + 4, y + 4, x + 30, y + 22), 6, fill=(20, 20, 28))
        d.text((x + 17, y + 13), str(i + 1), fill=(230, 228, 240), font=font, anchor="mm")
        while d.textlength(label, font=font) > cell and len(label) > 4:
            label = label[:-2]
        d.text((x + cell / 2, y + cell + 4), label, fill=(220, 218, 232), font=font, anchor="ma")
    return out


def load_any(p):
    if p.lower().endswith(".svg"):
        return None
    return K.load(p)


@tool(
    "view",
    "Посмотреть картинки (вернёт изображение). Одна - крупно (size до 1024), несколько - лист "
    f"с номерами (до {MAX_VIEW}). Прозрачное показано на шахматке.",
    {
        "paths": {"type": "array", "items": {"type": "string"}},
        "size": {"type": "integer", "default": 512, "description": "сторона для одной картинки"},
    },
    ["paths"],
)
def view(paths, size=512):
    ps = images(paths, MAX_VIEW)
    if len(ps) == 1:
        im = load_any(ps[0])
        if im is None:
            raise ApiError("svg не показывается - он векторный; info() расскажет о нём.")
        w, h = im.size
        im.thumbnail((max(64, min(1024, size)),) * 2, Image.LANCZOS)
        return Picture(on_checker(im), f"{rel(ps[0])}  {w}x{h}")
    ims = [load_any(p) for p in ps]
    text = "\n".join("%d. %s" % (i + 1, rel(p)) for i, p in enumerate(ps))
    return Picture(sheet(ims, [os.path.splitext(os.path.basename(p))[0] for p in ps]), text)


# ---------------------------------------------------------------- метки, заметки, избранное
@tool(
    "suggest_tags",
    "Подсказать метки по смыслу картинки (словарь частых меток и метки похожих картинок). Ставит tag().",
    {"paths": {"type": "array", "items": {"type": "string"}}},
    ["paths"],
)
def suggest_tags(paths):
    ps = images(paths, 100)
    sem = sem_index()
    if not sem.ok:
        raise ApiError("Нет моделей поиска по смыслу (py -3.14 _tools/get_models.py clip).")
    t = tagger(sem)
    out = {}
    for p in ps:
        v = sem.vecs_of([p])
        if not len(v):
            v = np.asarray([sem.embed_file(p)], np.float32)
        out[rel(p)] = t.suggest_vecs(v, set(db.tags_of(key(p))))
    return out


@tool(
    "tag",
    "Метки картинок: add - добавить, remove - убрать, set - заменить все. Метки ищутся search() и видны в дереве окна.",
    {
        "paths": {"type": "array", "items": {"type": "string"}},
        "add": {"type": "array", "items": {"type": "string"}},
        "remove": {"type": "array", "items": {"type": "string"}},
        "set": {"type": "array", "items": {"type": "string"}},
    },
    ["paths"],
    write=True,
)
def tag(paths, add=(), remove=(), set=None):  # noqa: A002 - имя параметра видно помощнику
    ps = images(paths, 2000)
    steps = []
    for p in ps:
        r = key(p)
        before = db.tags_of(r)
        if set is not None:
            db.set_tags([r], set, "set")
        db.set_tags([r], add, "add")
        db.set_tags([r], remove, "remove")
        after = db.tags_of(r)
        if after != before:
            steps.append(["tags", r, before, after])
    what = ", ".join(([f"+{t}" for t in add] + [f"-{t}" for t in remove]) or [", ".join(set or []) or "сняты"])
    res = dict(changed=len(steps), tags={s[1].replace(os.sep, "/"): s[3] for s in steps})
    res.update(record(f"Метки ({what}): {len(steps)} шт.", steps))
    return res


@tool(
    "note",
    "Заметка к картинке (откуда, где использована, что поправить). Пустая - убрать.",
    {"path": {"type": "string"}, "text": {"type": "string"}},
    ["path", "text"],
    write=True,
)
def note(path, text):
    r = key(images(path)[0])
    before = db.note_of(r)
    db.set_note(r, text)
    return dict(path=r.replace(os.sep, "/"), note=text) | record(
        f"Заметка: {os.path.basename(r)}", [["note", r, before, text]]
    )


@tool(
    "favorite",
    "Добавить в избранное (on=true) или убрать (on=false).",
    {"paths": {"type": "array", "items": {"type": "string"}}, "on": {"type": "boolean", "default": True}},
    ["paths"],
    write=True,
)
def favorite(paths, on=True):
    rels = [key(p) for p in images(paths, 2000)]
    favs = db.favs()
    db.set_fav(rels, on)
    steps = [["fav", r, r in favs, bool(on)] for r in rels if (r in favs) != bool(on)]
    return dict(changed=len(steps)) | record(("В избранное" if on else "Из избранного") + f": {len(steps)} шт.", steps)


# ---------------------------------------------------------------- файлы
@tool(
    "rename",
    "Переименовать картинку (расширение остаётся). Метки и избранное переезжают с ней.",
    {"path": {"type": "string"}, "new_name": {"type": "string", "description": "без расширения"}},
    ["path", "new_name"],
    write=True,
)
def rename(path, new_name):
    p = images(path)[0]
    name = C.clean_name(os.path.splitext(new_name)[0] if new_name.lower().endswith(K.EXT) else new_name)
    if not name:
        raise ApiError("Пустое имя.")
    dst = os.path.join(os.path.dirname(p), name + os.path.splitext(p)[1])
    if os.path.exists(dst) and dst.lower() != p.lower():
        raise ApiError(f"«{rel(dst)}» уже есть. Выберите другое имя.")
    os.rename(p, dst)
    db.moved(key(p), key(dst))
    return dict(path=rel(dst)) | record(f"Переименовано: {os.path.basename(dst)}", [["move", p, dst]])


@tool(
    "move",
    "Перенести картинки в папку библиотеки (создаётся, если нет). Метки едут с файлами.",
    {
        "paths": {"type": "array", "items": {"type": "string"}},
        "folder": {"type": "string", "description": "например «02 Наклейки/Котики»"},
    },
    ["paths", "folder"],
    write=True,
)
def move(paths, folder):
    ps = images(paths, 2000)
    dest = folder_path(folder, create=True)
    steps, out = [], []
    for p in ps:
        if os.path.dirname(p) == dest:
            continue
        dst = C.unique(os.path.join(dest, os.path.basename(p)))
        shutil.move(p, dst)
        db.moved(key(p), key(dst))
        steps.append(["move", p, dst])
        out.append(rel(dst))
    return dict(moved=out) | record(f"Перенесено: {len(out)} шт. в «{rel(dest)}»", steps)


@tool(
    "trash",
    "Убрать картинки из библиотеки. Не стираются: лежат в _sources/_deleted, undo возвращает их вместе с метками.",
    {"paths": {"type": "array", "items": {"type": "string"}}},
    ["paths"],
    write=True,
)
def trash(paths):
    ps = images(paths, 500)
    day = os.path.join(C.DELETED, time.strftime("%Y-%m-%d"))
    steps = []
    for p in ps:
        r = rel(p)
        dst = C.unique(os.path.join(day, r.replace("/", os.sep)))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        steps += journal.forget_steps(key(p))
        shutil.move(p, dst)
        steps.append(["move", p, dst])
    return dict(removed=len(ps)) | record(f"Убрано: {len(ps)} шт.", steps)


@tool(
    "import_images",
    "Взять картинки с диска (полные пути) в библиотеку: во входящие (по умолчанию) или сразу в папку.",
    {
        "files": {"type": "array", "items": {"type": "string"}},
        "folder": {"type": "string", "description": "раздел; пусто - во входящие"},
    },
    ["files"],
    write=True,
)
def import_images(files, folder=None):
    dest = folder_path(folder, create=True) if folder else C.INBOX
    os.makedirs(dest, exist_ok=True)
    steps, out = [], []
    for f in files:
        src = absolute(f, inside=False)
        if not os.path.isfile(src) or not C.is_image(os.path.basename(src)):
            raise ApiError(f"«{f}» - не картинка.")
        dst = C.unique(os.path.join(dest, os.path.basename(src)))
        shutil.copy2(src, dst)
        steps.append(["new", dst])
        out.append(rel(dst))
    return dict(imported=out) | record(f"Добавлено: {len(out)} шт. в «{rel(dest)}»", steps)


# ---------------------------------------------------------------- правка
OPS_DOC = """Рецепт: adj - цвет (bright, contrast, sat, warm, shadows, highlights, sharp: -100..100; hue: -180..180;
opacity: 0..100), ops - шаги по порядку:
  {"op":"nobg_ai"} убрать любой фон нейросетью | {"op":"nobg","tol":38} убрать однотонный фон
  {"op":"trim"} срезать прозрачные поля | {"op":"defringe","px":1} убрать кайму после фона
  {"op":"crop","box":[x0,y0,x1,y1]} доли 0..1 | {"op":"center"} квадрат из середины
  {"op":"rotate","deg":90|180|270} | {"op":"angle","deg":-3.5,"fit":true} | {"op":"flip","dir":"h"|"v"}
  {"op":"resize","size":512} длинная сторона | {"op":"upscale","x":2|4,"kind":"auto"|"art"|"photo"}
  {"op":"square","pad":0.06} | {"op":"pad","k":0.1,"color":"#ffffff"} | {"op":"fill","color":"#000000"}
  {"op":"outline","px":8,"color":"#ffffff"} обводка наклейки | {"op":"round","rad":0.2} скругление
  {"op":"shadow","dx":0.02,"dy":0.03,"blur":0.03,"a":0.45,"rel":true} | {"op":"glow","r":0.04,"a":0.8,"color":"#fff","rel":true}
  {"op":"recolor","colors":["#1a1b26","#7aa2f7","#c0caf5"],"k":1} перекраска в палитру (см. palettes)"""


def check_ops(ops, adj):
    known = {
        "rotate",
        "flip",
        "crop",
        "trim",
        "nobg",
        "nobg_ai",
        "upscale",
        "outline",
        "square",
        "resize",
        "angle",
        "fill",
        "pad",
        "recolor",
        "defringe",
        "shadow",
        "glow",
        "round",
        "center",
    }
    for o in ops or []:
        if not isinstance(o, dict) or o.get("op") not in known:
            raise ApiError(f"Непонятный шаг {o!r}.\n{OPS_DOC}")
        if o["op"] == "nobg_ai" and not neural.bg_available():
            raise ApiError(
                'Нет модели удаления фона (py -3.14 _tools/get_models.py bg). Есть {"op":"nobg"} - '
                "для однотонного фона."
            )
        if o["op"] == "upscale" and not neural.upscale_available():
            raise ApiError("Нет моделей увеличения (py -3.14 _tools/get_models.py upscale); есть resize.")
    bad = [k for k in (adj or {}) if k not in dict(K.ADJ)]
    if bad:
        raise ApiError(f"Непонятные поля adj: {bad}.\n{OPS_DOC}")


def save_recipe(ps, ops, adj, mode, folder, title):
    check_ops(ops, adj)
    ps = [p for p in ps if K.fmt_of(p) in K.EDITABLE and not K.is_animated(p)]
    if not ps:
        raise ApiError("Эти файлы не правятся (svg, ico, анимация).")
    if mode == "preview":
        p = ps[0]
        im = K.apply_edits(K.load(p), ops or [], adj)
        before = K.load(p)
        w, h = im.size
        pair = sheet([before, im], ["было", "стало"], cell=420)
        return Picture(
            pair,
            f"Предпросмотр {rel(p)}: {before.width}x{before.height} -> {w}x{h}. "
            "Сохранить - тот же вызов с mode=replace или copy.",
        )
    target = folder_path(folder, create=True) if folder else None
    steps, done, bad = batch.save_edits(ps, ops or [], adj or {}, mode == "copy", lambda _v: None, target)
    for old, new in done:
        if mode == "replace" and old != new:
            db.moved(key(old), key(new))
    res = dict(saved=[rel(n) for _o, n in done], errors=bad)
    if mode == "replace":
        res["originals"] = "_sources/edit <дата> (undo вернёт)"
    return res | record(f"{title}: {len(done)} шт.", steps)


MODE = {
    "type": "string",
    "enum": ["preview", "copy", "replace"],
    "description": "preview - только показать было/стало; copy - новый файл рядом; replace - вместо "
    "оригинала (он уходит в _sources)",
}


@tool(
    "edit",
    "Поправить картинки по рецепту (цвет и шаги). Сначала mode=preview - вернёт было/стало, потом "
    "copy или replace. Одна правка на много файлов.\n" + OPS_DOC,
    {
        "paths": {"type": "array", "items": {"type": "string"}},
        "adj": {"type": "object"},
        "ops": {"type": "array", "items": {"type": "object"}},
        "mode": dict(MODE, default="preview"),
        "folder": {"type": "string", "description": "copy в другую папку (перекраска в другую палитру)"},
    },
    ["paths"],
    write=True,
)
def edit(paths, adj=None, ops=None, mode="preview", folder=None):
    return save_recipe(images(paths, 500), ops, adj, mode, folder, "Правка")


@tool(
    "remove_background",
    "Убрать фон: нейросеть (любой фон) или, без модели, однотонный. По умолчанию - копия рядом с прозрачным фоном.",
    {"paths": {"type": "array", "items": {"type": "string"}}, "mode": dict(MODE, default="copy")},
    ["paths"],
    write=True,
)
def remove_background(paths, mode="copy"):
    op = {"op": "nobg_ai"} if neural.bg_available() else {"op": "nobg"}
    return save_recipe(images(paths, 200), [op, {"op": "defringe", "px": 1}], None, mode, None, "Фон убран")


@tool(
    "upscale",
    "Увеличить нейросетью x2/x4 без мыла (Real-ESRGAN): kind=art бережёт контуры рисунков, "
    "photo - текстуры. По умолчанию копия рядом.",
    {
        "paths": {"type": "array", "items": {"type": "string"}},
        "factor": {"type": "integer", "enum": [2, 4], "default": 2},
        "kind": {"type": "string", "enum": ["auto", "art", "photo"], "default": "auto"},
        "mode": dict(MODE, default="copy"),
    },
    ["paths"],
    write=True,
)
def upscale(paths, factor=2, kind="auto", mode="copy"):
    return save_recipe(
        images(paths, 50), [{"op": "upscale", "x": int(factor), "kind": kind}], None, mode, None, f"Увеличено x{factor}"
    )


@tool(
    "convert",
    "Другой формат или размер с подбором качества «разницы не видно». replace=false - копии рядом, "
    "true - вместо оригиналов (они уходят в _sources). format: webp avif png jpg ico best (самый лёгкий).",
    {
        "paths": {"type": "array", "items": {"type": "string"}},
        "format": {"type": "string", "enum": ["webp", "avif", "png", "jpg", "ico", "best"]},
        "max_side": {"type": "integer", "default": 0},
        "budget_kb": {"type": "integer", "default": 0},
        "replace": {"type": "boolean", "default": False},
    },
    ["paths", "format"],
    write=True,
)
def convert(paths, format, max_side=0, budget_kb=0, replace=False):  # noqa: A002
    ps = [p for p in images(paths, 1000) if not p.lower().endswith(".svg") and not K.is_animated(p)]
    o = dict(fmt=K.BEST if format == "best" else format, q=0, target=0.99, kind="auto", size=max_side, budget=budget_kb)
    if replace:
        steps, r = batch.compress_files(ps, dict(o, smaller=False), lambda _v: None)
        out = dict(done=r["done"], before_kb=r["before"] // 1024, after_kb=r["after"] // 1024, skipped=r["skipped"])
        return out | record(f"Сжато ({format}): {r['done']} шт.", steps)
    steps, made, bad = [], [], []
    for p, res in batch.run(K.job_compress, [(p, dict(o)) for p in ps]):
        if isinstance(res, Exception) or res[0] is None:
            bad.append(f"{os.path.basename(p)}: {res}")
            continue
        data, inf = res
        new = C.unique(os.path.splitext(p)[0] + "." + inf["fmt"])
        with open(new, "wb") as fh:
            fh.write(data)
        steps.append(["new", new])
        made.append(dict(path=rel(new), kb=round(len(data) / 1024, 1)))
    return dict(made=made, errors=bad) | record(f"Копии ({format}): {len(made)} шт.", steps)


@tool(
    "export",
    "Выгрузить копии в папку проекта (вне библиотеки) - журнал «где использовано» это запомнит. "
    "preset - готовая заготовка (список - в описании format) или свои format/size.",
    {
        "paths": {"type": "array", "items": {"type": "string"}},
        "dest": {"type": "string", "description": "полный путь к папке проекта"},
        "preset": {"type": "string", "enum": [n for n, o in batch.EXPORT_PRESETS if o]},
        "format": {"type": "string", "description": "''/webp/avif/png/jpg/ico/best/svg/iconset/atlas/svgsprite"},
        "size": {"type": "integer", "default": 0},
        "fit": {"type": "string", "enum": ["fit", "square", "fill"]},
        "retina": {"type": "boolean", "default": False},
        "budget_kb": {"type": "integer", "default": 0},
        "trim": {"type": "boolean", "default": False},
    },
    ["paths", "dest"],
)
def export(paths, dest, preset=None, format="", size=0, fit="fit", retina=False, budget_kb=0, trim=False):  # noqa: A002
    ps = images(paths, 2000)
    if not os.path.isabs(dest):
        raise ApiError("dest - полный путь к папке проекта.")
    if preset:
        o = dict(dict(batch.EXPORT_PRESETS).get(preset) or {})
        if not o:
            raise ApiError(f"Нет заготовки «{preset}».")
    else:
        o = dict(
            fmt="" if format in ("", "same") else (K.BEST if format == "best" else format),
            q=0,
            size=size,
            fit=fit,
            retina=retina,
            budget=budget_kb,
            trim=trim,
        )
    n = batch.export(ps, dest, o)
    db.log_export([key(p) for p in ps], dest)
    return dict(exported=n, dest=dest)


# ---------------------------------------------------------------- входящие и нарезка
@tool("inbox", "Неразобранные листы во входящих: размер и что окно о них знает по имени файла (раздел, сетка).")
def inbox():
    out = []
    for f in C.inbox_files():
        r = sorting.route(f)
        d = dict(file=os.path.basename(f))
        try:
            d["width"], d["height"] = K.size_of(f)
        except Exception:
            pass
        if r:
            o = r["o"]
            d.update(
                folder=rel(r["dest"]),
                grid=f"{o['cols']}x{o['rows']}" if o["mode"] == "grid" else o["mode"],
                names=r["names"],
            )
        out.append(d)
    return dict(inbox=rel(C.INBOX), sheets=out)


@tool(
    "cut_sheet",
    "Нарезать лист (обычно из входящих) на картинки и разложить в раздел. grid: «4x3» - сетка, "
    "«auto» - найти рисунки, «whole» - картинка целиком. Если имя файла с меткой («Космос [ic tokyo]»), "
    "раздел, сетка и имена берутся сами. Повторы того, что уже есть в библиотеке, пропускаются. "
    "preview=true - только показать куски с номерами (оранжевые - уже есть).",
    {
        "path": {"type": "string"},
        "grid": {"type": "string"},
        "folder": {"type": "string"},
        "names": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "bg": {"type": "string", "enum": ["auto", "remove", "ai", "keep"]},
        "outline": {"type": "integer", "description": "белая обводка, px"},
        "size": {"type": "integer"},
        "format": {"type": "string", "enum": ["webp", "png", "avif", "jpg", "ico"]},
        "only": {"type": "array", "items": {"type": "integer"}, "description": "сохранить только эти номера (с 1)"},
        "preview": {"type": "boolean", "default": False},
        "keep_existing": {"type": "boolean", "default": False, "description": "сохранить и повторы"},
    },
    ["path"],
    write=True,
)
def cut_sheet(
    path,
    grid=None,
    folder=None,
    names=None,
    tags=(),
    bg=None,
    outline=None,
    size=None,
    format=None,  # noqa: A002
    only=None,
    preview=False,
    keep_existing=False,
):
    p = absolute(path, inside=False)
    r = sorting.route(p) or {}
    o = dict(r.get("o") or dict(mode="grid", cols=4, rows=3, bg_mode="auto", obv=0, pad=6, size=256, fmt="webp"))
    kind = None
    if not r and not grid and os.path.splitext(os.path.basename(p))[0].count(",") < 2:
        kind = K.sheet_kind(K.load(p))  # фон - целиком, один рисунок - вырезать, лист - сеткой
        grid = {"whole": "whole", "single": "auto"}.get(kind)
        if grid == "whole" and size is None:
            size = 1920
    if grid:
        g = grid.lower().replace("х", "x")
        if g in ("auto", "whole"):
            o["mode"] = g
            if g == "whole":
                o.update(bg_mode=bg or "keep", pad=0, size=size if size is not None else 0)
        else:
            try:
                o["cols"], o["rows"] = (int(v) for v in g.split("x"))
            except ValueError as e:
                raise ApiError("grid - «4x3», «auto» или «whole».") from e
            o["mode"] = "grid"
    for k, v in (("bg_mode", bg), ("obv", outline), ("size", size), ("fmt", format)):
        if v is not None:
            o[k] = v
    if o["bg_mode"] == "ai" and not neural.bg_available():
        raise ApiError("Нет модели удаления фона; bg=auto убирает однотонный.")
    _im, pieces, _boxes = sorting.process(p, o)
    sigs = None if keep_existing else sig_index()
    have = [sigs.find(pc) if sigs else None for pc in pieces]
    names = [C.clean_name(n) for n in names] if names else sorting.default_names(p, len(pieces))
    if preview:
        labels = [names[i] if i < len(names) else str(i + 1) for i in range(len(pieces))]
        text = "\n".join(
            "%d. %s%s" % (i + 1, labels[i], f"  (уже есть: {h.replace(os.sep, '/')})" if h else "")
            for i, h in enumerate(have)
        )
        dest = folder or (rel(r["dest"]) if r else "не задан - нужен folder")
        how = {"whole": "цельная картинка", "single": "один рисунок"}.get(kind, o["mode"])
        like = ""
        sem = sem_index(update=False)
        if sem.ready() and not folder and not r:
            tags_, where = tagger(sem).suggest_all(pieces)
            if where:
                like = "\nПохоже на раздел: %s (там лежат похожие картинки)" % where[0].replace(os.sep, "/")
            if tags_:
                like += "\nМетки по смыслу: " + ", ".join(tags_)
        return Picture(
            sheet(pieces, labels, 150, ["есть" if h else "" for h in have]),
            f"Кусков: {len(pieces)} ({how}), раздел: {dest}{like}\n{text}",
        )
    if not folder and not r:
        raise ApiError("Куда класть? Задайте folder (например «04 Иконки/Космос»).")
    dest = folder_path(folder, create=True) if folder else r["dest"]
    pick = [i for i in range(len(pieces)) if not have[i] and (not only or i + 1 in only)]
    saved = sorting.store(p, o, [pieces[i] for i in pick], [names[i] if i < len(names) else "" for i in pick], dest)
    steps = [["new", s] for s in saved]
    if tags:
        db.set_tags([key(s) for s in saved], tags, "add")
    if os.path.dirname(p) == C.INBOX:
        steps.append(["move", p, C.archive(p)])
    out = dict(saved=[rel(s) for s in saved], skipped_existing=sum(1 for h in have if h), folder=rel(dest))
    return out | record(f"Нарезано: {len(saved)} шт. в «{rel(dest)}»", steps)


# ---------------------------------------------------------------- порядок
def in_folder(paths, folder):
    if not folder:
        return paths
    root = folder_path(folder)
    return [p for p in paths if os.path.normcase(p).startswith(os.path.normcase(root) + os.sep)]


@tool(
    "duplicates",
    "Одинаковые картинки: тот же рисунок в другом размере или формате. В каждой группе первой идёт самая "
    "крупная - её обычно оставляют, остальные можно убрать trash.",
    {
        "folder": {"type": "string", "description": "только в этой папке; пусто - вся библиотека"},
        "imported": {"type": "boolean", "default": False,
                     "description": "и в чужих наборах (Kenney, Hero Patterns): там похожие детали - нарочно"},
    },
)
def duplicates(folder=None, imported=False):
    def quality(p):
        try:
            w, h = K.size_of(p)
            return w * h, os.path.getsize(p)
        except Exception:
            return 0, 0

    favs, out = db.favs(), []
    for g in sig_index().groups():
        g = sorted(in_folder(g, folder), key=quality, reverse=True)
        if not imported:
            g = [p for p in g if not any(x in rel(p).split("/") for x in K.IMPORTED)]
        if len(g) > 1:
            out.append([item(p, favs=favs) for p in g])
    return dict(groups=len(out), duplicates=out)


@tool(
    "check",
    "Доктор: что не так с картинками - не открывается, пустая, слишком мелкая, фон не убран, рисунок обрезан "
    "краем, кусок соседа у края, светлая кайма. Чинить - edit (nobg_ai, defringe, trim...) или trash.",
    {
        "folder": {"type": "string", "description": "папка; пусто - вся библиотека"},
        "limit": {"type": "integer", "default": 200},
    },
)
def check(folder=None, limit=200):
    files = [p for p in in_folder(K.images_in(C.LIB), folder) if not p.lower().endswith(".svg")]
    names, bad = dict(K.PROBLEMS), []
    for p, res in batch.run(K.job_doctor, [(p, None) for p in files]):
        if isinstance(res, Exception) or not res:
            continue
        bad.append(dict(path=rel(p), problems=[names[c] for c in res]))
    bad.sort(key=lambda d: d["path"])
    return dict(checked=len(files), with_problems=len(bad), items=bad[:limit])


# ---------------------------------------------------------------- прочее
@tool(
    "smart_folder",
    "Умная папка - сохранённый поиск в дереве окна, сама пополняется. delete=true - убрать.",
    {
        "name": {"type": "string"},
        "query": {"type": "string", "default": ""},
        "color": {"type": "string", "default": ""},
        "semantic": {"type": "boolean", "default": False},
        "delete": {"type": "boolean", "default": False},
    },
    ["name"],
    write=True,
)
def smart_folder(name, query="", color="", semantic=False, delete=False):
    name = C.clean_name(name)
    if delete:
        db.delete_smart(name)
        return dict(deleted=name)
    if not query and not color:
        raise ApiError("Нужен query или color.")
    db.save_smart(name, query, color, semantic)
    return dict(saved=name)


@tool(
    "palettes",
    "Палитры из Prompts.html (имя, цвета) - для перекраски edit(ops=[{op:recolor,colors:[...]}]) "
    "и папок наборов <раздел>/<набор>/<палитра>.",
)
def palettes():
    return [dict(id=i, name=n, folder=f, colors=c) for i, n, f, c in prompts.palettes()]


@tool(
    "history",
    "Последние действия с библиотекой (и окна, и помощников) - id для undo.",
    {"limit": {"type": "integer", "default": 20}, "mine": {"type": "boolean", "default": False}},
)
def history(limit=20, mine=False):
    out = []
    for e in journal.entries(limit, who=AGENT["who"] if mine else None):
        out.append(
            dict(
                id=e["id"],
                when=time.strftime("%Y-%m-%d %H:%M", time.localtime(e["t"])),
                who=e["who"],
                text=e["text"],
                undone=e["undone"],
            )
        )
    return out


@tool(
    "undo",
    "Отменить действие: без id - последнее своё (не отменённое). Файлы возвращаются на места, "
    "новые убираются в _sources/_deleted, метки - как были.",
    {"id": {"type": "integer"}},
    write=True,
)
def undo(id=None):  # noqa: A002
    if id is None:
        mine = journal.entries(1, who=AGENT["who"], undone=False)
        if not mine:
            raise ApiError("Отменять нечего: своих действий нет.")
        e = mine[0]
    else:
        e = journal.get(id)
        if not e:
            raise ApiError(f"Нет действия {id} (history() покажет список).")
        if e["undone"]:
            raise ApiError(f"Действие {id} уже отменено.")
    park = os.path.join(C.DELETED, time.strftime("%Y-%m-%d"), "отменено")
    _done, bad = journal.undo_steps(e["steps"], C.LIB, park)
    journal.mark(e["id"])
    return dict(undone=e["text"], id=e["id"], failed_steps=bad)


@tool(
    "index",
    "Досчитать векторы поиска по смыслу и отпечатки для новых картинок (окно делает это само; "
    "нужно, если окно закрыто, а картинок добавили много).",
)
def index():
    sigs = sig_index()
    sem = sem_index(update=False)
    before = len(sem.data)
    if sem.ok:
        sem.refresh()
    return dict(signatures=len(sigs.data), semantic=len(sem.data), new_semantic=len(sem.data) - before)
