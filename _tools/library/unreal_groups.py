"""Раскладка ассетов Unreal для навигации: группа -> раздел, плюс стиль. Без Qt - её берут окно (дерево
слева) и ИИ-помощники (ue_search, ue_overview).

Темы скачивания (THEMES в unreal.py) остаются как есть - по ним качается и пишется asset.json. А смотреть
5000+ моделей удобнее не по источникам («Город - Kenney», «Город - KayKit»...), а так:
  группа  - что это за мир: Дом, Природа, Город, Средневековье, Космос, Персонажи, Прототипы, Еда;
  раздел  - что за вещь внутри группы: деревья, камни, здания, дороги, транспорт, оружие...;
  стиль   - реалистичные (Poly Haven, ambientCG) или low-poly (Kenney, Quaternius, KayKit) - фильтр сверху.
"""

import re

from library import unreal as U

OTHER = "Прочее"

# группа -> базовые темы (тема без « - <источник> low-poly»)
GROUPS = (
    ("Дом", ("Дом", "Интерьер")),
    ("Природа", ("Лес и природа", "Пустыня и скалы", "Зима")),
    ("Город и транспорт", ("Город", "Ночь и закат")),
    ("Средневековье и фэнтези", ("Средневековье", "Средневековье и фэнтези")),
    ("Космос и sci-fi", ("Космос", "Индустрия и sci-fi")),
    ("Персонажи и животные", ("Персонажи", "Животные")),
    ("Прототипы и уровни", ("Прототипы и уровни",)),
    ("Еда", ("Еда",)),
    ("Студия и свет", ("Студия", "Свои профили")),
)
GROUP_ICON = {
    "Дом": "house",
    "Природа": "bonsai-tree",
    "Город и транспорт": "structure_tower",
    "Средневековье и фэнтези": "tool_sword_a",
    "Космос и sci-fi": "gear",
    "Персонажи и животные": "pawn",
    "Прототипы и уровни": "hand_cube",
    "Еда": "coffee-mug-steam",
    "Студия и свет": "camera",
    "Разное": "folder",
}
_BASE_GROUP = {b: g for g, bases in GROUPS for b in bases}

# стили: фильтр сверху списка
STYLES = (
    ("all", "Стиль: любой"),
    ("real", "Реалистичные (PBR)"),
    ("low", "Low-poly: все"),
    ("Kenney", "Low-poly: Kenney"),
    ("Quaternius", "Low-poly: Quaternius"),
    ("KayKit", "Low-poly: KayKit"),
)

