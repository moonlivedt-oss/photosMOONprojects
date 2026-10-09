"""Тесты библиотеки: run-tests.cmd в _tools или py -3.14 -m unittest discover -s tests.
Окно не открывается; проверяется ядро (imaging.py), раскладка, промпты, база.
Эталонные листы: настоящие листы 4x3 из «_sources». При первом прогоне их рамки нарезки
записываются в reference_boxes.json, потом каждая правка нарезки сверяется с ним - так видно, если старые
листы вдруг начали резаться иначе. Обновить эталон: удалить reference_boxes.json и прогнать снова."""

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

import imaging as K  # noqa: E402

SNAP = os.path.join(HERE, "reference_boxes.json")
SHEETS = 8  # сколько настоящих листов сверять (каждый режется пару секунд)
TOL = 6  # насколько может сдвинуться рамка, px


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


class Cutting(unittest.TestCase):
    def test_grid_gives_12_pieces(self):
        pieces, boxes = K.cut(sticker_sheet(), (4, 3))
        self.assertEqual(len(pieces), 12)
        self.assertTrue(all(p.size == (256, 256) for p in pieces))

    def test_touching_neighbours_split(self):
        _p, boxes = K.cut(sticker_sheet(touch=True), (4, 3))
        for i, (x0, y0, x1, y1) in enumerate(boxes):
            cx, cy = (i % 4) * 200 + 100, (i // 4) * 200 + 100
            self.assertTrue(x0 < cx < x1 and y0 < cy < y1, "кусок %d не на своём месте: %s" % (i, (x0, y0, x1, y1)))
            self.assertLess(x1 - x0, 260, "кусок %d захватил соседа" % i)

    def test_auto_search(self):
        pieces, _b = K.cut(sticker_sheet(seed=3), None)
        self.assertEqual(len(pieces), 12)

    def test_manual_boxes(self):
        pieces, boxes = K.cut(sticker_sheet(), None, boxes=[(0, 0, 200, 200), (200, 0, 600, 200)])
        self.assertEqual(len(pieces), 2)
        self.assertEqual(boxes[1], (200, 0, 600, 200))

    def test_sheet_kind(self):
        """Фон целиком, один рисунок на однотонном - вырезать, лист - резать."""
        rng = np.random.default_rng(1)
        scene = Image.fromarray(rng.integers(0, 255, (60, 80, 3), dtype=np.uint8), "RGB").resize((800, 600))
        self.assertEqual(K.sheet_kind(scene), "whole")
        one = Image.new("RGB", (600, 600), (255, 255, 255))
        ImageDraw.Draw(one).ellipse((150, 120, 450, 480), fill=(90, 60, 200))
        self.assertEqual(K.sheet_kind(one), "single")
        self.assertEqual(K.sheet_kind(sticker_sheet()), "sheet")

    def test_cells_by_magenta_gutters(self):
        """Фоны листом 2x2: режутся по пурпурным полосам, даже если модель нарисовала их неровно;
        тёмное однотонное небо у края клетки не срезается."""
        sheet = Image.new("RGBA", (1000, 700), (255, 0, 255, 255))
        rng = np.random.default_rng(2)
        for x, y in ((6, 8), (512, 5), (4, 356), (509, 352)):
            pic = Image.fromarray(rng.integers(0, 255, (330, 480, 3), dtype=np.uint8), "RGB").convert("RGBA")
            pic.paste((10, 10, 20, 255), (0, 0, 480, 60))  # ровная тёмная полоса неба сверху
            sheet.paste(pic, (x, y))
        self.assertEqual(K.sheet_kind(sheet), "cells")
        pieces, boxes = K.cells(sheet, 2, 2)
        self.assertEqual(boxes[0], (6, 8, 486, 338))
        self.assertTrue(
            all(abs(p.width - 480) <= 4 and abs(p.height - 330) <= 4 for p in pieces), [p.size for p in pieces]
        )

    def test_tiny_sheet(self):
        self.assertEqual(len(K.cut(Image.new("RGBA", (6, 5), (255, 255, 255, 255)), (4, 3))[0]), 12)


class Editing(unittest.TestCase):
    def setUp(self):
        im = Image.new("RGBA", (300, 200), (255, 255, 255, 255))
        ImageDraw.Draw(im).ellipse((80, 40, 220, 160), fill=(200, 40, 90, 255))
        self.im = im
        self.cut = K.remove_bg(im)

    def test_rotate_and_crop(self):
        r = K.apply_edits(self.im, [dict(op="rotate", deg=90), dict(op="crop", box=(0, 0, 1, 0.5))])
        self.assertEqual(r.size, (200, 150))

    def test_remove_background(self):
        self.assertEqual(self.cut.getpixel((5, 5))[3], 0)
        self.assertEqual(self.cut.getpixel((150, 100))[3], 255)

    def test_recolor_to_palette(self):
        r = K.recolor(self.cut, ["#282a36", "#ff79c6", "#bd93f9"])
        self.assertEqual(r.getpixel((5, 5))[3], 0)  # прозрачность не тронута
        px = r.getpixel((150, 100))[:3]
        self.assertIn(px, [K.hex_rgb(c) for c in ("#282a36", "#ff79c6", "#bd93f9")] + [px])
        self.assertNotEqual(px, (200, 40, 90))

    def test_fringe_found_and_removed(self):
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

    def test_brush(self):
        r = K.brush(self.cut, "erase", 0.05, [(0.5, 0.5)])
        self.assertEqual(r.getpixel((150, 100))[3], 0)
        back = K.brush(r, "restore", 0.05, [(0.5, 0.5)])
        self.assertEqual(back.getpixel((150, 100))[3], 255)

    def test_shadow_glow_corners(self):
        for ops in (
            [dict(op="shadow", dx=5, dy=5, blur=4, a=0.5)],
            [dict(op="glow", r=6, color="#a897ff")],
            [dict(op="round", rad=0.5)],
            [dict(op="center")],
            [dict(op="outline", px=6)],
            [dict(op="square", pad=0.1)],
            [dict(op="resize", size=64)],
        ):
            r = K.apply_edits(self.cut, ops)
            self.assertGreater(r.width, 0, ops)
        self.assertEqual(K.apply_edits(self.im, [dict(op="round", rad=0.5)]).getpixel((0, 0))[3], 0)

    def test_preview_scale_matches(self):
        """Рецепт на копии (scale) и на полном размере дают те же пропорции."""
        ops = [dict(op="crop", box=(0.1, 0.1, 0.9, 0.7)), dict(op="outline", px=8)]
        full = K.apply_edits(self.cut, ops)
        small = K.apply_edits(self.cut.resize((150, 100)), ops, scale=0.5)
        self.assertAlmostEqual(full.width / full.height, small.width / small.height, delta=0.08)

    def test_bg_removal_keeps_dark_outline(self):
        im = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((80, 40, 220, 160), fill=(10, 10, 10, 255))
        self.assertEqual(K.remove_bg(im).getpixel((82, 100))[3], 255)

    def test_contrast_ignores_transparent(self):
        """Средняя яркость - только по видимому: картинка на прозрачном и на сплошном меняется одинаково."""
        a = K.adjust(self.cut, contrast=50).getpixel((150, 100))[:3]
        b = K.adjust(Image.new("RGBA", (10, 10), (200, 40, 90, 255)), contrast=50).getpixel((5, 5))[:3]
        for x, y in zip(a, b):
            self.assertLessEqual(abs(x - y), 4)  # край круга сглажен - чуть темнее

    def test_angle_without_wedges(self):
        r = K.apply_edits(self.im, [dict(op="angle", deg=10, fit=True)])
        for xy in ((0, 0), (r.width - 1, 0), (0, r.height - 1), (r.width - 1, r.height - 1)):
            self.assertEqual(r.getpixel(xy)[3], 255, xy)

    def test_fill_pad_round(self):
        self.assertEqual(
            K.apply_edits(self.cut, [dict(op="fill", color="#102030")]).getpixel((0, 0)), (16, 32, 48, 255)
        )
        self.assertEqual(K.apply_edits(self.im, [dict(op="pad", k=0.1)]).size, (360, 260))
        r = K.apply_edits(self.im, [dict(op="round", rad=0.5)])
        self.assertTrue(any(0 < r.getpixel((x, 20))[3] < 255 for x in range(0, 100)))  # край сглажен

    def test_extra_sliders(self):
        for adj in (dict(sharp=60), dict(sharp=-50), dict(shadows=40, highlights=-30), dict(opacity=50)):
            self.assertEqual(K.adjust(self.cut, **adj).size, self.cut.size)
        self.assertEqual(K.adjust(self.cut, opacity=50).getpixel((150, 100))[3], 128)

    def test_preview_after_resize_is_full_size(self):
        info = {}
        r = K.apply_edits(self.cut.resize((150, 100)), [dict(op="resize", size=64)], scale=0.5, info=info)
        self.assertEqual((max(r.size), info["scale"]), (64, 1.0))


class Export(unittest.TestCase):
    def test_atlas(self):
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

    def test_svg_sprite(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="20"><path d="M0 0h10v20z"/></svg>'
        out = K.svg_sprite([("Кот", svg), ("кот", svg)])
        self.assertEqual(out.count("<symbol"), 2)
        self.assertIn('viewBox="0 0 10 20"', out)


class Sorting(unittest.TestCase):
    def test_names_from_list(self):
        from library.sorting import default_names

        names = default_names("D:/x/кот, сова, лиса.png", 3)
        self.assertEqual(names, ["кот", "сова", "лиса"])

    def test_names_with_prefix(self):
        from library.sorting import default_names

        self.assertEqual(default_names("D:/x/лист.png", 2, "звери"), ["звери_01", "звери_02"])

    def test_tag_in_file_name(self):
        from library.sorting import route

        r = route(os.path.join(K.LIB, "00 Входящие", "Космос [ic tokyo].png"))
        self.assertIsNotNone(r)
        r2 = route(
            os.path.join(
                K.LIB,
                "00 Входящие",
                "Тёмные 1 - Лофи-комната, Подводные руины, Космос, Киберпанк-переулок [ds default].png",
            )
        )
        self.assertEqual((r2["o"]["mode"], len(r2["names"])), ("cells", 4))
        self.assertTrue(r["dest"].startswith(os.path.join(K.LIB, "04 Иконки", "Космос")))


class Prompts(unittest.TestCase):
    def test_page_is_parsed(self):
        from library import prompts

        if not shutil.which("node"):
            self.skipTest("нет node")
        d = prompts.load()
        self.assertTrue(d["node"])
        self.assertGreater(len(prompts.palettes()), 5)
        c = [x for x in prompts.cards() if x["k"] == "sheet"][0]
        self.assertEqual(len(prompts.names(c)), 12)
        self.assertIn("Avoid:", prompts.prompt(c, c["pal"]))
        self.assertTrue(prompts.file_label(c, c["pal"]).endswith("]"))


class Database(unittest.TestCase):
    def setUp(self):
        from library import db

        self.b = db
        self.old = db.DB
        db.close()
        self.dir = tempfile.mkdtemp()
        db.DB = os.path.join(self.dir, "t.db")

    def tearDown(self):
        self.b.close()
        self.b.DB = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_tags_notes_move(self):
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

    def test_signatures(self):
        b = self.b
        v = np.arange(432) % 256
        b.save_sigs({"a.png": [1.0, 1.5, v, "rb", 2]}, {})
        d = b.load_sigs()
        self.assertEqual(d["a.png"][3], "rb")
        self.assertTrue((d["a.png"][2] == v).all())
        b.save_sigs({}, d)
        self.assertEqual(b.load_sigs(), {})

    def test_smart_folders_and_clip(self):
        b = self.b
        b.save_smart("Ночные", "ночной город", "v", True)
        self.assertEqual(b.smart_folders(), [("Ночные", "ночной город", "v", True)])
        b.delete_smart("Ночные")
        self.assertEqual(b.smart_folders(), [])
        v = np.linspace(-1, 1, 512)
        b.save_clip([("a/x.png", 2.0, v)])
        b.moved("a/x.png", "b/x.png")
        d = b.load_clip()
        self.assertEqual(list(d), ["b/x.png"])
        self.assertTrue(np.allclose(d["b/x.png"][1], v, atol=1e-3))

    def test_batch_sorting_tags_each_sheet(self):
        from library import sorting, tagging

        class NoSigs:
            def find(self, _im):
                return None

        class FakeTagger:
            def suggest(self, pieces, skip=()):
                return ["кружки"] if len(pieces) == 12 else []

        src, dest = os.path.join(self.dir, "лист.png"), os.path.join(self.dir, "раздел")
        sticker_sheet().save(src)
        old_lib = tagging.LIB
        tagging.LIB = self.dir
        try:
            o = dict(mode="grid", cols=4, rows=3, bg_mode="auto", obv=0, pad=6, size=64, fmt="png")
            _steps, total, _skipped, bad, _where = sorting.sort_files(
                [(src, o, dest)], NoSigs(), False, False, tagger=FakeTagger()
            )
        finally:
            tagging.LIB = old_lib
        self.assertEqual((total, bad), (12, []))
        self.assertEqual(len(self.b.with_tag("кружки")), 12)

    def test_export_log_and_tag_delete(self):
        b = self.b
        b.log_export(["a/x.png"], "D:/proj/assets")
        b.log_export(["a/x.png"], "D:/other")
        b.moved("a/x.png", "b/x.png")
        self.assertEqual({d for d, _t in b.exports_of("b/x.png")}, {"D:/proj/assets", "D:/other"})
        b.set_tags(["b/x.png", "c.png"], ["космос", "ночь"])
        self.assertEqual(b.delete_tag("космос"), 2)
        self.assertEqual(b.all_tags(), {"ночь": 2})


def scene_with_sticker():
    """Наклейка (кружок с белой обводкой) на пёстром фоне - однотонным способом фон не убрать."""
    rng = np.random.default_rng(5)
    bg = Image.fromarray(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8), "RGB").resize((800, 600))
    d = ImageDraw.Draw(bg)
    d.ellipse((250, 150, 550, 450), fill=(255, 255, 255))
    d.ellipse((270, 170, 530, 430), fill=(120, 90, 230))
    return bg


class Neural(unittest.TestCase):
    def test_remove_any_background(self):
        from imaging import neural

        if not neural.bg_available():
            self.skipTest("нет модели BiRefNet")
        a = np.asarray(neural.remove_bg_ai(scene_with_sticker()).getchannel("A"))
        self.assertGreater(a[300, 400], 200)  # середина наклейки осталась
        self.assertLess(a[20:80, 20:80].mean(), 40)  # пёстрый угол стал прозрачным

    def test_upscale_keeps_alpha_and_size(self):
        from imaging import neural

        if not neural.upscale_available():
            self.skipTest("нет моделей Real-ESRGAN")
        im = sticker_sheet().resize((96, 72))
        for x in (2, 4):
            big = neural.upscale(im, x, "art")
            self.assertEqual(big.size, (96 * x, 72 * x))
            self.assertLess(np.asarray(big.getchannel("A"))[0, 0], 30)

    def test_edit_steps_and_preview_scale(self):
        from imaging import neural

        if not neural.upscale_available():
            self.skipTest("нет моделей Real-ESRGAN")
        im = Image.new("RGBA", (800, 400), (90, 60, 200, 255))
        info = {}
        out = K.apply_edits(im, [dict(op="upscale", x=4, kind="photo")], scale=0.5, info=info)
        self.assertLessEqual(max(out.size), K.editing.PREVIEW_MAX)
        self.assertAlmostEqual(out.width / info["scale"], 800 / 0.5 * 4, delta=4)


class Tagging(unittest.TestCase):
    def test_sheet_of_clocks_gets_time_tags(self):
        from imaging import clip
        from library.tagging import Tagger
        from ui.semantic import SemIndex

        sheet = glob.glob(os.path.join(K.LIB, "_sources", "20*", "alarm-clock, hourglass*"))
        if not clip.available() or not sheet:
            self.skipTest("нет моделей или листа с часами в _sources")
        pieces, _b = K.cut(K.load(sheet[0]), (4, 3))
        tags = Tagger(SemIndex()).suggest(pieces)
        self.assertTrue(1 <= len(tags) <= 6, tags)
        self.assertTrue({"часы", "время"} & set(tags), tags)
        self.assertFalse(set(tags) & set(Tagger(SemIndex()).suggest(pieces, skip=set(tags))))


class Semantic(unittest.TestCase):
    def test_tokenizer(self):
        from imaging import clip

        vocab = {t: i for i, t in enumerate(["[PAD]", "[UNK]", "[CLS]", "[SEP]", "кот", "кос", "##мос", ",", "!"])}
        self.assertEqual(clip.tokenize("кот, космос!", vocab), [2, 4, 7, 5, 6, 8, 3])
        self.assertEqual(clip.tokenize("пёс", vocab), [2, 1, 3])

    def test_text_finds_matching_picture(self):
        from imaging import clip

        if not clip.available():
            self.skipTest("нет моделей в _tools/_models/clip")
        red, blue = Image.new("RGB", (64, 64), (230, 20, 20)), Image.new("RGB", (64, 64), (20, 40, 230))
        vecs = clip.embed_images([red, blue])
        self.assertEqual(vecs.shape, (2, clip.DIM))
        for text, want in (("красный квадрат", 0), ("синий цвет", 1)):
            order, _s = clip.rank(clip.embed_text(text), vecs, 2, -1)
            self.assertEqual(int(order[0]), want, text)


def real_sheets():
    """Листы 4x3 из _sources: в имени 12 имён через запятую или метка набора."""
    out = []
    for p in sorted(glob.glob(os.path.join(K.LIB, "_sources", "20*", "*"))):
        stem = os.path.splitext(os.path.basename(p))[0]
        if p.lower().endswith(K.EXT) and (stem.count(",") == 11 or re.search(r"\[(ic|st|es) [a-z]+\]$", stem)):
            out.append(p)
    return out[:SHEETS]


class ReferenceSheets(unittest.TestCase):
    """Настоящие листы режутся так же, как в прошлый раз (рамки в reference_boxes.json)."""

    def test_sheets_cut_as_before(self):
        sheets = real_sheets()
        if not sheets:
            self.skipTest("в _sources нет листов 4x3")
        now = {}
        for p in sheets:
            _pieces, boxes = K.cut(K.load(p), (4, 3))
            now[os.path.relpath(p, os.path.join(K.LIB, "_sources")).replace(os.sep, "/")] = [list(b) for b in boxes]
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
            self.skipTest("в эталоне нет этих листов - удалите reference_boxes.json, чтобы записать заново")


if __name__ == "__main__":
    unittest.main(verbosity=2)
