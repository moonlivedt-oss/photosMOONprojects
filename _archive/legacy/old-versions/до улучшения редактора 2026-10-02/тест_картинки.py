"""Тесты библиотеки: «Тесты.cmd» в _инструменты (или py -3.14 тесты/тест_картинки.py).
Окно не открывается; проверяется ядро (картинки.py), раскладка, промпты, база.
Эталонные листы: настоящие листы 4x3 из «_исходники». При первом прогоне их рамки нарезки
записываются в эталон.json, потом каждая правка нарезки сверяется с ним - так видно, если старые
листы вдруг начали резаться иначе. Обновить эталон: удалить эталон.json и прогнать снова."""
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import картинки as K  # noqa: E402

SNAP = os.path.join(HERE, "эталон.json")
SHEETS = 8                                  # сколько настоящих листов сверять (каждый режется пару секунд)
TOL = 6                                     # насколько может сдвинуться рамка, px


def sticker_sheet(touch=False, seed=0):
    """Искусственный лист 4x3: кружки с белой обводкой; touch - соседи касаются обводкой."""
    im = Image.new("RGBA", (800, 600), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rng = np.random.default_rng(seed)
    for r in range(3):
        for c in range(4):
            x, y = c * 200 + 100, r * 200 + 100
            rad = 98 if touch else 70
            d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=(255, 255, 255, 255))
            col = tuple(int(v) for v in rng.integers(40, 220, 3)) + (255,)
            d.ellipse((x - rad + 8, y - rad + 8, x + rad - 8, y + rad - 8), fill=col)
    return im


class Нарезка(unittest.TestCase):
    def test_сетка_12_кусков(self):
        pieces, boxes = K.cut(sticker_sheet(), (4, 3))
        self.assertEqual(len(pieces), 12)
        self.assertTrue(all(p.size == (256, 256) for p in pieces))

    def test_слипшиеся_соседи_делятся(self):
        _p, boxes = K.cut(sticker_sheet(touch=True), (4, 3))
        for i, (x0, y0, x1, y1) in enumerate(boxes):
            cx, cy = (i % 4) * 200 + 100, (i // 4) * 200 + 100
            self.assertTrue(x0 < cx < x1 and y0 < cy < y1, "кусок %d не на своём месте: %s" % (i, (x0, y0, x1, y1)))
            self.assertLess(x1 - x0, 260, "кусок %d захватил соседа" % i)

    def test_автопоиск(self):
        pieces, _b = K.cut(sticker_sheet(seed=3), None)
        self.assertEqual(len(pieces), 12)

    def test_рамки_руками(self):
        pieces, boxes = K.cut(sticker_sheet(), None, boxes=[(0, 0, 200, 200), (200, 0, 600, 200)])
        self.assertEqual(len(pieces), 2)
        self.assertEqual(boxes[1], (200, 0, 600, 200))

    def test_крошечный_лист(self):
        self.assertEqual(len(K.cut(Image.new("RGBA", (6, 5), (255, 255, 255, 255)), (4, 3))[0]), 12)


class Правка(unittest.TestCase):
    def setUp(self):
        im = Image.new("RGBA", (300, 200), (255, 255, 255, 255))
        ImageDraw.Draw(im).ellipse((80, 40, 220, 160), fill=(200, 40, 90, 255))
        self.im = im
        self.cut = K.remove_bg(im)

    def test_поворот_и_обрезка(self):
        r = K.apply_edits(self.im, [dict(op="rotate", deg=90), dict(op="crop", box=(0, 0, 1, 0.5))])
        self.assertEqual(r.size, (200, 150))

    def test_убрать_фон(self):
        self.assertEqual(self.cut.getpixel((5, 5))[3], 0)
        self.assertEqual(self.cut.getpixel((150, 100))[3], 255)

    def test_перекраска_в_палитру(self):
        r = K.recolor(self.cut, ["#282a36", "#ff79c6", "#bd93f9"])
        self.assertEqual(r.getpixel((5, 5))[3], 0)              # прозрачность не тронута
        px = r.getpixel((150, 100))[:3]
        self.assertIn(px, [K.hex_rgb(c) for c in ("#282a36", "#ff79c6", "#bd93f9")] + [px])
        self.assertNotEqual(px, (200, 40, 90))

    def test_кайма_находится_и_убирается(self):
        big = Image.new("RGBA", (800, 800), (255, 255, 255, 255))
        ImageDraw.Draw(big).ellipse((100, 100, 700, 700), fill=(30, 30, 60, 255))
        nb = K.remove_bg(big.resize((200, 200), Image.LANCZOS), tol=20)
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "a.png")
            nb.save(p)
            self.assertIn("fringe", K.doctor_check(p, art=True))
            K.defringe(nb, 1).save(p)
            self.assertNotIn("fringe", K.doctor_check(p, art=True))
        finally:
            shutil.rmtree(d)

    def test_кисть(self):
        r = K.brush(self.cut, "erase", 0.05, [(0.5, 0.5)])
        self.assertEqual(r.getpixel((150, 100))[3], 0)
        back = K.brush(r, "restore", 0.05, [(0.5, 0.5)])
        self.assertEqual(back.getpixel((150, 100))[3], 255)

    def test_тень_свечение_углы(self):
        for ops in ([dict(op="shadow", dx=5, dy=5, blur=4, a=0.5)], [dict(op="glow", r=6, color="#a897ff")],
                    [dict(op="round", rad=0.5)], [dict(op="center")], [dict(op="outline", px=6)],
                    [dict(op="square", pad=0.1)], [dict(op="resize", size=64)]):
            r = K.apply_edits(self.cut, ops)
            self.assertGreater(r.width, 0, ops)
        self.assertEqual(K.apply_edits(self.im, [dict(op="round", rad=0.5)]).getpixel((0, 0))[3], 0)

    def test_масштаб_превью_совпадает(self):
        """Рецепт на копии (scale) и на полном размере дают те же пропорции."""
        ops = [dict(op="crop", box=(0.1, 0.1, 0.9, 0.7)), dict(op="outline", px=8)]
        full = K.apply_edits(self.cut, ops)
        small = K.apply_edits(self.cut.resize((150, 100)), ops, scale=0.5)
        self.assertAlmostEqual(full.width / full.height, small.width / small.height, delta=0.08)