# разделы внутри групп: (раздел, слова) - первое совпадение выигрывает; слова ищутся в имени, потом в метках
W = lambda s: set(s.split())  # noqa: E731
_VOCAB = {}  # группа -> все слова её разделов (для split_compounds)
SECTIONS = {
    "Природа": (
        ("Деревья", W("tree trees pine birch oak palm fir spruce trunk stump log logs sapling willow maple")),
        ("Камни и скалы", W("rock rocks stone stones cliff boulder pebble pebbles cave crystal")),
        (
            "Кусты, трава, цветы",
            W(
                "bush bushes plant plants flower flowers grass fern mushroom mushrooms crop crops lily reed vine "
                "cactus clover moss petal hedge"
            ),
        ),
        ("Земля и дорожки", W("ground path tile tiles terrain dirt sand water bridge platform")),
        (
            "Лагерь и выживание",
            W(
                "tent campfire fire axe bucket barrel chest fence sign signpost workbench bedroll tool hammer hoe "
                "pickaxe shovel canoe paddle box bottle pot structure floor panel roof building ladder bed flag fish "
                "statue column resource"
            ),
        ),
    ),
    "Город и транспорт": (
        (
            "Транспорт",
            W(
                "car cars truck bus van train tram wagon boat ship taxi police ambulance vehicle firetruck "
                "locomotive carriage tractor sedan suv pickup delivery hatchback race kart"
            ),
        ),
        ("Индустрия", W("pipe pipes tank container crate pallet conveyor machine generator silo hopper watertower")),
        ("Железная дорога", W("rail rails railroad railroadrail railstraight track tracks")),
        (
            "Дороги",
            W(
                "road roads street crossing intersection highway bridge sidewalk asphalt decal arrow lane crosswalk "
                "stripe doubleyellow curve turn"
            ),
        ),
        ("Окна и двери", W("window windows door doors balcony entrance awning")),
        ("Крыши", W("roof roofs roofflat chimney")),
        (
            "Дома целиком",
            W("building buildings house skyscraper shop store garage factory warehouse apartment office"),
        ),
        (
            "Стены и фасады",
            W("wall walls facade stairs brick column trim cornice corner angle cap inset concrete floor tile"),
        ),
        (
            "Улица и детали",
            W(
                "lamp light bench sign trash bin hydrant fence cone barrier mailbox pole antenna tree planter "
                "dumpster bollard billboard manhole drain acunit lantern"
            ),
        ),
    ),
    "Средневековье и фэнтези": (
        (
            "Гексы и карта",
            W("hex hexriver hexroad hexcoast river coast hills waterless rivercrossing border"),
        ),
        (
            "Оружие и броня",
            W("sword swords axe bow arrow arrows shield spear dagger hammer crossbow staff wand mace helmet armor"),
        ),
        ("Кладбище и подземелье", W("grave tomb coffin skull bone bones crypt dungeon trap cage gravestone")),
        ("Корабли", W("ship boat pirate cannon anchor mast")),
        ("Природа", W("tree trees treesa treesb pine rock grass bush mushroom stone hedge trunk hill mountain")),
        ("Башни и ворота", W("tower towers towersquare buildingtower battlement gate castle arch drawbridge")),
        ("Крыши", W("roof roofs roofhigh overhang overhangside chimney")),
        ("Двери и окна", W("door doors doorway window windows balcony shutter")),
        ("Полы и лестницы", W("floor floortile tile tiles stairs stair bridge corridor corridorwide platform")),
        ("Дома целиком", W("building house home windmill well structure mill hut shack")),
        (
            "Стены",
            W(
                "wall walls wallwood wallcorner corner brick plaster exterior interior unevenbrick column pillar "
                "room cover hole road path"
            ),
        ),
        ("Знамёна и флаги", W("banner bannerpattern bannerthin bannertriple flag flags")),
        (
            "Утварь и мебель",
            W(
                "barrel crate chest table chair bed bookcase shelf candle torch lantern bottle mug plate bucket cart "
                "sack bag book potion coin fence ironfence bench stall fountain prop pumpkin vine propvine detail "
                "shovel pickaxe anvil workbench weaponrack vase urn lightpost lamppost post pouch dummy"
            ),
        ),
        ("Карты", W("card cards")),
    ),
    "Космос и sci-fi": (
        ("Персонажи", W("alien astronaut robot")),
        (
            "Корабли и транспорт",
            W(
                "ship spaceship rover rocket craft mech turret drone vehicle satellite monorail monorailtrack "
                "monorailtrain train"
            ),
        ),
        ("Декали", W("decal decalline line linebend")),
        ("Поверхность", W("terrain terrainroad terrainside rock rocks crater")),
        (
            "Инструменты",
            W("wrench screwdriver hammer pliers drill saw vice cutters sledgehammer toolbox tool"),
        ),
        ("Коридоры и двери", W("corridor door doors window gate hangar tunnel wallwindow")),
        ("Платформы и лестницы", W("platform stairs floor rail track slope incline")),
        (
            "Стены и углы",
            W(
                "wall walls panel column module room roof corner cornerround cornersquare basemodule roofmodule "
                "structure top bottom inner outer"
            ),
        ),
        (
            "Предметы",
            W(
                "crate barrel terminal computer console chair table container containers pipe cable cables gun "
                "weapon box cargo cargoa cargob shelves propshelves bed prop barrels machine generator supports"
            ),
        ),
    ),
    "Персонажи и животные": (
        (
            "Животные",
            W(
                "dog cat horse cow pig sheep fox deer wolf fish bird chicken duck bull alpaca stag llama husky "
                "shibainu shiba animal"
            ),
        ),
        (
            "Снаряжение и одежда",
            W(
                "sword axe bow shield hair hat outfit helmet mug arrow quiver dagger staff crossbow spellbook wand "
                "smokebomb blade cane wheelchair defibrillator aid glasses sunglasses mask crutch"
            ),
        ),
        (
            "Персонажи",
            W(
                "character female male ranger peasant skeleton barbarian knight rogue mage superhero minion "
                "warrior body head arms legs feet eyebrows man woman"
            ),
        ),
    ),
    "Еда": (
        (
            "Фрукты и овощи",
            W(
                "apple banana carrot tomato orange lemon pear grape grapes cherry cherries strawberry watermelon "
                "pumpkin corn potato onion pepper paprika avocado advocado broccoli cabbage eggplant mushroom "
                "pineapple coconut beet cauliflower celery leek radish"
            ),
        ),
        (
            "Выпечка и сладкое",
            W(
                "cake bread donut cookie pie cupcake icecream croissant muffin waffle pancake pancakes candy "
                "chocolate loaf baguette popsicle lollypop pudding honey"
            ),
        ),
        (
            "Блюда",
            W(
                "burger pizza sushi sandwich hotdog fries meat steak soup taco egg cheese bacon sausage ham maki "
                "dimsum skewer tajine frikandel butter peanutbutter fishbones mussel fish"
            ),
        ),
        ("Напитки", W("bottle cup mug soda juice wine beer coffee tea can carton cocktail frappe")),
        (
            "Посуда",
            W("plate bowl pan pot knife fork spoon glass tray cutting board mortar pestle spatula chopstick bag"),
        ),
    ),
    "Прототипы и уровни": (  # по набору (метка набора у Kenney и KayKit)
        ("Платформер", W("platformer")),
        ("Гонки", W("racing")),
        ("Tower defense", W("tower")),
        ("Гексы", W("hexagon")),
        ("Арена", W("arena")),
        ("Блоки-заготовки", W("prototype bits")),
    ),
}


