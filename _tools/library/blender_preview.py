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


# ---------------------------------------------------------------- модель с четырёх сторон (для помощника)
VIEWS = (("спереди", 0, 0.15), ("справа", 90, 0.15), ("сзади", 180, 0.15), ("сверху", 35, 1.05))

VIEWS_SCRIPT = r"""
import bpy, math, mathutils
FILES, OUT, VIEWS, SIDE = {files!r}, {out!r}, {views!r}, {side!r}
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
for m in bpy.data.materials:
    if m.use_nodes:
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf and not bsdf.inputs["Base Color"].is_linked:
            bsdf.inputs["Base Color"].default_value = (0.55, 0.55, 0.58, 1)
world = bpy.data.worlds.new("w"); world.color = (0.5, 0.5, 0.52); bpy.context.scene.world = world
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
bpy.context.scene.collection.objects.link(cam)
cam.data.lens = 50
bpy.context.scene.camera = cam
key = bpy.data.objects.new("key", bpy.data.lights.new("key", "SUN"))
key.data.energy = 3.0
bpy.context.scene.collection.objects.link(key)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x = sc.render.resolution_y = SIDE
sc.render.film_transparent = True
d = size * 1.55
for i, (name, ang, up) in enumerate(VIEWS):
    a = math.radians(ang)
    cam.location = center + mathutils.Vector((math.sin(a) * d, -math.cos(a) * d, up * d))
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    key.rotation_euler = (center - (cam.location + mathutils.Vector((d * 0.4, 0, d * 0.6)))).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = OUT + "_%d.png" % i
    bpy.ops.render.render(write_still=True)
"""


def views(fbx_files, cache, cfg=None, side=384, timeout=600):
    """Модель с четырёх сторон листом 2x2 с подписями (спереди, справа, сзади, сверху) -> PIL.Image или None.
    cache - путь файла: лист пересчитывается, только если FBX новее."""
    from PIL import ImageDraw

    newest = max((os.path.getmtime(f) for f in fbx_files if os.path.exists(f)), default=0)
    if os.path.exists(cache) and os.path.getmtime(cache) >= newest:
        with Image.open(cache) as im:
            return im.convert("RGB")
    exe = B.find_blender(cfg)
    if not exe:
        return None
    tmp = tempfile.mkdtemp(prefix="bl_views_")
    base = os.path.join(tmp, "v")
    script = os.path.join(tmp, "views.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(VIEWS_SCRIPT.format(files=[os.path.realpath(f) for f in fbx_files], out=base, views=VIEWS, side=side))
    subprocess.run(
        [exe, "-b", "--factory-startup", "--python", script],
        capture_output=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    cap, pad = 26, 8
    sheet = Image.new("RGB", (2 * side + 3 * pad, 2 * (side + cap) + 3 * pad), (21, 21, 28))
    d = ImageDraw.Draw(sheet)
    from imaging.sprites import _font

    font = _font(15)  # с кириллицей
    got = 0
    for i, (name, _a, _u) in enumerate(VIEWS):
        png = f"{base}_{i}.png"
        x, y = pad + (i % 2) * (side + pad), pad + (i // 2) * (side + cap + pad)
        tile = Image.new("RGBA", (side, side), (44, 44, 56, 255))
        if os.path.exists(png):
            with Image.open(png) as im:
                tile.alpha_composite(im.convert("RGBA").resize((side, side)))
            got += 1
        sheet.paste(tile.convert("RGB"), (x, y))
        d.text((x + side / 2, y + side + 5), name, fill=(220, 218, 232), font=font, anchor="ma")
    if not got:
        return None
    try:
        sheet.save(cache, quality=88)
    except OSError:
        pass
    return sheet


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
