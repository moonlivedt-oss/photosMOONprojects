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
GENERIC = ("a photo", "an object", "a picture", "предмет", "вещь", "картинка")  # «похожесть на всё» вычитается, как в библиотеке


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
        self.bias = None
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
            self.bias = None
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
        if self.bias is None or len(self.bias[0]) != len(img):
            g = np.stack([clip.embed_text(w) for w in GENERIC])
            self.bias = ((img @ g.T).mean(1), (txt @ g.T).mean(1))

        def z(x):  # картинка и текст - в одной шкале
            return (x - x.mean()) / (x.std() + 1e-6)

        s = z(img @ q - self.bias[0]) + TEXT_WEIGHT * z(txt @ q - self.bias[1])
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
