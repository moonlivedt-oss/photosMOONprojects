"""Операции для ИИ-помощников по вкладке «Unreal»: найти ассеты (и по смыслу), посмотреть превью,
собрать подборку и комнату по описанию, скачать по теме, сделать пакет, импортировать в проект
Unreal и собрать сцену в Blender. Регистрируются в общем списке library.api (тот же MCP и cli.py api)."""

import os
import tempfile

from PIL import Image

from library import unreal as U
from library.api import ApiError, Picture, sheet, tool

ASSET_LIMIT = 40


def _items():
    return U.assets()


def _key(a):
    return a.get("id") or os.path.relpath(a["dir"], U.ROOT).replace(os.sep, "/")


def _section(a):
    if a.get("kind") == "model" and a.get("theme", "").startswith("Дом - "):
        return U.home_section(a)
    return ""


def _brief(a):
    out = {
        "id": _key(a),
        "name": a.get("name", ""),
        "kind": a.get("kind"),
        "theme": a.get("theme", ""),
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


@tool("ue_overview", "Ассеты Unreal: сколько каких видов и тем скачано, подборки, найденные Unreal и Blender.")
def ue_overview():
    from library import blender_scene, unreal_engine, unreal_sets

    items = _items()
    kinds = {}
    for a in items:
        k = kinds.setdefault(a.get("kind"), {"count": 0, "themes": {}})
        k["count"] += 1
        k["themes"][a.get("theme", "")] = k["themes"].get(a.get("theme", ""), 0) + 1
    return {
        "folder": U.ROOT,
        "kinds": kinds,
        "themes_available": list(U.THEMES),
        "collections": {n: len(v) for n, v in unreal_sets.load().items()},
        "unreal_engines": unreal_engine.engines(),
        "unreal_projects": unreal_engine.projects(),
        "blender": blender_scene.find_blender(),
        "license": U.LICENSE,
    }


@tool(
    "ue_search",
    "Найти ассеты Unreal по смыслу («деревянный стул», «rusty metal») или по словам; фильтры вид и тема.",
    {
        "query": {"type": "string"},
        "kind": {"type": "string", "enum": ["tex", "hdri", "model", "ies"]},
        "theme": {"type": "string", "description": "тема или раздел дома («Кровати»)"},
        "limit": {"type": "integer", "default": 20},
    },
)
def ue_search(query="", kind=None, theme=None, limit=20):
    items = _items()
    if kind:
        items = [a for a in items if a.get("kind") == kind]
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
    return {"total": len(found), "assets": [_brief(a) for a in found[: max(1, min(100, limit))]]}


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
    ids = unreal_sets.load().get(name, [])
    idx = {_key(a): a for a in _items()}
    return {"name": name, "count": len(ids), "assets": [_brief(idx[i]) for i in ids if i in idx]}


@tool(
    "ue_download",
    "Скачать новые бесплатные ассеты (CC0, Poly Haven, ambientCG, Kenney, Quaternius) по теме. Долго: сеть.",
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
    got = U.get_many(kind, theme, max(1, min(20, count)), res, log=lambda s: s.startswith("  !") and errs.append(s))
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
    res = E.import_into(_by_ids(ids), project)
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
