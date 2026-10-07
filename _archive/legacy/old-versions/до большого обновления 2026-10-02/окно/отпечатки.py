"""Отпечатки библиотеки: «уже есть», «найти похожие», поиск по цвету, дубли."""
import json
import os

import numpy as np
import картинки as K
from PIL import Image

from окно.общее import CLOSING, LIB, SIGS, bg


# ---------------------------------------------------------------- отпечатки библиотеки ("уже есть")
def build_sigs(old):
    """В фоне: отпечатки всех картинок библиотеки, неизменённые берутся из кэша."""
    new = {}
    for f in K.images_in(LIB):
        if CLOSING.is_set():
            return None                         # окно закрыли - недосчитанное не записываем
        if f.lower().endswith(".svg"):
            continue
        rel = os.path.relpath(f, LIB)
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        o = old.get(rel)
        if o and o[0] == mt and len(o) > 4:        # 5-е поле - версия: отпечатки с поворотом по EXIF
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
        new[rel] = [mt, round(ratio, 4), np.rint(v).astype(int).ravel().tolist(), col, 2]
    return new


class SigIndex:
    def __init__(self):
        self.data, self.busy, self.again = {}, False, False
        self.paths, self.ratio, self.vec = [], np.zeros(0), np.zeros((0, 432))
        try:
            with open(SIGS, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except Exception:
            pass
        self._arrays()

    def _arrays(self):
        items = [(k, v) for k, v in self.data.items() if len(v[2]) == 432]
        self.paths = [k for k, _v in items]
        self.ratio = np.array([v[1] for _k, v in items], dtype=float)
        self.vec = np.array([v[2] for _k, v in items], dtype=float).reshape(-1, 432)
        self.col = {k: (v[3] if len(v) > 3 else "") for k, v in items}

    def has_color(self, path, code):
        return code in self.col.get(os.path.relpath(path, LIB), "")

    def similar(self, path, n=48):
        """Самые похожие картинки по отпечатку (рисунок и пропорции), без самой картинки."""
        rel = os.path.relpath(path, LIB)
        if rel not in self.data or not len(self.paths):
            return []
        o = self.data[rel]
        v, r = np.array(o[2], dtype=float), o[1]
        d = np.abs(self.vec - v).mean(1) + 40 * np.abs(np.log(self.ratio / r))
        out = []
        for i in np.argsort(d):
            p = os.path.join(LIB, self.paths[i])
            if self.paths[i] != rel and os.path.exists(p):
                out.append(p)
            if len(out) >= n:
                break
        return out

    def refresh(self):
        if self.busy:
            self.again = True
            return
        self.busy = True
        old = dict(self.data)
        bg(lambda: build_sigs(old), self._built)

    def _built(self, res):
        self.busy = False
        if isinstance(res, dict):
            self.data = res
            self._arrays()
            try:
                tmp = SIGS + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(res, fh, separators=(",", ":"))
                os.replace(tmp, SIGS)
            except OSError:
                pass
        if self.again:
            self.again = False
            self.refresh()

    def find(self, im):
        """Путь похожей картинки из библиотеки (относительно LIB) или None."""
        paths, ratio, vec = self.paths, self.ratio, self.vec        # разом: индекс могут обновить из другого потока
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

        for i in range(len(paths) - 1):
            d = np.abs(vec[i + 1:] - vec[i]).mean(1)
            ok = (d < K.SAME_DIFF) & (np.abs(ratio[i + 1:] - ratio[i]) / ratio[i] < K.SAME_RATIO)
            for j in np.flatnonzero(ok):
                up[root(i + 1 + int(j))] = root(i)
        out = {}
        for i, rel in enumerate(paths):
            p = os.path.join(LIB, rel)
            if os.path.exists(p):
                out.setdefault(root(i), []).append(p)
        return [g for g in out.values() if len(g) > 1]