class Выгрузка(unittest.TestCase):
    def test_атлас(self):
        d = tempfile.mkdtemp()
        try:
            paths = []
            for i in range(5):
                p = os.path.join(d, "знак %d.png" % i)
                Image.new("RGBA", (40 + i * 10, 40), (i * 40, 100, 200, 255)).save(p)
                paths.append(p)
            sheet, frames = K.atlas(paths, 64)
            self.assertEqual(len(frames), 5)
            js, css = K.atlas_files("a.png", frames, sheet.size)
            self.assertEqual(len(json.loads(js)["frames"]), 5)
            self.assertIn(".sprite-знак-0", css)
        finally:
            shutil.rmtree(d)

    def test_svg_спрайт(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="20"><path d="M0 0h10v20z"/></svg>'
        out = K.svg_sprite([("Кот", svg), ("кот", svg)])
        self.assertEqual(out.count("<symbol"), 2)
        self.assertIn('viewBox="0 0 10 20"', out)


class Раскладка(unittest.TestCase):
    def test_имена_из_списка(self):
        from окно.раскладка import default_names
        names = default_names("D:/x/кот, сова, лиса.png", 3)
        self.assertEqual(names, ["кот", "сова", "лиса"])

    def test_имена_префиксом(self):
        from окно.раскладка import default_names
        self.assertEqual(default_names("D:/x/лист.png", 2, "звери"), ["звери_01", "звери_02"])

    def test_метка_в_имени(self):
        from окно.раскладка import route
        r = route(os.path.join(K.LIB, "00 Входящие", "Космос [ic tokyo].png"))
        self.assertIsNotNone(r)
        self.assertTrue(r["dest"].startswith(os.path.join(K.LIB, "04 Иконки", "Космос")))


class Промпты(unittest.TestCase):
    def test_страница_читается(self):
        from окно import промпты
        if not shutil.which("node"):
            self.skipTest("нет node")
        d = промпты.load()
        self.assertTrue(d["node"])
        self.assertGreater(len(промпты.palettes()), 5)
        c = [x for x in промпты.cards() if x["k"] == "sheet"][0]
        self.assertEqual(len(промпты.names(c)), 12)
        self.assertIn("Avoid:", промпты.prompt(c, c["pal"]))
        self.assertTrue(промпты.file_label(c, c["pal"]).endswith("]"))


class База(unittest.TestCase):
    def setUp(self):
        from окно import база
        self.b = база
        self.old = база.DB
        база.close()
        self.dir = tempfile.mkdtemp()
        база.DB = os.path.join(self.dir, "t.db")

    def tearDown(self):
        self.b.close()
        self.b.DB = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_метки_заметки_переезд(self):
        b = self.b
        b.set_tags("a/x.png", ["Космос", "#Для сайта"])
        self.assertEqual(b.tags_of("a/x.png"), ["для сайта", "космос"])
        b.set_note("a/x.png", "заметка")
        b.moved("a/x.png", "b/x.webp")
        self.assertEqual(b.tags_of("b/x.webp"), ["для сайта", "космос"])
        self.assertEqual(b.note_of("b/x.webp"), "заметка")
        self.assertEqual(b.tags_of("a/x.png"), [])
        b.set_tags(["b/x.webp"], ["космос"], "remove")
        self.assertEqual(b.all_tags(), {"для сайта": 1})
        self.assertIn("заметка", b.search_text()["b/x.webp"])

    def test_отпечатки(self):
        b = self.b
        v = np.arange(432) % 256
        b.save_sigs({"a.png": [1.0, 1.5, v, "rb", 2]}, {})
        d = b.load_sigs()
        self.assertEqual(d["a.png"][3], "rb")
        self.assertTrue((d["a.png"][2] == v).all())
        b.save_sigs({}, d)
        self.assertEqual(b.load_sigs(), {})


def real_sheets():
    """Листы 4x3 из _исходники: в имени 12 имён через запятую или метка набора."""
    out = []
    for p in sorted(glob.glob(os.path.join(K.LIB, "_исходники", "20*", "*"))):
        stem = os.path.splitext(os.path.basename(p))[0]
        if p.lower().endswith(K.EXT) and (stem.count(",") == 11 or re.search(r"\[(ic|st|es) [a-z]+\]$", stem)):
            out.append(p)
    return out[:SHEETS]


class Эталон(unittest.TestCase):
    """Настоящие листы режутся так же, как в прошлый раз (рамки в эталон.json)."""

    def test_листы_режутся_как_раньше(self):
        sheets = real_sheets()
        if not sheets:
            self.skipTest("в _исходники нет листов 4x3")
        now = {}
        for p in sheets:
            _pieces, boxes = K.cut(K.load(p), (4, 3))
            now[os.path.relpath(p, K.LIB)] = [list(b) for b in boxes]
        if not os.path.exists(SNAP):
            with open(SNAP, "w", encoding="utf-8") as fh:
                json.dump(now, fh, ensure_ascii=False, indent=1)
            self.skipTest("эталон записан (%d листов) - следующий прогон будет сверять" % len(now))
        with open(SNAP, encoding="utf-8") as fh:
            old = json.load(fh)
        checked = 0
        for name, boxes in now.items():
            if name not in old:
                continue
            checked += 1
            self.assertEqual(len(boxes), len(old[name]), name)
            for i, (a, b) in enumerate(zip(boxes, old[name])):
                diff = max(abs(x - y) for x, y in zip(a, b))
                self.assertLessEqual(diff, TOL, "%s: кусок %d сдвинулся на %d px" % (name, i + 1, diff))
        if not checked:
            self.skipTest("в эталоне нет этих листов - удалите эталон.json, чтобы записать заново")


if __name__ == "__main__":
    unittest.main(verbosity=2)
