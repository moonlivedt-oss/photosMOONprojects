"""Импорт в Unreal одним скриптом: файлы ассетов копируются в папку проекта, рядом пишется
import_to_unreal.py - его запускают в самом Unreal (Tools -> Execute Python Script или в Output Log:
py "путь"). Скрипт импортирует всё в /Game/Library/<вид>/<имя> с правильными настройками текстур
и собирает материал M_<имя> из PBR-карт. Нужен плагин Python Editor Script Plugin (в UE5 включён).

Без Qt: зовут вкладка («Импорт в Unreal...») и командная строка."""

import json
import os
import re
import shutil

GAME_ROOT = "/Game/Library"
SUB = {"tex": "Textures", "hdri": "HDRI", "model": "Models", "ies": "Lights"}


def asset_name(name):
    """Имя для Unreal: латиница, цифры и _ (Unreal не любит пробелы и кириллицу в именах ассетов)."""
    from imaging.ies import translit

    s = re.sub(r"[^A-Za-z0-9_]+", "_", translit(name)).strip("_")
    return s or "Asset"


def tryon_of(a, tryons=None):
    """Примерка этой модели из окна 3D (settings.json, ue_tryon): текстура и настройки -> для материала в Unreal.
    Шахматку и примерку без файлов не берём."""
    if a.get("kind") != "model":
        return None
    if tryons is None:
        from library.common import load_cfg

        try:
            tryons = load_cfg().get("ue_tryon") or {}
        except Exception:
            tryons = {}
    t = tryons.get(a["dir"])
    if not t or t.get("tex") in (None, "checker") or not os.path.isdir(t["tex"]):
        return None
    files = [
        os.path.join(t["tex"], f)
        for f in sorted(os.listdir(t["tex"]))
        if f.lower().endswith((".jpg", ".jpeg", ".png")) and not f.startswith("preview") and "_nor_gl" not in f.lower()
    ]
    return dict(t, files=files) if files else None


def plan(assets, dst, tryons=None):
    """Скопировать файлы ассетов в dst/<имя>/ и составить список работ для скрипта. Модель с примеркой из окна 3D
    везёт и свою текстуру - скрипт соберёт из неё материал с тем же повтором, поворотом, оттенком и глянцем."""
    from library import budget

    jobs, used = [], set()
    for a in map(budget.for_import, assets):
        name = base = asset_name(a.get("name", "asset"))
        n = 2
        while name.lower() in used:  # одинаковые имена (Stool в двух наборах Quaternius) - не в одну папку
            name, n = f"{base}_{n}", n + 1
        used.add(name.lower())
        folder = os.path.join(dst, name)
        os.makedirs(folder, exist_ok=True)
        files = []
        for m in a.get("main", []):
            src = os.path.join(a["dir"], *m.split("/"))
            if not os.path.exists(src):
                continue
            out = os.path.join(folder, os.path.basename(src))
            shutil.copy2(src, out)
            files.append(out)
        for x in a.get("extra", []):  # общая текстура Kenney: FBX ищет её по своему пути (Textures/...)
            src = os.path.join(a["dir"], *x.split("/"))
            if os.path.exists(src):
                out = os.path.join(folder, *x.split("/"))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy2(src, out)
        if a.get("kind") == "model":  # текстуры модели - рядом, FBX ищет их по пути
            tex = os.path.join(a["dir"], "textures")
            if os.path.isdir(tex):
                shutil.copytree(tex, os.path.join(folder, "textures"), dirs_exist_ok=True)
        job = {
            "kind": a.get("kind") or "",
            "rigged": bool(a.get("rigged")),
            "name": name,
            "files": files,
            "dest": f"{GAME_ROOT}/{SUB.get(a.get('kind'), 'Misc')}/{name}",
        }
        t = tryon_of(a, tryons)
        if t:
            tex_name = asset_name(os.path.basename(t["tex"]))
            tdir = os.path.join(folder, "tryon_" + tex_name)
            os.makedirs(tdir, exist_ok=True)
            tfiles = []
            for f in t["files"]:
                out = os.path.join(tdir, os.path.basename(f))
                shutil.copy2(f, out)
                tfiles.append(out)
            job["tryon"] = {
                "name": tex_name,
                "files": tfiles,
                "tiling": float(t.get("tiling", 1) or 1),
                "rot": float(t.get("rot", 0) or 0),
                "tint": t.get("tint", "#ffffff"),
                "rough": 1 - float(t.get("gloss", 0) or 0) / 100,
                "off": list(t.get("off") or []),  # детали без примерки - по имени слота материала
            }
        jobs.append(job)
    return jobs


