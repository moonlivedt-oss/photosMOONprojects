"""Сцена в Blender из ассетов Unreal: модели (FBX), PBR-текстуры, небо HDRI, комната с полом и стенами.
Пишется скрипт build_scene.py и запускается Blender: он собирает сцену и сохраняет .blend рядом - дальше
её можно дорабатывать руками или через Blender MCP. Без Qt.

- модели подгоняются по размеру (у Poly Haven - настоящий, у простых - по разделу, как в 3D-комнате окна);
- нормаль DirectX (как ждёт Unreal) переворачивается в OpenGL для Blender, ARM - на AO/шероховатость/металл;
- комната - та же расстановка, что в окне (library.room_layout), сантиметры -> метры."""

import glob
import json
import os
import subprocess

from library import room_layout

STEAM = r"D:\SteamLibrary\steamapps\common\Blender\blender.exe"
CANDIDATES = (
    STEAM,
    r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
    r"C:\Program Files\Steam\steamapps\common\Blender\blender.exe",
)


def find_blender(cfg=None):
    """Путь к blender.exe: из настроек, известных мест Steam, Program Files или PATH. -> путь или None."""
    if cfg and cfg.get("blender") and os.path.exists(cfg["blender"]):
        return cfg["blender"]
    for p in CANDIDATES:
        if os.path.exists(p):
            return p
    for p in sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True):
        return p
    from shutil import which

    return which("blender")


def _maps(a):
    """Карты текстуры по именам файлов (как у 3D-просмотра окна)."""
    files = [os.path.join(a["dir"], f) for f in sorted(os.listdir(a["dir"])) if f.lower().endswith((".jpg", ".png"))]

    def find(*keys):
        for k in keys:
            for f in files:
                if k in os.path.basename(f).lower() and "preview" not in os.path.basename(f).lower():
                    return f
        return ""

    return {
        "color": find("_diff_", "_color", "albedo", "basecolor"),
        "normal_dx": find("_nor_dx_", "normaldx"),
        "normal_gl": find("_nor_gl_", "normalgl"),
        "arm": find("_arm_"),
        "rough": find("_rough", "roughness"),
        "metal": find("metalness", "_metal"),
    }


def _main_file(a, exts):
    for m in a.get("main", []):
        p = os.path.join(a["dir"], *m.split("/"))
        if p.lower().endswith(exts) and os.path.exists(p):
            return p
    return ""


HANG_WORDS = ("chandelier", "pendant", "ceiling", "люстра")


def hangs(a):
    """Люстру и потолочный свет - под потолок, а не на пол."""
    name = a.get("name", "").lower()
    return any(w in name for w in HANG_WORDS)


def jobs(assets, room=False, floor=None, wall=None, hdri=None):
    """Что строить: {models: [{name, fbx, x, y, size}], textures: [...], floor, wall, hdri, room: {w, d}}.
    room=True - расставить модели в комнате (метры); иначе - рядом в линию."""
    models = [a for a in assets if a.get("kind") == "model" and _main_file(a, (".fbx",))]
    texs = [a for a in assets if a.get("kind") == "tex"]
    hdri = hdri or next((a for a in assets if a.get("kind") == "hdri"), None)
    out = {"models": [], "textures": [], "room": None, "floor": None, "wall": None, "hdri": ""}
    if room and models:
        items, w, d = room_layout.layout(models)
        out["room"] = {"w": w / 100, "d": d / 100}
        for it in items:
            a = it["a"]
            out["models"].append(
                {
                    "name": a.get("name", ""),
                    "fbx": _main_file(a, (".fbx",)),
                    "x": it["x"] / 100,
                    "y": -it["z"] / 100,
                    "size": it["size"] / 100,
                    "hang": hangs(a),
                }
            )
        floor = floor or next((t for t in texs if "пол" in t.get("theme", "").lower()), None)
        wall = wall or next((t for t in texs if "стен" in t.get("theme", "").lower() and t is not floor), None)
        out["floor"] = {"name": floor["name"], **_maps(floor)} if floor else None
        out["wall"] = {"name": wall["name"], **_maps(wall)} if wall else None
        texs = [t for t in texs if t is not floor and t is not wall]
    else:
        x = 0.0
        for a in models:
            size = room_layout.size_cm(a) / 100
            out["models"].append(
                {"name": a.get("name", ""), "fbx": _main_file(a, (".fbx",)), "x": x + size / 2, "y": 0.0, "size": size}
            )
            x += size + 0.4
    for i, t in enumerate(texs):  # текстуры - шарами в ряд перед моделями
        out["textures"].append({"name": t.get("name", ""), "x": i * 1.2, "y": -2.5, **_maps(t)})
    if hdri:
        out["hdri"] = _main_file(hdri, (".hdr", ".exr"))
    return out


