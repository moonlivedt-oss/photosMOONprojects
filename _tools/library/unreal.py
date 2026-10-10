"""Ассеты для Unreal Engine: PBR-текстуры, HDRI-небо (фоны и свет), 3D-модели, IES-профили света.
Скачиваются с Poly Haven и ambientCG (всё CC0 - можно в любые проекты, без указания автора)
в папку _Unreal: она начинается с «_», поэтому окно картинок, галерея и поиск дублей её не трогают.

Каждый ассет - папка <вид>/<тема>/<имя>/ с файлами, preview.webp и asset.json.
Без Qt: это зовут вкладка «Unreal» в окне и командная строка (cli.py unreal ...)."""

import hashlib
import html
import io
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
import zipfile

from PIL import Image

import imaging as K
from library.common import clean_name

ROOT = os.path.join(K.LIB, "_Unreal")
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_unreal_cache.json")
UA = "MoonImageLibrary/2.3 (personal asset library for learning Unreal Engine)"  # Poly Haven просит свой UA
PH_API = "https://api.polyhaven.com"
ACG_API = "https://ambientcg.com/api/v2/full_json"
LICENSE = "CC0 1.0 - общественное достояние: можно в любые проекты, указывать автора не нужно"

# вид -> (папка, подпись, тип в API Poly Haven)
KINDS = {
    "tex": ("Текстуры", "PBR-текстуры", "textures"),
    "hdri": ("Фоны HDRI", "Небо и фоны HDRI", "hdris"),
    "model": ("Модели", "3D-модели", "models"),
    "ies": ("Свет IES", "IES-профили света", None),
}
RES = ("1k", "2k", "4k")

# Темы: для каждого вида - слова, которые ищутся в категориях и метках Poly Haven;
# "acg" - запросы к ambientCG (там больше металла и плит - для sci-fi).
NOT_HOME = {
    "industrial",
    "weapons",
    "firearms",
    "ships",
    "rocks",
    "trees",
    "structures",
    "buildings",
    "ground cover",
    "grass",
    "machine",
}  # в «Дом» не попадают

