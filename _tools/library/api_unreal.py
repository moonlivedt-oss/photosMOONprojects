"""Операции для ИИ-помощников по вкладке «Unreal»: найти ассеты (и по смыслу), посмотреть превью,
собрать подборку и комнату по описанию, скачать по теме, сделать пакет, импортировать в проект
Unreal и собрать сцену в Blender. Регистрируются в общем списке library.api (тот же MCP и cli.py api)."""

import os
import tempfile

from PIL import Image

from library import ui_bridge
from library import unreal as U
from library import unreal_groups as G
from library.api import AGENT, ApiError, Picture, report, sheet, tool
from library.unreal_sem import GAP as U_GAP

ASSET_LIMIT = 40


def _items():
    from library import unreal_extra as X

    return G.annotate(X.apply_meta(U.assets()))


def _key(a):
    return a.get("id") or os.path.relpath(a["dir"], U.ROOT).replace(os.sep, "/")


def _section(a):
    return a.get("_s") or G.section_of(a)


def _brief(a, score=None):
    out = {
        "id": _key(a),
        "name": a.get("name", ""),
        "kind": a.get("kind"),
        "theme": a.get("theme", ""),
        "group": a.get("_g") or G.group_of(a),
        "style": G.style_of(a),
        "source": a.get("source", ""),
        "size_mb": round(a.get("size", 0) / 2**20, 1),
    }
    for k in ("res", "polycount", "dims_cm"):
        if a.get(k):
            out[k] = a[k]
    if a.get("rigged"):
        out["rigged"] = True
        out["animations"] = len(a.get("animations", []))
    if _section(a):
        out["section"] = _section(a)
    if score is not None:
        out["score"] = round(score, 2)  # похожесть на запрос: от лучшего вниз, разница > 2 - уже далеко
    return out


def _preview(a):
    p = os.path.join(a["dir"], "preview.webp")
    try:
        im = Image.open(p).convert("RGBA") if os.path.exists(p) else None
    except OSError:
        return None
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox() if im else None
    if box:  # пустые поля прочь: маленькая пальма Kenney иначе занимает десятую часть клетки
        x0, y0, x1, y1 = box
        m = max(x1 - x0, y1 - y0) // 14
        im = im.crop((max(0, x0 - m), max(0, y0 - m), min(im.width, x1 + m), min(im.height, y1 + m)))
    return im


def _sheet(assets):
    return sheet([_preview(a) for a in assets], [a.get("name", "") for a in assets])


def _as_text(d):
    import json

    return json.dumps(d, ensure_ascii=False, indent=1)


def _by_ids(ids, limit=ASSET_LIMIT):
    if isinstance(ids, str):
        ids = [ids]
    if not ids:
        raise ApiError("Не задано ни одного ассета (ids). Найти - ue_search.")
    if len(ids) > limit:
        raise ApiError(f"Слишком много за раз: {len(ids)}, можно до {limit}.")
    idx = {_key(a): a for a in _items()}
    out, missing = [], []
    for i in ids:
        (out.append(idx[i]) if i in idx else missing.append(i))
    if missing:
        raise ApiError("Нет таких ассетов: " + ", ".join(missing[:5]) + ". Найти - ue_search.")
    return out


def _sem():
    from library import unreal_sem

    return unreal_sem.AssetSem() if unreal_sem.available() else None


@tool(
    "ue_overview",
    "Ассеты Unreal: сколько каких видов; группы и разделы (как в дереве окна: Природа -> Деревья, "
    "Город и транспорт -> Транспорт...); стили (real - PBR, Kenney / Quaternius / KayKit - low-poly); подборки, "
    "темы для ue_download, найденные Unreal и Blender. Начинать с него; набор под тему целиком - ue_kit.",
)
def ue_overview():
    from library import blender_scene, unreal_engine, unreal_sets

    items = _items()
    kinds, groups, styles = {}, {}, {}
    for a in items:
        kinds[a.get("kind")] = kinds.get(a.get("kind"), 0) + 1
        g = groups.setdefault(a["_g"], {"count": 0, "sections": {}})
        g["count"] += 1
        g["sections"][a["_s"]] = g["sections"].get(a["_s"], 0) + 1
        st = G.style_of(a)
        styles[st] = styles.get(st, 0) + 1
    return {
        "folder": U.ROOT,
        "kinds": kinds,
        "groups": {k: groups[k] for k in G.group_order() if k in groups},
        "styles": styles,
        "themes_available": list(U.THEMES),
        "archives_folder": os.path.join(U.ROOT, "_Архивы"),
        "collections": {n: len(v) for n, v in unreal_sets.load().items()},
        "unreal_engines": unreal_engine.engines(),
        "unreal_projects": unreal_engine.projects(),
        "blender": blender_scene.find_blender(),
        "license": U.LICENSE,
    }


