"""Поиск по смыслу: векторы CLIP всех картинок библиотеки (в базе), досчёт новых. Без Qt -
окно (ui.semantic) досчитывает в фоне, командная строка и сервер для ИИ - сразу."""

import os

import numpy as np
from PIL import Image

import imaging as K
from imaging import clip
from library import db
from library.common import CLOSING, LIB, log_error

BATCH = 16
GAP = 0.05  # от лучшего совпадения: дальше - уже случайные картинки
READ_SIDE = 448
# Мелкие однотонные детали (кнопки, полоски) похожи «на всё сразу» и лезут наверх в любом запросе.
# Их средняя похожесть на общие слова вычитается из оценки - так наверх выходит то, что похоже именно на запрос.
GENERIC = (
    "картинка",
    "предмет",
    "животное",
    "пейзаж",
    "интерфейс",
    "значок",
    "человек",
    "еда",
    "техника",
    "узор",
    "текст",
    "цвет",
    "ночь",
    "день",
    "игра",
    "кнопка",
    "фон",
    "рисунок",
    "объект",
    "вещь",
)  # хватает для 224 после обрезки середины, а читается быстро (draft у jpg)


def _read(path):
    with Image.open(path) as im:
        im.draft("RGB", (READ_SIDE, READ_SIDE))
        im = K.upright(im).convert("RGBA")
    im.thumbnail((READ_SIDE, READ_SIDE))
    return im


class SemIndex:
    def __init__(self, lib=LIB):
        self.lib = lib
        self.ok = clip.available()
        self.data, self.busy, self.again = {}, False, False
        self.paths, self.mat = [], np.zeros((0, clip.DIM), np.float32)
        self.progress = None  # (готово, всего) пока идёт досчёт
        self.on_progress = None  # окно показывает ход в строке состояния
        self._queries = {}
        self.outside = {}  # векторы картинок не из библиотеки (поиск по картинке)
        if self.ok:
            try:
                self.data = db.load_clip()
            except Exception as e:
                log_error(f"векторы CLIP не прочитались: {e}")
            self._arrays()

    def ready(self):
        return self.ok and len(self.paths) > 0

    def _arrays(self):
        items = [(k, v) for k, (_mt, v) in self.data.items() if len(v) == clip.DIM]
        self.paths = [k for k, _v in items]
        self.mat = np.stack([v.astype(np.float32) for _k, v in items]) if items else np.zeros((0, clip.DIM), np.float32)
        self.bias = None

    def _rel(self, path):
        try:
            return os.path.relpath(path, self.lib)
        except ValueError:  # другой диск
            return path

    def refresh(self, step=None):
        """Досчитать векторы новых картинок сразу (step((готово, всего)) - ход)."""
        if self.ok:
            self.busy = True
            self._built(self._build(dict(self.data), step))

    def missing(self):
        """Сколько картинок ещё без векторов."""
        n = 0
        for f in K.images_in(self.lib):
            if f.lower().endswith((".svg", ".ico")):
                continue
            o = self.data.get(self._rel(f))
            try:
                n += not (o and o[0] == os.path.getmtime(f))
            except OSError:
                pass
        return n

    def _build(self, old, step=None):
        files = [f for f in K.images_in(self.lib) if not f.lower().endswith((".svg", ".ico"))]
        new, todo = {}, []
        for f in files:
            rel = os.path.relpath(f, self.lib)
            try:
                mt = os.path.getmtime(f)
            except OSError:
                continue
            o = old.get(rel)
            if o and o[0] == mt:
                new[rel] = o
            else:
                todo.append((f, rel, mt))
        pending = {t[1] for t in todo}
        db.save_clip([], [r for r in old if r not in new and r not in pending])
        if todo:
            clip.embed_text("")  # модели грузятся здесь, а не при первом поиске
        for i in range(0, len(todo), BATCH):
            if CLOSING.is_set():
                return None
            part, ims = [], []
            for f, rel, mt in todo[i : i + BATCH]:
                try:
                    ims.append(_read(f))
                    part.append((rel, mt))
                except Exception:
                    continue
            if not ims:
                continue
            vecs = clip.embed_images(ims).astype(np.float16)
            rows = [(rel, mt, v) for (rel, mt), v in zip(part, vecs)]
            db.save_clip(rows)
            new.update({rel: (mt, v) for rel, mt, v in rows})
            if step:
                step((min(i + BATCH, len(todo)), len(todo)))
        return new

    def _step(self, prog):
        self.progress = prog
        if self.on_progress:
            self.on_progress(prog)

    def _built(self, res):
        self.busy = False
        if isinstance(res, Exception):
            log_error(f"поиск по смыслу: {res}")
        elif isinstance(res, dict):
            self.data = res
            self._arrays()
        self.progress = None
        if self.on_progress:
            self.on_progress(None)
        if self.again:
            self.again = False
            self.refresh()

    def _bias(self):
        if self.bias is None or len(self.bias) != len(self.mat):
            g = np.stack([clip.embed_text(w) for w in GENERIC])
            self.bias = (self.mat @ g.T).mean(1)
        return self.bias

    def search(self, text, top=150):
        """Пути картинок по убыванию похожести на описание."""
        return [p for p, _s in self.rank(text, top)]

    def rank(self, text, top=150):
        """[(путь, оценка)] по убыванию похожести; дальше GAP от лучшего - уже случайные картинки."""
        if not self.ready() or not text.strip():
            return []
        v = self._queries.get(text)
        if v is None:
            v = self._queries[text] = clip.embed_text(text)
        s = self.mat @ v - self._bias()
        order = np.argsort(-s)[:top]
        order = order[s[order] >= s[order[0]] - GAP]
        return [(p, float(s[i])) for i, p in self._existing(order, True)]

    def vecs_of(self, paths):
        """Готовые векторы картинок библиотеки (без чтения файлов); непосчитанные пропускаются."""
        out = [self.data[r][1] for r in map(self._rel, paths) if r in self.data]
        return np.stack(out).astype(np.float32) if out else np.zeros((0, clip.DIM), np.float32)

    def embed_file(self, path):
        """Вектор любой картинки, в том числе не из библиотеки (поиск по картинке). Из фонового потока."""
        v = clip.embed_images([_read(path)])[0]
        self.outside[path] = v
        return v

    def similar(self, path, n=60):
        rel = self._rel(path)
        if rel in self.data:
            v = self.data[rel][1].astype(np.float32)
        elif path in self.outside:
            v = self.outside[path]
        else:
            return []
        if not self.ready():
            return []
        # то же, что у текста: «похожесть на всё» (близость к средней картинке библиотеки) вычитается
        s = self.mat @ (v / max(np.linalg.norm(v), 1e-8)) - self.mat @ self.mat.mean(0)
        order = np.argsort(-s)[: n + 1]
        return [p for p in self._existing(order) if self._rel(p) != rel][:n]

    def _existing(self, order, with_index=False):
        out = []
        for i in order:
            p = os.path.join(self.lib, self.paths[i])
            if os.path.exists(p):
                out.append((i, p) if with_index else p)
        return out