THEMES = {
    "Лес и природа": {
        "tex": {"bark", "terrain", "forest", "moss", "leaves", "grass", "gravel", "mud"},
        "hdri": {"forest", "nature", "tree", "lake", "meadow", "field"},
        "model": {"trees", "plants", "rocks", "ground cover", "flowers", "grass", "collection: pine_forest"},
        "acg": ["Grass", "Moss", "Ground"],
    },
    "Город": {
        "tex": {"brick", "asphalt", "road", "concrete", "pavement", "street"},
        "hdri": {"urban", "city", "street", "town", "alley"},
        "model": {"buildings", "structures", "collection: hidden_alley", "street"},
        "acg": ["Asphalt", "Bricks", "PavingStones"],
    },
    "Интерьер": {
        "tex": {"floor", "tiles", "fabric", "plaster", "carpet", "leather", "wood"},
        "hdri": {"indoor", "room", "hall", "museum"},
        "model": {"furniture", "seating", "table", "shelves", "decorative", "office", "vases", "bed"},
        "acg": ["WoodFloor", "Tiles", "Fabric"],
        "no": {"outdoor", "terrain", "aerial", "nature"},
    },
    "Индустрия и sci-fi": {
        "tex": {"metal", "industrial", "rust", "steel", "corrugated"},
        "hdri": {"industrial", "warehouse", "workshop", "factory", "garage", "tunnel"},
        "model": {"industrial", "electronics", "tools", "appliances", "machine"},
        "acg": ["MetalPlates", "DiamondPlate", "SheetMetal", "CorrugatedSteel", "Metal"],
    },
    "Средневековье и фэнтези": {
        "tex": {"cobblestone", "raw wood", "roofing", "castle", "medieval", "stone wall", "rock"},
        "hdri": {"castle", "ruin", "church", "medieval", "countryside", "rural"},
        "model": {"weapons", "containers", "collection: smugglers_cove", "barrel", "chest", "medieval"},
        "acg": ["Bricks", "Planks", "Rock"],
    },
    "Пустыня и скалы": {
        "tex": {"sand", "sandstone", "rock", "cliff", "dry"},
        "hdri": {"desert", "arid", "rocky", "mountain", "canyon"},
        "model": {"rocks", "cliff", "boulder"},
        "acg": ["Rock", "Ground", "Sand"],
    },
    "Зима": {
        "tex": {"snow", "ice", "frozen"},
        "hdri": {"snow", "winter", "christmas", "frozen"},
        "model": {"snow", "winter", "christmas"},
        "acg": ["Snow", "Ice"],
    },
    "Ночь и закат": {
        "tex": set(),
        "hdri": {"night", "sunrise-sunset", "stars", "milky way", "moon"},
        "model": {"lighting", "lamp", "lantern"},
        "acg": [],
    },
    "Студия": {  # ровный свет для показа моделей
        "tex": set(),
        "hdri": {"studio", "softbox"},
        "model": set(),
        "acg": [],
    },
    # дом - только модели, по комнатам и назначению; что уже скачано в другой теме, второй раз не берётся
    "Дом - мебель": {
        "model": {"furniture", "seating", "table", "shelves", "bed", "sofa", "chair", "cabinet", "wardrobe", "desk"},
        "no": NOT_HOME,
    },
    "Дом - кухня и посуда": {
        "model": {"dishes", "food", "appliances", "kitchen", "cup", "plate", "bowl", "pot", "kettle", "bottle"},
        "no": NOT_HOME,
    },
    "Дом - декор": {
        "model": {
            "decorative",
            "vases",
            "wall decoration",
            "books",
            "instrument",
            "frame",
            "clock",
            "statue",
            "candle",
        },
        "no": NOT_HOME,
    },
    "Дом - свет и техника": {
        "model": {"lighting", "electronics", "office", "lamp", "tv", "radio", "computer"},
        "no": NOT_HOME,
    },
    "Дом - растения": {
        "model": {"potted plants", "succulent", "houseplant", "planter", "potted"},
        "no": NOT_HOME,
    },
    "Дом - мелочи": {
        "model": {"containers", "props", "tools", "box", "basket", "toy"},
        "no": NOT_HOME,
    },
    # дом - текстуры: полы, стены, плитка и камень, ткани и кожа (для обивки)
    "Дом - полы": {
        "tex": {"wood floor", "laminate", "parquet", "floor", "carpet", "planks"},
        "no": NOT_HOME | {"outdoor", "terrain", "aerial", "road", "asphalt", "gravel", "nature"},
        "acg": ["WoodFloor", "Carpet", "Cork", "Tatami", "Planks"],
        "acg_per": 12,
    },
    "Дом - стены": {
        "tex": {"plaster", "wallpaper", "painted", "plaster-concrete", "interior wall"},
        "no": {"outdoor", "terrain", "aerial", "road", "dirty", "facade"},
        "acg": ["Wallpaper", "PaintedPlaster", "Plaster", "PaintedWood", "OfficeCeiling"],
        "acg_per": 12,
    },
    "Дом - плитка и камень": {
        "tex": {"tiles", "marble", "terrazzo", "granite", "travertine", "onyx"},
        "no": {"outdoor", "terrain", "aerial", "road", "roofing"},
        "acg": ["Tiles", "Marble", "Terrazzo", "Travertine", "Onyx", "Granite"],
        "acg_per": 10,
    },
    "Дом - ткани и кожа": {
        "tex": {
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
            "crepe",
            "hessian",
            "woven",
            "stretchy",
        },
        "acg": ["Fabric", "Leather", "Wicker"],
        "acg_per": 16,
    },
    # Kenney: простые low-poly модели одним архивом - для черновой расстановки комнат
    "Дом - Kenney low-poly": {"kenney": ["furniture-kit"]},
    # Quaternius: low-poly с цветными материалами, тоже CC0; папки FBX на Google Drive
    "Дом - Quaternius low-poly": {"quaternius": ["ultimate-home-interior", "furniture", "ultimatefurniture"]},
    # другие наборы Kenney (CC0) - для уровней и прототипов; цвета в общей текстуре colormap.png
    "Лес и природа - Kenney low-poly": {
        "kenney": ["nature-kit", "survival-kit", "mini-forest"],
        "categories": ["nature"],
    },
    "Город - Kenney low-poly": {
        "kenney": [
            "city-kit-suburban",
            "city-kit-commercial",
            "city-kit-roads",
            "city-kit-industrial",
            "car-kit",
            "factory-kit",
            "retro-urban-kit",
            "modular-buildings",
            "mini-market",
            "train-kit",
            "watercraft-kit",
        ],
        "categories": ["buildings", "street"],
    },
    "Средневековье - Kenney low-poly": {
        "kenney": [
            "castle-kit",
            "fantasy-town-kit",
            "graveyard-kit",
            "mini-dungeon",
            "modular-dungeon-kit",
            "modular-cave-kit",
            "retro-fantasy-kit",
            "pirate-kit",
        ],
        "categories": ["medieval", "fantasy"],
    },
    "Космос - Kenney low-poly": {
        "kenney": ["space-kit", "space-station-kit", "modular-space-kit"],
        "categories": ["sci-fi", "space"],
    },
    # уровни начерно: серые блоки, платформы, гексы, трассы - для первых карт в Unreal
    "Прототипы и уровни - Kenney low-poly": {
        "kenney": ["prototype-kit", "platformer-kit", "tower-defense-kit", "hexagon-kit", "mini-arena", "racing-kit"],
        "categories": ["prototype", "level"],
    },
    "Персонажи - Kenney low-poly": {"kenney": ["mini-characters", "blocky-characters"], "categories": ["characters"]},
    "Еда - Kenney low-poly": {"kenney": ["food-kit"], "categories": ["food"]},
    # другие наборы Quaternius (CC0): папки FBX и OBJ находятся сами по странице набора (quaternius_folders)
    "Лес и природа - Quaternius low-poly": {
        "quaternius": ["ultimatenature", "simplenature", "survival"],
        "categories": ["nature"],
    },
    "Город - Quaternius low-poly": {
        "quaternius": ["cars", "buildings", "modularstreets", "publictransport"],
        "categories": ["buildings", "street"],
    },
    "Средневековье - Quaternius low-poly": {
        "quaternius": ["medievalvillage", "modularmedievalbuildings", "medievaldungeon", "modulardungeon", "piratekit"],
        "categories": ["medieval", "fantasy"],
    },
    "Космос - Quaternius low-poly": {
        "quaternius": ["ultimatespacekit", "ultimatemodularscifi", "spaceships"],
        "categories": ["sci-fi", "space"],
    },
    "Еда - Quaternius low-poly": {"quaternius": ["ultimatefood", "junkfood"], "categories": ["food"]},
    # KayKit (Kay Lousberg, CC0): официальные репозитории на GitHub, FBX + одна текстура-палитра на набор
    "Дом - KayKit low-poly": {"kaykit": ["KayKit-Furniture-Bits-1.0", "KayKit-Restaurant-Bits-1.0"]},
    "Средневековье - KayKit low-poly": {
        "kaykit": ["KayKit-Dungeon-Remastered-1.0", "KayKit-Medieval-Hexagon-Pack-1.0", "KayKit-Halloween-Bits-1.0"],
        "categories": ["medieval", "fantasy"],
    },
    "Город - KayKit low-poly": {"kaykit": ["KayKit-City-Builder-Bits-1.0"], "categories": ["buildings", "street"]},
    "Космос - KayKit low-poly": {"kaykit": ["KayKit-Space-Base-Bits-1.0"], "categories": ["sci-fi", "space"]},
    "Прототипы и уровни - KayKit low-poly": {
        "kaykit": ["KayKit-Prototype-Bits-1.0"],
        "categories": ["prototype", "level"],
    },
    "Персонажи - KayKit low-poly": {
        "kaykit": ["KayKit-Character-Pack-Adventures-1.0", "KayKit-Character-Pack-Skeletons-1.0"],
        "categories": ["characters", "rigged"],
    },
    "Животные - Quaternius low-poly": {
        "quaternius": ["ultimateanimatedanimals", "farmanimal"],
        "categories": ["animals", "rigged"],
    },
}

# куда в Unreal и как - подсказка в окне и в asset.json
HOWTO = {
    "tex": (
        "Перетащите файлы в Content Browser. Цвет (diff/Color) - sRGB; нормаль (nor_dx/NormalDX) - "
        "Compression: Normalmap; ARM, Roughness, AO, Displacement - галку sRGB снять. "
        "ARM: R = Ambient Occlusion, G = Roughness, B = Metallic - три канала в три входа материала."
    ),
    "hdri": (
        "Перетащите .hdr в Content Browser - станет Texture Cube. Небо: Place Actors -> HDRI Backdrop "
        "(плагин HDRI Backdrop) и выбрать куб; или Sky Light -> Source Type: SLS Specified Cubemap. "
        "Задний план без освещения - Sky Sphere с материалом из этой текстуры."
    ),
    "model": (
        "Перетащите .fbx в Content Browser, в окне импорта - Import Materials и Import Textures. "
        "Нормаль у FBX от Poly Haven в формате OpenGL: в текстуре нормали включить Flip Green Channel "
        "или взять готовую *_nor_dx_*.jpg из папки textures."
    ),
    "ies": (
        "Перетащите .ies в Content Browser - станет IES Texture. У Point Light или Spot Light: "
        "Light Profiles -> IES Texture. Галка Use IES Brightness берёт яркость из профиля."
    ),
}


