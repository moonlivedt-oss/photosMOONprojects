"""Просмотровая копия MetaHuman (_view.glb) с текстурами: кожа лица и тела, волосы-карточки с прозрачностью,
глаза, зубы, одежда. Текстуры - выгрузка из Unreal в _Unreal/_export/MetaHumans/<Имя>|Common (PNG, папки как
в Content; скрипт _Unreal/_export/export_textures.py). Цвет волос и одежды у MetaHuman - параметры материала,
не текстура: берётся с портрета Bridge (blender_preview.portrait_colors). Оригинальные FBX не меняются. Без Qt."""

import json
import os
import re
import subprocess
import tempfile

import numpy as np
from PIL import Image

from library import blender_preview as BP
from library import blender_scene as B
from library import unreal as U

EXPORT = os.path.join(U.ROOT, "_export", "MetaHumans")
SIDE = 2048  # карты в копии - не больше 2K: 8K кожи тела не нужны для просмотра
KIND = re.compile(r"^([fm]_(?:srt|med|tal)_(?:unw|nrw|ovw))_(top|btm|shs|body)", re.I)
GARMENT = re.compile(r"_(?:top|btm|shs)_([a-z]+)", re.I)


# ---------------------------------------------------------------- части модели
def view_parts(files):
    """Части для копии: одежда под тело персонажа (у многих в выгрузку попал наряд шаблона - карго и
    кроссовки на другое тело) и без повторов (одна и та же вещь *_nrm и *_nrm_Cinematic)."""
    names = [os.path.basename(f) for f in files]
    body = next((KIND.match(n).group(1).lower() for n in names if KIND.match(n) and "_body" in n.lower()), "")
    own = {KIND.match(n).group(2).lower() for n in names if KIND.match(n) and KIND.match(n).group(1).lower() == body}
    out, seen = [], set()
    for f, n in zip(files, names):
        m = KIND.match(n)
        if m and body and m.group(1).lower() != body and m.group(2).lower() in own:
            continue  # такая же вещь есть под своё тело
        key = re.sub(r"(_Cinematic)?\.fbx$", "", n, flags=re.I).lower()
        if m:
            key = key[len(m.group(1)) :]  # вещь без типа тела: карго на m_tal и на m_med - одна
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


# ---------------------------------------------------------------- текстуры
def index(root=EXPORT):
    out = {}
    for d, _sub, fs in os.walk(root):
        for f in fs:
            if f.lower().endswith((".png", ".tga")):
                out.setdefault(os.path.splitext(f)[0].lower(), []).append(os.path.join(d, f))
    return out


def pick(idx, stem, own="", strict=False):
    """Файл по имени: сначала из папки персонажа; strict - только оттуда (лицо и тело у каждого свои)."""
    lst = idx.get(stem.lower(), [])
    mine = [p for p in lst if own and (os.sep + own.lower() + os.sep) in p.lower()]
    if mine or strict:
        return mine[0] if mine else ""
    return lst[0] if lst else ""


def _srgb(c):
    return tuple(int(round(255 * (v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055))) for v in c)


def _load(path, mode="RGB"):
    im = Image.open(path)
    im.draft(mode, (SIDE, SIDE))
    im = im.convert(mode)
    if max(im.size) > SIDE:
        im = im.resize((SIDE, SIDE), Image.LANCZOS)
    return im


def prep_color(path, out):
    _load(path).save(out, quality=92)
    return out


def prep_gray(path, out):
    """Одноканальная карта MetaHuman (шероховатость) - в красном канале; серым её читать нельзя:
    G и B пустые, и вышла бы шероховатость ~0.25 - кожа как мокрая."""
    _load(path).getchannel("R").save(out, quality=92)
    return out


def prep_normal(path, out):
    """Нормаль из Unreal - DirectX (зелёный вниз), glTF ждёт OpenGL: зелёный перевернуть."""
    r, g, b = _load(path).split()
    Image.merge("RGB", (r, g.point(lambda v: 255 - v), b)).save(out, quality=95)
    return out


