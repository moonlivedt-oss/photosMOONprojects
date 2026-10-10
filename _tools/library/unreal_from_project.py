"""Модели, скачанные в самом Unreal (Fab, Megascans, MetaHuman из Bridge), -> ассеты библиотеки. Без Qt.

Скачанное лежит в формате .uasset, который вне Unreal не открыть. Поэтому Unreal сам выгружает модели в FBX:
редактор без окна (-RenderOffscreen) со скриптом, который в конце закрывает редактор. Коммандлет
(-run=pythonscript) не годится: выгрузка Skeletal Mesh без отрисовки роняет Unreal (Assertion: MeshObject).
Один запуск выгружает сразу несколько папок - запуск редактора стоит минуты.

MetaHuman - одним ассетом (тело, лицо, волосы-карточки, одежда - несколькими FBX), остальное - ассет на модель.
Лицензия - не CC0: у MetaHuman своя (только в проектах на Unreal Engine), у Fab - лицензия продавца.

Библиотека Megascans (Documents/Megascans Library/Downloaded/UAssets, туда качает Bridge) - не проект:
папки персонажей по очереди кладутся во временный проект _tools/_ue_stage и выгружаются оттуда; проекты
пользователя не трогаются."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from PIL import Image

import imaging as K
from library import unreal as U
from library import unreal_engine as E
from library.common import HERE, clean_name

METAHUMAN_LICENSE = (
    "MetaHuman (Epic Games): использовать можно только в проектах на Unreal Engine - не CC0, в другие движки "
    "и на продажу как ассет нельзя"
)
FAB_LICENSE = "из проекта Unreal (Fab / Megascans): лицензия - та, с которой ассет получен; не CC0"
MEGASCANS = os.path.join(os.path.expanduser("~"), "Documents", "Megascans Library", "Downloaded", "UAssets")
STAGE = os.path.join(HERE, "_ue_stage")  # временный проект для выгрузки из библиотеки Megascans

SCRIPT = r"""# Выгрузка моделей папок проекта в FBX (библиотека картинок). Редактор без окна, в конце закрывается.
import json, os
import unreal

JOBS = {jobs!r}  # [[путь /Game/..., папка выгрузки]]
eal = unreal.EditorAssetLibrary
reg = unreal.AssetRegistryHelpers.get_asset_registry()
opts = unreal.AssetRegistryDependencyOptions(include_hard_package_references=True)


def export(obj, path, options=None):
    t = unreal.AssetExportTask()
    t.object, t.filename = obj, path
    t.automated, t.prompt, t.replace_identical = True, False, True
    if options is not None:
        t.options = options
    return unreal.Exporter.run_asset_export_task(t)


