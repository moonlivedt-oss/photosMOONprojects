"""Скачанные вручную архивы моделей (itch.io: KayKit, Quaternius MegaKit и др.) -> ассеты _Unreal.
Без Qt. Архив (zip) или папка разбирается: каждый FBX - отдельный ассет со своими текстурами (какие
файлы картинок FBX называет внутри себя - те и кладутся рядом, по тому же относительному пути).
Тема и источник угадываются по имени архива (KNOWN), иначе - «Разное - Свои архивы»."""

import json
import os
import re
import shutil
import struct
import zipfile

from library import unreal as U
from library.common import clean_name, unique

DROP = os.path.join(U.ROOT, "_Архивы")  # сюда можно просто сложить скачанные zip - «Добавить архивы» их возьмёт
DONE = os.path.join(DROP, "_разобрано")
UNPACK = os.path.join(U.PACKS, "local")
SKIP = ("__macosx", "/obj", "/gltf", "/glb", "/blend", "godot")  # другие форматы - не FBX
IMAGES = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff")

# (слова в имени архива, источник, страница, тема без источника)
KNOWN = (
    (("forest",), "KayKit", "https://kaylousberg.itch.io/kaykit-forest", "Лес и природа"),
    (("platformer",), "KayKit", "https://kaylousberg.itch.io/kaykit-platformer", "Прототипы и уровни"),
    (
        ("block bits", "block_bits", "blockbits"),
        "KayKit",
        "https://kaylousberg.itch.io/block-bits",
        "Прототипы и уровни",
    ),
    (("resource",), "KayKit", "https://kaylousberg.itch.io/resource-bits", "Лес и природа"),
    (("board game", "boardgame", "board_game"), "KayKit", "https://kaylousberg.itch.io/board-game-bits", "Дом"),
    (
        ("fantasy weapons", "fantasy_weapons", "weapons bits"),
        "KayKit",
        "https://kaylousberg.itch.io/fantasy-weapons-bits",
        "Средневековье",
    ),
    (("rpg tools", "rpg_tools"), "KayKit", "https://kaylousberg.itch.io/rpg-tools-bits", "Средневековье"),
    (("holiday",), "KayKit", "https://kaylousberg.itch.io/holiday-bits", "Праздники"),
    (("mixed bag", "mixed_bag", "mixedbag"), "KayKit", "https://kaylousberg.itch.io/mixed-bag-1", "Разное"),
    (
        ("medieval builder", "medieval_builder"),
        "KayKit",
        "https://kaylousberg.itch.io/kaykit-medieval-builder-pack",
        "Средневековье",
    ),
    (
        ("mini game", "mini_game", "minigame"),
        "KayKit",
        "https://kaylousberg.itch.io/kay-kit-mini-game-variety-pack",
        "Прототипы и уровни",
    ),
    (("spooktober",), "KayKit", "https://kaylousberg.itch.io/kaykit-spooktober", "Праздники"),
    (
        ("character animations", "character_animations"),
        "KayKit",
        "https://kaylousberg.itch.io/kaykit-character-animations",
        "Персонажи",
    ),
    (
        ("stylized nature", "stylized_nature"),
        "Quaternius",
        "https://quaternius.itch.io/stylized-nature-megakit",
        "Лес и природа",
    ),
    (
        ("medieval village", "medieval_village"),
        "Quaternius",
        "https://quaternius.itch.io/medieval-village-megakit",
        "Средневековье",
    ),
    (
        ("modular sci-fi", "modular_sci-fi", "sci-fi megakit", "scifi megakit", "modular scifi"),
        "Quaternius",
        "https://quaternius.itch.io/modular-sci-fi-megakit",
        "Космос",
    ),
    (("downtown",), "Quaternius", "https://quaternius.itch.io/downtown-city-megakit", "Город"),
    (
        ("fantasy props", "fantasy_props"),
        "Quaternius",
        "https://quaternius.itch.io/fantasy-props-megakit",
        "Средневековье",
    ),
    (
        ("sci-fi essentials", "scifi essentials", "sci-fi_essentials"),
        "Quaternius",
        "https://quaternius.itch.io/sci-fi-essentials-kit",
        "Космос",
    ),
    (
        ("universal base characters", "base characters", "base_characters"),
        "Quaternius",
        "https://quaternius.itch.io/universal-base-characters",
        "Персонажи",
    ),
    (
        ("animation library", "animation_library"),
        "Quaternius",
        "https://quaternius.itch.io/universal-animation-library",
        "Персонажи",
    ),
    (("outfits",), "Quaternius", "https://quaternius.itch.io/modular-character-outfits-fantasy", "Персонажи"),
    (("bestiary",), "Quaternius", "https://quaternius.itch.io/bestiary-dungeon-monsters-kit", "Персонажи"),
    (("card kit", "card_kit"), "Quaternius", "https://quaternius.itch.io/3d-card-kit-fantasy", "Средневековье"),
)