KENNEY_HOWTO = (
    "Перетащите .fbx в Content Browser. Текстур нет - цвета в самой модели: в окне импорта оставьте "
    "Import Materials, в материале цвет берётся из Vertex Color. Если модель вышла крошечной - "
    "импортируйте заново с Import Uniform Scale 100 (Kenney меряет в метрах, Unreal - в сантиметрах)."
)


QUATERNIUS_HOWTO = (
    "Перетащите .fbx в Content Browser, в окне импорта оставьте Import Materials - цвета у Quaternius "
    "в материалах, текстур нет. Если модель вышла крошечной - Import Uniform Scale 100."
)


KAYKIT_HOWTO = (
    "Перетащите .fbx в Content Browser, в окне импорта - Import Materials и Import Textures: цвета берутся "
    "из одной картинки-палитры рядом с моделью (её можно перекрасить - поменяются все модели набора). "
    "Если модель вышла крошечной - Import Uniform Scale 100."
)
LOW_POLY = ("Kenney", "Quaternius", "KayKit")  # простые модели - отдельно от реалистичных


def howto(a):
    """Подсказка «как в Unreal» для ассета (у low-poly наборов своя: без PBR-текстур)."""
    if a.get("source") == "KayKit":
        return KAYKIT_HOWTO
    if a.get("source") == "Kenney":
        return KENNEY_HOWTO
    if a.get("source") == "Quaternius":
        return QUATERNIUS_HOWTO
    return a.get("howto") or HOWTO.get(a.get("kind"), "")


# ---------------------------------------------------------------- сеть
def get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(url):
    return json.loads(get(url).decode("utf-8"))