@tool(
    "ue_search",
    "Найти ассеты Unreal по смыслу («деревянный стул», «rusty metal») или по словам. Фильтры: вид, группа и "
    "раздел (из ue_overview: group «Природа», section «Деревья»), стиль (real - реалистичные PBR, low - любые "
    "low-poly, или Kenney / Quaternius / KayKit), тема скачивания.",
    {
        "query": {"type": "string"},
        "kind": {"type": "string", "enum": ["tex", "hdri", "model", "ies"]},
        "group": {"type": "string"},
        "section": {"type": "string"},
        "style": {"type": "string", "enum": [k for k, _t in G.STYLES]},
        "max_polycount": {"type": "integer", "description": "только модели легче (треугольников)"},
        "rigged": {"type": "boolean", "description": "только со скелетом (персонажи, животные - для анимаций)"},
        "theme": {"type": "string", "description": "тема скачивания или раздел («Кровати»)"},
        "limit": {"type": "integer", "default": 20},
        "offset": {"type": "integer", "default": 0},
        "broad": {
            "type": "boolean",
            "default": False,
            "description": "по смыслу - весь список по убыванию, а не только уверенные (листать offset)",
        },
        "preview": {"type": "boolean", "default": False, "description": "сразу вернуть и лист превью найденного"},
    },
)
def ue_search(
    query="",
    kind=None,
    group=None,
    section=None,
    style=None,
    max_polycount=None,
    rigged=None,
    theme=None,
    limit=20,
    offset=0,
    broad=False,
    preview=False,
):
    items = _items()
    if max_polycount:
        items = [a for a in items if a.get("kind") == "model" and 0 < (a.get("polycount") or 0) <= max_polycount]
    if rigged is not None:
        items = [a for a in items if bool(a.get("rigged")) == bool(rigged)]
    if kind:
        items = [a for a in items if a.get("kind") == kind]
    if group:
        if group not in G.group_order():
            raise ApiError("Нет такой группы. Группы: " + ", ".join(G.group_order()))
        items = [a for a in items if a["_g"] == group]
    if section:
        items = [a for a in items if a["_s"].lower() == section.lower()]
    if style:
        items = [a for a in items if G.style_ok(a, style)]
    if theme:
        items = [a for a in items if a.get("theme") == theme or _section(a) == theme]
    found, score = items, {}
    if query.strip():
        sem = _sem()
        ranked = sem.rank(query, items, gap=None if broad else U_GAP) if sem is not None else []
        score = {id(a): sc for a, sc in ranked}
        found = [a for a, _s in ranked]
        if not found:
            words = query.lower().split()
            found = [
                a
                for a in items
                if all(
                    w in " ".join([a.get("name", ""), *a.get("tags", []), a.get("theme", "")]).lower() for w in words
                )
            ]
    limit = max(1, min(100, limit))
    page = found[offset : offset + limit]
    out = {
        "total": len(found),
        "assets": [_brief(a, score.get(id(a))) for a in page],
        "hint": "Показать пользователю в окне - ue_show(ids); посмотреть самому - ue_view(ids) или preview=true; "
        "ещё похожих на удачный - ue_similar(id); сравнить кандидатов - ue_compare(ids); набор под тему - ue_kit.",
    }
    if preview and page:
        lines = [f"{i + 1}. {a.get('name', '')} ({_key(a)})" for i, a in enumerate(page[:36])]
        return Picture(_sheet(page[:36]), _as_text(out) + "\n\nНа листе:\n" + "\n".join(lines))
    return out


# части набора по умолчанию: (часть, вид, что искать вдобавок к описанию)
KIT_PARTS = (
    ("Деревья и крупные растения", "model", "trees and large plants"),
    ("Кусты, трава, цветы", "model", "bushes, ferns, grass and flowers"),
    ("Камни и земля", "model", "rocks, stones and ground pieces"),
    ("Постройки и вещи", "model", "buildings, props and objects"),
    ("Текстуры поверхности", "tex", "ground surface material"),
    ("Небо и свет HDRI", "hdri", "sky and lighting"),
)
KIND_RU = {"model": "модели", "tex": "текстуры", "hdri": "HDRI", "ies": "IES"}


