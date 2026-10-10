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
import json, os, re
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


# текстуры MetaHuman для просмотровой копии (library/mh_view): только нужные - без LOD и служебных масок
TEX = re.compile(
    r"^(FaceColor_MAIN|FaceNormal_MAIN|FaceRoughness_MAIN|BodyBaseColor|T_Sclera_D|T_Iris_A_M|"
    r"T_Teeth_BaseColor_Baked|teeth_color_map_001|(fe)?male_body_normal_map|.+_CardsAtlas_Attribute|"
    r"Eyelashes_.+_Coverage)$",
    re.I,
)
common_done = set()


def wanted(name, folder):
    if TEX.match(name):
        return True
    parts = folder.split("/")  # одежда: нормаль и AO в Materials/<Вещь>
    return bool(re.search(r"_(N|AO)$", name)) and len(parts) >= 2 and parts[-2] == "Materials"


def export_textures(root, out):
    n = 0
    for p in eal.list_assets(root, recursive=True, include_folder=False):
        ad = eal.find_asset_data(p)
        name, folder = str(ad.asset_name), str(ad.package_path)
        if str(ad.asset_class_path.asset_name) != "Texture2D" or not wanted(name, folder):
            continue
        rel = folder.split("/MetaHumans/", 1)[-1]
        base = os.path.join(out, "textures", *rel.split("/"), name)
        os.makedirs(os.path.dirname(base), exist_ok=True)
        try:
            obj = ad.get_asset()
            if export(obj, base + ".png") or export(obj, base + ".tga"):
                n += 1
        except Exception as e:
            unreal.log_warning("Библиотека: текстура " + name + ": " + str(e))
    unreal.log("Библиотека: выгружено текстур " + str(n) + " из " + root)
    return n


for job in JOBS:
    ROOT, OUT = job[0], job[1]
    mode = job[2] if len(job) > 2 else "meshes"  # meshes | textures | both
    res = {{"meshes": [], "previews": [], "errors": [], "textures": 0}}
    if mode in ("textures", "both"):
        res["textures"] = export_textures(ROOT, OUT)
        common = ROOT.rsplit("/", 1)[0] + "/Common"
        if "/MetaHumans/" in ROOT + "/" and common not in common_done and eal.does_directory_exist(common):
            common_done.add(common)  # общая папка - один раз на запуск, в выгрузку первой задачи
            res["textures"] += export_textures(common, OUT)
    paths = list(eal.list_assets(ROOT, recursive=True, include_folder=False)) if mode != "textures" else []
    # одежда MetaHuman лежит в общей папке (MetaHumans/Common): её модели - по связям Blueprint персонажа
    seen, todo = set(), [str(eal.find_asset_data(p).package_name) for p in paths if "/BP_" in p]
    if mode == "textures":
        todo = []
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