def guess(name):
    """Имя архива -> (источник, страница, тема) или (None, "", "Разное")."""
    low = name.lower().replace("_", " ").replace("-", " ").replace("+", " ")
    low_raw = name.lower()
    for words, src, page, theme in KNOWN:
        if any(w.replace("_", " ").replace("-", " ") in low or w in low_raw for w in words):
            return src, page, theme
    src = "KayKit" if "kaykit" in low else ("Quaternius" if "quaternius" in low else None)
    return src, "", "Разное"


def theme_of(base, src):
    return f"{base} - {src or 'Свои'} low-poly" if base != "Разное" else "Разное - Свои архивы"


def unpack(path):
    """Архив -> папка с содержимым (распаковывается один раз; папка как есть)."""
    if os.path.isdir(path):
        return path
    stem = clean_name(os.path.splitext(os.path.basename(path))[0]) or "archive"
    dst = os.path.join(UNPACK, stem)
    if not os.path.isdir(dst):
        tmp = dst + ".part"
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(path) as zf:
            for m in zf.infolist():
                if m.is_dir():
                    continue
                parts = [p for p in m.filename.replace("\\", "/").split("/") if p not in ("", ".", "..")]
                if not parts or ":" in parts[0]:
                    continue
                out = os.path.join(tmp, *parts)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with zf.open(m) as src, open(out, "wb") as fh:
                    shutil.copyfileobj(src, fh)
        os.replace(tmp, dst)
    return dst


def texture_refs(fbx):
    """Какие картинки называет FBX внутри себя: [строка пути как записана]."""
    try:
        with open(fbx, "rb") as fh:
            data = fh.read()
    except OSError:
        return []
    found = re.findall(rb"[\w .\\/:()-]{1,200}\.(?:png|jpe?g|tga|bmp|tiff?)", data, re.IGNORECASE)
    out = []
    for raw in found:
        s = raw.decode("utf-8", "replace").strip()
        if s and s not in out:
            out.append(s)
    return out


def scan(folder):
    """FBX внутри папки набора: [путь]. OBJ/glTF/Blend пропускаются. Наборы часто кладут одну модель
    несколько раз: «FBX (Unreal Engine)», «FBX (Unity)», просто «FBX» - для каждой модели (по имени файла)
    берётся одна копия: для Unreal, иначе обычная, и только если больше нет ничего - для Unity."""
    rank = {"unreal": 0, "plain": 1, "unity": 2}
    best = {}
    for d, dirs, files in os.walk(folder):
        dirs.sort()
        rel = "/" + os.path.relpath(d, folder).replace("\\", "/").lower()
        if any(s in rel for s in SKIP):
            continue
        variant = "unreal" if "unreal" in rel or "- ue" in rel else ("unity" if "unity" in rel else "plain")
        for f in sorted(files):
            if not f.lower().endswith(".fbx"):
                continue
            key = (rank[variant], "fbx" not in rel, len(rel))  # и лучше из папки «FBX», и поближе к корню
            have = best.get(f.lower())
            if have is None or key < have[0]:
                best[f.lower()] = (key, os.path.join(d, f))
    return sorted(p for _k, p in best.values())


def images_by_name(folder):
    out = {}
    for d, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(IMAGES):
                out.setdefault(f.lower(), []).append(os.path.join(d, f))
    return out


def candidates(path, theme=None, source=None, page=""):
    """Ассеты из архива: [cand для U.fetch с src="local"], тема."""
    name = os.path.basename(path.rstrip("\\/"))
    src, pg, base = guess(name)
    src, page = source or src, page or pg
    theme = theme or theme_of(base, src)
    folder = unpack(path)
    imgs = images_by_name(folder)
    pack = re.sub(r"[^a-z0-9]+", "-", os.path.splitext(name)[0].lower()).strip("-")
    out = []
    for f in scan(folder):
        refs = []
        for r in texture_refs(f):
            hits = imgs.get(os.path.basename(r.replace("\\", "/")).lower())
            if hits:
                near = min(hits, key=lambda h: len(os.path.relpath(h, os.path.dirname(f))))
                refs.append((r, near))
        base_name = os.path.splitext(os.path.basename(f))[0]
        rel = os.path.relpath(f, folder).replace("\\", "/")
        out.append(
            {
                "src": "local",
                "id": f"local-{pack}-{os.path.splitext(rel)[0].lower().replace('/', '-')}",
                "name": U.pretty(base_name),
                "info": {},
                "file": f,
                "textures": refs,
                "source": src or "Свои архивы",
                "url": page,
                "pack": name,
            }
        )
    return out, theme


