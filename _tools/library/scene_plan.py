"""Подборка по описанию: «уютная спальня в скандинавском стиле» -> кровать, шкаф, свет, растения, декор,
пол, стены и небо HDRI из скачанных ассетов Unreal. Без Qt: окно, сервер MCP и тесты.

Как подбирается (проверено на скачанных ассетах):
- тип комнаты - по словам запроса (спальня/bedroom, кухня/kitchen...), иначе - по смыслу (CLIP);
  от него - какие разделы «Дома» и сколько вещей;
- внутри раздела вещи ранжируются по самому запросу, без слова-предмета: раздел уже задан, а слово
  «floor» или «bed» перебивает стиль (пол был одинаковым для любых запросов; без него «тёмное дерево»
  даёт тёмные доски, «белая ванная» - мрамор);
- стиль не смешивается: реалистичные модели Poly Haven отдельно от low-poly Kenney и Quaternius;
- одинаковые модели из разных наборов (Bed bunk дважды) не повторяются."""

import re

ROOMS = {
    "спальня": {
        "words": ("спальн", "bedroom", "детск", "nursery", "кроват", "спать"),
        "prompt": "a bedroom",
        "sections": (
            ("Кровати", 1),
            ("Шкафы и полки", 2),
            ("Свет", 2),
            ("Стулья и кресла", 1),
            ("Растения", 1),
            ("Декор", 2),
        ),
    },
    "гостиная": {
        "words": ("гостин", "living", "lounge", "зал", "диван", "телевизор"),
        "prompt": "a living room",
        "sections": (
            ("Диваны", 1),
            ("Стулья и кресла", 2),
            ("Столы", 1),
            ("Шкафы и полки", 1),
            ("Свет", 2),
            ("Растения", 2),
            ("Декор", 2),
            ("Техника", 1),
        ),
    },
    "кухня": {
        "words": ("кухн", "kitchen"),
        "prompt": "a kitchen",
        "sections": (("Кухня и посуда", 4), ("Столы", 1), ("Стулья и кресла", 2), ("Свет", 1), ("Растения", 1)),
    },
    "ванная": {
        "words": ("ванн", "bathroom", "санузел", "туалет", "душ"),
        "prompt": "a bathroom",
        "sections": (("Ванная", 3), ("Свет", 1), ("Хозяйство и уборка", 1), ("Декор", 1), ("Растения", 1)),
    },
    "кабинет": {
        "words": ("кабинет", "office", "study", "рабоч", "мастерск", "workshop"),
        "prompt": "a home office",
        "sections": (
            ("Столы", 1),
            ("Стулья и кресла", 1),
            ("Шкафы и полки", 2),
            ("Свет", 2),
            ("Техника", 2),
            ("Декор", 1),
            ("Растения", 1),
        ),
    },
    "столовая": {
        "words": ("столов", "dining"),
        "prompt": "a dining room",
        "sections": (
            ("Столы", 1),
            ("Стулья и кресла", 4),
            ("Кухня и посуда", 2),
            ("Свет", 1),
            ("Декор", 1),
            ("Растения", 1),
        ),
    },
}
DEFAULT_ROOM = "гостиная"
LOW_POLY_WORDS = (
    "low-poly",
    "low poly",
    "лоу-поли",
    "лоупол",
    "мультяш",
    "простые",
    "cartoon",
    "kenney",
    "quaternius",
    "kaykit",
)
LOW_POLY_SOURCES = ("Kenney", "Quaternius", "KayKit")
FLOOR_THEMES = ("Дом - полы", "Дом - плитка и камень")
WALL_THEMES = ("Дом - стены", "Дом - плитка и камень")


def room_of(query, sem=None):
    """Тип комнаты по словам запроса; не нашлось - гостиная. (По смыслу пробовали: «светлая просторная
    комната» уходила в кабинет - на общих словах CLIP гадает, слова надёжнее.)"""
    low = query.lower()
    for key, r in ROOMS.items():
        if any(w in low for w in r["words"]):
            return key
    return DEFAULT_ROOM


def low_poly_wanted(query):
    low = query.lower()
    return any(w in low for w in LOW_POLY_WORDS)


def base_name(a):
    """Bed bunk и Bed bunk 2 из разных наборов - одна и та же вещь."""
    return re.sub(r"[\s_-]*\d+$", "", a.get("name", "").strip().lower())


def plan(sem, items, query, section_of, low_poly=None, room=None):
    """-> {room, low_poly, slots: [{section, choices: [ассет...]}], floor, wall, hdri: [ассет...]}.
    choices - по убыванию: первый - предложенный, дальше - замены для «Другой вариант».
    section_of(a) - раздел «Дома» модели (у окна - уже посчитанный, в т.ч. ИИ)."""
    room = room or room_of(query, sem)
    lp = low_poly_wanted(query) if low_poly is None else low_poly
    models = [a for a in items if a.get("kind") == "model" and a.get("theme", "").startswith("Дом - ")]

    def style_ok(a):
        return (a.get("source") in LOW_POLY_SOURCES) == lp

    def ranked(cands):
        cands = list(cands)
        if not cands:
            return []
        got = [a for a, _s in sem.rank(query, cands)]
        seen = {a["dir"] for a in got}
        return got + [a for a in cands if a["dir"] not in seen]  # за отсечкой - всё равно варианты

    slots, used = [], set()
    for sec, n in ROOMS[room]["sections"]:
        cands = [a for a in models if section_of(a) == sec]
        pool = [a for a in cands if style_ok(a)]
        if len(pool) < max(3, n):  # своего стиля почти нет (реалистичной ванной - один вантуз) - оба стиля
            pool = cands
        choices, names = [], set()
        for a in ranked(pool):
            if base_name(a) in used or base_name(a) in names:  # Stool из двух наборов - одна вещь
                continue
            names.add(base_name(a))
            choices.append(a)
        for i in range(n):
            if i < len(choices):
                used.add(base_name(choices[i]))
                # у каждого слота свой первый вариант, замены - остальные из того же раздела
                slots.append({"section": sec, "choices": [choices[i]] + choices[n:]})
    tex = [a for a in items if a.get("kind") == "tex"]
    floor = ranked(a for a in tex if a.get("theme") in FLOOR_THEMES)[:12]
    floor_dir = floor[0]["dir"] if floor else None  # стены - не той же текстурой, что пол
    return {
        "room": room,
        "low_poly": lp,
        "slots": slots,
        "floor": floor,
        "wall": [a for a in ranked(a for a in tex if a.get("theme") in WALL_THEMES) if a["dir"] != floor_dir][:12],
        # свет комнаты - сначала студийный: показывает материалы как есть («уютная» иначе брала фото
        # камина, и вся сцена выходила оранжевой); подходящие по описанию небеса - заменами
        "hdri": (
            ranked(a for a in items if a.get("kind") == "hdri" and a.get("theme") == "Студия")
            + ranked(a for a in items if a.get("kind") == "hdri" and a.get("theme") != "Студия")
        )[:12],
    }


def chosen(p):
    """Первые варианты плана - готовая подборка: [ассет]."""
    out = [s["choices"][0] for s in p["slots"] if s["choices"]]
    for k in ("floor", "wall", "hdri"):
        if p[k]:
            out.append(p[k][0])
    return out