def prep_cards(atlas, color, out):
    """Атлас карточек волос: прозрачность - красный канал (маска прядей), цвет - волос с портрета,
    вдоль пряди чуть темнее к корню (зелёный канал - градиент) - иначе волосы плоские."""
    im = _load(atlas, "RGB")
    a = np.asarray(im).astype(np.float32) / 255
    rgb = np.asarray(_srgb(color), np.float32)[None, None, :] / 255
    shade = 0.6 + 0.4 * a[..., 1:2]
    px = np.clip(rgb * shade, 0, 1)
    rgba = np.concatenate([px, a[..., 0:1]], axis=2)
    Image.fromarray((rgba * 255).astype(np.uint8), "RGBA").save(out)
    return out


def prep_cloth(ao, color, out):
    """Ткань: цвет с портрета, затенённый картой AO (складки, швы)."""
    rgb = np.asarray(_srgb(color), np.float32)
    k = (np.asarray(_load(ao, "L")).astype(np.float32) / 255)[..., None] if ao else np.ones((8, 8, 1), np.float32)
    Image.fromarray(np.clip(rgb * (0.35 + 0.65 * k), 0, 255).astype(np.uint8), "RGB").save(out, quality=92)
    return out


def prep_eye(sclera, iris, out, color=(0.16, 0.08, 0.035)):
    """Глаз: склера из текстуры MetaHuman, поверх - радужка в центре развёртки (радиус 0.15, как у MetaHuman)
    цветом color с рисунком из маски радужки, зрачок и тёмное кольцо по краю."""
    side = 1024
    base = _load(sclera).resize((side, side)) if sclera else Image.new("RGB", (side, side), (235, 228, 222))
    px = np.asarray(base).astype(np.float32)
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    r = np.hypot(xx - side / 2, yy - side / 2) / side  # в долях развёртки
    ir = 0.15
    detail = np.full((side, side), 0.5, np.float32)
    if iris:  # рисунок радужки: её текстура целиком ложится на круг радужки
        k = int(2 * ir * side / 0.86)
        t = np.asarray(_load(iris, "L").resize((k, k))).astype(np.float32) / 255
        o = (side - k) // 2
        detail[o : o + k, o : o + k] = t
    col = np.asarray(_srgb(color), np.float32)
    iris_px = col[None, None, :] * (0.55 + 0.9 * detail[..., None])
    edge = np.clip((r - ir * 0.82) / (ir * 0.18), 0, 1)[..., None]  # тёмное кольцо
    iris_px = iris_px * (1 - 0.6 * edge)
    pupil = np.clip((r - ir * 0.36) / 0.006, 0, 1)[..., None]
    iris_px = iris_px * pupil + np.array([6, 5, 5], np.float32) * (1 - pupil)
    m = np.clip((ir - r) / 0.004, 0, 1)[..., None]
    px = px * (1 - m) + iris_px * m
    Image.fromarray(np.clip(px, 0, 255).astype(np.uint8), "RGB").save(out, quality=92)
    return out


