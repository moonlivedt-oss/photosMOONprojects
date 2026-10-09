"""Поиск ассетов Unreal по смыслу: «деревянный стул», «ржавый металл», «закат над морем» - по-русски
и по-английски, без слов в имени. Та же модель CLIP, что у библиотеки картинок (imaging/clip.py).

Оценка - похожесть запроса на превью ассета плюс (с меньшим весом) на его имя и метки: превью ловит
внешний вид, метки - то, чего на маленькой картинке не видно (материал, назначение).
Векторы - в _tools/_unreal_clip.npz, ключ - папка ассета и время его asset.json. Без Qt."""

import os
import threading

import numpy as np

from imaging import clip
from library.semantic import _read
from library.unreal import CACHE, ROOT

STORE = os.path.join(os.path.dirname(CACHE), "_unreal_clip.npz")
TEXT_WEIGHT = 0.6  # насколько важны имя и метки рядом с картинкой
GAP = 2.2  # дальше этого от лучшего (в стандартных отклонениях) - уже случайные
GENERIC = (
    "a photo",
    "an object",
    "a picture",
    "предмет",
    "вещь",
    "картинка",
)  # «похожесть на всё» вычитается, как в библиотеке


def available():
    return clip.available()


def key_of(a):
    try:
        t = os.path.getmtime(os.path.join(a["dir"], "asset.json"))
    except OSError:
        t = 0
    return f"{os.path.relpath(a['dir'], ROOT)}|{t:.0f}"


def text_of(a):
    words = [
        a.get("name", ""),
        a.get("theme", "").replace("Дом - ", "дом "),
        *a.get("tags", [])[:12],
        *a.get("categories", [])[:4],
    ]
    return ", ".join(w for w in words if w)


class AssetSem:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}  # ключ -> (вектор превью, вектор текста)
        self.queries = {}
        self.generic = None  # векторы «похожести на всё» (GENERIC) - один раз на модель
        self.load()

    def load(self):
        try:
            z = np.load(STORE, allow_pickle=False)
            keys, img, txt = list(z["keys"]), z["img"], z["txt"]
            self.data = {k: (img[i], txt[i]) for i, k in enumerate(keys)}
        except (OSError, KeyError, ValueError):
            self.data = {}

    def save(self):
        with self.lock:
            keys = list(self.data)
            if not keys:
                return
            img = np.stack([self.data[k][0] for k in keys]).astype(np.float16)
            txt = np.stack([self.data[k][1] for k in keys]).astype(np.float16)
        tmp = STORE + ".tmp.npz"
        np.savez(tmp, keys=np.array(keys), img=img, txt=txt)
        os.replace(tmp, STORE)

    def missing(self, items):
        return [
            a for a in items if key_of(a) not in self.data and os.path.exists(os.path.join(a["dir"], "preview.webp"))
        ]

    def build(self, items, progress=None, stop=None, batch=16):
        """Досчитать векторы новых ассетов (из фонового потока). progress(готово, всего)."""
        todo = self.missing(items)
        for i in range(0, len(todo), batch):
            if stop is not None and stop.is_set():
                break
            part = todo[i : i + batch]
            ims = []
            for a in part:
                try:
                    ims.append(_read(os.path.join(a["dir"], "preview.webp")))
                except Exception:
                    ims.append(None)
            ok = [(a, im) for a, im in zip(part, ims) if im is not None]
            vecs = clip.embed_images([im for _a, im in ok])
            with self.lock:
                for (a, _im), v in zip(ok, vecs):
                    self.data[key_of(a)] = (v.astype(np.float16), clip.embed_text(text_of(a)).astype(np.float16))
            if progress:
                progress(min(i + batch, len(todo)), len(todo))
        if todo:
            self.save()
        return len(todo)

    def rank(self, query, items):
        """[(ассет, оценка)] по убыванию похожести; непосчитанные пропускаются."""
        if not query.strip():
            return []
        have = [(a, self.data.get(key_of(a))) for a in items]
        have = [(a, v) for a, v in have if v is not None]
        if not have:
            return []
        q = self.queries.get(query)
        if q is None:
            q = self.queries[query] = clip.embed_text(query)
        img = np.stack([v[0] for _a, v in have]).astype(np.float32)
        txt = np.stack([v[1] for _a, v in have]).astype(np.float32)
        if self.generic is None:
            self.generic = np.stack([clip.embed_text(w) for w in GENERIC])
        # поправка - у каждого ассета своя: считается для этого списка (раздел, поиск), а не берётся от другого
        g = self.generic
        bias = ((img @ g.T).mean(1), (txt @ g.T).mean(1))

        def z(x):  # картинка и текст - в одной шкале
            return (x - x.mean()) / (x.std() + 1e-6)

        s = z(img @ q - bias[0]) + TEXT_WEIGHT * z(txt @ q - bias[1])
        order = np.argsort(-s)
        best = s[order[0]]
        return [(have[i][0], float(s[i])) for i in order if s[i] >= best - GAP]

    def similar(self, a, items, top=60):
        """Похожие на ассет по превью и меткам: [(ассет, оценка)], сам ассет не входит."""
        me = self.data.get(key_of(a))
        if me is None:
            return []
        have = [(x, self.data.get(key_of(x))) for x in items if x["dir"] != a["dir"]]
        have = [(x, v) for x, v in have if v is not None]
        if not have:
            return []
        img = np.stack([v[0] for _x, v in have]).astype(np.float32)
        txt = np.stack([v[1] for _x, v in have]).astype(np.float32)
        s = img @ me[0].astype(np.float32) + 0.5 * (txt @ me[1].astype(np.float32))
        order = np.argsort(-s)[:top]
        return [(have[i][0], float(s[i])) for i in order]


