"""Мелочи вкладки «Unreal» без Qt: цвета превью (фильтр по цвету), «новое», проверка ассетов."""

import json
import os
import shutil
import threading
import time

from PIL import Image

import imaging as K
from library.unreal import CACHE, KINDS, ROOT, assets

COLORS_STORE = os.path.join(os.path.dirname(CACHE), "_unreal_colors.json")
SIGS_STORE = os.path.join(os.path.dirname(CACHE), "_unreal_sigs.json")  # отпечатки превью для повторов
_lock = threading.Lock()


# ---------------------------------------------------------------- цвета
def _key(a):
    t = a.get("_pt")  # из обхода assets() - без запроса к диску
    if t is None:
        try:
            t = os.path.getmtime(os.path.join(a["dir"], "preview.webp"))
        except OSError:
            return None
    return f"{os.path.relpath(a['dir'], ROOT)}|{t:.0f}" if t else None


def load_colors():
    try:
        with open(COLORS_STORE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def build_colors(items, cache=None):
    """Коды главных цветов превью (как у картинок библиотеки: «vbk»). Досчитывает новые. -> {ключ: коды}."""
    cache = load_colors() if cache is None else cache
    changed = False
    for a in items:
        k = _key(a)
        if k is None or k in cache:
            continue
        try:
            with Image.open(os.path.join(a["dir"], "preview.webp")) as im:
                cache[k] = K.colors(im)
        except Exception:
            cache[k] = ""
        changed = True
    if changed:
        with _lock:
            K.write_atomic(COLORS_STORE, json.dumps(cache), "utf-8")
    return cache


def color_of(a, cache):
    k = _key(a)
    return cache.get(k, "") if k else ""


# ---------------------------------------------------------------- новое
def added(a):
    if "_t" in a:
        return a["_t"]
    try:
        return os.path.getmtime(os.path.join(a["dir"], "asset.json"))
    except OSError:
        return 0


# ---------------------------------------------------------------- повторы
def _norm(name):
    """Имя для сравнения: «Birch Tree 1», «birch_tree_1», «BirchTree1» - одно и то же."""
    return "".join(c for c in name.lower() if c.isalnum())


def build_sigs(items, cache=None):
    """Отпечатки превью (12x12, как у картинок библиотеки) - досчитываются только новые. -> {ключ: [..]}."""
    if cache is None:
        try:
            with open(SIGS_STORE, encoding="utf-8") as fh:
                cache = json.load(fh)
        except (OSError, ValueError):
            cache = {}
    changed = False
    for a in items:
        k = _key(a)
        if k is None or k in cache:
            continue
        try:
            with Image.open(os.path.join(a["dir"], "preview.webp")) as im:
                ratio, vec = K.signature(im)
            cache[k] = [round(ratio, 4)] + [int(v) for v in vec.reshape(-1)]
        except Exception:
            cache[k] = []
        changed = True
    if changed:
        with _lock:
            K.write_atomic(SIGS_STORE, json.dumps(cache), "utf-8")
    return cache


def duplicates(items):
    """Один и тот же ассет, скачанный дважды (из архива и из сети, из двух наборов): то же имя и то же
    превью. Только имя - мало (у Kenney и KayKit бывают разные «Wall»), только превью - тоже (простые
    кубики похожи). -> [[ассеты]], в группе первым - тот, что оставить (из сети, а не из архива; крупнее)."""
    import numpy as np

    by_name = {}
    for a in items:
        if a.get("kind") == "model" and a.get("_pt", 1):
            by_name.setdefault((_norm(a.get("name", "")), a.get("kind")), []).append(a)
    cands = [g for g in by_name.values() if len(g) > 1]
    if not cands:
        return []
    sigs = build_sigs([a for g in cands for a in g])
    out = []
    for g in cands:
        vecs = []
        for a in g:
            s = sigs.get(_key(a) or "")
            vecs.append((s[0], np.asarray(s[1:], float).reshape(12, 12, 3)) if s else None)
        used = set()
        for i in range(len(g)):
            if i in used or vecs[i] is None:
                continue
            same = [
                j
                for j in range(i + 1, len(g))
                if j not in used and vecs[j] is not None and K.same_sig(vecs[i], vecs[j])
            ]
            if same:
                group = [g[i]] + [g[j] for j in same]
                used.update(same)
                group.sort(key=lambda x: (str(x.get("id", "")).startswith("local-"), -x.get("size", 0)))
                out.append(group)
    return out


# ---------------------------------------------------------------- проверка
def check(items=None):
    """Проблемные ассеты: [(ассет или None, что не так)]. Недокачанные папки *.part убираются сразу."""
    out = []
    for d, dirs, _files in os.walk(ROOT):
        for x in list(dirs):
            # *.part - недокачанное; свежая папка может качаться прямо сейчас - её не трогать
            if x.endswith((".part", ".old")) and time.time() - os.path.getmtime(os.path.join(d, x)) > 3600:
                shutil.rmtree(os.path.join(d, x), ignore_errors=True)
                dirs.remove(x)
                out.append((None, f"убрана недокачанная папка {x}"))
    for a in assets() if items is None else items:
        main = [os.path.join(a["dir"], *m.split("/")) for m in a.get("main", [])]
        lost = [os.path.basename(p) for p in main if not os.path.exists(p)]
        if not main:
            out.append((a, "нет ни одного файла"))
        elif lost:
            out.append((a, "нет файлов: " + ", ".join(lost[:3])))
        elif a.get("kind") == "model" and any(p.lower().endswith(".fbx") and os.path.getsize(p) < 3000 for p in main):
            out.append((a, "пустой FBX"))
        elif any(os.path.getsize(p) == 0 for p in main):
            out.append((a, "пустой файл"))
        if not os.path.exists(os.path.join(a["dir"], "preview.webp")) and a.get("kind") != "model":
            out.append((a, "нет превью"))
        if a.get("kind") not in KINDS:
            out.append((a, "непонятный вид"))
    for group in duplicates(assets() if items is None else items):
        keep = group[0]
        for a in group[1:]:
            out.append((a, f"повтор: {keep.get('name', '')} ({keep.get('source', '')}) - можно убрать"))
    return out


# ---------------------------------------------------------------- полигоны, размеры, скелет (из FBX)
META_STORE = os.path.join(os.path.dirname(CACHE), "_unreal_meta.json")


def _fbx_of(a):
    return next((m for m in a.get("main", []) if m.lower().endswith(".fbx")), None)


def _meta_key(a):
    m = _fbx_of(a)
    if not m:
        return None
    t = a.get("_t")  # время asset.json из обхода assets(): перекачанный ассет - новые сведения
    if t is None:
        try:
            t = os.path.getmtime(os.path.join(a["dir"], "asset.json"))
        except OSError:
            return None
    return f"{os.path.relpath(a['dir'], ROOT)}|{m}|{t:.0f}"


def load_meta():
    try:
        with open(META_STORE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def build_meta(items, cache=None, progress=None, stop=None):
    """Треугольники, размеры, скелет и анимации моделей (library/fbx_meta) - досчитываются новые.
    asset.json не трогается: иначе «Новое» и поиск по смыслу сочли бы ассет изменённым. -> {ключ: сведения}."""
    from library import fbx_meta

    cache = load_meta() if cache is None else cache
    todo = [a for a in items if a.get("kind") == "model" and _meta_key(a) not in cache]
    for i, a in enumerate(todo):
        if stop is not None and stop.is_set():
            break
        k = _meta_key(a)
        if k is None:
            continue
        try:
            cache[k] = fbx_meta.read(os.path.join(a["dir"], *_fbx_of(a).split("/"))) or {}
        except Exception:
            cache[k] = {}
        if progress and i % 100 == 0:
            progress(i, len(todo))
    if todo:
        with _lock:
            K.write_atomic(META_STORE, json.dumps(cache, ensure_ascii=False), "utf-8")
    return cache


def apply_meta(items, cache=None):
    """Сведения из FBX - в ассеты (в памяти): polycount (если каталог его не дал), dims_cm, rigged, animations."""
    cache = load_meta() if cache is None else cache
    for a in items:
        if a.get("kind") != "model":
            continue
        m = cache.get(_meta_key(a) or "")
        if not m:
            continue
        if not a.get("polycount") and m.get("triangles"):
            a["polycount"] = m["triangles"]
        if m.get("dims_cm") and not a.get("dimensions_mm"):
            a["dims_cm"] = m["dims_cm"]
        a["rigged"] = bool(m.get("rigged"))
        if m.get("animations"):
            a["animations"] = m["animations"]
    return items