def texture_rules(files, own, colors, tmp, idx=None):
    """Правила материалов для Blender: [(где: "obj"|"mat", [слова], {base, normal, rough, alpha, hide,
    color, rough_value})] - первое подходящее. -> (правила, сколько текстур нашлось)."""
    idx = index() if idx is None else idx
    col = {words[0]: c for words, c in colors}
    skin, hair = col.get("face", (0.5, 0.3, 0.22)), col.get("hair", (0.03, 0.025, 0.02))
    top = col.get("top", (0.2, 0.2, 0.22))
    found = 0

    def out(name, ext="jpg"):
        return os.path.join(tmp, f"{name}.{ext}")

    def make(fn, src, name, *args, ext="jpg"):
        nonlocal found
        if not src:
            return ""
        found += 1
        try:
            return fn(src, *args, out(name, ext)) if args else fn(src, out(name, ext))
        except Exception as e:
            print("mh_view:", name, e)
            return ""

    rules = []
    # волосы, брови, борода - карточки: атлас по имени части (Hair_S_AfroFade_CardsMesh -> ..._CardsAtlas_Attribute)
    for f in files:
        n = os.path.splitext(os.path.basename(f))[0]
        if "_card" in n.lower():
            prefix = re.split(r"_Card", n, flags=re.I)[0]
            atlas = pick(idx, prefix + "_CardsAtlas_Attribute", own)
            spec = {"rough_value": 0.75, "color": hair}
            if atlas:
                spec.update(base=make(prep_cards, atlas, prefix, hair, ext="png"), alpha=True)
            rules.append(("obj", [prefix.lower()], spec))
    # одежда: нормаль и AO из Common/Materials/<Вещь>, цвет - с портрета
    for f in files:
        n = os.path.splitext(os.path.basename(f))[0]
        g = GARMENT.search(n)
        if not g or "_body" in n.lower():
            continue
        thing = g.group(1).lower()
        lst = [p for v in idx.values() for p in v if (os.sep + thing + os.sep) in p.lower()]
        nrm = next((p for p in lst if os.path.splitext(p)[0].lower().endswith("_n")), "")
        ao = next((p for p in lst if os.path.splitext(p)[0].lower().endswith("_ao")), "")
        c = top if "_top_" in n.lower() else (0.05, 0.06, 0.08) if "_btm_" in n.lower() else (0.04, 0.04, 0.05)
        spec = {"rough_value": 0.85, "base": prep_cloth(ao, c, out(n + "_c"))}
        found += bool(ao)
        if nrm:
            spec["normal"] = make(prep_normal, nrm, n + "_n")
        rules.append(("obj", [n.lower()], spec))
    # лицо и тело - карты самого персонажа
    face = {
        "base": make(prep_color, pick(idx, "FaceColor_MAIN", own, True), "face_c"),
        "normal": make(prep_normal, pick(idx, "FaceNormal_MAIN", own, True), "face_n"),
        "rough": make(prep_gray, pick(idx, "FaceRoughness_MAIN", own, True), "face_r"),
        "color": skin,
        "rough_value": 0.5,
    }
    sex = "female" if any(os.path.basename(f).lower().startswith("f_") for f in files) else "male"
    body_n = next((p for k, v in idx.items() if k == f"{sex}_body_normal_map" for p in v), "")
    body = {
        "base": make(prep_color, pick(idx, "BodyBaseColor", own, True), "body_c"),
        "normal": make(prep_normal, body_n, "body_n"),
        "color": skin,
        "rough_value": 0.5,
    }
    # ресницы - полоски с маской покрытия; без маски это чёрные пластины - тогда лучше без ресниц
    cover = next((v[0] for k, v in sorted(idx.items()) if k.startswith("eyelashes") and k.endswith("coverage")), "")
    dark = tuple(x * 0.4 for x in hair)
    lashes = (
        {"base": make(prep_cards, cover, "lashes", dark, ext="png"), "alpha": True, "rough_value": 0.7}
        if cover
        else {"hide": True}
    )
    teeth = pick(idx, "T_Teeth_BaseColor_Baked", own) or pick(idx, "teeth_color_map_001", own)
    eye = prep_eye(pick(idx, "T_Sclera_D", own), pick(idx, "T_Iris_A_M", own), out("eye"))
    rules += [
        ("mat", ["headsynthesized"], face),
        ("mat", ["bodysynthesized"], body),
        ("mat", ["teeth"], {"base": make(prep_color, teeth, "teeth"), "color": (0.8, 0.75, 0.68), "rough_value": 0.35}),
        ("mat", ["eyerefractive"], {"base": eye, "rough_value": 0.06}),
        # плёнки поверх глаза (слёзы, тень век) и хрящ уголка - свои шейдеры, без них белые оболочки
        ("mat", ["lacrimal", "eyeocclusion", "cartilage", "eyeshell"], {"hide": True}),
        ("mat", ["eyelash"], lashes),
    ]
    return rules, found


