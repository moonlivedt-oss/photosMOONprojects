"""Ещё реалистичные ассеты для вкладки «Unreal».

Текстуры - весь каталог Poly Haven и ambientCG (фотосканы, CC0), без повторов: одинаковые на вид материалы
(одна съёмка под двумя именами, почти одинаковые варианты) отсеиваются по превью ещё до скачивания.
Тема (папка) - по материалу: кирпич и бетон - в «Город», металл - в «Индустрию», ткани - в «Дом - ткани»...
что не подошло ни к одной - в «Материалы».

Модели - четыре источника реалистичных сканов и PBR-моделей:
  gso      - Google Scanned Objects: ~1000 сканов бытовых вещей (CC BY 4.0, указать автора - Google);
  si       - Smithsonian 3D: музейные предметы и находки (CC0, Smithsonian Open Access);
  khronos  - glTF Sample Assets: эталонные PBR-модели Khronos (лицензия своя у каждой);
  nasa     - NASA 3D Resources: корабли, спутники, телескопы (общественное достояние, без логотипов NASA).
Они приходят в glb / gltf / obj и переводятся в FBX через Blender (library/blender_convert.py) - дальше путь
как у Poly Haven. Просмотровая копия для 3D-окна - исходный glb (view в asset.json): в нём PBR без потерь.

Без Qt: это зовут unreal.fetch / unreal.candidates и командная строка (cli.py unreal more ...)."""

import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from library import unreal as U

CACHE = os.path.join(os.path.dirname(U.CACHE), "_unreal_more_cache.json")  # каталоги источников
SIGS = os.path.join(os.path.dirname(U.CACHE), "_unreal_tex_sigs.json")  # отпечатки превью текстур
_lock = threading.Lock()

SOURCES = ("gso", "si", "khronos", "nasa")
THEME = {  # источник моделей -> тема (папка)
    "gso": "Дом - сканы Google",
    "si": "Музей - Smithsonian",
    "khronos": "Дом - витрина Khronos",
    "nasa": "Космос - NASA",
}
NAMES = {
    "gso": "Google Scanned Objects",
    "si": "Smithsonian 3D",
    "khronos": "glTF Sample Assets (Khronos)",
    "nasa": "NASA 3D Resources",
}
LICENSES = {
    "gso": "CC BY 4.0 - можно в любые проекты, но указать автора: Google (Google Scanned Objects)",
    "si": "CC0 1.0 - общественное достояние (Smithsonian Open Access): можно в любые проекты",
    "nasa": (
        "Общественное достояние (NASA): можно в любые проекты; нельзя использовать логотипы NASA "
        "и намекать, что NASA одобряет проект"
    ),
}
HOWTO = (
    "Перетащите .fbx в Content Browser вместе с папкой textures, в окне импорта - Import Materials и "
    "Import Textures. Модель - скан, сетка плотная: для сцены включите Nanite (Build Nanite) или упростите её "
    "кнопкой «Бюджет». Нормаль в формате OpenGL: в текстуре нормали включите Flip Green Channel."
)
FUEL = "https://fuel.gazebosim.org/1.0/GoogleResearch/models"
SI_API = "https://3d-api.si.edu/api/v1.0/content/file/search"
KH_RAW = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models"
NASA_REPO = "nasa/NASA-3D-Resources"
NASA_RAW = f"https://raw.githubusercontent.com/{NASA_REPO}/master/"