def relink(fbx):
    """Абсолютные пути к текстурам в FBX (с компьютера автора) -> имена файлов рядом. Unreal и Blender
    находят такие текстуры и сами, а 3D-просмотр окна - нет. -> сколько путей заменено."""
    from library import fbx_colors

    have = {f.lower() for f in os.listdir(os.path.dirname(fbx))}
    with open(fbx, "rb") as fh:
        data = fh.read()
    try:
        new, n = fbx_colors.relink_textures(data, have)
    except (ValueError, IndexError, struct.error):  # необычный FBX - оставить как есть
        return 0
    if n:
        with open(fbx, "wb") as fh:
            fh.write(new)
    return n


def fetch_local(cand, dst):
    fn = os.path.basename(cand["file"])
    shutil.copy2(cand["file"], os.path.join(dst, fn))
    extra = []
    for ref, path in cand.get("textures", []):
        r = ref.replace("\\", "/")
        places = [os.path.basename(r)]  # рядом с FBX - так находят и Unreal, и Blender, и 3D-просмотр
        if not re.match(r"^([a-zA-Z]:|/)", r) and "/" in r and ".." not in r:
            places.append(r)  # и по относительному пути, как записано в FBX
        for p in places:
            out = os.path.join(dst, *p.split("/"))
            if not os.path.exists(out):
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy2(path, out)
                extra.append(p)
    relink(os.path.join(dst, fn))
    low = cand["source"] in U.LOW_POLY
    meta = {
        "source": cand["source"],
        "url": cand.get("url") or "",
        "authors": [{"KayKit": "Kay Lousberg"}.get(cand["source"], cand["source"])],
        "tags": (["low-poly"] if low else []) + [cand["source"].lower(), cand["pack"].lower()],
        "categories": [],
        "main": [fn],
        "description": f"Из скачанного архива «{cand['pack']}».",
    }
    if extra:
        meta["extra"] = extra
    return meta


def import_archives(paths, log=print, stop=None):
    """Разобрать архивы в _Unreal. -> {"added": n, "themes": {тема: n}, "errors": [..]}.
    Повторный импорт того же архива пропускает уже добавленное."""
    have = U.have_ids(U.ROOT)
    res = {"added": 0, "themes": {}, "errors": []}
    for path in paths:
        try:
            cands, theme = candidates(path)
        except (OSError, zipfile.BadZipFile) as e:
            res["errors"].append(f"{os.path.basename(path)}: {e}")
            continue
        if not cands:
            res["errors"].append(f"{os.path.basename(path)}: внутри нет FBX")
            continue
        log(f"{os.path.basename(path)}: {len(cands)} моделей -> {theme}")
        for c in cands:
            if stop is not None and stop.is_set():
                return res
            if c["id"] in have:
                continue
            try:
                U.fetch(c, "model", theme)
                res["added"] += 1
                res["themes"][theme] = res["themes"].get(theme, 0) + 1
            except Exception as e:
                res["errors"].append(f"{c['name']}: {e}")
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(DROP) and os.path.isfile(path):
            os.makedirs(DONE, exist_ok=True)  # разобранный архив из папки - в «_разобрано», чтобы не брать снова
            shutil.move(path, unique(os.path.join(DONE, os.path.basename(path))))
    return res


def dropped():
    """Архивы, сложенные в _Unreal/_Архивы."""
    if not os.path.isdir(DROP):
        return []
    return [os.path.join(DROP, f) for f in sorted(os.listdir(DROP)) if f.lower().endswith(".zip")]


def known_list():
    """Для ссылок и справки: [(источник, страница, тема)] без повторов."""
    seen, out = set(), []
    for _w, src, page, theme in KNOWN:
        if page not in seen:
            seen.add(page)
            out.append((src, page, theme))
    return out


if __name__ == "__main__":
    print(json.dumps(known_list(), ensure_ascii=False, indent=1))
