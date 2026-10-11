"""Бюджет сцены: сколько треугольников и памяти видеокарты займёт подборка ассетов в Unreal, что из неё
готово к Nanite, а что лучше упростить. Упрощение - модификатором Decimate в Blender: рядом с оригиналом
появляется <имя>_<N>k.fbx (оригинал не трогается), список - в simplified.json папки ассета. Без Qt.

Оценка памяти текстур - примерная: как Unreal сжимает по умолчанию (цвет без прозрачности - BC1, 0.5 байта на
пиксель; нормаль, цвет с прозрачностью и маски - BC5/BC7/DXT5, 1 байт; HDRI - BC6H, 1 байт) плюс мип-уровни (+1/3)."""

import json
import os
import time

from PIL import Image

from library import blender_scene

TEX_EXT = (".png", ".jpg", ".jpeg", ".tga", ".exr", ".hdr", ".webp")
SKIP = ("preview", "_views", "_view.", "thumb")  # картинки ассета, которые в Unreal не уходят
UNUSED = ("_disp", "displacement", "height")  # смещение Unreal без тесселяции не использует
STORE = "simplified.json"

# пороги - для обычной видеокарты среднего уровня
HEAVY = 1_000_000  # без Nanite не тянуть
NANITE = 100_000  # Nanite окупается
SCENE_TRIS = 5_000_000  # примерно столько треугольников в кадре без Nanite ещё комфортно
POOL_MB = 1000  # пул стриминга текстур Unreal по умолчанию


def textures(a):
    """[(путь, ширина, высота)] - текстуры в папке ассета (с подпапками), без превью."""
    out = []
    for root, _dirs, files in os.walk(a["dir"]):
        for f in files:
            low = f.lower()
            if not low.endswith(TEX_EXT) or any(s in low for s in SKIP):
                continue
            p = os.path.join(root, f)
            try:
                with Image.open(p) as im:
                    out.append((p, im.width, im.height, im.mode))
            except Exception:
                continue
    return out


def tex_bytes(path, w, h, mode="RGB"):
    """Примерная память видеокарты под текстуру (байты) с мип-уровнями."""
    low = os.path.basename(path).lower()
    if any(s in low for s in UNUSED):
        return 0
    one = ("nor", "normal", "alpha", "opacity", "mask", "arm", "orm")  # BC5/BC7/DXT5 и HDR (BC6H) - байт на пиксель
    per = 1.0 if low.endswith((".hdr", ".exr")) or any(s in low for s in one) or "A" in mode else 0.5
    return int(w * h * per * 4 / 3)


def _tris(a):
    return int(a.get("polycount") or 0)


def advice(a, tex_alpha=False, tris=None):
    """Что делать с моделью в Unreal: (уровень ok|nanite|heavy, текст)."""
    t = tris if tris is not None else _tris(a)
    if a.get("kind") != "model" or not t:
        return "ok", ""
    if a.get("rigged") and t >= NANITE:
        return "heavy", "со скелетом и тяжёлая: Nanite для скелетных моделей пока экспериментальный - лучше упростить"
    if t >= HEAVY:
        if tex_alpha:
            return "heavy", "очень тяжёлая листва с маской: упростить или Nanite Foliage (UE 5.7+, экспериментально)"
        return "heavy", "очень тяжёлая: при импорте включить Nanite, без него - упростить"
    if t >= NANITE:
        if tex_alpha:
            return "nanite", "листва с маской прозрачности: Nanite с маской дороже - проверить или упростить"
        return "nanite", "включить Nanite при импорте (Build Nanite)"
    return "ok", "хватит обычных LOD, Unreal строит их сам"


def scene(assets):
    """Бюджет подборки -> {items: [...], total: {...}, notes: [...]}."""
    from library import unreal_extra as X

    meta = X.load_meta()
    items, tris, gpu, disk = [], 0, 0, 0
    for a in assets:
        tex = textures(a) if a.get("kind") in ("model", "tex", "hdri") else []
        mem = sum(tex_bytes(p, w, h, m) for p, w, h, m in tex)
        alpha = any(any(s in os.path.basename(p).lower() for s in ("alpha", "opacity")) for p, *_r in tex)
        t = (meta.get(X._meta_key(a) or "") or {}).get("triangles") or _tris(a) if a.get("kind") == "model" else 0
        level, text = advice(a, alpha, t)
        tris += t
        gpu += mem
        disk += int(a.get("size") or 0)
        items.append(
            dict(
                id=a.get("id") or os.path.basename(a["dir"]),
                name=a.get("name", ""),
                kind=a.get("kind"),
                triangles=t,
                textures=len(tex),
                max_tex=max((max(w, h) for _p, w, h, _m in tex), default=0),
                gpu_mb=round(mem / 2**20, 1),
                level=level,
                advice=text,
                simplified=[s["file"] for s in simplified(a)],
            )
        )
    notes = []
    heavy = [i for i in items if i["level"] == "heavy"]
    nanite = [i for i in items if i["level"] == "nanite"]
    if tris > SCENE_TRIS:
        notes.append(
            f"Треугольников {tris:,} - больше {SCENE_TRIS:,}: без Nanite сцена будет тяжёлой. "
            "Тяжёлым моделям включить Nanite или упростить.".replace(",", " ")
        )
    if gpu / 2**20 > POOL_MB:
        notes.append(
            f"Текстуры ~{gpu / 2**20:.0f} МБ - больше пула стриминга по умолчанию ({POOL_MB} МБ): Unreal начнёт "
            "размывать их. Взять разрешение меньше (1k вместо 2k) или поднять r.Streaming.PoolSize."
        )
    if heavy:
        notes.append(f"Упростить или Nanite: {', '.join(i['name'] for i in heavy[:8])}.")
    if nanite:
        notes.append(f"Nanite при импорте: {len(nanite)} шт.")
    if not notes:
        notes.append("Подборка лёгкая: можно импортировать как есть.")
    return dict(
        items=items,
        total=dict(
            assets=len(items),
            triangles=tris,
            gpu_mb=round(gpu / 2**20),
            disk_mb=round(disk / 2**20),
            heavy=len(heavy),
            nanite=len(nanite),
        ),
        notes=notes,
    )