def kit_sheet(rows, cell=150):
    """Лист набора: строка на часть - подпись слева, превью с общими номерами (1, 2, 3... по всему листу)."""
    from PIL import ImageDraw

    import imaging as K
    from library.api import checker

    cols = max([len(r[1]) for r in rows] + [1])
    head, pad, cap = 190, 8, 20
    w = head + cols * (cell + pad) + pad
    h = pad + len(rows) * (cell + cap + pad)
    out = Image.new("RGB", (w, h), (21, 21, 28))
    d = ImageDraw.Draw(out)
    f, fb = K.sprites._font(13), K.sprites._font(15)
    n = 0
    for r, (title, assets) in enumerate(rows):
        y = pad + r * (cell + cap + pad)
        d.rounded_rectangle((pad, y, head - 8, y + cell), 10, fill=(30, 30, 40))
        words, line, ty = title.split(), "", y + 12
        for word in words + [""]:  # подпись части - по словам в несколько строк
            if word and d.textlength((line + " " + word).strip(), font=fb) < head - 30:
                line = (line + " " + word).strip()
                continue
            d.text((pad + 10, ty), line, fill=(236, 234, 246), font=fb)
            ty, line = ty + 20, word
        for c, a in enumerate(assets):
            n += 1
            x = head + c * (cell + pad)
            tile = checker((cell, cell))
            im = _preview(a)
            if im is not None:
                im.thumbnail((cell - 8, cell - 8), Image.LANCZOS)
                tile.alpha_composite(im, ((cell - im.width) // 2, (cell - im.height) // 2))
            out.paste(tile.convert("RGB"), (x, y))
            col = (126, 224, 160) if G.style_of(a) == "real" else (240, 163, 94)  # PBR - зелёная метка, low - рыжая
            d.rounded_rectangle((x + 4, y + 4, x + 32, y + 22), 6, fill=(20, 20, 28), outline=col)
            d.text((x + 18, y + 13), str(n), fill=(230, 228, 240), font=f, anchor="mm")
            label = a.get("name", "")
            while d.textlength(label, font=f) > cell and len(label) > 4:
                label = label[:-2]
            d.text((x + cell / 2, y + cell + 3), label, fill=(220, 218, 232), font=f, anchor="ma")
    return out


@tool(
    "ue_kit",
    "Набор под тему за один вызов: «джунгли», «заброшенная фабрика», «уютная таверна». Делит тему на части "
    "(деревья, кусты, камни, вещи, текстуры, небо - или свои parts), в каждой - лучшие по смыслу, без повторов, "
    "и возвращает ОДИН лист превью: строка на часть, номера сквозные, рамка номера - стиль (зелёная PBR, рыжая "
    "low-poly). Дальше: ue_similar(id) - ещё таких, ue_compare(ids) - выбрать из похожих, ue_collection - "
    "сохранить, ue_show - показать пользователю.",
    {
        "description": {"type": "string", "description": "тема по-русски или по-английски"},
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "query": {"type": "string", "description": "что искать в этой части"},
                    "kind": {"type": "string", "enum": ["model", "tex", "hdri", "ies"]},
                    "section": {"type": "string", "description": "раздел из ue_overview («Деревья»)"},
                },
                "required": ["query"],
            },
            "description": "свои части вместо стандартных: [{name, query, kind}]",
        },
        "style": {"type": "string", "enum": [k for k, _t in G.STYLES], "description": "один стиль на весь набор"},
        "per_part": {"type": "integer", "default": 6, "description": "сколько в каждой части (до 10)"},
        "max_polycount": {"type": "integer"},
    },
    ["description"],
)
def ue_kit(description, parts=None, style=None, per_part=6, max_polycount=None):
    sem = _sem()
    if sem is None:
        raise ApiError("Нужна модель поиска по смыслу: py -3.14 _tools/get_models.py clip")
    items = _items()
    if style:
        items = [a for a in items if G.style_ok(a, style)]
    if max_polycount:
        items = [a for a in items if a.get("kind") != "model" or 0 < (a.get("polycount") or 0) <= max_polycount]
    per_part = max(1, min(10, per_part))
    plan = (
        [(p.get("name") or p["query"], p.get("kind") or "model", p["query"], p.get("section")) for p in parts]
        if parts
        else [(n, k, f"{description}: {q}", None) for n, k, q in KIT_PARTS]
    )
    used, rows, out, n = set(), [], [], 0
    for name, kind, query, section in plan:
        pool = [a for a in items if a.get("kind") == kind and a["dir"] not in used]
        if section:
            pool = [a for a in pool if a["_s"].lower() == section.lower()]
        ranked = sem.rank(query, pool, gap=None)[:per_part]
        if not ranked:
            continue
        picks = []
        for a, sc in ranked:
            used.add(a["dir"])
            n += 1
            picks.append(dict(_brief(a, sc), n=n))
        rows.append((f"{name} ({KIND_RU.get(kind, kind)})", [a for a, _s in ranked]))
        out.append({"part": name, "kind": kind, "query": query, "assets": picks})
    if not rows:
        raise ApiError("Ничего не нашлось: скачанного по этой теме нет - ue_download или другой style.")
    lines = []
    for part in out:
        lines.append(f"\n{part['part']}:")
        for a in part["assets"]:
            extra = ", ".join(
                x
                for x in (
                    a["style"],
                    f"{a['polycount']} полиг." if a.get("polycount") else "",
                    a.get("section", ""),
                    f"оценка {a['score']}",
                )
                if x
            )
            lines.append(f"{a['n']}. {a['name']} ({a['id']}) - {extra}")
    styles = {}
    for part in out:
        for x in part["assets"]:
            styles[x["style"]] = styles.get(x["style"], 0) + 1
    mix = ", ".join(f"{k}: {v}" for k, v in sorted(styles.items(), key=lambda kv: -kv[1]))
    text = (
        f"Набор «{description}»: {sum(len(p['assets']) for p in out)} шт. в {len(out)} частях. Стили: {mix}"
        + ("" if style or len(styles) < 2 else " - для единого вида повторить с style='real' или 'low'.")
        + "".join("\n" + x for x in lines)
        + "\n\nДальше: ue_similar(id) - ещё таких; ue_compare(ids) - сравнить; "
        "ue_collection(name, add=ids) - сохранить; ue_show(ids) - показать пользователю."
    )
    return Picture(kit_sheet(rows), text)