def export_folders(project, folders, log=None, timeout=3600, modes=None):
    """Unreal выгружает модели папок в FBX. modes - на папку: "meshes" (по умолчанию), "textures" (только
    текстуры MetaHuman для просмотра) или "both". -> [(папка выгрузки, сведения export.json или None)]."""
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
        jobs.append([game_path(project, f), out, (modes or {}).get(f, "meshes")])
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
    for _root, d, _mode in jobs:
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
    from library import blender_preview, mh_view

    view = None  # для 3D окна - все части одним GLB без морфов: с текстурами, если они выгружены,
    # иначе подкрашенные по портрету
    if mh_view.has_textures(os.path.basename(dst)) and mh_view.make_view(dst, meta_main=main)[0]:
        view = "_view.glb"
    if view is None and blender_preview.make_view_model(
        [os.path.join(dst, m) for m in main],
        os.path.join(dst, "_view.glb"),
        colors=blender_preview.portrait_colors(os.path.join(dst, "preview.webp")),
    ):
        view = "_view.glb"
    _write(
        dst,
        {
            "id": aid,
            "name": f"{name} (MetaHuman)",
            "view": view,
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


TEX_SIDE = 2048  # текстуры для просмотра - не больше 2K (лицо и тело в 8K - сотни МБ на персонажа)


def collect_textures(out, root=None):
    """Выгруженные Unreal текстуры (out/textures/<Имя>|Common/...) -> root (_Unreal/_export/MetaHumans),
    уменьшенные до 2K, в PNG. -> сколько."""
    from library import mh_view

    root = root or mh_view.EXPORT
    src = os.path.join(out, "textures")
    n = 0
    for d, _sub, files in os.walk(src):
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() not in (".png", ".tga"):
                continue
            dst = os.path.join(root, os.path.relpath(d, src), stem + ".png")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                with Image.open(os.path.join(d, f)) as im:
                    im.load()
                    if max(im.size) > TEX_SIDE:
                        k = TEX_SIDE / max(im.size)
                        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
                    im.save(dst + ".part.png")
                os.replace(dst + ".part.png", dst)
                n += 1
            except OSError:
                pass
    return n


def needs_textures(asset_dir):
    """MetaHuman из библиотеки без выгруженных текстур - их копия для 3D окна ещё цветами с портрета."""
    from library import mh_view

    return not mh_view.has_textures(os.path.basename(asset_dir.rstrip("\\/")))


def import_megascans(items=None, batch=6, log=None, stop=None, textures=True):
    """MetaHuman из библиотеки Megascans -> ассеты. Уже добавленные (тот же id или то же имя) пропускаются;
    textures - заодно текстуры для 3D окна: у новых - вместе с моделями, у добавленных раньше без текстур -
    только текстуры, и их копия _view.glb пересобирается. -> {"added", "retextured", "skipped", "errors"}."""
    from library import mh_view

    items = [a for a in (items or megascans_list()) if a["type"] == "metahuman-preset"]
    have = U.assets(U.ROOT)
    by_id = {a.get("id"): a for a in have}
    by_name = {a.get("name", "").lower(): a for a in have}

    def existing(a):
        return by_id.get(f"megascans-{a['id']}") or by_name.get(f"{a['name']} (metahuman)".lower())

    todo = [a for a in items if existing(a) is None]
    retex = [a for a in items if textures and existing(a) is not None and needs_textures(existing(a)["dir"])]
    res = {"added": [], "retextured": [], "errors": []}
    res["skipped"] = [a["name"] for a in items if a not in todo and a not in retex]
    work = [(a, "both" if textures else "meshes") for a in todo] + [(a, "textures") for a in retex]
    if not work:
        return res
    proj = _stage_project()
    content = os.path.join(STAGE, "Content", "MetaHumans")
    for i in range(0, len(work), batch):
        if stop is not None and stop.is_set():
            break
        part = work[i : i + batch]
        folders = []
        for a, mode in part:  # персонаж и общая Common - во временный проект
            src = os.path.join(a["dir"], "Tier0", "asset_ue", "MetaHumans")
            if not os.path.isdir(os.path.join(src, a["name"])):
                res["errors"].append(f"{a['name']}: нет папки персонажа в загрузке Bridge")
                continue
            if log:
                log(f"копирую {a['name']}")
            _merge(os.path.join(src, "Common"), os.path.join(content, "Common"))
            shutil.copytree(os.path.join(src, a["name"]), os.path.join(content, a["name"]), dirs_exist_ok=True)
            folders.append((a, mode, os.path.join(content, a["name"])))
        if not folders:
            continue
        try:
            outs = export_folders(proj, [f for _a, _m, f in folders], log, modes={f: m for _a, m, f in folders})
            for out, _info in outs:  # текстуры - до сборки ассетов: put_metahuman их подхватит
                collect_textures(out)
            for (a, mode, _f), (_out, info) in zip(folders, outs):
                if mode == "textures":
                    old = existing(a)
                    if mh_view.has_textures(os.path.basename(old["dir"])) and mh_view.make_view(old["dir"])[0]:
                        res["retextured"].append(old["dir"])
                    else:
                        res["errors"].append(f"{a['name']}: текстуры не выгрузились")
                    continue
                meshes = [m for m in (info or {}).get("meshes", []) if m["ok"] and os.path.exists(m["file"])]
                if not meshes:
                    res["errors"].append(f"{a['name']}: Unreal не выгрузил модели")
                    continue
                res["added"].append(
                    put_metahuman(a["name"], meshes, info, f"megascans-{a['id']}", "Quixel Bridge", None, a["png"])
                )
            shutil.rmtree(os.path.dirname(outs[0][0]), ignore_errors=True)
        except Exception as e:
            res["errors"].append("; ".join(a["name"] for a, _m, _f in folders) + f": {e}")
        finally:
            for _a, _m, f in folders:  # персонажей - прочь из временного проекта, Common остаётся до следующей пачки
                shutil.rmtree(f, ignore_errors=True)
    shutil.rmtree(STAGE, ignore_errors=True)  # временный проект - несколько ГБ: создаётся заново при надобности
    return res
