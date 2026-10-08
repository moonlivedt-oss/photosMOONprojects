"""Отпечатки библиотеки: «уже есть», «найти похожие», поиск по цвету, дубли."""

import os

import numpy as np
from PIL import Image

import imaging as K
from library import db
from library.common import CLOSING, LIB


def build_sigs(old, lib=LIB):
    """Отпечатки всех картинок библиотеки (в фоне), неизменённые берутся из кэша."""
    new = {}
    for f in K.images_in(lib):
        if CLOSING.is_set():
            return None  # окно закрыли - недосчитанное не записываем
        if f.lower().endswith(".svg"):
            continue
        rel = os.path.relpath(f, lib)
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        o = old.get(rel)
        if o and o[0] == mt and len(o) > 4:  # 5-е поле - версия: отпечатки с поворотом по EXIF
            new[rel] = o
            continue
        try:
            with Image.open(f) as im:
                im.draft("RGB", (96, 96))
                im = K.upright(im)
                ratio = im.width / im.height
                _r, v = K.signature(im)
                col = K.colors(im)
        except Exception:
            continue
        new[rel] = [mt, round(ratio, 4), np.clip(np.rint(v), 0, 255).astype(np.uint8).ravel(), col, 2]
    return new


class SigIndex:
    """Отпечатки в памяти. refresh() здесь считает сразу; окно (ui.signatures) - в фоне."""

    def __init__(self, lib=LIB):
        self.lib = lib
        self.data, self.busy, self.again = {}, False, False
        self.paths, self.ratio, self.vec = [], np.zeros(0), np.zeros((0, 432))
        try:
            self.data = db.load_sigs()  # база вместо 7-мегабайтного json
        except Exception:
            self.data = {}
        self._arrays()

    def _arrays(self):
        items = [(k, v) for k, v in self.data.items() if len(v[2]) == 432]
        self.paths = [k for k, _v in items]
        self.ratio = np.array([v[1] for _k, v in items], dtype=float)
        self.vec = np.stack([np.asarray(v[2], dtype=float) for _k, v in items]) if items else np.zeros((0, 432))
        self.col = {k: (v[3] if len(v) > 3 else "") for k, v in items}

    def has_color(self, path, code):
        return code in self.col.get(os.path.relpath(path, self.lib), "")

    def similar(self, path, n=48):
        """Самые похожие картинки по отпечатку (рисунок и пропорции), без самой картинки."""
        rel = os.path.relpath(path, self.lib)
        if rel not in self.data or not len(self.paths):
            return []
        o = self.data[rel]
        v, r = np.array(o[2], dtype=float), o[1]
        d = np.abs(self.vec - v).mean(1) + 40 * np.abs(np.log(self.ratio / r))
        out = []
        for i in np.argsort(d):
            p = os.path.join(self.lib, self.paths[i])
            if self.paths[i] != rel and os.path.exists(p):
                out.append(p)
            if len(out) >= n:
                break
        return out

    def refresh(self):
        self.busy = True
        self._built(build_sigs(dict(self.data), self.lib))

    def _built(self, res):
        self.busy = False
        if isinstance(res, dict):
            old, self.data = self.data, res
            self._arrays()
            try:
                db.save_sigs(res, old)  # только изменившиеся строки
            except Exception:
                pass
        if self.again:
            self.again = False
            self.refresh()

    def find(self, im):
        """Путь похожей картинки из библиотеки (относительно LIB) или None."""
        paths, ratio, vec = self.paths, self.ratio, self.vec  # разом: индекс могут обновить из другого потока
        if not len(paths):
            return None
        r, v = K.signature(im)
        near = np.flatnonzero(np.abs(ratio - r) / r < K.SAME_RATIO)
        if not len(near):
            return None
        d = np.abs(vec[near] - v.ravel()).mean(1)
        i = int(d.argmin())
        return paths[near[i]] if d[i] < K.SAME_DIFF else None

    def groups(self):
        """Группы одинаковых картинок (тот же рисунок в другом размере или формате)."""
        paths, ratio, vec = self.paths, self.ratio, self.vec
        up = list(range(len(paths)))

        def root(i):
            while up[i] != i:
                up[i] = up[up[i]]
                i = up[i]
            return i

        # средняя разница не меньше разницы средних: сравниваем только соседей по средней яркости
        # отпечатка (окно SAME_DIFF) - вместо всех со всеми; на 4000 картинок секунды вместо 15-20
        mean = vec.mean(1) if len(paths) else np.zeros(0)
        order = np.argsort(mean)
        ms, vs, rs = mean[order], vec[order], ratio[order]
        for a in range(len(order) - 1):
            b = int(np.searchsorted(ms, ms[a] + K.SAME_DIFF, "right"))
            if b <= a + 1:
                continue
            d = np.abs(vs[a + 1 : b] - vs[a]).mean(1)
            ok = (d < K.SAME_DIFF) & (np.abs(rs[a + 1 : b] - rs[a]) / rs[a] < K.SAME_RATIO)
            for j in np.flatnonzero(ok):
                up[root(int(order[a + 1 + j]))] = root(int(order[a]))
        out = {}
        for i, rel in enumerate(paths):
            p = os.path.join(self.lib, rel)
            if os.path.exists(p):
                out.setdefault(root(i), []).append(p)
        return [g for g in out.values() if len(g) > 1]
