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


def plan(assets, dst):
    """Скопировать файлы ассетов в dst/<имя>/ и составить список работ для скрипта."""
    jobs, used = [], set()
    for a in assets:
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
        if a.get("kind") == "model":  # текстуры модели - рядом, FBX ищет их по пути
            tex = os.path.join(a["dir"], "textures")
            if os.path.isdir(tex):
                shutil.copytree(tex, os.path.join(folder, "textures"), dirs_exist_ok=True)
        jobs.append(
            {
                "kind": a.get("kind") or "",
                "name": name,
                "files": files,
                "dest": f"{GAME_ROOT}/{SUB.get(a.get('kind'), 'Misc')}/{name}",
            }
        )
    return jobs


SCRIPT = r'''# Импорт ассетов из библиотеки картинок. Запуск в Unreal: Tools -> Execute Python Script
# (или в Output Log, режим Cmd: py "{path}"). Нужен плагин Python Editor Script Plugin.
import json
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


def task(path, dest):
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
        ui.import_as_skeletal = False
        t.options = ui
    return t


def make_material(name, dest, maps):
    """M_<имя>: цвет -> Base Color, нормаль -> Normal, ARM -> AO/Roughness/Metallic."""
    mat = tools.create_asset("M_" + name, dest, unreal.Material, unreal.MaterialFactoryNew())
    y = 0
    for role, tex in maps.items():
        s = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSample, -480, y)
        s.texture = tex
        y += 260
        if role == "color":
            mel.connect_material_property(s, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
        elif role == "normal":
            s.sampler_type = unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL
            mel.connect_material_property(s, "RGB", unreal.MaterialProperty.MP_NORMAL)
        elif role == "arm":
            s.sampler_type = unreal.MaterialSamplerType.SAMPLERTYPE_MASKS
            mel.connect_material_property(s, "R", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
            mel.connect_material_property(s, "G", unreal.MaterialProperty.MP_ROUGHNESS)
            mel.connect_material_property(s, "B", unreal.MaterialProperty.MP_METALLIC)
        elif role in ("rough", "metal", "ao"):
            s.sampler_type = unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR
            prop = {{"rough": unreal.MaterialProperty.MP_ROUGHNESS, "metal": unreal.MaterialProperty.MP_METALLIC,
                    "ao": unreal.MaterialProperty.MP_AMBIENT_OCCLUSION}}[role]
            mel.connect_material_property(s, "R", prop)
    mel.recompile_material(mat)
    eal.save_loaded_asset(mat)


done = 0
for job in JOBS:
    tasks = [task(p, job["dest"]) for p in job["files"]]
    tools.import_asset_tasks(tasks)
    if job["kind"] == "tex":
        maps = {{}}
        for t, p in zip(tasks, job["files"]):
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
        if maps:
            make_material(job["name"], job["dest"], maps)
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


def export(assets, dst):
    """Скопировать и написать скрипт. -> путь скрипта."""
    os.makedirs(dst, exist_ok=True)
    return write_script(plan(assets, dst), dst)