def download(url, dst, size=0, md5=None, progress=None, stop=None):
    """Файл по кускам во временный, потом на место. progress(скачано байт этого файла)."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + ".part"
    h = hashlib.md5()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as fh:
        got = 0
        while True:
            if stop is not None and stop.is_set():
                raise InterruptedError("остановлено")
            buf = r.read(256 * 1024)
            if not buf:
                break
            fh.write(buf)
            h.update(buf)
            got += len(buf)
            if progress:
                progress(got)
    if md5 and h.hexdigest() != md5:
        os.remove(part)
        raise OSError("файл пришёл с ошибкой (не сошлась контрольная сумма): " + os.path.basename(dst))
    os.replace(part, dst)
    return got


# ---------------------------------------------------------------- каталоги
def catalog(kind, fresh=False):
    """Все ассеты Poly Haven этого вида: {id: info}. Кэш на сутки в _unreal_cache.json."""
    try:
        with open(CACHE, encoding="utf-8") as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(kind)
    if hit and not fresh and time.time() - hit["t"] < 86400:
        return hit["data"]
    data = get_json(f"{PH_API}/assets?t={KINDS[kind][2]}")
    cache[kind] = {"t": time.time(), "data": data}
    K.write_atomic(CACHE, json.dumps(cache, ensure_ascii=False), "utf-8")
    return data


def words_of(info):
    out = {w.lower() for w in info.get("categories", []) + info.get("tags", [])}
    return out | {w.lower() for w in info.get("name", "").split()}


def candidates(kind, theme, have=()):
    """Подходящие теме ассеты, популярные первыми, без уже скачанных: [{src, id, name, info}]."""
    want = THEMES[theme].get(kind) or set()
    out = []
    if kind == "model" and THEMES[theme].get("quaternius"):
        cats = THEMES[theme].get("categories") or ["furniture"]
        return [
            c for pack in THEMES[theme]["quaternius"] for c in quaternius_candidates(pack, cats) if c["id"] not in have
        ]
    if kind == "model" and THEMES[theme].get("kaykit"):
        cats = THEMES[theme].get("categories") or ["furniture"]
        return [c for repo in THEMES[theme]["kaykit"] for c in kaykit_candidates(repo, cats) if c["id"] not in have]
    if kind == "model" and THEMES[theme].get("kenney"):
        cats = THEMES[theme].get("categories") or ["furniture"]
        return [c for pack in THEMES[theme]["kenney"] for c in kenney_candidates(pack, cats) if c["id"] not in have]
    if want:
        for aid, info in catalog(kind).items():
            if aid in have:
                continue
            w = words_of(info)
            hit = len(w & want)
            if hit and not (w & THEMES[theme].get("no", set())):
                out.append(
                    {
                        "src": "ph",
                        "id": aid,
                        "name": info.get("name", aid),
                        "info": info,
                        "score": hit * 1e6 + info.get("download_count", 0),
                    }
                )
    if kind == "tex":
        acg = THEMES[theme].get("acg") or []
        if acg:
            extra = acg_candidates(acg, have, THEMES[theme].get("acg_per"))
            no = THEMES[theme].get("no", set()) | {"roofing", "roof", "facade"}
            extra = [c for c in extra if not (set(c["name"].lower().split()) | set(c["info"].get("tags", []))) & no]
            # ambientCG - вперемешку с Poly Haven, чтобы тема не состояла из одного источника
            out.sort(key=lambda c: -c["score"])
            mixed = []
            for i in range(max(len(out), len(extra))):
                for lst in (out, extra):
                    if i < len(lst):
                        mixed.append(lst[i])
            return mixed
    out.sort(key=lambda c: -c["score"])
    return out


# ---------------------------------------------------------------- Kenney (наборы одним архивом)
PACKS = os.path.join(os.path.dirname(CACHE), "_unreal_packs")  # архивы наборов, чтобы не качать на каждую модель


def kenney_zip(pack):
    """Архив набора Kenney (CC0). Ссылка со страницы набора - в ней меняется хэш версии."""
    dst = os.path.join(PACKS, pack + ".zip")
    if not os.path.exists(dst):
        page = get(f"https://kenney.nl/assets/{pack}").decode("utf-8", "replace")
        m = re.search(r"https://kenney\.nl/media/pages/assets/" + re.escape(pack) + r"/[^'\"]+\.zip", page)
        if not m:
            raise OSError("на странице Kenney нет ссылки на архив: " + pack)
        download(m.group(0), dst)
    if not zipfile.is_zipfile(dst):  # оборванная загрузка или страница ошибки - не держать в кэше
        os.remove(dst)
        raise OSError("архив Kenney скачался не целиком: " + pack + " - попробуйте ещё раз")
    return dst


def pretty(name):
    """bedDouble -> Bed double; Bathroom_Mirror1 -> Bathroom mirror 1; bridge-draw -> Bridge draw."""
    name = re.sub(r"(?<=[A-Za-z])(?=[0-9])", " ", name)
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ").replace("-", " ").split()
    return " ".join(words).capitalize()


def kenney_candidates(pack, categories=("furniture",)):
    with zipfile.ZipFile(kenney_zip(pack)) as zf:
        names = zf.namelist()
    fbx = sorted(n for n in names if n.startswith("Models/FBX format/") and n.lower().endswith(".fbx"))
    out = []
    for n in fbx:
        base = os.path.splitext(os.path.basename(n))[0]
        out.append(
            {
                "src": "kenney",
                "id": f"kenney-{pack}-{base}",
                "name": pretty(base),
                "info": {},
                "pack": pack,
                "member": n,
                "base": base,
                "categories": list(categories),
                "score": 0,
            }
        )
    return out


def fetch_kenney(cand, dst):
    """FBX набора + общая текстура цветов (у новых наборов FBX ссылается на Textures/colormap.png -
    без неё модель белая) + превью (Isometric у старых наборов, Previews у новых)."""
    extra = []
    with zipfile.ZipFile(kenney_zip(cand["pack"])) as zf:
        names = set(zf.namelist())
        fn = cand["base"] + ".fbx"
        with zf.open(cand["member"]) as src, open(os.path.join(dst, fn), "wb") as out:
            shutil.copyfileobj(src, out)
        tex_dir = os.path.dirname(cand["member"]) + "/Textures/"
        for n in sorted(names):
            if n.startswith(tex_dir) and n.lower().endswith((".png", ".jpg")) and "/" not in n[len(tex_dir) :]:
                rel = "Textures/" + os.path.basename(n)
                os.makedirs(os.path.join(dst, "Textures"), exist_ok=True)
                with zf.open(n) as src, open(os.path.join(dst, *rel.split("/")), "wb") as out:
                    shutil.copyfileobj(src, out)
                extra.append(rel)
        shots = [f"Isometric/{cand['base']}_{side}.png" for side in ("SW", "SE", "NW", "NE")]
        for shot in shots + [f"Previews/{cand['base']}.png"]:
            if shot in names:
                data = zf.read(shot)
                if max(Image.open(io.BytesIO(data)).size) >= 200:  # Previews у новых наборов - 64x64:
                    save_preview(data, dst)  # такое превью нарисует 3D-сцена окна (cli unreal previews)
                break
    kit = cand["pack"].replace("-kit", "").replace("-", " ")
    meta = {
        "source": "Kenney",
        "url": f"https://kenney.nl/assets/{cand['pack']}",
        "authors": ["Kenney"],
        "tags": ["low-poly", "kenney", kit],
        "categories": cand.get("categories") or ["furniture"],
        "main": [fn],
        "description": "Простая low-poly модель"
        + (" с цветами в общей текстуре colormap.png" if extra else " с цветами в вершинах, без текстур")
        + " - для прототипов и черновой расстановки.",
    }
    if extra:
        meta["extra"] = extra  # не импортируются отдельно, но едут рядом с FBX
    return meta


# ---------------------------------------------------------------- Quaternius (папки на Google Drive)
QUATERNIUS = {  # набор -> (папка FBX на Google Drive, страница набора)
    "ultimate-home-interior": (
        "16dX_4YSXSS57z2FWD7IEZ54OOIXCkOlB",
        "https://quaternius.com/packs/ultimatehomeinterior.html",
    ),
    "furniture": ("1UyKRG28MrkjlmhI1-Ejr61JZnqP_mx2r", "https://quaternius.com/packs/furniture.html"),
}
QUATERNIUS_OBJ = {  # папки OBJ: в их .mtl настоящие цвета, которых нет в FBX
    "ultimate-home-interior": "1LQTY5A0u17mgjsJzDDbL7Nssx9SynaqJ",
    "furniture": "1gIr2uiSfni70C5toD6S_lwh3QXYiln00",
}
_mtl_index = {}


QFOLDERS = os.path.join(os.path.dirname(CACHE), "_unreal_quaternius.json")  # набор -> файлы FBX и .mtl
SKIP_DIRS = ("blend", "gltf", "textures", "obj")  # при поиске FBX - не туда


def drive_entries(folder_id):
    """Открытая папка Google Drive: [(имя, id, это папка)]."""
    page = get(f"https://drive.google.com/embeddedfolderview?id={folder_id}").decode("utf-8", "replace")
    return [
        (html.unescape(t), i, k == "drive/folders")
        for k, i, t in re.findall(
            r'<a href="https://drive\.google\.com/(file/d|drive/folders)/([^/?"]+)[^"]*"[^>]*>.*?'
            r'<div class="flip-entry-title">([^<]+)</div>',
            page,
            re.S,
        )
    ]


def _walk_drive(folder_id, want, skip, depth=3):
    """Файлы с окончанием want во вложенных папках (кроме skip): [(имя, id)]."""
    out = []
    for name, fid, is_dir in drive_entries(folder_id):
        if is_dir:
            if depth and not name.lower().startswith(skip):
                out += _walk_drive(fid, want, skip, depth - 1)
        elif name.lower().endswith(want):
            out.append((name, fid))
    return out


def quaternius_folders(pack):
    """Файлы набора Quaternius по его странице: {"page", "fbx": [(имя, id)], "mtl": {имя: id}}.
    Ищется один раз и запоминается в _unreal_quaternius.json (у Google Drive лимит запросов)."""
    try:
        with open(QFOLDERS, encoding="utf-8") as fh:
            known = json.load(fh)
    except (OSError, ValueError):
        known = {}
    if pack in known:
        return known[pack]
    page_url = f"https://quaternius.com/packs/{pack}.html"
    page = get(page_url).decode("utf-8", "replace")
    roots = list(dict.fromkeys(re.findall(r"drive\.google\.com/drive/folders/([\w-]+)", page)))
    if not roots:
        raise OSError(f"у набора Quaternius «{pack}» нет папки на Google Drive (он на itch.io)")
    fbx, mtl = [], {}
    for root in roots:
        fbx += _walk_drive(root, ".fbx", SKIP_DIRS)
        mtl.update({n[:-4]: i for n, i in _walk_drive(root, ".mtl", ("blend", "gltf", "textures", "fbx"))})
    info = {"page": page_url, "fbx": fbx, "mtl": mtl}
    known[pack] = info
    K.write_atomic(QFOLDERS, json.dumps(known, ensure_ascii=False), "utf-8")
    return info


def quaternius_mtl(pack, base):
    """Текст .mtl модели набора (или '')."""
    if pack not in _mtl_index:
        if pack in QUATERNIUS_OBJ:
            _mtl_index[pack] = {n[:-4]: fid for n, fid in drive_folder(QUATERNIUS_OBJ[pack]) if n.endswith(".mtl")}
        else:
            _mtl_index[pack] = quaternius_folders(pack)["mtl"]
    fid = _mtl_index[pack].get(base)
    if not fid:
        return ""
    url = f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"
    return get(url).decode("utf-8", "replace")


def drive_folder(folder_id):
    """Файлы открытой папки Google Drive без входа: [(имя, id файла)]."""
    page = get(f"https://drive.google.com/embeddedfolderview?id={folder_id}").decode("utf-8", "replace")
    out = []
    for m in re.finditer(
        r'<a href="https://drive\.google\.com/file/d/([^/"]+)/[^"]*"[^>]*>.*?'
        r'<div class="flip-entry-title">([^<]+)</div>',
        page,
        re.S,
    ):
        out.append((html.unescape(m.group(2)), m.group(1)))
    return out


def quaternius_page(pack):
    return QUATERNIUS[pack][1] if pack in QUATERNIUS else f"https://quaternius.com/packs/{pack}.html"


def quaternius_candidates(pack, categories=("furniture",)):
    files = drive_folder(QUATERNIUS[pack][0]) if pack in QUATERNIUS else quaternius_folders(pack)["fbx"]
    out = []
    for name, fid in files:
        if not name.lower().endswith(".fbx"):
            continue
        base = os.path.splitext(name)[0]
        out.append(
            {
                "src": "quaternius",
                "id": f"quaternius-{pack}-{base}",
                "name": pretty(base),
                "info": {},
                "pack": pack,
                "file_id": fid,
                "base": base,
                "categories": list(categories),
                "score": 0,
            }
        )
    return out


def fetch_quaternius(cand, dst, progress=None, stop=None):
    fn = cand["base"] + ".fbx"
    url = f"https://drive.usercontent.google.com/download?id={cand['file_id']}&export=download&confirm=t"
    run_files([(fn, {"url": url, "size": 0})], dst, progress, stop, 0, 0.95)
    with open(os.path.join(dst, fn), "rb") as fh:
        if fh.read(64).lstrip().startswith(b"<"):  # вместо файла пришла страница Google
            raise OSError("Google Drive не отдал файл (лимит скачиваний) - попробуйте позже")
    if os.path.getsize(os.path.join(dst, fn)) < 3000:  # в наборе бывают пустышки: один заголовок FBX
        raise OSError("в наборе пустой файл - пропущен")
    try:  # цвета материалов из .mtl - иначе модель серая
        from library import fbx_colors

        mtl = quaternius_mtl(cand["pack"], cand["base"])
        if not (mtl and fbx_colors.colorize(os.path.join(dst, fn), mtl)):
            fbx_colors.colorize_by_name(os.path.join(dst, fn))
    except Exception:
        pass
    return {
        "source": "Quaternius",
        "url": quaternius_page(cand["pack"]),
        "authors": ["Quaternius"],
        "tags": ["low-poly", "quaternius", cand["pack"]],
        "categories": cand.get("categories") or ["furniture"],
        "main": [fn],
        "description": "Low-poly модель с цветными материалами, без текстур. Превью нарисовано библиотекой.",
    }


# ---------------------------------------------------------------- KayKit (репозитории на GitHub)
KAYKIT_TREES = os.path.join(PACKS, "kaykit-trees.json")  # список файлов репозитория - один запрос к API


def kaykit_tree(repo):
    """Файлы репозитория KayKit: [путь]. API GitHub без входа - 60 запросов в час, поэтому запоминается."""
    try:
        with open(KAYKIT_TREES, encoding="utf-8") as fh:
            known = json.load(fh)
    except (OSError, ValueError):
        known = {}
    if repo not in known:
        data = get_json(f"https://api.github.com/repos/KayKit-Game-Assets/{repo}/git/trees/main?recursive=1")
        known[repo] = [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"]
        os.makedirs(PACKS, exist_ok=True)
        K.write_atomic(KAYKIT_TREES, json.dumps(known, ensure_ascii=False), "utf-8")
    return known[repo]


def kaykit_raw(repo, path):
    return f"https://raw.githubusercontent.com/KayKit-Game-Assets/{repo}/main/" + urllib.parse.quote(path)


def kaykit_candidates(repo, categories=("furniture",)):
    files = kaykit_tree(repo)
    fbx = sorted(f for f in files if f.lower().endswith(".fbx") and "/fbx/" in f.lower() and "(unity)" not in f.lower())
    pngs = [f for f in files if f.lower().endswith(".png")]
    # текстура-палитра: из папки самой модели, иначе из Assets/texture(s) - не превью набора и не копии для Unity
    shared = [f for f in pngs if os.path.basename(os.path.dirname(f)).lower() in ("texture", "textures")]
    out = []
    for f in fbx:
        here = [p for p in pngs if os.path.dirname(p) == os.path.dirname(f)]
        tex = here or shared
        base = os.path.splitext(os.path.basename(f))[0]
        sub = f.lower().split("/fbx/", 1)[1]
        out.append(
            {
                "src": "kaykit",
                "id": f"kaykit-{repo}-{os.path.splitext(sub)[0].replace('/', '-')}",
                "name": pretty(base),
                "info": {},
                "repo": repo,
                "path": f,
                "textures": tex,
                "base": base,
                "categories": list(categories),
                "score": 0,
            }
        )
    return out


def kaykit_file(repo, path):
    """Общий файл набора (текстура) - один раз на набор, дальше из кэша."""
    dst = os.path.join(PACKS, "kaykit", repo, *path.split("/"))
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        download(kaykit_raw(repo, path), dst)
    return dst


def fetch_kaykit(cand, dst):
    """FBX + текстура-палитра рядом с ним (FBX ссылается на неё по имени). Превью рисует окно."""
    fn = cand["base"] + ".fbx"
    download(kaykit_raw(cand["repo"], cand["path"]), os.path.join(dst, fn))
    with open(os.path.join(dst, fn), "rb") as fh:
        if not fh.read(20).startswith(b"Kaydara FBX"):
            raise OSError("GitHub отдал не FBX - попробуйте позже")
    extra = []
    for t in cand.get("textures", []):
        name = os.path.basename(t)
        if name not in extra:
            shutil.copy2(kaykit_file(cand["repo"], t), os.path.join(dst, name))
            extra.append(name)
    from library import unreal_local

    unreal_local.relink(os.path.join(dst, fn))  # путь к текстуре в FBX - с компьютера автора: на файл рядом
    title = cand["repo"].replace("KayKit-", "").replace("-1.0", "").replace("-", " ")
    meta = {
        "source": "KayKit",
        "url": f"https://github.com/KayKit-Game-Assets/{cand['repo']}",
        "authors": ["Kay Lousberg"],
        "tags": ["low-poly", "kaykit", title.lower()],
        "categories": cand.get("categories") or ["furniture"],
        "main": [fn],
        "description": f"Low-poly модель KayKit ({title}): цвета - в общей текстуре-палитре набора.",
    }
    if extra:
        meta["extra"] = extra
    return meta


def acg_candidates(queries, have=(), per=None):
    out, seen = [], set(have)
    per = per or max(4, 24 // max(1, len(queries)))
    for q in queries:
        url = f"{ACG_API}?type=Material&q={urllib.parse.quote(q)}&sort=Popular&limit={per}&include=downloadData,previewData,tagData"
        try:
            found = get_json(url).get("foundAssets", [])
        except Exception:
            continue
        for a in found:
            aid = a["assetId"]
            if aid in seen:
                continue
            seen.add(aid)
            out.append({"src": "acg", "id": aid, "name": a.get("displayName", aid), "info": a, "score": 0})
    # по очереди из каждого запроса - так и металл, и плиты
    return out


def folder_id(d):
    try:
        with open(os.path.join(d, "asset.json"), encoding="utf-8") as fh:
            return json.load(fh).get("id")
    except (OSError, ValueError):
        return None


def refetch(a, res, progress=None, stop=None):
    """Перекачать скачанный ассет в другом разрешении на то же место (метки и избранное - по id, не теряются)."""
    kind, src = a.get("kind"), a.get("source")
    if src == "Poly Haven":
        info = catalog(kind).get(a["id"])
        if info is None:
            raise OSError("на Poly Haven больше нет такого ассета")
        cand = {"src": "ph", "id": a["id"], "name": a["name"], "info": info}
    elif src == "ambientCG":
        found = get_json(f"{ACG_API}?id={urllib.parse.quote(a['id'])}&include=downloadData,previewData,tagData")
        if not found.get("foundAssets"):
            raise OSError("на ambientCG больше нет такого ассета")
        cand = {"src": "acg", "id": a["id"], "name": a["name"], "info": found["foundAssets"][0]}
    else:
        raise ValueError("у этого источника одно качество")
    return fetch(cand, kind, a.get("theme", "Разное"), res, progress, stop, dst=a["dir"], replace=True)


def can_refetch(a):
    return a.get("source") in ("Poly Haven", "ambientCG") and a.get("kind") in ("tex", "hdri", "model")


# Разделы «Дома» для левой панели: по назначению, а не по источнику. Порядок правил важен - первое
# совпадение выигрывает (настольная лампа - свет, а не стол; шкафчик в ванной - ванная).
HOME_SECTIONS = (
    ("Ванная", {"bathroom", "bathtub", "toilet", "shower", "washbasin"}),
    ("Свет", {"lamp", "lighting", "lightbulb", "chandelier", "candle", "lantern", "sconce", "light", "torch"}),
    ("Кухня и посуда", {"kitchen", "fridge", "stove", "oven", "toaster", "microwave", "blender", "hood"}),
    ("Шкафы и полки", {"cabinet", "nightstand", "wardrobe"}),  # cabinetBed у Kenney - тумбочка, не кровать
    ("Кровати", {"bed", "bunk", "crib", "mattress"}),
    ("Стулья и кресла", {"chair", "armchair", "stool", "bench", "pouf"}),
    ("Диваны", {"sofa", "couch", "loveseat", "ottoman"}),
    ("Столы", {"table", "desk"}),
    (
        "Шкафы и полки",
        {
            "cabinet",
            "wardrobe",
            "drawer",
            "dresser",
            "bookcase",
            "shelf",
            "shelves",
            "cupboard",
            "nightstand",
            "sideboard",
            "closet",
            "chest",
            "drawers",
        },
    ),
    (
        "Декор",
        {
            "decorative",
            "vases",
            "vase",
            "frame",
            "painting",
            "picture",
            "clock",
            "statue",
            "rug",
            "carpet",
            "curtain",
            "books",
            "book",
            "pillow",
            "wall decoration",
            "mirror",
            "sculpture",
            "bust",
            "trophy",
            "sword",  # старинное оружие в доме - на стене
            "katana",
            "saber",
            "mace",
            "shield",
            "estoc",
            "warhammer",
        },
    ),
    ("Растения", {"potted plants", "plant", "plants", "succulent", "planter", "cactus", "flowers"}),
    (
        "Кухня и посуда",
        {
            "dishes",
            "food",
            "cup",
            "mug",
            "plate",
            "bowl",
            "pot",
            "kettle",
            "bottle",
            "pan",
            "jar",
            "glass",
            "teapot",
            "fruit",
            "bread",
            "cutlery",
            "spoon",
            "fork",
            "knife",
        },
    ),
    (
        "Техника",
        {
            "electronics",
            "tv",
            "television",
            "computer",
            "laptop",
            "radio",
            "speaker",
            "appliances",
            "washer",
            "dryer",
            "monitor",
            "keyboard",
            "phone",
            "camera",
            "fan",
        },
    ),
    # что раньше падало в «Мелочи»: инструменты, хозяйство, спорт, одежда (декор с оружием - выше)
    (
        "Инструменты",
        {
            "hammer",
            "saw",
            "hacksaw",
            "screwdriver",
            "screwdrivers",
            "pliers",
            "drill",
            "axe",
            "hatchet",
            "spade",
            "shovel",
            "pickaxe",
            "picke",
            "pump",
            "wrench",
            "ladder",
            "toolbox",
            "tools",
            "plane",
            "chisel",
        },
    ),
    (
        "Хозяйство и уборка",
        {
            "trashcan",
            "trashbag",
            "trash",
            "broom",
            "dustpan",
            "bucket",
            "mop",
            "jerrycan",
            "crate",
            "container",
            "box",
            "bags",
            "compost",
            "thermos",
            "can",
            "mousetrap",
            "watering",
            "cleaner",
            "medical",
            "basket",
        },
    ),
    (
        "Спорт и хобби",
        {
            "football",
            "baseball",
            "bat",
            "ball",
            "ukulele",
            "guitar",
            "piano",
            "binoculars",
            "chess",
            "dartboard",
            "bear",
            "toy",
            "skateboard",
            "bicycle",
            "postcard",
            "dumbbell",
            "kettlebell",
            "spinning",
        },
    ),
    (
        "Одежда и аксессуары",
        {
            "hat",
            "boots",
            "gloves",
            "spectacles",
            "glasses",
            "coat",
            "jacket",
            "watch",
            "lighter",
            "cigarette",
            "backpack",
            "umbrella",
            "shoes",
            "sneakers",
            "scarf",
        },
    ),
    ("Стены, двери, окна", {"wall", "floor", "doorway", "door", "window", "stairs", "paneling", "ceiling"}),
    ("Стулья и кресла", {"seating", "seat"}),
)
HOME_OTHER = "Мелочи"
# дописано после Quaternius: у него свои имена (Bookshelf, Houseplant, Curtains, Column)
for _sec, _keys in HOME_SECTIONS:
    _keys |= {
        "Шкафы и полки": {"bookshelf"},
        "Декор": {"curtains", "fireplace"},
        "Растения": {"houseplant"},
        "Стены, двери, окна": {"column", "columns"},
    }.get(_sec, set())
HOME_ORDER = (
    "Кровати",
    "Диваны",
    "Стулья и кресла",
    "Столы",
    "Шкафы и полки",
    "Кухня и посуда",
    "Ванная",
    "Свет",
    "Техника",
    "Декор",
    "Растения",
    "Инструменты",
    "Хозяйство и уборка",
    "Спорт и хобби",
    "Одежда и аксессуары",
    "Стены, двери, окна",
    HOME_OTHER,
)


def name_words(a):
    """Слова имени: bedDouble -> bed, double; Wooden_Chair-01 -> wooden, chair, 01."""
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", a.get("name", ""))
    words = [w for w in re.split(r"[^a-zа-яё0-9]+", name.lower()) if w]
    return set(words) | {x + y for x, y in zip(words, words[1:])}  # Night stand -> nightstand


def home_section(a):
    """Раздел «Дома»: сначала по имени модели, потом по меткам и категориям (метки бывают случайными:
    у кресла метка sofa, у вазы - pot)."""
    for words in (name_words(a), {w.lower() for w in a.get("tags", []) + a.get("categories", [])}):
        for sec, keys in HOME_SECTIONS:
            if words & keys:
                return sec
    return HOME_OTHER


def has_kind(theme, kind):
    """Есть ли у темы ассеты этого вида (у наборов Kenney и Quaternius - только модели)."""
    spec = THEMES.get(theme, {})
    if kind == "ies":
        return True
    if kind == "model" and (spec.get("kenney") or spec.get("quaternius") or spec.get("kaykit")):
        return True
    return bool(spec.get(kind) or (kind == "tex" and spec.get("acg")))


def guess_theme(kind, info):
    """Тема для ассета из каталога: где больше всего совпадений категорий и меток, иначе «Разное»."""
    w = words_of(info)
    best, score = "Разное", 0
    for th, spec in THEMES.items():
        want = spec.get(kind) or set()
        hit = len(w & want)
        if hit > score and not (w & spec.get("no", set())):
            best, score = th, hit
    return best


def browse(kind):
    """Весь каталог Poly Haven этого вида для окна «Каталог»: [{id, name, info, thumb}], популярные первыми."""
    out = [
        {
            "src": "ph",
            "id": aid,
            "name": info.get("name", aid),
            "info": info,
            "thumb": info.get("thumbnail_url")
            or f"https://cdn.polyhaven.com/asset_img/thumbs/{aid}.png?width=256&height=256",
        }
        for aid, info in catalog(kind).items()
    ]
    return sorted(out, key=lambda c: -c["info"].get("download_count", 0))


# ---------------------------------------------------------------- что уже есть
_parsed = {}  # папка -> (время и размер asset.json, разобранный dict): повторное чтение не разбирает JSON


def assets(root=ROOT):
    """Все скачанные ассеты: [dict из asset.json + dir]. Служебные поля без записи в файл:
    _t - время asset.json (когда добавлен), _pt - время preview.webp (0 - превью нет).
    Обход через os.scandir: время файлов приходит вместе со списком папки, без отдельного запроса на файл."""
    out = []
    if not os.path.isdir(root):
        return out

    def walk(d):
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            return
        files = {e.name: e for e in entries if not e.is_dir()}
        meta = files.get("asset.json")
        if meta is not None:
            try:
                st = meta.stat()
                stamp = (st.st_mtime_ns, st.st_size)
                hit = _parsed.get(d)
                if hit is None or hit[0] != stamp:
                    with open(meta.path, encoding="utf-8") as fh:
                        hit = _parsed[d] = (stamp, json.load(fh))
            except (OSError, ValueError):
                return
            a = dict(hit[1])
            a["dir"], a["_t"] = d, st.st_mtime
            prev = files.get("preview.webp")
            try:
                a["_pt"] = prev.stat().st_mtime if prev is not None else 0
            except OSError:
                a["_pt"] = 0
            if "preview.none" in files:  # превью не рисуется - окно не пробует снова (ui/render_previews.py)
                a["_np"] = True
            out.append(a)
            return
        for e in sorted((e for e in entries if e.is_dir()), key=lambda e: e.name):
            if not e.name.endswith((".part", ".old")):  # недокачанное и заменённое
                walk(e.path)

    walk(root)
    return out


def have_ids(root=ROOT):
    return {a.get("id") for a in assets(root)}


def folder_size(d):
    return sum(os.path.getsize(os.path.join(p, f)) for p, _, fs in os.walk(d) for f in fs)


# ---------------------------------------------------------------- скачать один
def fetch(cand, kind, theme, res="2k", progress=None, stop=None, dst=None, replace=False):
    """Скачать ассет в _Unreal/<вид>/<тема>/<имя>. progress(доля 0..1, подпись). -> папка.
    replace - перекачать поверх (другое разрешение): старая папка заменяется, только когда новая готова."""
    if dst is None:
        base = os.path.join(ROOT, KINDS[kind][0], clean_name(theme), clean_name(cand["name"]))
        dst, n = base, 2
        # то же имя у другого ассета (у Quaternius в двух наборах есть «Stool», «Chair») - своя папка с номером
        while os.path.exists(os.path.join(dst, "asset.json")) and folder_id(dst) != cand["id"]:
            dst, n = f"{base} {n}", n + 1
    if os.path.exists(os.path.join(dst, "asset.json")) and not replace:
        return dst
    tmp = dst + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        if cand["src"] == "ph":
            meta = fetch_ph(cand, kind, res, tmp, progress, stop)
        elif cand["src"] == "kenney":
            meta = fetch_kenney(cand, tmp)
        elif cand["src"] == "quaternius":
            meta = fetch_quaternius(cand, tmp, progress, stop)
        elif cand["src"] == "kaykit":
            meta = fetch_kaykit(cand, tmp)
        elif cand["src"] == "local":  # из скачанного вручную архива (library/unreal_local.py)
            from library import unreal_local

            meta = unreal_local.fetch_local(cand, tmp)
        else:
            meta = fetch_acg(cand, res, tmp, progress, stop)
        meta.update(
            {
                "id": cand["id"],
                "name": cand["name"],
                "kind": kind,
                "theme": theme,
                "res": res,
                "license": LICENSE,
                "added": time.strftime("%Y-%m-%d"),
                "howto": HOWTO[kind],
            }
        )
        if cand["src"] in ("kenney", "quaternius", "kaykit", "local"):
            meta["res"] = ""  # у Kenney нет текстур - разрешения тоже
        lost = [m for m in meta.get("main", []) if not os.path.exists(os.path.join(tmp, *m.split("/")))]
        if lost:  # ассет без своих файлов не сохраняем - пусть лучше будет ошибка и повтор
            raise OSError("не скачались: " + ", ".join(lost[:3]))
        meta["size"] = folder_size(tmp)
        K.write_atomic(os.path.join(tmp, "asset.json"), json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
        put_in_place(tmp, dst)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return dst


def put_in_place(tmp, dst):
    """Готовую папку - на место dst. Старая (перекачка) сначала отодвигается и стирается только после
    замены: если её файл занят (открыт в 3D-просмотре), старый ассет остаётся целым, а не наполовину стёртым."""
    old = None
    if os.path.exists(dst):
        old = dst + ".old"
        shutil.rmtree(old, ignore_errors=True)
        os.replace(dst, old)
    try:
        os.replace(tmp, dst)
    except BaseException:
        if old:
            os.replace(old, dst)
        raise
    if old:
        shutil.rmtree(old, ignore_errors=True)


def pick(fmt_map, prefer):
    for f in prefer:
        if f in fmt_map:
            return fmt_map[f]
    return None


def save_preview(data, dst, side=512):
    im = Image.open(io.BytesIO(data))
    im.load()
    im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
    im.thumbnail((side, side), Image.Resampling.LANCZOS)
    im.save(os.path.join(dst, "preview.webp"), quality=88)


def inside(root, rel):
    """root/rel, но не выше root: имена файлов приходят с сервера (include у FBX, имена на Google Drive)."""
    parts = [x for x in rel.replace("\\", "/").split("/") if x not in ("", ".")]
    if not parts or ".." in parts or rel.startswith(("/", "\\")) or ":" in rel:
        raise OSError("подозрительное имя файла от сервера: " + rel)
    return os.path.join(root, *parts)


def run_files(jobs, dst, progress, stop, start=0.0, span=1.0):
    """jobs = [(относительный путь, {url,size,md5})] - скачать подряд, общий ход в progress."""
    total = sum(j[1].get("size", 0) for j in jobs) or 1
    done = 0
    for rel, f in jobs:
        name = os.path.basename(rel)

        def tick(got, base=done, name=name):
            if progress:
                progress(start + span * (base + got) / total, name)

        download(f["url"], inside(dst, rel), f.get("size", 0), f.get("md5"), tick, stop)
        done += f.get("size", 0)


def fetch_ph(cand, kind, res, dst, progress, stop):
    aid, info = cand["id"], cand["info"]
    files = get_json(f"{PH_API}/files/{aid}")
    main, jobs = [], []
    if kind == "tex":
        for key in ("Diffuse", "nor_dx", "arm", "Displacement"):
            f = pick(files.get(key, {}).get(res) or files.get(key, {}).get("1k", {}), ("jpg", "png"))
            if f:
                rel = os.path.basename(urllib.parse.urlparse(f["url"]).path)
                jobs.append((rel, f))
                main.append(rel)
    elif kind == "hdri":
        f = pick(files["hdri"].get(res) or files["hdri"]["1k"], ("hdr", "exr"))
        rel = os.path.basename(urllib.parse.urlparse(f["url"]).path)
        jobs.append((rel, f))
        main.append(rel)
    elif kind == "model":
        fb = files["fbx"].get(res) or files["fbx"]["1k"]
        f = fb["fbx"]
        rel = os.path.basename(urllib.parse.urlparse(f["url"]).path)
        jobs.append((rel, f))
        main.append(rel)
        for inc, g in f.get("include", {}).items():
            jobs.append((inc, g))
        # нормаль для DirectX (как ждёт Unreal) - рядом с текстурами FBX
        nd = pick(files.get("nor_dx", {}).get(res) or files.get("nor_dx", {}).get("1k", {}), ("jpg", "png"))
        if nd:
            jobs.append(("textures/" + os.path.basename(urllib.parse.urlparse(nd["url"]).path), nd))
    run_files(jobs, dst, progress, stop, 0.0, 0.92)
    if progress:
        progress(0.95, "миниатюра")
    if kind == "hdri":
        tm = files.get("tonemapped", {}).get("url")
        prev = get(tm) if tm else None
        if prev:
            save_preview(prev, dst, 768)
    else:
        save_preview(get(f"https://cdn.polyhaven.com/asset_img/thumbs/{aid}.png?width=512&height=512"), dst)
    meta = {
        "source": "Poly Haven",
        "url": f"https://polyhaven.com/a/{aid}",
        "authors": list(info.get("authors", {})),
        "tags": info.get("tags", []),
        "categories": info.get("categories", []),
        "main": main,
    }
    if info.get("polycount"):
        meta["polycount"] = info["polycount"]
    if info.get("dimensions"):
        meta["dimensions_mm"] = [round(x) for x in info["dimensions"]]
    return meta


def fetch_acg(cand, res, dst, progress, stop):
    a = cand["info"]
    want = res.upper() + "-JPG"
    zips = a["downloadFolders"]["default"]["downloadFiletypeCategories"]["zip"]["downloads"]
    z = next((d for d in zips if d["attribute"] == want), None) or next(
        d for d in zips if d["attribute"].endswith("-JPG")
    )
    zpath = os.path.join(dst, "_pack.zip")
    run_files([("_pack.zip", {"url": z["downloadLink"], "size": z.get("size", 0)})], dst, progress, stop, 0, 0.9)
    main = []
    with zipfile.ZipFile(zpath) as zf:
        for m in zf.namelist():
            base = os.path.basename(m)
            low = base.lower()
            # OpenGL-нормаль Unreal не нужна; usd/mtlx - для других программ
            if not base or "normalgl" in low or not low.endswith((".jpg", ".png")):
                continue
            with zf.open(m) as src, open(os.path.join(dst, base), "wb") as out:
                shutil.copyfileobj(src, out)
            if "preview" not in low and low != cand["id"].lower() + ".png":  # <id>.png - картинка-превью набора
                main.append(base)
    os.remove(zpath)
    prev = a.get("previewImage", {}).get("512-PNG")
    if prev:
        save_preview(get(prev), dst)
    return {
        "source": "ambientCG",
        "url": a.get("shortLink") or f"https://ambientcg.com/a/{cand['id']}",
        "authors": ["ambientCG (Lennart Demes)"],
        "tags": a.get("tags", []),
        "categories": [a.get("displayCategory") or ""],
        "main": sorted(main),
    }


# ---------------------------------------------------------------- пачкой
def get_many(kind, theme, count, res="2k", progress=None, stop=None, log=print):
    """Скачать до count новых ассетов темы. progress(доля 0..1, подпись) - общий ход.
    -> [папки]. Один неудачный не останавливает остальные."""
    if kind == "ies":
        from imaging import ies

        return ies.write_all(os.path.join(ROOT, KINDS["ies"][0]))
    have = have_ids()
    cands = candidates(kind, theme, have)[:count]
    out = []
    for i, c in enumerate(cands):
        if stop is not None and stop.is_set():
            break

        def tick(frac, name, i=i, c=c):
            if progress:
                progress((i + frac) / len(cands), f"{c['name']}: {name}")

        try:
            out.append(fetch(c, kind, theme, res, tick, stop))
            log(f"  + {c['name']}")
        except InterruptedError:
            break
        except Exception as e:
            log(f"  ! {c['name']}: {e}")
    if progress:
        progress(1.0, "готово")
    return out


def estimate(kind, res):
    """Примерный вес одного ассета, МБ."""
    k = {"1k": 0.3, "2k": 1.0, "4k": 3.6}[res]
    return {"tex": 14 * k, "hdri": 6 * k, "model": 12 * k, "ies": 0.01}[kind]
