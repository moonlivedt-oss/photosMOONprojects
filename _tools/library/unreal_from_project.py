"""Модели, скачанные в самом Unreal (Fab, Megascans, MetaHuman из Bridge), -> ассеты библиотеки. Без Qt.

Скачанное лежит в проекте в формате .uasset, который вне Unreal не открыть. Поэтому Unreal сам (коммандлет
pythonscript, как при импорте - редактор с этим проектом должен быть закрыт) выгружает модели папки в FBX,
а картинки-превью - в PNG; дальше это обычные ассеты _Unreal: превью, 3D-просмотр, импорт в другие проекты.

MetaHuman выгружается одним ассетом (тело, лицо, одежда - несколько FBX), остальное - ассет на модель.
Лицензия - не CC0: у MetaHuman своя (только в проектах на Unreal Engine), у Fab - лицензия продавца."""

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
from library.common import clean_name

METAHUMAN_LICENSE = (
    "MetaHuman (Epic Games): использовать можно только в проектах на Unreal Engine - не CC0, в другие движки "
    "и на продажу как ассет нельзя"
)
FAB_LICENSE = "из проекта Unreal (Fab / Megascans): лицензия - та, с которой ассет получен; не CC0"

SCRIPT = r"""# Выгрузка моделей папки проекта в FBX (библиотека картинок). Запускается коммандлетом pythonscript.
import json, os
import unreal

ROOT, OUT = {root!r}, {out!r}
eal = unreal.EditorAssetLibrary
reg = unreal.AssetRegistryHelpers.get_asset_registry()
res = {{"meshes": [], "previews": [], "errors": []}}


def export(obj, path, options=None):
    t = unreal.AssetExportTask()
    t.object, t.filename = obj, path
    t.automated, t.prompt, t.replace_identical = True, False, True
    if options is not None:
        t.options = options
    return unreal.Exporter.run_asset_export_task(t)


paths = list(eal.list_assets(ROOT, recursive=True, include_folder=False))
# одежда MetaHuman лежит в общей папке (MetaHumans/Common): её модели берутся по связям Blueprint персонажа
opts = unreal.AssetRegistryDependencyOptions(include_hard_package_references=True)
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


def export_folder(project, folder, log=None, timeout=1800):
    """Unreal выгружает модели папки в FBX во временную папку. -> (папка выгрузки, сведения export.json)."""
    project = os.path.realpath(project)  # короткое имя 8.3 Unreal не сопоставит с Content
    if E.editor_running(project):
        raise RuntimeError("Редактор Unreal с этим проектом открыт - закройте его, выгрузку делает Unreal в фоне")
    engine = E.engine_for(project)
    if not engine:
        raise FileNotFoundError("Unreal Engine не найден")
    out = os.path.realpath(tempfile.mkdtemp(prefix="ue_export_"))
    script = os.path.join(out, "export_from_project.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(SCRIPT.format(root=game_path(project, folder), out=out))
    # не коммандлет, а редактор без окна: выгрузке Skeletal Mesh в FBX нужна отрисовка, без неё Unreal падает
    # (Assertion failed: MeshObject); скрипт в конце сам закрывает редактор
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
    info_path = os.path.join(out, "export.json")
    if not os.path.exists(info_path):
        raise RuntimeError("Unreal не выгрузил ничего:\n" + "\n".join(tail[-12:]))
    with open(info_path, encoding="utf-8") as fh:
        return out, json.load(fh)


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


def add_to_library(project, folder, theme=None, log=None):
    """Выгрузить папку проекта и положить в _Unreal. -> [папки новых ассетов]."""
    out, info = export_folder(project, folder, log)
    meshes = [m for m in info["meshes"] if m["ok"] and os.path.exists(m["file"])]
    if not meshes:
        raise RuntimeError("в папке нет моделей (StaticMesh / SkeletalMesh)" + "; ".join(info["errors"][:3]))
    proj = os.path.splitext(os.path.basename(project))[0]
    made = []
    try:
        if is_metahuman(folder):
            name = os.path.basename(folder.rstrip("\\/"))
            dst = os.path.join(U.ROOT, U.KINDS["model"][0], clean_name(theme or "Персонажи - MetaHuman"), name)
            os.makedirs(dst, exist_ok=True)
            main = []
            for m in sorted(meshes, key=lambda m: mh_order(m["name"])):
                if mh_skip(m["name"]):
                    continue
                fn = os.path.basename(m["file"])
                shutil.copy2(m["file"], os.path.join(dst, fn))
                main.append(fn)
            # картинки в Previews у MetaHuman - текстуры для Creator, а не снимок персонажа; 3D окна лицо с
            # сотнями морфов роняет - превью рисует Blender
            from library import blender_preview

            if not blender_preview.render([os.path.join(dst, m) for m in main], dst):
                prev = next((p["file"] for p in info["previews"] if p["ok"] and os.path.exists(p["file"])), None)
                if prev:
                    _preview(prev, dst)
            meta = {
                "id": f"unreal-{proj}-{re.sub(r'[^a-z0-9]+', '-', name.lower())}",
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
                "description": f"MetaHuman из проекта «{proj}»: тело, лицо и одежда - отдельными FBX (LOD0). "
                "Волосы (Groom) в FBX не выгружаются - они остаются в проекте.",
                "from_project": project,
                "res": "",
                "added": time.strftime("%Y-%m-%d"),
                "howto": "Перетащите FBX в Content Browser как Skeletal Mesh; в своём проекте MetaHuman удобнее "
                "добавить заново через Quixel Bridge / MetaHuman Creator - так приходят и волосы, и риг лица.",
            }
            meta["size"] = U.folder_size(dst)
            K.write_atomic(os.path.join(dst, "asset.json"), json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
            made.append(dst)
        else:
            th = theme or "Разное - Из проектов Unreal"
            for m in meshes:
                dst = os.path.join(U.ROOT, U.KINDS["model"][0], clean_name(th), clean_name(m["name"]))
                os.makedirs(dst, exist_ok=True)
                fn = os.path.basename(m["file"])
                shutil.copy2(m["file"], os.path.join(dst, fn))
                meta = {
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
                    "from_project": project,
                    "res": "",
                    "added": time.strftime("%Y-%m-%d"),
                    "howto": "Модель уже есть в проекте «%s»; в другой проект - перетащить FBX в Content Browser."
                    % proj,
                }
                meta["size"] = U.folder_size(dst)
                K.write_atomic(os.path.join(dst, "asset.json"), json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
                made.append(dst)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return made
