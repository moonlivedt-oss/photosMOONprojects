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
NEW_DAYS = 3
_lock = threading.Lock()


# ---------------------------------------------------------------- цвета
def _key(a):
    try:
        return f"{os.path.relpath(a['dir'], ROOT)}|{os.path.getmtime(os.path.join(a['dir'], 'preview.webp')):.0f}"
    except OSError:
        return None


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
    try:
        return os.path.getmtime(os.path.join(a["dir"], "asset.json"))
    except OSError:
        return 0


def is_new(a, days=NEW_DAYS):
    return time.time() - added(a) < days * 86400


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
    return out