def base_of(theme):
    """«Город - Kenney low-poly» -> «Город»; «Дом - мебель» -> «Дом»; «Персонажи - MetaHuman» -> «Персонажи»."""
    if theme.startswith("Дом - "):
        return "Дом"
    base = re.sub(r" - [^-]+ low-poly$", "", theme)
    head = base.split(" - ", 1)[0]
    return head if base not in _BASE_GROUP and head in _BASE_GROUP else base


def group_of(a_or_theme):
    theme = a_or_theme if isinstance(a_or_theme, str) else a_or_theme.get("theme", "")
    if theme == "Ночь и закат" and not isinstance(a_or_theme, str) and a_or_theme.get("kind") == "hdri":
        return "Природа"  # ночные небеса - поля и горы; модели этой темы (фонари) остаются в Городе
    return _BASE_GROUP.get(base_of(theme), "Разное")


def style_of(a):
    """real - Poly Haven / ambientCG и свои IES; иначе имя low-poly источника."""
    src = a.get("source") or ""
    return src if src in U.LOW_POLY else ("low" if "low-poly" in (a.get("tags") or []) else "real")


def style_ok(a, style):
    if not style or style == "all":
        return True
    s = style_of(a)
    if style == "real":
        return s == "real"
    if style == "low":
        return s != "real"
    return s == style


def _words(a):
    return U.name_words(a)


def _tags(a):
    out = set()
    for t in (a.get("tags") or []) + (a.get("categories") or []):
        out |= set(re.split(r"[^a-zа-яё0-9]+", str(t).lower()))
        out.add(str(t).lower())
    return out