# ---------------------------------------------------------------- Blender
SCRIPT = r"""
import bpy, bmesh, json, re
cfg = json.load(open({spec!r}, encoding="utf-8"))
bpy.ops.wm.read_factory_settings(use_empty=True)
for f in cfg["files"]:
    try:
        bpy.ops.import_scene.fbx(filepath=f, use_anim=False)
    except Exception as e:
        print("Библиотека: не открылся", f, e)


def key(n):
    return re.sub(r"\.\d+$", "", n or "").lower()


def rule(obj, mat):
    for where, words, spec in cfg["rules"]:
        name = key(obj.name) if where == "obj" else key(mat.name if mat else "")
        if any(w in name for w in words):
            return spec
    return None


cache = {{}}


def material(name, spec, uv):
    k = (name, uv)
    if k in cache:
        return cache[k]
    m = bpy.data.materials.new(name + "_view")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = spec.get("rough_value", 0.5)
    bsdf.inputs["Base Color"].default_value = (*spec.get("color", (0.6, 0.6, 0.6)), 1)

    def image(path, data=False):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(path)
        if data:
            n.image.colorspace_settings.name = "Non-Color"
        u = nt.nodes.new("ShaderNodeUVMap")
        u.uv_map = uv
        nt.links.new(u.outputs["UV"], n.inputs["Vector"])
        return n

    if spec.get("base"):
        b = image(spec["base"])
        nt.links.new(b.outputs["Color"], bsdf.inputs["Base Color"])
        if spec.get("alpha"):
            nt.links.new(b.outputs["Alpha"], bsdf.inputs["Alpha"])
            try:
                m.surface_render_method = "BLENDED"
            except Exception:
                m.blend_method = "BLEND"
    if spec.get("normal"):
        n = image(spec["normal"], True)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.uv_map = uv
        nt.links.new(n.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if spec.get("rough"):
        r = image(spec["rough"], True)
        nt.links.new(r.outputs["Color"], bsdf.inputs["Roughness"])
    cache[k] = m
    return m


for o in list(bpy.context.scene.objects):
    if o.type != "MESH":
        continue
    if o.data.shape_keys:
        o.shape_key_clear()  # морфы лица (сотни) - только для мимики; 3D окна на них падает
    while len(o.data.uv_layers) > 1:  # первая развёртка - рабочая (у карточек волос она и есть атлас)
        o.data.uv_layers.remove(o.data.uv_layers[-1])
    uv = o.data.uv_layers[0].name if o.data.uv_layers else ""
    hide = []
    for i, slot in enumerate(o.material_slots):
        spec = rule(o, slot.material)
        if spec is None:
            continue
        if spec.get("hide"):
            hide.append(i)
            continue
        slot.material = material(key(o.name) + "|" + key(slot.material.name if slot.material else ""), spec, uv)
    if hide:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index in hide], context="FACES")
        bm.to_mesh(o.data)
        bm.free()
bpy.ops.export_scene.gltf(
    filepath=cfg["out"], export_format="GLB", export_animations=False, export_morph=False, export_skins=True,
    export_apply=False, export_yup=True, export_image_format="AUTO",
)
"""


def has_textures(name, root=EXPORT):
    """Выгружены ли карты лица этого MetaHuman (папка <root>/<имя>/...)."""
    d = os.path.join(root, name)
    return os.path.isdir(d) and any("facecolor_main" in f.lower() for _d, _s, fs in os.walk(d) for f in fs)


def make_view(asset_dir, cfg=None, timeout=1200, idx=None, meta_main=None):
    """Пересобрать _view.glb MetaHuman с текстурами из выгрузки. meta_main - список FBX, если asset.json
    ещё не записан. -> (True/False, сколько текстур)."""
    exe = B.find_blender(cfg)
    if not exe:
        return False, 0
    if meta_main is None:
        with open(os.path.join(asset_dir, "asset.json"), encoding="utf-8") as fh:
            meta_main = json.load(fh).get("main", [])
    files = view_parts([os.path.join(asset_dir, m) for m in meta_main if m.lower().endswith(".fbx")])
    own = os.path.basename(asset_dir.rstrip("\\/"))
    colors = BP.portrait_colors(os.path.join(asset_dir, "preview.webp"))
    tmp = tempfile.mkdtemp(prefix="mh_view_")
    rules, found = texture_rules(files, own, colors, tmp, idx)
    out = os.path.join(asset_dir, "_view.glb")
    part = out + ".part.glb"
    spec = os.path.join(tmp, "spec.json")
    with open(spec, "w", encoding="utf-8") as fh:
        json.dump({"files": [os.path.realpath(f) for f in files], "rules": rules, "out": os.path.realpath(part)}, fh)
    script = os.path.join(tmp, "view.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(SCRIPT.format(spec=spec))
    subprocess.run(
        [exe, "-b", "--factory-startup", "--python", script],
        capture_output=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ok = os.path.exists(part) and os.path.getsize(part) > 1000
    if ok:
        os.replace(part, out)
    return ok, found