@tool(
    "ue_similar",
    "Ещё ассеты, похожие на этот (по превью и меткам): «нравится эта пальма - покажи ещё такие». Фильтры как у "
    "ue_search. preview=true - сразу лист превью.",
    {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": ["tex", "hdri", "model", "ies"]},
        "style": {"type": "string", "enum": [k for k, _t in G.STYLES]},
        "limit": {"type": "integer", "default": 12},
        "preview": {"type": "boolean", "default": True},
    },
    ["id"],
)
def ue_similar(id, kind=None, style=None, limit=12, preview=True):  # noqa: A002
    sem = _sem()
    if sem is None:
        raise ApiError("Нужна модель поиска по смыслу: py -3.14 _tools/get_models.py clip")
    me = _by_ids([id])[0]
    items = _items()
    items = [a for a in items if a.get("kind") == (kind or me.get("kind"))]
    if style:
        items = [a for a in items if G.style_ok(a, style)]
    found = sem.similar(me, items, top=max(1, min(36, limit)))
    if not found:
        raise ApiError("Для этого ассета нет векторов поиска (нет превью) - окно досчитает их само.")
    out = {"like": _brief(me), "assets": [_brief(a, sc) for a, sc in found]}
    if not preview:
        return out
    assets = [me] + [a for a, _s in found]
    lines = [
        f"{i + 1}. {a.get('name', '')} ({_key(a)})" + (" - образец" if i == 0 else "") for i, a in enumerate(assets)
    ]
    return Picture(_sheet(assets), _as_text(out) + "\n\nНа листе (1 - образец):\n" + "\n".join(lines))


@tool(
    "ue_compare",
    "Сравнить кандидатов рядом: лист превью и таблица - стиль, полигоны, вес, разрешение, размер в см, скелет и "
    "анимации, лицензия, раздел. Для выбора «какой из этих трёх деревьев взять».",
    {"ids": {"type": "array", "items": {"type": "string"}}},
    ["ids"],
)
def ue_compare(ids):
    assets = _by_ids(ids, 12)
    rows = [
        "| # | имя | стиль | полигоны | вес | разрешение | размер, см | скелет | лицензия | раздел |",
        "|" + "---|" * 10,
    ]
    for i, a in enumerate(assets):
        dims = (
            [round(x / 10) for x in a["dimensions_mm"]]
            if a.get("dimensions_mm")
            else [round(x) for x in a.get("dims_cm") or []]
        )
        rig = f"да, {len(a.get('animations', []))} анимаций" if a.get("rigged") else "-"
        rows.append(
            f"| {i + 1} | {a.get('name', '')} | {G.style_of(a)} | {a.get('polycount') or '-'} | "
            f"{round(a.get('size', 0) / 2**20, 1)} МБ | {a.get('res') or '-'} | {' x '.join(map(str, dims)) or '-'} | "
            f"{rig} | {'CC0' if U.is_cc0(a) else (a.get('license') or 'не CC0').split(' - ')[0][:40]} | {_section(a) or '-'} |"
        )
    ids_txt = "\n".join(f"{i + 1}. {_key(a)}" for i, a in enumerate(assets))
    return Picture(_sheet(assets), "\n".join(rows) + "\n\nid:\n" + ids_txt)