for ROOT, OUT in JOBS:
    res = {{"meshes": [], "previews": [], "errors": []}}
    paths = list(eal.list_assets(ROOT, recursive=True, include_folder=False))
    # одежда MetaHuman лежит в общей папке (MetaHumans/Common): её модели - по связям Blueprint персонажа
    seen, todo = set(), [str(eal.find_asset_data(p).package_name) for p in paths if "/BP_" in p]
    for _depth in range(3):
        nxt = []
        for pkg in todo:
            for dep in reg.get_dependencies(pkg, opts) or []:
                dep = str(dep)
                if dep in seen or not dep.startswith("/Game/") or dep.startswith(ROOT):
                    continue
                seen.add(dep)
                nxt.append(dep)
        todo = nxt
    for dep in sorted(seen):
        for ad in reg.get_assets_by_package_name(dep):
            if str(ad.asset_class_path.asset_name) == "SkeletalMesh":
                paths.append(str(ad.package_name) + "." + str(ad.asset_name))
    for p in paths:
        ad = eal.find_asset_data(p)
        cls = str(ad.asset_class_path.asset_name)
        name = str(ad.asset_name)
        folder = str(ad.package_path)
        try:
            if cls in ("SkeletalMesh", "StaticMesh"):
                opt = unreal.FbxExportOption()
                opt.collision = False
                opt.level_of_detail = False  # только LOD0: остальные утяжеляют файл в разы
                dst = os.path.join(OUT, name + ".fbx")
                ok = export(ad.get_asset(), dst, opt)
                res["meshes"].append({{"name": name, "class": cls, "folder": folder, "file": dst, "ok": bool(ok)}})
            elif cls == "Texture2D" and "/Previews" in folder:
                dst = os.path.join(OUT, name + ".png")
                ok = export(ad.get_asset(), dst)
                res["previews"].append({{"name": name, "file": dst, "ok": bool(ok)}})
        except Exception as e:
            res["errors"].append(name + ": " + str(e))
        unreal.log("Библиотека: выгружено " + name)
    with open(os.path.join(OUT, "export.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False)
unreal.SystemLibrary.quit_editor()
"""


def game_path(project, folder):
    """Папка на диске внутри Content -> путь Unreal «/Game/...»."""
    content = os.path.join(os.path.dirname(project), "Content")
    rel = os.path.relpath(folder, content)
    if rel.startswith(".."):
        raise ValueError("папка не внутри Content проекта")
    return "/Game" + ("" if rel == "." else "/" + rel.replace(os.sep, "/"))


def export_folders(project, folders, log=None, timeout=3600):
    """Unreal выгружает модели папок в FBX. -> [(папка выгрузки, сведения export.json или None)]."""
    project = os.path.realpath(project)  # короткое имя 8.3 Unreal не сопоставит с Content
    if E.editor_running(project):
        raise RuntimeError("Редактор Unreal с этим проектом открыт - закройте его, выгрузку делает Unreal в фоне")
    engine = E.engine_for(project)
    if not engine:
        raise FileNotFoundError("Unreal Engine не найден")
    base = os.path.realpath(tempfile.mkdtemp(prefix="ue_export_"))
    jobs = []
    for i, f in enumerate(folders):
        out = os.path.join(base, str(i))
        os.makedirs(out)
        jobs.append([game_path(project, f), out])
    script = os.path.join(base, "export_from_project.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(SCRIPT.format(jobs=jobs))
    exe = os.path.join(os.path.dirname(E.cmd_exe(engine)), "UnrealEditor.exe")
    args = [exe, project, f"-ExecutePythonScript={script}", "-RenderOffscreen", "-unattended", "-nopause"]
    args += ["-nosplash", "-nosound", "-stdout", "-FullStdOutLogOutput"]
    p = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    t0, tail = time.time(), []
    for line in p.stdout:
        tail = (tail + [line.rstrip()])[-40:]
        if log and "Библиотека: выгружено" in line:
            log(line.split("Библиотека: выгружено", 1)[1].strip())
        if time.time() - t0 > timeout:
            p.kill()
            raise TimeoutError("Unreal не закончил выгрузку за %d мин" % (timeout // 60))
    p.wait()
    out = []
    for _root, d in jobs:
        info_path = os.path.join(d, "export.json")
        info = None
        if os.path.exists(info_path):
            with open(info_path, encoding="utf-8") as fh:
                info = json.load(fh)
        out.append((d, info))
    if all(info is None for _d, info in out):
        shutil.rmtree(base, ignore_errors=True)
        raise RuntimeError("Unreal не выгрузил ничего:\n" + "\n".join(tail[-12:]))
    return out


def _preview(src_png, dst):
    with Image.open(src_png) as im:
        im = im.convert("RGBA")
        im.thumbnail((512, 512), Image.LANCZOS)
        im.save(os.path.join(dst, "preview.webp"), quality=90)


def mh_skip(name):
    """Упрощённые копии волос и бровей (LOD1 и дальше, «шлем» волос) и заготовки *_Preview из MetaHuman Creator."""
    return bool(re.search(r"_LOD[1-9]$", name)) or "_Helmet_" in name or name.lower().endswith("_preview")


def mh_order(name):
    low = name.lower()
    return (0 if "body" in low else 1 if "face" in low else 2, low)  # тело первым: по нему размеры и полигоны


def is_metahuman(folder):
    return "metahumans" in folder.replace("\\", "/").lower().split("/")


def _write(dst, meta):
    meta["size"] = U.folder_size(dst)
    K.write_atomic(os.path.join(dst, "asset.json"), json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")


def put_metahuman(name, meshes, info, aid, origin, theme=None, preview_png=None):
    """Части MetaHuman -> один ассет _Unreal/Модели/Персонажи - MetaHuman/<имя>. -> папка."""
    dst = os.path.join(U.ROOT, U.KINDS["model"][0], clean_name(theme or "Персонажи - MetaHuman"), clean_name(name))
    os.makedirs(dst, exist_ok=True)
    main = []
    for m in sorted(meshes, key=lambda m: mh_order(m["name"])):
        if mh_skip(m["name"]):
            continue
        fn = os.path.basename(m["file"])
        shutil.copy2(m["file"], os.path.join(dst, fn))
        main.append(fn)
    if preview_png and os.path.exists(preview_png):  # снимок от Bridge - цветной, с волосами
        _preview(preview_png, dst)
    else:  # 3D окна лицо с сотнями морфов роняет - серое превью рисует Blender
        from library import blender_preview

        if not blender_preview.render([os.path.join(dst, m) for m in main], dst):
            prev = next((p["file"] for p in info["previews"] if p["ok"] and os.path.exists(p["file"])), None)
            if prev:
                _preview(prev, dst)
    _write(
        dst,
        {
            "id": aid,
            "name": f"{name} (MetaHuman)",
            "kind": "model",
            "theme": theme or "Персонажи - MetaHuman",
            "source": "MetaHuman",
            "url": "https://www.metahuman.com",
            "authors": ["Epic Games"],
            "tags": ["metahuman", "character", "human", "rigged"],
            "categories": ["characters"],
            "main": main,
            "license": METAHUMAN_LICENSE,
            "no_qt3d": True,  # см. ui/viewer3d.viewable
            "description": f"MetaHuman ({origin}): тело, лицо, волосы-карточки и одежда - отдельными FBX (LOD0). "
            "Волосы-пряди (Groom) в FBX не выгружаются.",
            "res": "",
            "added": time.strftime("%Y-%m-%d"),
            "howto": "Перетащите FBX в Content Browser как Skeletal Mesh; в своём проекте MetaHuman удобнее "
            "добавить заново через Quixel Bridge / MetaHuman Creator - так приходят и волосы, и риг лица.",
        },
    )
    return dst


def add_to_library(project, folder, theme=None, log=None):
    """Выгрузить папку проекта и положить в _Unreal. -> [папки новых ассетов]."""
    ((out, info),) = export_folders(project, [folder], log)
    try:
        meshes = [m for m in (info or {}).get("meshes", []) if m["ok"] and os.path.exists(m["file"])]
        if not meshes:
            raise RuntimeError("в папке нет моделей (StaticMesh / SkeletalMesh)")
        proj = os.path.splitext(os.path.basename(project))[0]
        if is_metahuman(folder):
            name = os.path.basename(folder.rstrip("\\/"))
            aid = f"unreal-{proj}-{re.sub(r'[^a-z0-9]+', '-', name.lower())}"
            return [put_metahuman(name, meshes, info, aid, f"из проекта «{proj}»", theme)]
        made = []
        th = theme or "Разное - Из проектов Unreal"
        for m in meshes:
            dst = os.path.join(U.ROOT, U.KINDS["model"][0], clean_name(th), clean_name(m["name"]))
            os.makedirs(dst, exist_ok=True)
            fn = os.path.basename(m["file"])
            shutil.copy2(m["file"], os.path.join(dst, fn))
            _write(
                dst,
                {
                    "id": f"unreal-{proj}-{m['folder'].lower().replace('/', '-')}-{m['name'].lower()}",
                    "name": U.pretty(m["name"]),
                    "kind": "model",
                    "theme": th,
                    "source": "Unreal",
                    "url": "",
                    "authors": [],
                    "tags": ["unreal", m["class"].lower()],
                    "categories": [],
                    "main": [fn],
                    "license": FAB_LICENSE,
                    "description": f"Из проекта «{proj}»: {m['folder']}/{m['name']}",
                    "res": "",
                    "added": time.strftime("%Y-%m-%d"),
                    "howto": f"Модель есть в проекте «{proj}»; в другой проект - перетащить FBX в Content Browser.",
                },
            )
            made.append(dst)
        return made
    finally:
        shutil.rmtree(os.path.dirname(out), ignore_errors=True)


# ---------------------------------------------------------------- библиотека Megascans (Bridge)
def megascans_list(root=MEGASCANS):
    """Скачанное через Bridge: [{id, name, type, dir, png}] из uassetsData.json."""
    try:
        with open(os.path.join(root, "uassetsData.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for a in data.get("assets", []):
        d = os.path.join(root, a["id"])
        if os.path.isdir(d):
            out.append(
                {
                    "id": a["id"],
                    "name": a.get("name", a["id"]),
                    "type": a.get("assetType", ""),
                    "dir": d,
                    "png": os.path.join(d, a["id"] + ".png"),
                }
            )
    return out


def _stage_project():
    """Временный проект для выгрузки: такие же настройки, как у пустого проекта UE 5.8."""
    proj = os.path.join(STAGE, "LibStage.uproject")
    if not os.path.exists(proj):
        os.makedirs(os.path.join(STAGE, "Content"), exist_ok=True)
        engines = E.engines()
        ver = sorted(engines, key=lambda v: [int(x) for x in re.findall(r"\d+", v)])[-1] if engines else "5.8"
        with open(proj, "w", encoding="utf-8") as fh:
            json.dump(
                {"FileVersion": 3, "EngineAssociation": ver, "Category": "", "Description": "", "Plugins": []}, fh
            )
    return proj


def _merge(src, dst):
    """Скопировать папку, не перезаписывая то, что уже есть (Common у всех MetaHuman общая)."""
    for d, _dirs, files in os.walk(src):
        out = os.path.join(dst, os.path.relpath(d, src))
        os.makedirs(out, exist_ok=True)
        for f in files:
            if not os.path.exists(os.path.join(out, f)):
                shutil.copy2(os.path.join(d, f), os.path.join(out, f))


def import_megascans(items=None, batch=6, log=None, stop=None):
    """MetaHuman из библиотеки Megascans -> ассеты. Уже добавленные (тот же id или то же имя) пропускаются.
    -> {"added": [папки], "skipped": [имена], "errors": [..]}."""
    items = [a for a in (items or megascans_list()) if a["type"] == "metahuman-preset"]
    have = U.assets(U.ROOT)
    have_ids = {a.get("id") for a in have}
    have_names = {a.get("name", "").lower() for a in have}
    todo = [a for a in items if f"megascans-{a['id']}" not in have_ids and f"{a['name']} (metahuman)".lower() not in have_names]
    res = {"added": [], "skipped": [a["name"] for a in items if a not in todo], "errors": []}
    if not todo:
        return res
    proj = _stage_project()
    content = os.path.join(STAGE, "Content", "MetaHumans")
    for i in range(0, len(todo), batch):
        if stop is not None and stop.is_set():
            break
        part = todo[i : i + batch]
        folders = []
        for a in part:  # персонаж и общая Common - во временный проект
            src = os.path.join(a["dir"], "Tier0", "asset_ue", "MetaHumans")
            if not os.path.isdir(os.path.join(src, a["name"])):
                res["errors"].append(f"{a['name']}: нет папки персонажа в загрузке Bridge")
                continue
            if log:
                log(f"копирую {a['name']}")
            _merge(os.path.join(src, "Common"), os.path.join(content, "Common"))
            shutil.copytree(os.path.join(src, a["name"]), os.path.join(content, a["name"]), dirs_exist_ok=True)
            folders.append((a, os.path.join(content, a["name"])))
        if not folders:
            continue
        try:
            outs = export_folders(proj, [f for _a, f in folders], log)
            for (a, _f), (_out, info) in zip(folders, outs):
                meshes = [m for m in (info or {}).get("meshes", []) if m["ok"] and os.path.exists(m["file"])]
                if not meshes:
                    res["errors"].append(f"{a['name']}: Unreal не выгрузил модели")
                    continue
                res["added"].append(
                    put_metahuman(a["name"], meshes, info, f"megascans-{a['id']}", "Quixel Bridge", None, a["png"])
                )
            shutil.rmtree(os.path.dirname(outs[0][0]), ignore_errors=True)
        except Exception as e:
            res["errors"].append("; ".join(a["name"] for a, _f in folders) + f": {e}")
        finally:
            for _a, f in folders:  # персонажей - прочь из временного проекта, Common остаётся до следующей пачки
                shutil.rmtree(f, ignore_errors=True)
    shutil.rmtree(STAGE, ignore_errors=True)  # временный проект - несколько ГБ: создаётся заново при надобности
    return res