def section_of(a):
    """Раздел внутри группы. Дом - разделы назначения (unreal.home_section); текстуры и HDRI - тема
    без источника (в «Природе» это «Лес и природа», «Пустыня и скалы»...); модели - по словам имени."""
    g = group_of(a)
    kind = a.get("kind")
    if g == "Дом":
        if kind == "model":
            return a.get("section") or U.home_section(a)
        th = a.get("theme", "")
        if th.startswith("Дом - "):
            return th[len("Дом - ") :].capitalize()
        if kind == "tex":  # текстуры «Интерьера» - в те же разделы, что и текстуры Дома
            words = _words(a)
            for sec, keys in HOME_TEX:
                if words & keys:
                    return sec
        return base_of(th)
    if kind != "model":
        return base_of(a.get("theme", "")) or OTHER
    rules = SECTIONS.get(g)
    if not rules:
        return OTHER
    if g == "Персонажи и животные" and any("outfit" in str(t).lower() for t in a.get("tags") or []):
        return "Комплекты одежды"  # Modular Character Outfits: одежда без головы - на Universal Base Characters
    if g == "Прототипы и уровни":  # тут важен набор, а не имя модели
        tags = " ".join(str(t).lower() for t in a.get("tags") or [])
        for sec, keys in rules:
            if any(k in tags for k in keys):
                return sec
        return OTHER
    vocab = _VOCAB.get(g)
    if vocab is None:
        vocab = _VOCAB[g] = {k for _sec, keys in rules for k in keys}
    for words in (U.split_compounds(_words(a), vocab), _tags(a)):
        for sec, keys in rules:
            if words & keys:
                return sec
    return OTHER


# текстуры без раздела (тема «Интерьер») -> разделы текстур Дома; первое совпадение выигрывает
HOME_TEX = (
    ("Ткани и кожа", W("fabric leather carpet rug linen wool velvet denim cloth")),
    ("Плитка и камень", W("tiles tile marble granite terrazzo onyx mosaic stone")),
    ("Полы", W("floor flooring parquet laminate plank planks wood")),
    ("Стены", W("wall wallpaper plaster stucco concrete brick bricks")),
)


def group_order():
    return [g for g, _b in GROUPS] + ["Разное"]


def section_order(group):
    """Порядок разделов в дереве."""
    if group == "Дом":
        return list(U.HOME_ORDER)
    if group == "Персонажи и животные":
        return ["Персонажи", "Комплекты одежды", "Снаряжение и одежда", "Животные", OTHER]
    return [s for s, _k in SECTIONS.get(group, ())] + [OTHER]


def annotate(items):
    """Проставить группу и раздел (поля _g и _s; в файл не пишутся). Один раз на загрузку."""
    for a in items:
        if "_g" not in a:
            a["_g"] = group_of(a)
            a["_s"] = section_of(a)
    return items


