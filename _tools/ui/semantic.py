"""Поиск по смыслу в окне: векторы CLIP всех картинок библиотеки (в базе), досчёт новых в фоне."""

import os

import numpy as np
from PIL import Image

import imaging as K
from imaging import clip
from ui import db
from ui.common import CLOSING, LIB, bg, in_main, log_error

BATCH = 16
GAP = 0.05                  # от лучшего совпадения: дальше - уже случайные картинки
READ_SIDE = 448
# Мелкие однотонные детали (кнопки, полоски) похожи «на всё сразу» и лезут наверх в любом запросе.
# Их средняя похожесть на общие слова вычитается из оценки - так наверх выходит то, что похоже именно на запрос.
GENERIC = ("картинка", "предмет", "животное", "пейзаж", "интерфейс", "значок", "человек", "еда", "техника",
           "узор", "текст", "цвет", "ночь", "день", "игра", "кнопка", "фон", "рисунок", "объект", "вещь")  # хватает для 224 после обрезки середины, а читается быстро (draft у jpg)


def _read(path):
    with Image.open(path) as im:
        im.draft("RGB", (READ_SIDE, READ_SIDE))
        im = K.upright(im).convert("RGBA")
    im.thumbnail((READ_SIDE, READ_SIDE))
    return im


class SemIndex:
    def __init__(self):
        self.ok = clip.available()
        self.data, self.busy, self.again = {}, False, False
        self.paths, self.mat = [], np.zeros((0, clip.DIM), np.float32)
        self.progress = None  # (готово, всего) пока идёт досчёт
        self.on_progress = None  # окно показывает ход в строке состояния
        self._queries = {}
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

    def refresh(self):
        if not self.ok:
            return
        if self.busy:
            self.again = True
            return
        self.busy = True
        old = dict(self.data)
        bg(lambda: self._build(old), self._built)

    def _build(self, old):
        files = [f for f in K.images_in(LIB) if not f.lower().endswith((".svg", ".ico"))]
        new, todo = {}, []
        for f in files:
            rel = os.path.relpath(f, LIB)
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
            in_main(self._step, (min(i + BATCH, len(todo)), len(todo)))
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
        if not self.ready() or not text.strip():
            return []
        v = self._queries.get(text)
        if v is None:
            v = self._queries[text] = clip.embed_text(text)
        s = self.mat @ v - self._bias()
        order = np.argsort(-s)[:top]
        order = order[s[order] >= s[order[0]] - GAP]
        return self._existing(order)

    def similar(self, path, n=60):
        rel = os.path.relpath(path, LIB)
        if rel not in self.data or not self.ready():
            return []
        v = self.data[rel][1].astype(np.float32)
        order, _s = clip.rank(v / max(np.linalg.norm(v), 1e-8), self.mat, n + 1, 0.5)
        return [p for p in self._existing(order) if os.path.relpath(p, LIB) != rel][:n]

    def _existing(self, order):
        out = []
        for i in order:
            p = os.path.join(LIB, self.paths[i])
            if os.path.exists(p):
                out.append(p)
        return out
