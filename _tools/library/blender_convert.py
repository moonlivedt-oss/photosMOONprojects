"""Перевод моделей glb / gltf / obj в FBX через Blender (без окна): так у новых источников (сканы Google,
Smithsonian, Khronos, NASA) тот же путь, что у Poly Haven, - полигоны и размеры из FBX, бюджет сцены,
сцена в Blender, импорт в Unreal. Текстуры кладутся рядом в textures/, FBX ссылается на них относительно.

Сжатые Draco glb тоже открываются (Blender умеет); просмотровая копия для 3D-окна - glb без Draco.
Без Qt."""

import json
import os
import subprocess
import tempfile

# внутри Blender: задачи [{src, fbx, view, up}] -> рядом с файлом задач <имя>.out.json со списком ошибок
SCRIPT = r"""
import bpy, json, os, re, shutil, sys, traceback

jobs_path = sys.argv[sys.argv.index("--") + 1]
with open(jobs_path, encoding="utf-8") as fh:
    jobs = json.load(fh)
out = []


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "tex"


for job in jobs:
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        for src in job["src"] if isinstance(job["src"], list) else [job["src"]]:  # части одной модели - вместе
            low = src.lower()
            if low.endswith((".glb", ".gltf")):
                bpy.ops.import_scene.gltf(filepath=src)
            elif low.endswith(".obj"):
                if job.get("up") == "Z":
                    bpy.ops.wm.obj_import(filepath=src, forward_axis="Y", up_axis="Z")
                else:
                    bpy.ops.wm.obj_import(filepath=src)
            else:
                raise RuntimeError("не знаю формат: " + src)
        meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
        if not meshes:
            raise RuntimeError("в файле нет сетки")
        dst_dir = os.path.dirname(job["fbx"])
        tex_dir = os.path.join(dst_dir, "textures")
        used = set()
        for img in bpy.data.images:
            if img.source != "FILE" or not (img.packed_file or img.filepath):
                continue
            ext = ".jpg" if img.file_format == "JPEG" else ".png"
            base = safe(os.path.splitext(img.name)[0])
            name, n = base + ext, 2
            while name.lower() in used:
                name, n = f"{base}_{n}{ext}", n + 1
            used.add(name.lower())
            os.makedirs(tex_dir, exist_ok=True)
            path = os.path.join(tex_dir, name)
            if img.packed_file:
                img.save(filepath=path)
                img.unpack(method="REMOVE")
            else:
                orig = bpy.path.abspath(img.filepath)
                if not os.path.exists(orig):
                    continue
                path = os.path.join(tex_dir, safe(os.path.splitext(os.path.basename(orig))[0]) + os.path.splitext(orig)[1].lower())
                shutil.copyfile(orig, path)
            img.filepath = path
        bpy.ops.export_scene.fbx(
            filepath=job["fbx"],
            path_mode="RELATIVE",
            embed_textures=False,
            apply_unit_scale=True,
            bake_space_transform=False,
            mesh_smooth_type="FACE",
            add_leaf_bones=False,
            bake_anim=False,
        )
        if job.get("view"):
            bpy.ops.export_scene.gltf(filepath=job["view"], export_format="GLB", export_draco_mesh_compression_enable=False)
        tris = 0
        for o in meshes:
            for p in o.data.polygons:
                tris += len(p.vertices) - 2
        out.append({"ok": True, "tris": tris})
    except Exception:
        out.append({"ok": False, "error": traceback.format_exc(limit=2)[-600:]})

with open(jobs_path[:-5] + ".out.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh)
"""


def convert(jobs, blender=None, timeout=900):
    """jobs = [{"src": файл glb/gltf/obj (или список - части одной модели), "fbx": куда FBX, "view": куда glb для просмотра или None,
    "up": "Z" для obj с осью Z вверх}] -> [{"ok", "tris" | "error"}] в том же порядке. Один запуск Blender на все."""
    from library.blender_scene import find_blender

    exe = blender or find_blender()
    if not exe:
        raise RuntimeError("не найден Blender - он нужен, чтобы перевести модель в FBX")
    work = tempfile.mkdtemp(prefix="ue_convert_")
    try:
        script = os.path.join(work, "convert.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(SCRIPT)
        jp = os.path.join(work, "jobs.json")
        with open(jp, "w", encoding="utf-8") as fh:
            json.dump(jobs, fh, ensure_ascii=False)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(
            [exe, "-b", "--factory-startup", "--python", script, "--", jp],
            capture_output=True,
            timeout=timeout,
            creationflags=flags,
        )
        try:
            with open(jp[:-5] + ".out.json", encoding="utf-8") as fh:
                res = json.load(fh)
        except (OSError, ValueError):
            tail = (r.stderr or r.stdout or b"").decode("utf-8", "replace")[-400:]
            raise RuntimeError("Blender не перевёл модель: " + tail) from None
        return res + [{"ok": False, "error": "Blender закрылся раньше"}] * (len(jobs) - len(res))
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