@tool(
    "ue_views",
    "Изучить ассет со всех сторон одним листом: модель - с четырёх сторон (спереди, справа, сзади, сверху; рендер "
    "Blender в фоне, первый раз - до минуты, потом из кэша), текстура - все её карты с подписями (цвет, нормаль, "
    "шероховатость...), HDRI - панорама. Для «как это выглядит сзади», «подойдёт ли сбоку».",
    {"id": {"type": "string"}},
    ["id"],
)
def ue_views(id):  # noqa: A002
    a = _by_ids([id])[0]
    kind = a.get("kind")
    if kind == "model":
        from library import blender_preview

        fbx = [os.path.join(a["dir"], *m.split("/")) for m in a.get("main", []) if m.lower().endswith(".fbx")]
        if not fbx:
            raise ApiError("У модели нет FBX - смотрите ue_view (превью).")
        im = blender_preview.views(fbx, os.path.join(a["dir"], "_views.webp"))
        if im is None:
            raise ApiError("Blender не найден или модель не открылась - ue_view покажет обычное превью.")
        return Picture(im, f"{a.get('name', '')} ({_key(a)}): спереди, справа, сзади, сверху.\n" + _as_text(_brief(a)))
    if kind == "tex":
        from library.unreal_import import role_of

        names = {
            "color": "цвет",
            "normal": "нормаль",
            "arm": "AO/шероховатость/металл",
            "rough": "шероховатость",
            "metal": "металл",
            "ao": "AO",
            "height": "высота",
        }
        files = [
            f
            for f in sorted(os.listdir(a["dir"]))
            if f.lower().endswith((".jpg", ".jpeg", ".png")) and not f.startswith("preview") and role_of(f)
        ]
        ims, labels = [], []
        for f in files[:9]:
            try:
                with Image.open(os.path.join(a["dir"], f)) as im:
                    im.draft("RGB", (512, 512))
                    ims.append(im.convert("RGB").resize((256, 256)))
                labels.append(names.get(role_of(f), f))
            except OSError:
                continue
        prev = _preview(a)
        if prev is not None:
            ims.insert(0, prev)
            labels.insert(0, "на шаре")
        return Picture(sheet(ims, labels), f"{a.get('name', '')} ({_key(a)}): " + ", ".join(labels))
    return ue_view([id])


@tool(
    "ue_view",
    "Посмотреть превью ассетов Unreal листом с номерами (по id из ue_search).",
    {"ids": {"type": "array", "items": {"type": "string"}}},
    ["ids"],
)
def ue_view(ids):
    assets = _by_ids(ids, 24)
    text = "\n".join(f"{i + 1}. {a.get('name', '')} ({_key(a)})" for i, a in enumerate(assets))
    return Picture(_sheet(assets), text)


@tool(
    "ue_info",
    "Всё об ассете Unreal: файлы, источник, авторы, лицензия, как подключить в Unreal.",
    {"id": {"type": "string"}},
    ["id"],
)
def ue_info(id):  # noqa: A002 - так параметр называется у помощника
    a = _by_ids([id])[0]
    out = _brief(a)
    out.update(
        files=a.get("main", []),
        folder=a["dir"],
        url=a.get("url", ""),
        authors=a.get("authors", []),
        license=a.get("license", ""),
        tags=a.get("tags", []),
        howto=U.howto(a),
    )
    if a.get("dimensions_mm"):
        out["dimensions_cm"] = [round(x / 10, 1) for x in a["dimensions_mm"]]
    if a.get("animations"):
        out["animation_names"] = a["animations"]
    return out


@tool(
    "ue_plan_room",
    "Подобрать комнату по описанию («уютная спальня в скандинавском стиле»): вещи по разделам, пол, стены, "
    "небо HDRI - из скачанного. У каждой позиции - варианты замены. Ничего не меняет.",
    {"description": {"type": "string"}, "low_poly": {"type": "boolean"}},
    ["description"],
)
def ue_plan_room(description, low_poly=None):
    from library import scene_plan

    sem = _sem()
    if sem is None:
        raise ApiError("Нет модели поиска по смыслу (py -3.14 _tools/get_models.py clip).")
    p = scene_plan.plan(sem, _items(), description, U.home_section, low_poly=low_poly)
    slot = lambda ch: {"pick": _brief(ch[0]), "alternatives": [_brief(a) for a in ch[1:6]]}  # noqa: E731
    return {
        "room": p["room"],
        "low_poly": p["low_poly"],
        "items": [{"section": s["section"], **slot(s["choices"])} for s in p["slots"]],
        "floor": slot(p["floor"]) if p["floor"] else None,
        "wall": slot(p["wall"]) if p["wall"] else None,
        "hdri": slot(p["hdri"]) if p["hdri"] else None,
        "ids": [_key(a) for a in scene_plan.chosen(p)],
    }


@tool(
    "ue_collection",
    "Подборки ассетов Unreal: добавить (add) или убрать (remove) ассеты, без них - показать подборку. "
    "Подборки видны во вкладке «Unreal» слева.",
    {
        "name": {"type": "string"},
        "add": {"type": "array", "items": {"type": "string"}},
        "remove": {"type": "array", "items": {"type": "string"}},
    },
    ["name"],
    write=True,
)
def ue_collection(name, add=None, remove=None):
    from library import unreal_sets

    if add:
        _by_ids(add, 200)
        unreal_sets.add(name, add)
    if remove:
        unreal_sets.remove(name, remove)
    if add or remove:
        ui_bridge.ue_changed()  # окно перечитает подборки
    ids = unreal_sets.load().get(name, [])
    idx = {_key(a): a for a in _items()}
    return {"name": name, "count": len(ids), "assets": [_brief(idx[i]) for i in ids if i in idx]}


