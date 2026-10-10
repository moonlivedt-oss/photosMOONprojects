"""Превью модели рендером Blender - для того, что 3D окна (Qt Quick 3D) не открывает: лицо MetaHuman с
сотнями морфов роняет его. Blender в фоне импортирует FBX, ставит камеру по габаритам, рендерит 512x512 на
прозрачном фоне -> preview.webp. Без Qt."""

import os
import subprocess
import tempfile

from PIL import Image

from library import blender_scene as B

SCRIPT = r"""
import bpy, math, mathutils
FILES, OUT = {files!r}, {out!r}
bpy.ops.wm.read_factory_settings(use_empty=True)
for f in FILES:
    try:
        bpy.ops.import_scene.fbx(filepath=f, use_anim=False)
    except Exception as e:
        print("Библиотека: не открылся", f, e)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
lo = mathutils.Vector((1e9, 1e9, 1e9)); hi = -lo
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        lo = mathutils.Vector(map(min, lo, w)); hi = mathutils.Vector(map(max, hi, w))
center, size = (lo + hi) / 2, max((hi - lo).length, 1e-3)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
bpy.context.scene.collection.objects.link(cam)
cam.data.lens = 50
d = size * 1.6
cam.location = center + mathutils.Vector((d * 0.35, -d, d * 0.15))
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam
for m in bpy.data.materials:  # без текстур FBX приходит белым - нейтральный серый читается лучше
    if m.use_nodes:
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf and not bsdf.inputs["Base Color"].is_linked:
            bsdf.inputs["Base Color"].default_value = (0.55, 0.55, 0.58, 1)
for loc, en in (((3, -3, 4), 60), ((-4, -2, 2), 25)):
    l = bpy.data.objects.new("l", bpy.data.lights.new("l", "AREA"))
    l.data.energy, l.data.size = en * size * size, size
    l.location = center + mathutils.Vector(loc) * size * 0.5
    l.rotation_euler = (center - l.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(l)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x = sc.render.resolution_y = 512
sc.render.film_transparent = True
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
"""


def render(fbx_files, dst, cfg=None, timeout=600):
    """FBX -> dst/preview.webp рендером Blender. -> True, если вышло."""
    exe = B.find_blender(cfg)
    if not exe:
        return False
    tmp = tempfile.mkdtemp(prefix="bl_prev_")
    png = os.path.join(tmp, "preview.png")
    script = os.path.join(tmp, "preview.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(SCRIPT.format(files=[os.path.realpath(f) for f in fbx_files], out=png))
    subprocess.run(
        [exe, "-b", "--factory-startup", "--python", script],
        capture_output=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if not os.path.exists(png):
        return False
    with Image.open(png) as im:
        im = im.convert("RGBA")
        box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
        if not box:
            return False
        im = im.crop(box)
        k = 512 * 0.86 / max(im.size)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        out = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        out.alpha_composite(im, ((512 - im.width) // 2, (512 - im.height) // 2))
        out.save(os.path.join(dst, "preview.webp"), quality=90)
    return True


VIEW_SCRIPT = r"""
import bpy
FILES, OUT = {files!r}, {out!r}
bpy.ops.wm.read_factory_settings(use_empty=True)
for f in FILES:
    try:
        bpy.ops.import_scene.fbx(filepath=f, use_anim=False)
    except Exception as e:
        print("Библиотека: не открылся", f, e)
COLORS = {colors!r}  # части по словам в имени -> цвет (линейный RGB)


def tint(o):
    low = o.name.lower()
    for words, col in COLORS:
        if any(w in low for w in words):
            mat = bpy.data.materials.new(o.name + "_lib")
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (*col, 1)
            bsdf.inputs["Roughness"].default_value = 0.6
            o.data.materials.clear()
            o.data.materials.append(mat)
            return


for o in list(bpy.context.scene.objects):
    if o.type == "MESH" and o.data.shape_keys:
        o.shape_key_clear()  # морфы лица (сотни) - только для мимики; 3D окна на них падает
    if o.type == "MESH" and COLORS:
        tint(o)
bpy.ops.export_scene.gltf(
    filepath=OUT, export_format="GLB", export_animations=False, export_morph=False, export_skins=True,
    export_apply=False, export_yup=True,
)
"""


def _lin(c):
    c = c / 255
    return round(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4, 4)


def portrait_colors(png):
    """Цвета частей MetaHuman по портрету от Bridge (лицо по центру, волосы сверху, одежда внизу).
    -> [(слова в имени части, линейный RGB)] для make_view_model."""
    try:
        with Image.open(png) as im:
            im = im.convert("RGB").resize((256, 256))
    except OSError:
        return []

    def at(x, y, r=6):
        box = im.crop((int(x * 256) - r, int(y * 256) - r, int(x * 256) + r, int(y * 256) + r))
        px = list(box.getdata())
        return tuple(_lin(sum(p[i] for p in px) / len(px)) for i in range(3))

    def avg(*cs):
        return tuple(round(sum(c[i] for c in cs) / len(cs), 4) for i in range(3))

    def grey(c):  # фон портрета - ровный серый
        return max(c) - min(c) < 0.01 and 0.08 < c[0] < 0.2

    skin = at(0.5, 0.5)
    hair = next((c for c in (at(0.5, 0.2), at(0.42, 0.24), at(0.58, 0.24)) if not grey(c)), (0.03, 0.025, 0.02))
    top = avg(at(0.15, 0.97), at(0.85, 0.97))  # плечи: по центру внизу бывает шея
    dark = (0.04, 0.04, 0.05)
    return [
        (("face", "body", "head", "teeth"), skin),
        (("hair", "eyebrow", "eyelash", "beard", "mustache", "fuzz"), hair),
        (("top", "hoodie", "shirt", "jacket", "tshirt", "dress", "sweater"), top),
        (("btm", "pants", "jeans", "shorts", "skirt", "trousers"), (0.05, 0.06, 0.08)),
        (("shs", "shoe", "sneaker", "boot"), dark),
    ]


def make_view_model(fbx_files, out_glb, cfg=None, timeout=900, colors=()):
    """Модель для 3D окна: все части (тело, голова, волосы, одежда) одним GLB без морфов - их сотни у лица
    MetaHuman, и Qt Quick 3D на них падает. colors - цвета частей (portrait_colors): текстур у выгрузки нет.
    Оригинальные FBX не меняются. -> True, если вышло."""
    exe = B.find_blender(cfg)
    if not exe:
        return False
    tmp = tempfile.mkdtemp(prefix="bl_view_")
    script = os.path.join(tmp, "view.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(
            VIEW_SCRIPT.format(
                files=[os.path.realpath(f) for f in fbx_files], out=os.path.realpath(out_glb), colors=list(colors)
            )
        )
    subprocess.run(
        [exe, "-b", "--factory-startup", "--python", script],
        capture_output=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return os.path.exists(out_glb) and os.path.getsize(out_glb) > 1000