# ---------------------------------------------------------------- «Прочее» - по картинке (CLIP)
# что за вещь в разделе - для поиска по смыслу: раздел ставится, только когда ИИ уверен (unreal_sem.classify)
PROMPTS = {
    "Природа": {
        "Деревья": "a tree",
        "Камни и скалы": "a rock or boulder",
        "Кусты, трава, цветы": "a bush, grass or flowers",
        "Земля и дорожки": "a ground tile or path",
        "Лагерь и выживание": "camping gear, tools or a wooden structure",
    },
    "Город и транспорт": {
        "Транспорт": "a car or vehicle",
        "Железная дорога": "railway tracks",
        "Дороги": "a road piece",
        "Окна и двери": "a window or door",
        "Крыши": "a roof",
        "Дома целиком": "a whole building",
        "Стены и фасады": "a brick wall segment",
        "Улица и детали": "a street lamp, bench or sign",
        "Индустрия": "industrial pipes or containers",
    },
    "Средневековье и фэнтези": {
        "Гексы и карта": "a hexagonal map tile",
        "Оружие и броня": "a medieval weapon or shield",
        "Кладбище и подземелье": "a gravestone, skull or dungeon prop",
        "Корабли": "a wooden ship",
        "Природа": "a tree or rock",
        "Башни и ворота": "a castle tower or gate",
        "Крыши": "a roof",
        "Двери и окна": "a door or window",
        "Полы и лестницы": "a floor tile or stairs",
        "Дома целиком": "a medieval house",
        "Стены": "a stone wall segment",
        "Знамёна и флаги": "a banner or flag",
        "Утварь и мебель": "a barrel, crate, table or chest",
    },
    "Космос и sci-fi": {
        "Персонажи": "an alien or robot",
        "Корабли и транспорт": "a spaceship or vehicle",
        "Декали": "a flat decal sign",
        "Поверхность": "planet terrain rocks",
        "Инструменты": "a hand tool",
        "Коридоры и двери": "a sci-fi corridor or door",
        "Платформы и лестницы": "a metal platform or stairs",
        "Стены и углы": "a sci-fi wall panel",
        "Предметы": "a sci-fi crate, computer or container",
    },
    "Персонажи и животные": {
        "Животные": "an animal",
        "Снаряжение и одежда": "a weapon, hat or clothing item",
        "Персонажи": "a human character",
    },
    "Еда": {
        "Фрукты и овощи": "a fruit or vegetable",
        "Выпечка и сладкое": "a cake, bread or sweets",
        "Блюда": "a cooked dish",
        "Напитки": "a drink bottle or cup",
        "Посуда": "kitchen utensils or dishes",
    },
}


def classify_other(sem, items):
    """Модели из «Прочего» -> раздел своей группы по превью и имени (только уверенно). -> {папка: раздел}."""
    from library import unreal_sem

    out = {}
    for g, prompts in PROMPTS.items():
        rest = [a for a in items if a.get("kind") == "model" and a.get("_g") == g and a.get("_s") == OTHER]
        if rest:
            out.update(unreal_sem.classify(sem, rest, prompts, margin=1.5))  # строже, чем у Дома: разделов больше
    return out


# ---------------------------------------------------------------- цветовые варианты одной плиткой
# Kenney и KayKit кладут одну вещь в нескольких цветах: «Banner red», «Banner blue»... - в сетке это одна
# плитка с цветными точками. Слово цвета -> цвет точки.
VARIANT_COLORS = {
    "red": "#e0524e",
    "blue": "#4f86e0",
    "green": "#58b46a",
    "yellow": "#e8c547",
    "white": "#eeeef2",
    "black": "#2b2b33",
    "brown": "#8a5a3a",
    "gray": "#8d8d96",
    "grey": "#8d8d96",
    "purple": "#9c6ad6",
    "orange": "#ec8a3c",
    "pink": "#ec7fb4",
    "gold": "#d8b04a",
    "silver": "#c3c6cf",
    "teal": "#3fb8ad",
    "cyan": "#53c9e6",
    "beige": "#d9c6a0",
}


def variant_of(a):
    """(ключ вещи без цвета, слово цвета) или None, если в имени нет цвета."""
    words = re.split(r"[^a-z0-9]+", a.get("name", "").lower())
    col = [w for w in words if w in VARIANT_COLORS]
    if not col:
        return None
    rest = tuple(w for w in words if w and w not in VARIANT_COLORS)
    if not rest:
        return None
    return (a.get("kind"), a.get("source", ""), a.get("theme", ""), rest), col[-1]


def group_variants(items):
    """[(показанный, [(цвет, ассет), ...])] в прежнем порядке: вещи одного вида, набора и имени без цвета -
    одной записью (первый встреченный - на плитке). Одиночки - с пустым списком вариантов."""
    groups, order = {}, []
    for a in items:
        v = variant_of(a)
        key = v[0] if v else ("one", id(a))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((VARIANT_COLORS[v[1]] if v else "", a))
    out = []
    for key in order:
        g = groups[key]
        out.append((g[0][1], g if len(g) > 1 else []))
    return out