@tool(
    "ue_download",
    "Скачать новые бесплатные ассеты (CC0: Poly Haven, ambientCG, Kenney, Quaternius, KayKit) по теме "
    "(themes_available из ue_overview). Долго: сеть; ход работы - уведомлениями progress. Окно увидит сразу.",
    {
        "kind": {"type": "string", "enum": ["tex", "hdri", "model", "ies"]},
        "theme": {"type": "string"},
        "count": {"type": "integer", "default": 4},
        "res": {"type": "string", "enum": ["1k", "2k", "4k"], "default": "2k"},
    },
    ["kind", "theme"],
    write=True,
)
def ue_download(kind, theme, count=4, res="2k"):
    if kind != "ies" and theme not in U.THEMES:
        raise ApiError("Нет такой темы. Темы: " + ", ".join(U.THEMES))
    errs = []
    got = U.get_many(
        kind,
        theme,
        max(1, min(50, count)),
        res,
        progress=lambda frac, text: report(round(frac * 100), 100, text),
        log=lambda s: s.startswith("  !") and errs.append(s),
    )
    if got:
        ui_bridge.ue_changed()  # вкладка Unreal перечитает ассеты и дорисует превью сама
    have = {a["dir"]: a for a in _items()}
    return {"downloaded": [_brief(have[d]) for d in got if d in have], "errors": errs[:5]}


@tool(
    "ue_pack",
    "Пакет для проекта: файлы ассетов, import_to_unreal.py, CREDITS.md (авторы, лицензии) и manifest.json "
    "в папку dest (по желанию - zip).",
    {
        "ids": {"type": "array", "items": {"type": "string"}},
        "dest": {"type": "string"},
        "title": {"type": "string"},
        "zip": {"type": "boolean", "default": False},
    },
    ["ids", "dest"],
    write=True,
)
def ue_pack(ids, dest, title="Пакет", zip=False):  # noqa: A002
    from library import db, unreal_pack

    assets = _by_ids(ids)
    out = unreal_pack.pack(assets, dest, title, zip)
    db.log_ue_use([_key(a) for a in assets], os.path.abspath(dest))  # для авторов и лицензий проекта
    return {"path": out}


@tool(
    "ue_import",
    "Импортировать ассеты прямо в проект Unreal (.uproject) без открытия редактора: Content/Library, "
    "текстуры с настройками и материалом M_<имя>. Редактор с проектом должен быть закрыт. Минута-две.",
    {"ids": {"type": "array", "items": {"type": "string"}}, "project": {"type": "string"}},
    ["ids", "project"],
    write=True,
)
def ue_import(ids, project):
    from library import unreal_engine as E

    if not os.path.exists(project) or not project.lower().endswith(".uproject"):
        raise ApiError("Нужен путь к .uproject. Проекты на компьютере - ue_overview (unreal_projects).")
    if E.editor_running(project):
        raise ApiError("Редактор Unreal открыт - пусть импортирует он сам, или закройте его и повторите.")
    if not E.python_enabled(project):
        E.enable_python(project)
    from library import db

    assets = _by_ids(ids)
    res = E.import_into(assets, project, log=lambda text: report(0, None, text))
    if res.get("ok"):
        db.log_ue_use([_key(a) for a in assets], os.path.dirname(os.path.abspath(project)))
    return {k: res[k] for k in ("ok", "imported", "errors", "log")}


@tool(
    "ue_blender",
    "Собрать сцену в Blender из ассетов: модели в масштабе, PBR-материалы, HDRI; room=true - комнатой с полом "
    "и стенами. Сохраняет .blend; render=true - вернёт картинку сцены.",
    {
        "ids": {"type": "array", "items": {"type": "string"}},
        "title": {"type": "string"},
        "room": {"type": "boolean", "default": False},
        "render": {"type": "boolean", "default": True},
    },
    ["ids"],
    write=True,
)
def ue_blender(ids, title="Сцена", room=False, render=True):
    from library import blender_scene as B
    from library.unreal_import import asset_name

    exe = B.find_blender()
    if not exe:
        raise ApiError("Blender не найден на этом компьютере.")
    assets = _by_ids(ids)
    folder = os.path.join(U.ROOT, "_scenes", asset_name(title))
    script, blend = B.write_script(assets, folder, title, room)
    r = B.run(exe, script, background=True)
    if r.returncode != 0 or not os.path.exists(blend):
        raise ApiError("Blender не собрал сцену: " + (r.stderr or r.stdout)[-400:])
    if not render:
        return {"blend": blend}
    png = os.path.join(tempfile.gettempdir(), asset_name(title) + "_render.png")
    rs = os.path.join(folder, "render_preview.py")
    with open(rs, "w", encoding="utf-8") as fh:
        fh.write(
            "import bpy\nsc = bpy.context.scene\nsc.render.engine = 'BLENDER_EEVEE'\n"
            "sc.render.resolution_x, sc.render.resolution_y = 1280, 720\n"
            f"sc.render.filepath = {png!r}\nbpy.ops.render.render(write_still=True)\n"
        )
    subprocess_res = B.subprocess.run(
        [exe, "-b", blend, "--python", rs],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        creationflags=getattr(B.subprocess, "CREATE_NO_WINDOW", 0),
    )
    if subprocess_res.returncode != 0 or not os.path.exists(png):
        return {"blend": blend, "render": "не вышло"}
    im = Image.open(png).convert("RGBA")
    back = Image.new("RGBA", im.size, (40, 40, 48, 255))  # фон рендера прозрачный - серым, а не чёрным
    back.alpha_composite(im)
    return Picture(back.convert("RGB"), f"Сцена сохранена: {blend}")


