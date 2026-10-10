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

ASSET_LIMIT = 40


def _items():
    return G.annotate(U.assets())


def _key(a):
    return a.get("id") or os.path.relpath(a["dir"], U.ROOT).replace(os.sep, "/")


def _section(a):
    return a.get("_s") or G.section_of(a)


def _brief(a):
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
    for k in ("res", "polycount"):
        if a.get(k):
            out[k] = a[k]
    if _section(a):
        out["section"] = _section(a)
    return out


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
    "темы для ue_download, найденные Unreal и Blender. Начинать с него.",
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
        "theme": {"type": "string", "description": "тема скачивания или раздел («Кровати»)"},
        "limit": {"type": "integer", "default": 20},
        "offset": {"type": "integer", "default": 0},
    },
)
def ue_search(query="", kind=None, group=None, section=None, style=None, theme=None, limit=20, offset=0):
    items = _items()
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
    found = items
    if query.strip():
        sem = _sem()
        found = [a for a, _s in sem.rank(query, items)] if sem is not None else []
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
    return {
        "total": len(found),
        "assets": [_brief(a) for a in found[offset : offset + limit]],
        "hint": "Показать пользователю в окне - ue_show(ids); посмотреть самому - ue_view(ids).",
    }


@tool(
    "ue_view",
    "Посмотреть превью ассетов Unreal листом с номерами (по id из ue_search).",
    {"ids": {"type": "array", "items": {"type": "string"}}},
    ["ids"],
)
def ue_view(ids):
    assets = _by_ids(ids, 24)
    ims = []
    for a in assets:
        p = os.path.join(a["dir"], "preview.webp")
        ims.append(Image.open(p).convert("RGBA") if os.path.exists(p) else None)
    text = "\n".join(f"{i + 1}. {a.get('name', '')} ({_key(a)})" for i, a in enumerate(assets))
    return Picture(sheet(ims, [a.get("name", "") for a in assets]), text)


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
    from library import unreal_pack

    return {"path": unreal_pack.pack(_by_ids(ids), dest, title, zip)}


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
    res = E.import_into(_by_ids(ids), project, log=lambda text: report(0, None, text))
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