ROLES = (
    (("_diff", "_color", "albedo", "basecolor"), "color"),
    (("nor_dx", "normaldx", "_normal", "nor_gl", "normalgl"), "normal"),
    (("_arm_",), "arm"),
    (("rough",), "rough"),
    (("metal",), "metal"),
    (("ambientocclusion", "_ao_", "_ao."), "ao"),
    (("_disp", "displacement", "height"), "height"),
)


def role_of(fn):
    """Роль карты по имени файла (как в скрипте для Unreal): color, normal, arm, rough, metal, ao, height."""
    low = fn.lower()
    return next((role for keys, role in ROLES if any(k in low for k in keys)), "")


SCRIPT = r'''# Импорт ассетов из библиотеки картинок. Запуск в Unreal: Tools -> Execute Python Script
# (или в Output Log, режим Cmd: py "{path}"). Нужен плагин Python Editor Script Plugin.
import json
import math
import os

import unreal

JOBS = json.loads({jobs})

tools = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary


def role_of(fn):
    low = fn.lower()
    for keys, role in ((("_diff", "_color", "albedo", "basecolor"), "color"),
                       (("nor_dx", "normaldx", "_normal"), "normal"), (("_arm_",), "arm"), (("rough",), "rough"),
                       (("metal",), "metal"), (("ambientocclusion", "_ao_", "_ao."), "ao"),
                       (("_disp", "displacement", "height"), "height")):
        if any(k in low for k in keys):
            return role
    return ""


def task(path, dest, skeletal=False):
    t = unreal.AssetImportTask()
    t.filename = path
    t.destination_path = dest
    t.automated = True
    t.replace_existing = True
    t.save = True
    if path.lower().endswith(".fbx"):
        ui = unreal.FbxImportUI()
        ui.import_materials = True
        ui.import_textures = True
        ui.import_as_skeletal = skeletal  # персонаж со скелетом - Skeletal Mesh и его анимации
        ui.import_animations = skeletal
        if skeletal:
            ui.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH
        t.options = ui
    return t


def make_material(name, dest, maps, look=None):
    """M_<имя>: цвет -> Base Color, нормаль -> Normal, ARM -> AO/Roughness/Metallic.
    look (примерка из окна 3D): повтор, поворот в градусах, оттенок, множитель шероховатости."""
    mat = tools.create_asset("M_" + name, dest, unreal.Material, unreal.MaterialFactoryNew())
    uv = None
    if look:
        uv = mel.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -1100, 0)
        uv.set_editor_property("u_tiling", look["tiling"])
        uv.set_editor_property("v_tiling", look["tiling"])
        if look["rot"]:
            rot = mel.create_material_expression(mat, unreal.MaterialExpressionRotator, -900, 0)
            ang = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -1100, 160)
            ang.set_editor_property("r", math.radians(look["rot"]))
            rot.set_editor_property("speed", 1.0)  # угол = время x скорость: «время» - постоянный угол
            mel.connect_material_expressions(uv, "", rot, "Coordinate")
            mel.connect_material_expressions(ang, "", rot, "Time")
            uv = rot
    y = 0
    for role, tex in maps.items():
        s = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSample, -480, y)
        s.texture = tex
        if uv is not None:
            mel.connect_material_expressions(uv, "", s, "UVs")
        y += 260
        if role == "color" and look and look["tint"].lower() != "#ffffff":
            h = look["tint"].lstrip("#")
            c = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -480, y)
            c.set_editor_property("constant", unreal.LinearColor(*[int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], 1.0))
            mul = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -220, y - 200)
            mel.connect_material_expressions(s, "RGB", mul, "A")
            mel.connect_material_expressions(c, "", mul, "B")
            mel.connect_material_property(mul, "", unreal.MaterialProperty.MP_BASE_COLOR)
            y += 120
        elif role == "color":
            mel.connect_material_property(s, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
        elif role == "normal":
            s.sampler_type = unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL
            mel.connect_material_property(s, "RGB", unreal.MaterialProperty.MP_NORMAL)
        elif role == "arm":
            s.sampler_type = unreal.MaterialSamplerType.SAMPLERTYPE_MASKS
            mel.connect_material_property(s, "R", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
            rough_out(mat, s, "G", look, y)
            mel.connect_material_property(s, "B", unreal.MaterialProperty.MP_METALLIC)
        elif role == "rough":
            s.sampler_type = unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR
            rough_out(mat, s, "R", look, y)
        elif role in ("metal", "ao"):
            s.sampler_type = unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR
            prop = {{"metal": unreal.MaterialProperty.MP_METALLIC, "ao": unreal.MaterialProperty.MP_AMBIENT_OCCLUSION}}[role]
            mel.connect_material_property(s, "R", prop)
    mel.recompile_material(mat)
    eal.save_loaded_asset(mat)
    return mat


def rough_out(mat, s, ch, look, y):
    """Шероховатость - как в карте или, с глянцем из примерки, умноженная на множитель."""
    if not look or look["rough"] >= 0.999:
        mel.connect_material_property(s, ch, unreal.MaterialProperty.MP_ROUGHNESS)
        return
    k = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -480, y + 40)
    k.set_editor_property("r", look["rough"])
    mul = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -220, y)
    mel.connect_material_expressions(s, ch, mul, "A")
    mel.connect_material_expressions(k, "", mul, "B")
    mel.connect_material_property(mul, "", unreal.MaterialProperty.MP_ROUGHNESS)


def texture_maps(tasks, files):
    """Импортированные текстуры -> {{роль: Texture2D}} с правильными sRGB и сжатием."""
    maps = {{}}
    for t, p in zip(tasks, files):
        for obj in t.get_editor_property("imported_object_paths") or []:
            tex = eal.load_asset(obj)
            role = role_of(os.path.basename(p))
            if not isinstance(tex, unreal.Texture2D) or not role or role == "height":
                continue
            if role != "color":                       # всё, кроме цвета, - данные, не картинка
                tex.set_editor_property("srgb", False)
            if role == "normal":
                tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
            elif role in ("arm", "rough", "metal", "ao"):
                tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
            eal.save_loaded_asset(tex)
            maps[role] = tex
    return maps


def wear(job, tasks):
    """Примерка из окна 3D: материал из её текстуры - на слоты модели (кроме снятых галочкой деталей)."""
    t = job["tryon"]
    dest = job["dest"] + "/Tryon"
    tt = [task(p, dest) for p in t["files"]]
    tools.import_asset_tasks(tt)
    maps = texture_maps(tt, t["files"])
    if not maps:
        return
    mat = make_material(job["name"] + "_" + t["name"], dest, maps, t)
    off = {{x.lower() for x in t["off"]}}
    for tk in tasks:
        for obj in tk.get_editor_property("imported_object_paths") or []:
            mesh = eal.load_asset(obj)
            if isinstance(mesh, unreal.StaticMesh):
                slots = mesh.get_editor_property("static_materials")
                names = [str(x.get_editor_property("material_slot_name")).lower() for x in slots]
                use = [i for i, n in enumerate(names) if n not in off] if off & set(names) else list(range(len(names)))
                for i in use:
                    mesh.set_material(i, mat)
                eal.save_loaded_asset(mesh)
            elif isinstance(mesh, unreal.SkeletalMesh):
                mats = list(mesh.get_editor_property("materials"))
                names = [str(x.get_editor_property("material_slot_name")).lower() for x in mats]
                for i, m in enumerate(mats):
                    if not (off & set(names)) or names[i] not in off:
                        m.set_editor_property("material_interface", mat)
                mesh.set_editor_property("materials", mats)
                eal.save_loaded_asset(mesh)
    unreal.log("Библиотека: на {{}} надет материал примерки M_{{}}_{{}}".format(job["name"], job["name"], t["name"]))


done = 0
for job in JOBS:
    tasks = [task(p, job["dest"], job.get("rigged", False)) for p in job["files"]]
    tools.import_asset_tasks(tasks)
    if job["kind"] == "tex":
        maps = texture_maps(tasks, job["files"])
        if maps:
            make_material(job["name"], job["dest"], maps)
    if job.get("tryon"):
        wear(job, tasks)
    done += 1
    unreal.log("Библиотека: импортировано {{}} ({{}} из {{}})".format(job["name"], done, len(JOBS)))
unreal.log("Библиотека: готово, ассеты в {root}")
'''


def write_script(jobs, dst):
    path = os.path.join(dst, "import_to_unreal.py")
    text = SCRIPT.format(
        jobs=repr(json.dumps(jobs, ensure_ascii=False, indent=1)), path=path.replace("\\", "/"), root=GAME_ROOT
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def export(assets, dst, tryons=None):
    """Скопировать и написать скрипт. -> путь скрипта."""
    os.makedirs(dst, exist_ok=True)
    return write_script(plan(assets, dst, tryons), dst)