# разделы «Дома» описаниями для CLIP: когда по имени и меткам раздел не нашёлся, решает картинка
SECTION_PROMPTS = {
    "Кровати": "a bed",
    "Диваны": "a sofa or a couch",
    "Стулья и кресла": "a chair or an armchair",
    "Столы": "a table or a desk",
    "Шкафы и полки": "a cabinet, a wardrobe or a shelf",
    "Кухня и посуда": "kitchenware, dishes or food",
    "Ванная": "a bathroom fixture, a toilet, a sink or a bathtub",
    "Свет": "a lamp or a light",
    "Техника": "an electronic device or an appliance",
    "Декор": "a decorative object, a vase, a frame or a statue",
    "Растения": "a potted plant",
    "Инструменты": "a hand tool",
    "Хозяйство и уборка": "a household item, a box, a bin or a container",
    "Спорт и хобби": "sports equipment, a toy or a musical instrument",
    "Одежда и аксессуары": "clothing or a personal accessory",
    "Стены, двери, окна": "a wall, a door or a window",
}
MARGIN = 1.0  # отрыв лучшего раздела от второго (в стандартных отклонениях); меньше - не угадывать
# проверено на 551 модели, где раздел известен по словам: картинка + имя и метки, отрыв 1.0 -
# верно 84% при решении для ~60% моделей; одна картинка давала 46-65% - этого мало


def classify(sem, items, prompts=SECTION_PROMPTS, margin=MARGIN):
    """Раздел по превью и по имени с метками: {папка ассета: раздел} - только там, где уверенно.
    Ассеты без посчитанных векторов пропускаются."""
    names = list(prompts)
    key = tuple(prompts.values())
    if getattr(sem, "_sec_key", None) != key:
        sem._sec = np.stack([clip.embed_text(f"a photo of {t}") for t in prompts.values()]).astype(np.float32)
        sem._sec_key = key
    have = [(a, sem.data.get(key_of(a))) for a in items]
    have = [(a, v) for a, v in have if v is not None]
    if not have:
        return {}
    img = np.stack([v[0] for _a, v in have]).astype(np.float32) @ sem._sec.T
    txt = np.stack([v[1] for _a, v in have]).astype(np.float32) @ sem._sec.T

    def z(x):  # по строке: какой раздел выделяется у этого ассета
        return (x - x.mean(1, keepdims=True)) / (x.std(1, keepdims=True) + 1e-6)

    s = z(img) + z(txt)
    top = np.sort(s, 1)
    best = s.argmax(1)
    return {a["dir"]: names[best[i]] for i, (a, _v) in enumerate(have) if top[i, -1] - top[i, -2] >= margin}


# из чего обычно делают вещь такого раздела: запросы к поиску по смыслу по текстурам (проверено: «fabric
# upholstery» поднимает ткани и букле, «wood for a table» - дерево, «ceramic bathroom tiles» - плитку и мрамор)
MATERIALS = {
    "Диваны": ("fabric upholstery", "leather"),
    "Стулья и кресла": ("wood", "fabric upholstery", "leather"),
    "Столы": ("wood for a table", "marble"),
    "Кровати": ("fabric bedding", "wood"),
    "Шкафы и полки": ("wood", "painted wood"),
    "Кухня и посуда": ("ceramic", "metal", "wood"),
    "Ванная": ("ceramic bathroom tiles", "marble"),
    "Свет": ("metal", "fabric lampshade", "wood"),  # стекла среди текстур нет - поиск подставлял бы мрамор
    "Техника": ("plastic", "metal"),
    "Декор": ("ceramic", "brass metal", "stone"),
    "Растения": ("ceramic", "wood"),
    "Инструменты": ("metal", "wood"),
    "Хозяйство и уборка": ("plastic", "metal", "wicker"),
    "Спорт и хобби": ("leather", "wood", "fabric"),
    "Одежда и аксессуары": ("fabric", "leather"),
    "Стены, двери, окна": ("wood", "painted plaster"),
}
DEFAULT_MATERIALS = ("wood", "fabric", "metal")


def materials_for(sem, section, textures, top=8):
    """Текстуры, которые подходят вещи этого раздела: по очереди из каждого материала (ткань, кожа, ткань...),
    без повторов. -> [ассет текстуры]."""
    lists = [[a for a, _s in sem.rank(q, textures)] for q in MATERIALS.get(section, DEFAULT_MATERIALS)]
    out, seen = [], set()
    for i in range(max((len(x) for x in lists), default=0)):
        for lst in lists:
            if i < len(lst) and lst[i]["dir"] not in seen:
                seen.add(lst[i]["dir"])
                out.append(lst[i])
                if len(out) >= top:
                    return out
    return out