SCRIPT = r'''# Сцена из библиотеки картинок. Собрана автоматически; запуск: blender --python build_scene.py
import json
import math
import os

import bpy
from mathutils import Vector

J = json.loads({jobs})
OUT = {out}
CEIL = 2.7  # высота комнаты, м
TILE = 2.0  # одна плитка текстуры - примерно 2 м поверхности (как у Poly Haven)


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def import_fbx(path):
    before = set(bpy.data.objects)
    try:
        bpy.ops.wm.fbx_import(filepath=path)
    except Exception:
        bpy.ops.import_scene.fbx(filepath=path)
    return [o for o in bpy.data.objects if o not in before]


def bounds(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == "MESH" for c in o.bound_box]
    if not pts:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def image(path, data=False):
    img = bpy.data.images.load(path, check_existing=True)
    if data:
        img.colorspace_settings.name = "Non-Color"
    return img


def pbr(name, m, tiling=(1.0, 1.0)):
    """Материал из карт: цвет, нормаль (DirectX -> OpenGL), ARM или шероховатость/металл.
    tiling - сколько раз текстура ложится по ширине и высоте (по метрам поверхности, без растяжения)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (tiling[0], tiling[1], 1.0)
    nt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])

    def tex(path, data=False):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = image(path, data)
        nt.links.new(mapping.outputs["Vector"], n.inputs["Vector"])
        return n

    if m.get("color"):
        nt.links.new(tex(m["color"]).outputs["Color"], bsdf.inputs["Base Color"])
    nrm = m.get("normal_gl") or m.get("normal_dx")
    if nrm:
        t = tex(nrm, True)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        if not m.get("normal_gl"):  # DirectX: зелёный канал наоборот
            sep = nt.nodes.new("ShaderNodeSeparateColor")
            inv = nt.nodes.new("ShaderNodeMath")
            inv.operation = "SUBTRACT"
            inv.inputs[0].default_value = 1.0
            comb = nt.nodes.new("ShaderNodeCombineColor")
            nt.links.new(t.outputs["Color"], sep.inputs["Color"])
            nt.links.new(sep.outputs["Red"], comb.inputs["Red"])
            nt.links.new(sep.outputs["Green"], inv.inputs[1])
            nt.links.new(inv.outputs["Value"], comb.inputs["Green"])
            nt.links.new(sep.outputs["Blue"], comb.inputs["Blue"])
            nt.links.new(comb.outputs["Color"], nm.inputs["Color"])
        else:
            nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if m.get("arm"):  # R - AO (в Principled нет), G - шероховатость, B - металл
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(tex(m["arm"], True).outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    else:
        if m.get("rough"):
            nt.links.new(tex(m["rough"], True).outputs["Color"], bsdf.inputs["Roughness"])
        if m.get("metal"):
            nt.links.new(tex(m["metal"], True).outputs["Color"], bsdf.inputs["Metallic"])
    return mat


def plane(name, size_x, size_y, loc, rot=(0, 0, 0), mat=None):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size_x, size_y, 1)
    bpy.ops.object.transform_apply(scale=True)
    if mat:
        o.data.materials.append(mat)
    return o


clear()
col = bpy.data.collections.new("Библиотека")
bpy.context.scene.collection.children.link(col)
for m in J["models"]:
    objs = import_fbx(m["fbx"])
    if not objs:
        continue
    empty = bpy.data.objects.new(m["name"], None)
    col.objects.link(empty)
    for o in objs:
        for c in o.users_collection:
            c.objects.unlink(o)
        col.objects.link(o)
        if o.parent is None:
            o.parent = empty
    bpy.context.view_layer.update()
    lo, hi = bounds(objs)
    k = m["size"] / max(1e-6, max(hi - lo))  # подгонка: самая большая сторона - нужный размер
    empty.scale = (k, k, k)
    bpy.context.view_layer.update()
    lo, hi = bounds(objs)
    z = (CEIL - 0.05 - hi.z) if m.get("hang") and J["room"] else -lo.z  # люстра - под потолком
    empty.location += Vector((m["x"] - (lo.x + hi.x) / 2, m["y"] - (lo.y + hi.y) / 2, z))
for t in J["textures"]:
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.45, location=(t["x"], t["y"], 0.45), segments=64, ring_count=32)
    s = bpy.context.active_object
    s.name = t["name"]
    bpy.ops.object.shade_smooth()
    s.data.materials.append(pbr(t["name"], t))
room = J["room"]
if room:
    w, d, h = room["w"], room["d"], CEIL
    fl, wl = J["floor"], J["wall"]
    plane("Пол", w, d, (0, 0, 0), mat=pbr("Пол - " + fl["name"], fl, (w / TILE, d / TILE)) if fl else None)
    back = pbr("Стена - " + wl["name"], wl, (w / TILE, h / TILE)) if wl else None
    side = pbr("Стена бок - " + wl["name"], wl, (d / TILE, h / TILE)) if wl else None
    plane("Стена задняя", w, h, (0, d / 2, h / 2), (math.pi / 2, 0, 0), back)
    plane("Стена левая", d, h, (-w / 2, 0, h / 2), (math.pi / 2, 0, math.pi / 2), side)
    plane("Стена правая", d, h, (w / 2, 0, h / 2), (math.pi / 2, 0, -math.pi / 2), side)
if J["hdri"]:
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    env = world.node_tree.nodes.new("ShaderNodeTexEnvironment")
    env.image = image(J["hdri"])
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    world.node_tree.links.new(env.outputs["Color"], bg.inputs["Color"])
else:
    bpy.ops.object.light_add(type="SUN", location=(2, -2, 5))
    bpy.context.active_object.data.energy = 3
if room:  # спереди стены нет - камера там, чуть выше роста, вся комната в кадре (объектив 35 мм, ~54°)
    # 24 мм видят ~74° по ширине: от передней кромки до камеры - 0.62 ширины комнаты, чтобы стены влезли
    dist = room["d"] / 2 + room["w"] * 0.62
    cam_loc, look = (0, -dist, 1.7), (0, 0, 0.9)
    bpy.context.scene.render.film_transparent = True  # HDRI - свет, а не чужая комната на фоне
else:
    span = 2 + sum(m["size"] + 0.4 for m in J["models"])
    cx = span / 2 - 1
    cam_loc, look = (cx, -span * 0.9 - 2, span * 0.35 + 1), (cx, 0, 0.5)
bpy.ops.object.camera_add(location=cam_loc)
cam = bpy.context.active_object
cam.data.lens = 24 if room else 35
target = bpy.data.objects.new("Цель камеры", None)
col.objects.link(target)
target.location = look
c = cam.constraints.new("TRACK_TO")
c.target = target
bpy.context.scene.camera = cam
if OUT:
    bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("Сцена из библиотеки: моделей", len(J["models"]), "текстур", len(J["textures"]), "->", OUT)
'''


def write_script(assets, folder, title="Сцена", room=False, floor=None, wall=None, hdri=None):
    """build_scene.py и путь будущего .blend в folder. -> (скрипт, .blend)."""
    os.makedirs(folder, exist_ok=True)
    from library.unreal_import import asset_name

    blend = os.path.join(folder, asset_name(title) + ".blend")
    text = SCRIPT.replace("{jobs}", repr(json.dumps(jobs(assets, room, floor, wall, hdri), ensure_ascii=False)))
    text = text.replace("{out}", repr(blend.replace("\\", "/")))
    script = os.path.join(folder, "build_scene.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(text)
    return script, blend


def run(blender, script, background=False, timeout=600):
    """Запустить Blender со скриптом. background=True - без окна, дождаться (проверка, командная строка)."""
    args = [blender] + (["-b", "--factory-startup"] if background else []) + ["--python", script]
    if background:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    return subprocess.Popen(args)