# ---------------------------------------------------------------- упрощение в Blender
def simplified(a):
    """[{file, triangles, ratio, made, use}] - упрощённые копии модели (use - брать её при импорте)."""
    try:
        with open(os.path.join(a["dir"], STORE), encoding="utf-8") as fh:
            data = json.load(fh)
        return [s for s in data if os.path.exists(os.path.join(a["dir"], s["file"]))]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def active(a):
    """Упрощённая копия, которую брать вместо оригинала при импорте и в пакет (последняя включённая) -> имя или None."""
    on = [s for s in simplified(a) if s.get("use", True)]
    return on[-1]["file"] if on else None


def set_active(a, file=None):
    """Включить упрощённую копию file (None - снова брать оригинал)."""
    data = simplified(a)
    for s in data:
        s["use"] = s["file"] == file
    with open(os.path.join(a["dir"], STORE), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def for_import(a):
    """Ассет для импорта: main с упрощённой копией вместо оригинального FBX, если она включена."""
    f = active(a)
    if not f:
        return a
    main = [f if m.lower().endswith(".fbx") else m for m in a.get("main", [])]
    return dict(a, main=main, polycount=next((s["triangles"] for s in simplified(a) if s["file"] == f), None))


def main_fbx(a):
    for f in a.get("main") or []:
        if f.lower().endswith(".fbx"):
            p = os.path.join(a["dir"], *f.split("/"))
            if os.path.exists(p):
                return p
    return None


SCRIPT = r"""
import bpy, json, sys
src, dst, ratio, report = {src!r}, {dst!r}, {ratio!r}, {report!r}
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
tris = 0
for ob in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
    if any(m.type == "ARMATURE" for m in ob.modifiers):
        continue  # скелетную не упрощаем - веса костей поплывут
    mod = ob.modifiers.new("decimate", "DECIMATE")
    mod.ratio = ratio
    mod.use_collapse_triangulate = True
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=mod.name)
for ob in bpy.context.scene.objects:
    if ob.type == "MESH":
        ob.data.calc_loop_triangles()
        tris += len(ob.data.loop_triangles)
bpy.ops.export_scene.fbx(filepath=dst, path_mode="RELATIVE", apply_unit_scale=True, bake_space_transform=False)
json.dump({{"triangles": tris}}, open(report, "w"))
"""


def simplify(a, target=100_000, blender=None, timeout=1800):
    """Упрощённая копия модели в Blender (Decimate) -> {file, triangles, ratio}. Оригинал не меняется."""
    src = main_fbx(a)
    if not src:
        raise ValueError("у ассета нет FBX")
    from library import fbx_meta

    try:  # число из каталога (Poly Haven) бывает в полигонах, а не треугольниках - доля по самому файлу
        t = (fbx_meta.read(src) or {}).get("triangles") or _tris(a)
    except Exception:
        t = _tris(a)
    if t and t <= target:
        raise ValueError(f"модель и так лёгкая: {t} треугольников")
    if a.get("rigged"):
        raise ValueError("модель со скелетом: Decimate испортит веса костей - упрощать в Blender вручную")
    blender = blender or blender_scene.find_blender()
    if not blender:
        raise ValueError("Blender не найден (путь можно указать в настройках)")
    ratio = max(0.001, min(1.0, target / t)) if t else 0.25
    stem = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(os.path.dirname(src), f"{stem}_{max(1, round(target / 1000))}k.fbx")
    report = dst + ".json"
    script = dst + ".py"
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(SCRIPT.format(src=src, dst=dst, ratio=ratio, report=report))
    try:
        res = blender_scene.run(blender, script, background=True, timeout=timeout)
        if not os.path.exists(report):
            tail = (res.stderr or res.stdout or "")[-600:]
            raise RuntimeError("Blender не сохранил модель: " + tail.strip())
        with open(report, encoding="utf-8") as fh:
            got = json.load(fh)["triangles"]
    finally:
        for p in (script, report):
            try:
                os.remove(p)
            except OSError:
                pass
    item = dict(
        file=os.path.relpath(dst, a["dir"]).replace(os.sep, "/"),
        triangles=got,
        ratio=round(ratio, 4),
        made=time.strftime("%Y-%m-%d"),
    )
    data = [dict(s, use=False) for s in simplified(a) if s["file"] != item["file"]] + [dict(item, use=True)]
    with open(os.path.join(a["dir"], STORE), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    return item