@tool(
    "ue_show",
    "Показать ассеты пользователю во вкладке «Unreal» открытого окна (отдельным списком с заголовком): "
    "«вот модели для твоей сцены». Ничего не меняет.",
    {"ids": {"type": "array", "items": {"type": "string"}}, "title": {"type": "string"}},
    ["ids"],
)
def ue_show(ids, title=""):
    assets = _by_ids(ids, 300)
    ui_bridge.request("unreal", [_key(a) for a in assets], title or "Подборка помощника", AGENT["who"])
    return {"shown": len(assets), "title": title or "Подборка помощника"}


@tool(
    "ue_add_archives",
    "Разобрать скачанные пользователем архивы моделей (zip или папки: KayKit, Quaternius MegaKit с itch.io...) "
    "по группам. Без paths - всё из папки _Unreal/_Архивы. Повторы пропускаются, превью окно нарисует само.",
    {"paths": {"type": "array", "items": {"type": "string"}}},
    write=True,
)
def ue_add_archives(paths=None):
    from library import unreal_local as L

    paths = paths or L.dropped()
    if not paths:
        raise ApiError(f"Архивов нет: положите zip в {L.DROP} или передайте paths.")
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise ApiError("Нет таких файлов: " + "; ".join(missing[:5]))
    res = L.import_archives(paths, log=lambda text: report(0, None, text))
    if res["added"]:
        ui_bridge.ue_changed()
    return res


@tool(
    "ue_check",
    "Проверка ассетов Unreal: нет файлов, пустой FBX, нет превью и повторы (одна модель, скачанная дважды: то же "
    "имя и то же превью). Убрать - пользователь сам в окне («Проверка» -> правый щелчок -> в корзину). Ничего не меняет.",
    {"limit": {"type": "integer", "default": 100}},
)
def ue_check(limit=100):
    from library import unreal_extra as X

    items = _items()
    probs = [(a, why) for a, why in X.check(items) if a is not None]
    return {
        "checked": len(items),
        "problems": len(probs),
        "items": [dict(_brief(a), problem=why) for a, why in probs[: max(1, limit)]],
    }


@tool(
    "ue_from_project",
    "Модели, скачанные в самом Unreal (Fab, Megascans, MetaHuman из Bridge), - в библиотеку: Unreal выгружает "
    "папку проекта в FBX (редактор с проектом должен быть закрыт; минуты). MetaHuman - одним ассетом. "
    "folder - папка на диске внутри Content (например, .../Content/MetaHumans/Emanuel).",
    {"project": {"type": "string"}, "folder": {"type": "string"}, "theme": {"type": "string"}},
    ["project", "folder"],
    write=True,
)
def ue_from_project(project, folder, theme=None):
    from library import unreal_from_project as P

    if not os.path.exists(project) or not project.lower().endswith(".uproject"):
        raise ApiError("Нужен путь к .uproject. Проекты на компьютере - ue_overview (unreal_projects).")
    if not os.path.isdir(folder):
        raise ApiError("Нет такой папки.")
    try:
        made = P.add_to_library(project, folder, theme, log=lambda t: report(0, None, "выгружено: " + t))
    except (RuntimeError, ValueError, FileNotFoundError, TimeoutError) as e:
        raise ApiError(str(e)) from e
    ui_bridge.ue_changed()
    return {"added": [_brief(a) for a in _items() if a["dir"] in made]}


