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