# ---------------------------------------------------------------- кэш каталогов
def cached(key, build, days=7, fresh=False):
    """Каталог источника из _unreal_more_cache.json; старше days - собрать заново (build())."""
    with _lock:
        try:
            with open(CACHE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
    hit = data.get(key)
    if hit and not fresh and time.time() - hit["t"] < days * 86400:
        return hit["data"]
    value = build()
    with _lock:
        try:
            with open(CACHE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        data[key] = {"t": time.time(), "data": value}
        U.K.write_atomic(CACHE, json.dumps(data, ensure_ascii=False), "utf-8")
    return value


def quote(url):
    """Ссылка с пробелами, скобками и запятыми в имени файла (Smithsonian, NASA) - в годную для запроса."""
    return urllib.parse.quote(url, safe=":/?&=%")


# ---------------------------------------------------------------- текстуры: тема и раздел по материалу
# (раздел, слова) - первое совпадение выигрывает; слова и фразы ищутся в имени, категориях и метках.
# Раздел - для дерева окна (unreal_groups.section_of); тема - папка, куда кладётся новая текстура.
TEX_SECTIONS = (
    ("Снег и лёд", ("snow", "ice", "frozen", "frost")),
    ("Износ и декали", ("imperfection", "fingerprint", "smear", "scratches", "footsteps", "decal", "leaking")),
    (
        "Ткани и кожа",
        (
            "fabric",
            "leather",
            "cotton",
            "denim",
            "wool",
            "velvet",
            "fleece",
            "knitted",
            "satin",
            "suede",
            "corduroy",
            "jacquard",
            "hessian",
            "woven",
            "linen",
            "cloth",
            "wicker",
            "rope",
            "carpet",
            "rug",
            "tatami",
        ),
    ),
    ("Крыши", ("roofing", "roof", "thatched", "shingle")),
    ("Полы", ("wood floor", "woodfloor", "parquet", "laminate", "floorboard", "cork")),
    ("Плитка", ("tiles", "tile", "mosaic", "terrazzo")),
    ("Мрамор и гранит", ("marble", "granite", "onyx", "travertine", "porcelain")),
    ("Брусчатка", ("cobblestone", "paving stones", "pavingstones", "pavers", "cobble")),
    ("Кирпич", ("brick",)),
    ("Асфальт и дороги", ("asphalt", "road", "pavement", "sidewalk", "tactile", "manhole")),
    ("Штукатурка и обои", ("plaster", "stucco", "wallpaper", "painted wall", "office ceiling")),
    ("Бетон", ("concrete", "cement")),
    (
        "Металл",
        (
            "metal",
            "rust",
            "steel",
            "iron",
            "diamond plate",
            "diamondplate",
            "corrugated",
            "chainmail",
            "foil",
            "aluminium",
            "aluminum",
            "copper",
            "brass",
            "solar panel",
            "grate",
            "walkway",
        ),
    ),
    ("Дерево", ("wood", "planks", "plywood", "chipboard", "bamboo", "siding", "timber", "log")),
    ("Песок", ("sand", "dune", "beach")),
    ("Камни и скалы", ("rock", "rocks", "cliff", "stone", "boulder", "pebble", "slate", "lava")),
    (
        "Земля и трава",
        (
            "ground",
            "grass",
            "moss",
            "soil",
            "mud",
            "dirt",
            "forest",
            "leaves",
            "leaf",
            "gravel",
            "terrain",
            "bark",
            "chips",
            "tree end",
            "pathway",
            "aerial",
        ),
    ),
)
TEX_OTHER = "Пластик и прочее"
SECTION_THEME = {  # раздел -> тема (папка) для новой текстуры
    "Снег и лёд": "Зима",
    "Ткани и кожа": "Дом - ткани и кожа",
    "Полы": "Дом - полы",
    "Плитка": "Дом - плитка и камень",
    "Мрамор и гранит": "Дом - плитка и камень",
    "Штукатурка и обои": "Дом - стены",
    "Брусчатка": "Город",
    "Кирпич": "Город",
    "Асфальт и дороги": "Город",
    "Бетон": "Город",
    "Крыши": "Средневековье и фэнтези",
    "Металл": "Индустрия и sci-fi",
    "Песок": "Пустыня и скалы",
    "Камни и скалы": "Пустыня и скалы",
    "Земля и трава": "Лес и природа",
}
MATERIALS = "Материалы"  # тема для остального: дерево, пластик, бумага, износ и декали


def tex_text(a):
    """Имя, категории и метки строкой для поиска фраз: «Wood Floor 041» -> «wood floor 041 ...»."""
    parts = [a.get("name") or a.get("displayName") or ""]
    parts += [str(x) for x in (a.get("categories") or [])]
    parts += [str(a.get("displayCategory") or "")]
    parts += [str(x) for x in (a.get("tags") or [])]
    s = " ".join(parts)
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s).replace("_", " ").lower()
    return " " + " ".join(s.split()) + " "


def tex_section(a):
    """Раздел текстуры по материалу. Сначала имя (оно точнее меток), потом всё вместе."""
    name = tex_text({"name": a.get("name") or a.get("displayName") or ""})
    full = tex_text(a)
    for text in (name, full):
        for sec, keys in TEX_SECTIONS:
            if any(" " + k in text for k in keys):
                return sec
    return TEX_OTHER


def tex_theme(a):
    return SECTION_THEME.get(tex_section(a), MATERIALS)


# ---------------------------------------------------------------- текстуры: каталоги и повторы
def acg_all(fresh=False):
    """Все материалы ambientCG (около 2000) с данными для скачивания и превью."""

    def build():
        out, off = [], 0
        while True:
            url = (
                f"{U.ACG_API}?type=Material&sort=Popular&limit=250&offset={off}"
                "&include=downloadData,previewData,tagData,displayData"
            )
            found = U.get_json(url).get("foundAssets", [])
            if not found:
                break
            for a in found:  # лишнее не храним: ссылки на просмотр и статистика
                for k in ("previewLinks", "createdUsing", "basedOnThis", "variations", "description"):
                    a.pop(k, None)
            out += found
            off += len(found)
        return out

    return cached("acg", build, days=1, fresh=fresh)


def tex_candidates(have=None):
    """Все текстуры Poly Haven и ambientCG, которых ещё нет: [{src, id, name, info, theme, thumb}],
    популярные первыми (Poly Haven и ambientCG вперемешку)."""
    have = U.have_ids() if have is None else have
    ph = []
    for aid, info in U.catalog("tex").items():
        if aid in have:
            continue
        c = {"src": "ph", "id": aid, "name": info.get("name", aid), "info": info}
        c["thumb"] = f"https://cdn.polyhaven.com/asset_img/thumbs/{aid}.png?width=128&height=128"
        c["pop"] = info.get("download_count", 0)
        ph.append(c)
    acg = []
    for a in acg_all():
        aid = a["assetId"]
        if aid in have or not a.get("downloadFolders"):
            continue
        c = {"src": "acg", "id": aid, "name": a.get("displayName", aid), "info": a}
        c["thumb"] = (a.get("previewImage") or {}).get("128-PNG", "")
        c["pop"] = a.get("downloadCount", 0)
        acg.append(c)
    ph.sort(key=lambda c: -c["pop"])
    acg.sort(key=lambda c: -c["pop"])
    out = []
    for i in range(max(len(ph), len(acg))):
        for lst in (ph, acg):
            if i < len(lst):
                c = lst[i]
                info = dict(c["info"], name=c["name"])
                c["theme"] = tex_theme(info)
                out.append(c)
    return out


SIG_VERSION = 2
SIG_SIDE = 32


def tex_sig(im):
    """Отпечаток превью-шара: середина шара 32x32 без освещения (яркость минус её размытие - остаётся
    рисунок: зёрна, швы, волокна) и средний цвет. -> строка base64 (32*32 байт + 3 байта цвета).
    Сравнивать сам шар нельзя: у гладких материалов он почти весь - свет и тень, и пластик «совпадает» с обоями."""
    from PIL import ImageFilter

    im = im.convert("RGB")
    w, h = im.size
    c = im.crop((round(w * 0.27), round(h * 0.27), round(w * 0.73), round(h * 0.73)))
    g = c.convert("L").resize((SIG_SIDE, SIG_SIDE), Image.Resampling.BOX)
    hp = np.asarray(g, dtype=float) - np.asarray(g.filter(ImageFilter.GaussianBlur(3)), dtype=float)
    hp = (hp - hp.mean()) / (hp.std() + 1.0)  # +1: у ровного пластика рисунка нет - не раздувать шум
    q = np.clip(np.round(hp * 32), -127, 127).astype(np.int8).tobytes()
    mean = np.asarray(c.resize((1, 1), Image.Resampling.BOX), dtype=np.uint8).reshape(3).tobytes()
    import base64

    return base64.b64encode(q + mean).decode("ascii")


def _unpack(sig):
    import base64

    raw = base64.b64decode(sig)
    n = SIG_SIDE * SIG_SIDE
    hp = np.frombuffer(raw[:n], np.int8).astype(np.float32) / 32
    return hp, np.frombuffer(raw[n : n + 3], np.uint8).astype(np.float32)


def same_tex(a, b, corr=0.8, color=12.0):
    """Одна и та же текстура? Рисунок совпадает (корреляция >= corr) и цвет почти тот же.
    Тот же рисунок другого цвета (ткань в пяти цветах) - не повтор."""
    ha, ca = _unpack(a)
    hb, cb = _unpack(b)
    r = float(ha @ hb) / (float(np.linalg.norm(ha) * np.linalg.norm(hb)) + 1e-6)
    return r >= corr and float(np.abs(ca - cb).max()) < color


def _load_sigs():
    try:
        with open(SIGS, encoding="utf-8") as fh:
            data = json.load(fh)
        return data["sigs"] if data.get("v") == SIG_VERSION else {}
    except (OSError, ValueError, KeyError, AttributeError):
        return {}


def tex_sigs(cands, have_items, log=print):
    """Отпечатки: у кандидатов - по миниатюре с сайта, у скачанных - по preview.webp. Кэш в _unreal_tex_sigs.json."""
    import io

    sigs = _load_sigs()
    todo = [c for c in cands if f"{c['src']}:{c['id']}" not in sigs and c.get("thumb")]

    def one(c):
        try:
            im = Image.open(io.BytesIO(U.get(c["thumb"], timeout=30)))
            return f"{c['src']}:{c['id']}", tex_sig(im)
        except Exception:
            return f"{c['src']}:{c['id']}", None

    if todo:
        log(f"Миниатюры для проверки повторов: {len(todo)}")
        with ThreadPoolExecutor(12) as ex:
            for i, (k, s) in enumerate(ex.map(one, todo), 1):
                if s:
                    sigs[k] = s
                if i % 300 == 0:
                    log(f"  {i} из {len(todo)}")
    for a in have_items:
        k = "have:" + str(a.get("id"))
        if k in sigs:
            continue
        try:
            with Image.open(os.path.join(a["dir"], "preview.webp")) as im:
                sigs[k] = tex_sig(im)
        except Exception:
            pass
    U.K.write_atomic(SIGS, json.dumps({"v": SIG_VERSION, "sigs": sigs}), "utf-8")
    return sigs


def family(name):
    """«Planks 037 B» -> «planks 037»: у ambientCG варианты одной съёмки - буквы A, B, C после номера."""
    return re.sub(r"\s+[A-Z]$", "", name.strip()).lower()


def dedupe(cands, sigs, have_items=()):
    """Убрать повторы до скачивания: кандидат, похожий на уже скачанную текстуру или на кандидата выше
    по списку (популярнее), не берётся. -> (оставшиеся, [(повтор, на что похож)]).

    По превью-шару надёжно видно только одно: варианты одной съёмки ambientCG (A, B, C) почти совпадают -
    они и сравниваются. Разные материалы по шару не сравнить: у блестящего металла на нём отражения, у тканей
    Poly Haven - одинаковые складки, а не рисунок. Их повторы ловит проверка по самим картам цвета после
    скачивания (tex_duplicates)."""
    rows = []  # (отпечаток, имя, семейство)
    for a in have_items:
        sig = sigs.get("have:" + str(a.get("id")))
        if sig:
            rows.append((sig, a.get("name", ""), family(a.get("name", ""))))
    n_ref = len(rows)
    mine = []
    for i, c in enumerate(cands):
        sig = sigs.get(f"{c['src']}:{c['id']}")
        if sig:
            rows.append((sig, c["name"], family(c["name"])))
        mine.append((i, sig))
    if not rows:
        return list(cands), []
    hp = np.stack([_unpack(r[0])[0] for r in rows])
    col = np.stack([_unpack(r[0])[1] for r in rows])
    hp /= np.linalg.norm(hp, axis=1, keepdims=True) + 1e-6
    sim = hp @ hp.T  # все пары сразу: 2600 x 2600 - доли секунды
    dcol = np.abs(col[:, None, :] - col[None, :, :]).max(axis=2)
    fam = np.array([r[2] for r in rows])
    near = (fam[:, None] == fam[None, :]) & (sim >= 0.8) & (dcol < 8)
    alive = np.zeros(len(rows), bool)
    alive[:n_ref] = True
    kept, dropped, row = [], [], n_ref
    for i, sig in mine:
        c = cands[i]
        if not sig:
            kept.append(c)
            continue
        twins = np.flatnonzero(near[row, :row] & alive[:row])
        if len(twins):
            dropped.append((c["name"], rows[twins[0]][1]))
        else:
            alive[row] = True
            kept.append(c)
        row += 1
    return kept, dropped


def color_map(a):
    """Файл цвета скачанной текстуры (diff у Poly Haven, Color у ambientCG)."""
    for m in a.get("main", []):
        low = m.lower()
        if "_diff_" in low or "_color" in low or "basecolor" in low or "albedo" in low:
            return os.path.join(a["dir"], m)
    return None


def map_sig(path):
    """Отпечаток самой карты цвета (плоской, без освещения) - как tex_sig, но по всему кадру."""
    with Image.open(path) as im:
        im.draft("RGB", (256, 256))  # JPEG читается сразу уменьшенным - в разы быстрее
        im = im.convert("RGB").resize((128, 128), Image.Resampling.BOX)
    w = im.width
    # tex_sig берёт середину кадра - отдать ему кадр, у которого «середина» - вся карта
    big = Image.new("RGB", (round(w / 0.46), round(w / 0.46)))
    big.paste(im, ((big.width - w) // 2, (big.width - w) // 2))
    return tex_sig(big)


def tex_duplicates(items=None, corr=0.9, color=6.0):
    """Повторы среди скачанных текстур по самим картам цвета: одна съёмка под двумя именами, в том числе
    между Poly Haven и ambientCG. -> [[ассеты]], первым - тот, что оставить (скачан раньше)."""
    items = [a for a in (U.assets() if items is None else items) if a.get("kind") == "tex"]
    cache_path = os.path.join(os.path.dirname(U.CACHE), "_unreal_tex_maps.json")
    try:
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)
        cache = cache["sigs"] if cache.get("v") == SIG_VERSION else {}
    except (OSError, ValueError, KeyError, AttributeError):
        cache = {}
    todo = [a for a in items if str(a.get("id")) not in cache and color_map(a)]

    def one(a):
        try:
            return str(a.get("id")), map_sig(color_map(a))
        except Exception:
            return str(a.get("id")), None

    with ThreadPoolExecutor(8) as ex:
        for k, sig in ex.map(one, todo):
            if sig:
                cache[k] = sig
    U.K.write_atomic(cache_path, json.dumps({"v": SIG_VERSION, "sigs": cache}), "utf-8")
    items = sorted(
        (a for a in items if cache.get(str(a.get("id")))), key=lambda a: (a.get("added", ""), a.get("_t", 0))
    )
    if len(items) < 2:
        return []
    hp = np.stack([_unpack(cache[str(a["id"])])[0] for a in items])
    col = np.stack([_unpack(cache[str(a["id"])])[1] for a in items])
    hp /= np.linalg.norm(hp, axis=1, keepdims=True) + 1e-6
    near = (hp @ hp.T >= corr) & (np.abs(col[:, None, :] - col[None, :, :]).max(axis=2) < color)
    out, used = [], set()
    for i in range(len(items)):
        if i in used:
            continue
        js = [j for j in np.flatnonzero(near[i]) if j > i and j not in used]
        if js:
            used.update(js)
            out.append([items[i]] + [items[j] for j in js])
    return out


# ---------------------------------------------------------------- модели: Google Scanned Objects
def gso_list(fresh=False):
    def build():
        out, page = [], 1
        while True:
            try:
                rows = U.get_json(f"{FUEL}?per_page=100&page={page}")
            except Exception:
                break
            if not rows:
                break
            out += [
                {"name": r["name"], "description": r.get("description", ""), "size": r.get("filesize", 0)} for r in rows
            ]
            page += 1
        return out

    return cached("gso", build, fresh=fresh)


GSO_SKIP = ("test",)  # служебные записи


def gso_candidates(have=()):
    out = []
    for r in gso_list():
        aid = "gso-" + r["name"]
        if aid in have or r["name"].lower() in GSO_SKIP:
            continue
        title = (r.get("description") or "").split("\n")[0].strip() or r["name"].replace("_", " ")
        out.append(
            {
                "src": "gso",
                "id": aid,
                "name": title[:80],
                "info": r,
                "thumb": f"{FUEL}/{urllib.parse.quote(r['name'])}/tip/files/thumbnails/0.jpg",
            }
        )
    return out


def fetch_gso(cand, dst, progress, stop):
    name = cand["info"]["name"]
    q = urllib.parse.quote(name)
    zp = os.path.join(dst, "_src.zip")
    U.download(f"{FUEL}/{q}/1/{q}.zip", zp, progress=_bytes(progress, 0.0, 0.6, cand), stop=stop)
    src = os.path.join(dst, "_src")
    os.makedirs(src)
    base = _base(cand["name"])
    with zipfile.ZipFile(zp) as zf:
        names = zf.namelist()
        obj = next(n for n in names if n.lower().endswith(".obj"))
        mtl = next((n for n in names if n.lower().endswith(".mtl")), None)
        tex = [n for n in names if n.startswith("materials/textures/") and n.lower().endswith((".png", ".jpg"))]
        with zf.open(obj) as fh:
            data = fh.read().decode("utf-8", "replace")
        data = re.sub(r"^mtllib .*$", f"mtllib {base}.mtl", data, count=1, flags=re.M)
        with open(os.path.join(src, base + ".obj"), "w", encoding="utf-8") as fh:
            fh.write(data)
        maps = {}
        for i, t in enumerate(tex):
            # цвет скана - PNG по 8 МБ; JPEG того же размера на глаз не отличить, а места в 5 раз меньше
            out = f"{base}_diff{'' if i == 0 else '_' + str(i + 1)}.jpg"
            with zf.open(t) as fh:
                Image.open(fh).convert("RGB").save(os.path.join(src, out), quality=92)
            maps[os.path.basename(t)] = out
        if mtl:
            with zf.open(mtl) as fh:
                m = fh.read().decode("utf-8", "replace")
            for old, new in maps.items():
                m = m.replace(old, new)
            with open(os.path.join(src, base + ".mtl"), "w", encoding="utf-8") as fh:
                fh.write(m)
    os.remove(zp)
    words = [w for w in re.split(r"[^a-z0-9]+", cand["name"].lower()) if len(w) > 2]
    meta = {
        "source": NAMES["gso"],
        "url": f"https://app.gazebosim.org/GoogleResearch/fuel/models/{q}",
        "authors": ["Google"],
        "tags": ["scan", "google scanned objects"] + words[:6],
        "categories": ["scan"],
        "description": "Скан настоящей вещи (Google Scanned Objects): сетка и цвет с фотографий.",
    }
    return meta, {"src": os.path.join(src, base + ".obj"), "up": "Z"}, None


# ---------------------------------------------------------------- модели: Smithsonian 3D
SI_SKIP_TITLE = re.compile(
    r"(^:|floor\b|nebula|supernova|remnant|\btau\b|scorpii|^sco\b|^vela$|^ic \d|^v\d+|cad model|detail view)",
    re.I,
)
SCI = re.compile(r"^[A-Z][a-z]+ (\(?[A-Z]?[a-z]+\)? )?[a-z.]+(\b|:)")
BONES = re.compile(
    r":\s*(mt\d|mc\d|cuneiform|cuboid|navicular|talus|calcaneus|fibula|tibia|ulna|radius|humerus|femur|"
    r"patella|trapezium|trapezoid|capitate|hamate|lunate|scaphoid|pisiform|triquetrum|vertebra|rib|clavicle|"
    r"scapula|pelvis|sacrum|phalanx|tooth|teeth|basihyal|limb|fragment)",
    re.I,
)


def si_list(fresh=False):
    """Все glb Smithsonian 3D, по пакету (модели): {пакет: {title, files: [(uri, quality, usage)]}}."""

    def build():
        rows, start = [], 0
        while True:
            d = U.get_json(f"{SI_API}?file_type=glb&start={start}&rows=1000")
            rows += d.get("rows", [])
            start += 1000
            if start >= d.get("rowCount", 0) or not d.get("rows"):
                break
        out = {}
        for r in rows:
            c = r.get("content") or {}
            p = out.setdefault(c.get("model_url", ""), {"title": (r.get("title") or "").strip(), "files": []})
            p["files"].append([c.get("uri", ""), c.get("quality", ""), c.get("usage", "")])
        return out

    return cached("si", build, fresh=fresh)


def si_url(uri):
    """У части записей ссылка склеена из двух: «.../3d_package:X/https://cdn.3d-api.si.edu/.../файл».
    Тот же файл отдаёт и сам пакет - а у cdn неполная цепочка сертификатов (Python её не принимает)."""
    i = uri.find("https://", 8)
    return uri[:i] + uri.rsplit("/", 1)[-1] if i > 0 else uri


def si_pick(files):
    """Файлы для скачивания: «Medium» для веба (текстуры 2048, ~150 тыс. треугольников на часть) - ссылки
    Download3D у Smithsonian часто битые. Большие предметы разбиты на части (самолёт братьев Райт - двигатель,
    крылья, остальное) - берутся все части одного качества. Сжатие Draco снимет Blender. -> [ссылки]."""
    for want in ("Medium", "High", "Low"):
        got = [
            si_url(u) for u, quality, usage in files if usage == "Web3D" and quality == want and "/resources/" not in u
        ]
        if got:
            return sorted(set(got))
    return []


def si_wanted(title):
    """Брать ли модель: предметы культуры - да; научные образцы (кости приматов, сотни ракушек одного рода) -
    только целые и по одному на род, кроме отдельных костей."""
    if not title or SI_SKIP_TITLE.search(title):
        return False, None
    if SCI.match(title) and not re.search(r"\b(of|the|and|for|with|from|in)\b", title):
        if BONES.search(title):
            return False, None
        part = title.split(":", 1)[1].strip().lower() if ":" in title else ""
        if part and not re.search(r"cranium|skull|bloom|shell", part):
            return False, None
        return True, title.split()[0]  # род - не больше одного
    return True, None


def si_candidates(have=()):
    out, genera = [], set()
    for pkg, p in sorted(si_list().items(), key=lambda kv: kv[1]["title"]):
        ok, genus = si_wanted(p["title"])
        if not ok:
            continue
        if genus:
            if genus in genera:
                continue
            genera.add(genus)
        uris = si_pick(p["files"])
        if not uris or len(uris) > 12:  # здание из десятков частей - не предмет
            continue
        aid = "si-" + pkg.split(":")[-1]
        if aid in have:
            continue
        title = re.sub(r"<[^>]+>", "", p["title"])
        out.append({"src": "si", "id": aid, "name": title[:90], "info": {"package": pkg, "uris": uris, "title": title}})
    return out


def fetch_si(cand, dst, progress, stop):
    info = cand["info"]
    src = os.path.join(dst, "_src")
    files = []
    for i, uri in enumerate(info["uris"]):
        f = os.path.join(src, f"part{i}.glb")
        U.download(
            quote(uri),
            f,
            progress=_bytes(progress, 0.7 * i / len(info["uris"]), 0.7 / len(info["uris"]), cand),
            stop=stop,
        )
        files.append(f)
    words = [w for w in re.split(r"[^a-z0-9]+", info["title"].lower()) if len(w) > 2]
    meta = {
        "source": NAMES["si"],
        "url": "https://3d.si.edu/object/" + info["package"],
        "authors": ["Smithsonian Institution"],
        "tags": ["scan", "museum", "smithsonian"] + words[:6],
        "categories": ["museum"],
        "description": "Скан музейного предмета (Smithsonian 3D Digitization).",
    }
    return meta, {"src": files}, "view"  # Draco - просмотровую копию пишет Blender


# ---------------------------------------------------------------- модели: glTF Sample Assets
KH_SKIP = {"USDShaderBallForGltf", "PotOfCoalsAnimationPointer", "SheenCloth"}  # шар-образец, повтор, кусок ткани


def kh_list(fresh=False):
    def build():
        idx = U.get_json(f"{KH_RAW}/model-index.json")
        out = []
        for m in idx:
            if "showcase" not in m.get("tags", []) or m["name"] in KH_SKIP:
                continue
            try:
                meta = U.get_json(f"{KH_RAW}/{m['name']}/metadata.json")
            except Exception:
                meta = {}
            out.append(
                {
                    "name": m["name"],
                    "label": m.get("label") or m["name"],
                    "variants": m.get("variants", {}),
                    "legal": meta.get("legal", []),
                    "summary": meta.get("summary", ""),
                }
            )
        return out

    return cached("khronos", build, fresh=fresh)


def kh_license(legal):
    """Лицензия модели Khronos строкой: CC0 - как у остальных; иначе с авторами (их надо указать)."""
    lic = sorted({x.get("spdx") or x.get("license", "") for x in legal if x.get("license") or x.get("spdx")})
    who = sorted({x.get("artist") or x.get("owner") or "" for x in legal} - {""})
    if lic and all(x.startswith("CC0") for x in lic):
        return U.LICENSE, who
    text = ", ".join(lic) or "см. страницу модели"
    return f"{text} - смотрите условия; автор: {', '.join(who) or 'Khronos Group'}", who


def kh_candidates(have=()):
    out = []
    for m in kh_list():
        aid = "khronos-" + m["name"]
        if aid in have:
            continue
        if not ({"glTF-Binary", "glTF"} & set(m["variants"])):
            continue
        out.append({"src": "khronos", "id": aid, "name": m["label"], "info": m})
    return out


def fetch_khronos(cand, dst, progress, stop):
    m = cand["info"]
    src = os.path.join(dst, "_src")
    if "glTF-Binary" in m["variants"]:
        f = os.path.join(src, "model.glb")
        url = f"{KH_RAW}/{m['name']}/glTF-Binary/{m['variants']['glTF-Binary']}"
        U.download(quote(url), f, progress=_bytes(progress, 0.0, 0.7, cand), stop=stop)
        view = "copy"
    else:  # только .gltf с отдельными файлами: забрать всё, на что он ссылается
        base_url = f"{KH_RAW}/{m['name']}/glTF/"
        f = os.path.join(src, m["variants"]["glTF"])
        U.download(quote(base_url + m["variants"]["glTF"]), f, stop=stop)
        with open(f, encoding="utf-8") as fh:
            g = json.load(fh)
        uris = [x.get("uri") for x in g.get("buffers", []) + g.get("images", []) if x.get("uri")]
        for i, u in enumerate(uris):
            if u.startswith("data:"):
                continue
            U.download(quote(base_url + u), U.inside(src, urllib.parse.unquote(u)), stop=stop)
            if progress:
                progress(0.7 * (i + 1) / len(uris), cand["name"])
        view = "view"
    lic, who = kh_license(m.get("legal", []))
    words = [w for w in re.split(r"[^a-z0-9]+", m["label"].lower()) if len(w) > 2]
    meta = {
        "source": NAMES["khronos"],
        "url": f"https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/{m['name']}",
        "authors": who or ["Khronos Group"],
        "tags": ["pbr", "khronos", "showcase"] + words,
        "categories": ["showcase"],
        "description": (m.get("summary") or "Эталонная PBR-модель Khronos.")[:300],
        "license": lic,
    }
    return meta, {"src": f}, view


# ---------------------------------------------------------------- модели: NASA
def nasa_list(fresh=False):
    """Модели репозитория NASA 3D Resources: [{folder, glb, png}] - один glb на папку."""

    def build():
        tree = U.get_json(f"https://api.github.com/repos/{NASA_REPO}/git/trees/master?recursive=1")["tree"]
        by = {}
        for x in tree:
            p = x["path"].split("/")
            if p[0] != "3D Models" or len(p) < 3 or x["type"] != "blob":
                continue
            d = by.setdefault(p[1], {"folder": p[1], "glb": None, "png": None, "size": 0})
            low = p[-1].lower()
            if low.endswith(".glb") and (d["glb"] is None or x.get("size", 0) > d["size"]):
                d["glb"], d["size"] = x["path"], x.get("size", 0)
            elif low.endswith(".png") and d["png"] is None:
                d["png"] = x["path"]
        return [d for d in by.values() if d["glb"]]

    return cached("nasa", build, fresh=fresh)


def nasa_candidates(have=()):
    out = []
    for d in sorted(nasa_list(), key=lambda d: d["folder"]):
        aid = "nasa-" + re.sub(r"[^a-z0-9]+", "-", d["folder"].lower()).strip("-")
        if aid in have:
            continue
        thumb = quote(NASA_RAW + d["png"]) if d.get("png") else ""
        out.append({"src": "nasa", "id": aid, "name": d["folder"], "info": d, "thumb": thumb})
    return out


def fetch_nasa(cand, dst, progress, stop):
    d = cand["info"]
    f = os.path.join(dst, "_src", "model.glb")
    U.download(quote(NASA_RAW + d["glb"]), f, d.get("size", 0), progress=_bytes(progress, 0.0, 0.7, cand), stop=stop)
    words = [w for w in re.split(r"[^a-z0-9]+", d["folder"].lower()) if len(w) > 2]
    meta = {
        "source": NAMES["nasa"],
        "url": f"https://github.com/{NASA_REPO}/tree/master/" + quote("3D Models/" + d["folder"]),
        "authors": ["NASA"],
        "tags": ["nasa", "space", "spacecraft"] + words,
        "categories": ["sci-fi", "space"],
        "description": "Модель NASA (3D Resources): корабль, спутник или телескоп.",
    }
    return meta, {"src": f}, "copy"


# ---------------------------------------------------------------- общее для моделей
FETCH = {"gso": fetch_gso, "si": fetch_si, "khronos": fetch_khronos, "nasa": fetch_nasa}
LIST = {"gso": gso_candidates, "si": si_candidates, "khronos": kh_candidates, "nasa": nasa_candidates}


def _base(name):
    """Имя файлов модели: латиница, цифры, подчёркивания (Unreal не любит пробелы и скобки в именах)."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return (s[:60].rstrip("_") or "model") if s else "model"


def _bytes(progress, start, span, cand):
    if not progress:
        return None
    return lambda got: progress(start + span * min(1.0, got / 20e6), cand["name"])


def needs_rewrite(glb):
    """glb, который 3D-окно не откроет как есть: сжатие Draco или meshopt, картинки webp (у NASA бывает всё)."""
    import struct

    try:
        with open(glb, "rb") as fh:
            head = fh.read(20)
            n = struct.unpack("<I", head[12:16])[0]
            j = json.loads(fh.read(n))
    except (OSError, ValueError, struct.error):
        return True
    used = set(j.get("extensionsUsed", [])) | set(j.get("extensionsRequired", []))
    return bool(
        used & {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "EXT_texture_webp", "KHR_texture_basisu"}
    )


def candidates(src, have=()):
    return LIST[src](set(have))


def fetch(cand, dst, progress=None, stop=None):
    """Скачать модель источника в dst (папка .part) и перевести в FBX. -> meta для asset.json."""
    meta, job, view = FETCH[cand["src"]](cand, dst, progress, stop)
    base = _base(cand["name"])
    fbx = os.path.join(dst, base + ".fbx")
    job["fbx"] = fbx
    keep = None
    if view == "copy" and needs_rewrite(job["src"]):
        view = "view"
    if view == "view":  # Draco или .gltf с файлами - Blender пишет glb заново
        job["view"] = os.path.join(dst, base + "_view.glb")
    elif view == "copy":  # обычный glb - он и есть просмотровая копия, PBR без потерь
        keep = os.path.join(dst, base + "_view.glb")
    if progress:
        progress(0.75, "перевод в FBX (Blender)")
    from library import blender_convert

    res = blender_convert.convert([job])[0]
    if not res.get("ok"):
        raise OSError("Blender: " + res.get("error", "").strip().splitlines()[-1][:200])
    if keep:
        os.replace(job["src"], keep)
    shutil.rmtree(os.path.join(dst, "_src"), ignore_errors=True)
    meta["main"] = [base + ".fbx"]
    if keep or job.get("view"):
        meta["view"] = base + "_view.glb"
    if res.get("tris"):
        meta["polycount"] = res["tris"]
    meta.setdefault("license", LICENSES.get(cand["src"], U.LICENSE))
    meta["howto"] = HOWTO
    return meta


def model_dedupe(cands, log=print):
    """Повторы среди моделей с миниатюрами на сайте (сканы Google, NASA): одна вещь под двумя именами.
    Варианты A/B/C у NASA и цвета одной кроссовки - разные на вид, они остаются."""
    with_thumb = [c for c in cands if c.get("thumb")]
    if not with_thumb:
        return cands, []
    sigs = tex_sigs(with_thumb, [], log)
    keep, dropped, seen = [], [], []
    for c in cands:
        s = sigs.get(f"{c['src']}:{c['id']}")
        twin = next((n for t, n in seen if same_tex(s, t, corr=0.9, color=8.0)), None) if s else None
        if twin:
            dropped.append((c["name"], twin))
            continue
        keep.append(c)
        if s:
            seen.append((s, c["name"]))
    return keep, dropped


# ---------------------------------------------------------------- пачкой
def plan(what, log=print):
    """Что скачать: what - tex | gso | si | khronos | nasa. -> ([(кандидат, вид, тема)], [повторы])."""
    have = U.have_ids()
    if what == "tex":
        cands = tex_candidates(have)
        mine = [a for a in U.assets() if a.get("kind") == "tex"]
        sigs = tex_sigs(cands, mine, log)
        cands, dropped = dedupe(cands, sigs, mine)
        return [(c, "tex", c["theme"]) for c in cands], dropped
    cands = candidates(what, have)
    cands, dropped = model_dedupe(cands, log)
    return [(c, "model", THEME[what]) for c in cands], dropped


def unique_names(cands):
    """Одинаковые названия у разных моделей («Abraham Lincoln», «TABLEWARE SET») -> «Имя 2», «Имя 3».
    Папка ассета - по названию: при загрузке в несколько потоков два ассета писали бы в одну папку .part."""
    seen = {}
    for c in cands:
        key = c["name"].strip().lower()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            c["name"] = f"{c['name']} {seen[key]}"


def run(what, workers=4, res="2k", log=print, stop=None, limit=None):
    """Скачать всё по плану. Ошибка одного ассета не останавливает остальные. -> (скачано, ошибки)."""
    todo, dropped = plan(what, log)
    if dropped:
        log(f"Повторы не берутся: {len(dropped)}")
        for name, twin in dropped[:15]:
            log(f"  = {name} ~ {twin}")
    unique_names(c for c, _k, _t in todo)
    if limit:
        todo = todo[:limit]
    log(f"Скачать: {len(todo)}")
    ok, errors, n = [], [], [0]
    stop = stop or threading.Event()

    def one(item):
        c, kind, theme = item
        if stop.is_set():
            return
        try:
            U.fetch(c, kind, theme, res, stop=stop)
            ok.append(c["id"])
            tag = "+"
        except InterruptedError:
            return
        except Exception as e:
            errors.append((c["name"], str(e)[:200]))
            tag = "!"
        with _lock:
            n[0] += 1
            if tag == "!" or n[0] % 25 == 0:
                log(f"  {n[0]}/{len(todo)} {tag} {c['name']}" + (f": {errors[-1][1]}" if tag == "!" else ""))

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))
    if what == "tex" and ok:
        # проверка по самим картам цвета: убрать только что скачанные повторы (старые ассеты не трогать)
        fresh = set(ok)
        for g in tex_duplicates():
            keep = g[0]
            for a in g[1:]:
                if a.get("id") in fresh and a.get("dir") != keep.get("dir"):
                    shutil.rmtree(a["dir"], ignore_errors=True)
                    ok.remove(a["id"])
                    log(f"  = повтор убран: {a.get('name')} ~ {keep.get('name')}")
    return ok, errors