@tool(
    "ue_from_megascans",
    "Всё, что пользователь скачал через Quixel Bridge в Documents/Megascans Library (MetaHuman), - в библиотеку: "
    "Unreal выгружает в FBX во временном проекте (долго: минуты на каждые шесть). Уже добавленные пропускаются; "
    "у добавленных без текстур выгружаются только текстуры для 3D-просмотра.",
    write=True,
)
def ue_from_megascans():
    from library import unreal_from_project as P

    res = P.import_megascans(log=lambda t: report(0, None, t))
    if res["added"] or res["retextured"]:
        ui_bridge.ue_changed()
    return {
        "added": len(res["added"]),
        "retextured": len(res["retextured"]),
        "skipped": res["skipped"],
        "errors": res["errors"],
    }


@tool(
    "ue_budget",
    "Бюджет сцены в Unreal для подборки или списка ассетов: треугольники (по самим FBX), память видеокарты под "
    "текстуры (примерно, со сжатием Unreal и мипами), что включить с Nanite, что упростить (ue_simplify), "
    "общий вывод. Перед импортом большой сцены.",
    {
        "ids": {"type": "array", "items": {"type": "string"}},
        "collection": {"type": "string", "description": "или имя подборки (ue_overview -> collections)"},
    },
)
def ue_budget(ids=None, collection=None):
    from library import budget, unreal_sets

    if collection:
        sets = unreal_sets.load()
        if collection not in sets:
            raise ApiError(f"Нет подборки «{collection}». Есть: {', '.join(sets) or 'ни одной'}.")
        ids = list(sets[collection])
    if not ids:
        raise ApiError("Нужны ids или collection.")
    return budget.scene(_by_ids(ids, 400))


@tool(
    "ue_simplify",
    "Упростить тяжёлую модель в Blender (Decimate) до triangles треугольников: рядом с оригиналом появляется "
    "<имя>_<N>k.fbx, и при импорте и в пакете берётся она (use=false - снова оригинал). Оригинал не меняется. "
    "Модели со скелетом не упрощаются. Тяжёлая модель - минута-другая.",
    {
        "id": {"type": "string"},
        "triangles": {"type": "integer", "default": 100000},
        "use": {"type": "boolean", "default": True, "description": "false - не брать упрощённую копию при импорте"},
    },
    ["id"],
    write=True,
)
def ue_simplify(id, triangles=100000, use=True):  # noqa: A002
    from library import budget

    a = _by_ids([id])[0]
    if a.get("kind") != "model":
        raise ApiError("Упрощать можно только модели.")
    if not use:
        budget.set_active(a, None)
        return {"id": id, "use": "оригинал"}
    if triangles < 500:
        raise ApiError("Меньше 500 треугольников - от модели ничего не останется.")
    report(0, None, f"упрощаю {a.get('name')} в Blender")
    try:
        item = budget.simplify(a, triangles)
    except (ValueError, RuntimeError) as e:
        raise ApiError(str(e)) from e
    return {"id": id, **item}


@tool(
    "ue_scale_check",
    "Модели не в своём масштабе: размер из FBX против настоящего (стул 70-110 см высотой, дверь 180-290). "
    "Low-poly наборы часто сделаны не в сантиметрах - стул Kenney Furniture Kit 4.7 м. packs - общий множитель "
    "на весь набор (одна единица на кит), items - поштучно. Исправить - ue_set_scale.",
    {"limit": {"type": "integer", "default": 60}},
)
def ue_scale_check(limit=60):
    from library import scale_check

    r = scale_check.check(_items())
    return dict(
        packs=[
            {k: p[k] for k in ("pack", "source", "url", "factor", "checked", "wrong", "fixed", "examples")}
            for p in r["packs"]
        ],
        items=[dict({k: v for k, v in x.items() if k != "asset"}, id=_key(x["asset"])) for x in r["items"][:limit]],
        total_items=len(r["items"]),
    )


@tool(
    "ue_set_scale",
    "Поправить масштаб моделей: множитель для ids или для всего набора (pack из ue_scale_check). Файлы не "
    "меняются - множитель берут размеры в окне и импорт в Unreal (Import Uniform Scale). factor=1 - как в файле.",
    {
        "factor": {"type": "number"},
        "ids": {"type": "array", "items": {"type": "string"}},
        "pack": {"type": "string"},
    },
    ["factor"],
    write=True,
)
def ue_set_scale(factor, ids=None, pack=None):
    from library import scale_check
    from library import unreal_extra as X

    try:
        factor = float(factor)
    except (TypeError, ValueError):
        raise ApiError("factor - число, например 0.2 или 4.") from None
    if not 0.001 <= factor <= 1000:
        raise ApiError("factor - от 0.001 до 1000.")
    if pack:
        assets = scale_check.pack_members(_items(), pack)
        if not assets:
            raise ApiError(f"Нет набора «{pack}» - список: ue_scale_check.")
    elif ids:
        assets = [a for a in _by_ids(ids, 400) if a.get("kind") == "model"]
    else:
        raise ApiError("Нужны ids или pack.")
    n = X.set_scale(assets, factor)
    return {"changed": n, "models": len(assets), "factor": factor}
