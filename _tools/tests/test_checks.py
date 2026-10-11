"""Проверки манеры и проекта: выбивается из набора, контраст на фонах, авторы и лицензии, бюджет сцены.
На временной библиотеке; Blender не нужен (упрощение проверяется только на отказах)."""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PIL import Image, ImageDraw

import library.common as C
from imaging import contrast, style
from library import api, budget, credits, db, style_check


def sticker(fill, outline=(255, 255, 255, 255), size=128, shape="ellipse"):
    """Наклейка: фигура с белой обводкой на прозрачном."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = (10, 10, size - 10, size - 10)
    draw = d.ellipse if shape == "ellipse" else d.rectangle
    draw(box, fill=outline)
    draw((18, 18, size - 18, size - 18), fill=fill)
    return im


class Style(unittest.TestCase):
    def test_same_manner_is_quiet_and_stranger_is_found(self):
        purple = [(120 + i * 6, 90, 230, 255) for i in range(7)]
        feats = {
            f"p{i}": style.features(sticker(c, shape="rect" if i % 2 else "ellipse")) for i, c in enumerate(purple)
        }
        self.assertEqual(style.odd_ones(feats), {})
        feats["green"] = style.features(sticker((40, 200, 60, 255)))
        feats["no-outline"] = style.features(sticker((130, 90, 230, 255), outline=(130, 90, 230, 255)))
        odd = style.odd_ones(feats)
        self.assertIn("green", odd)
        self.assertIn("no-outline", odd)
        self.assertTrue(any(n == "rim" and s < 0 for n, s in odd["no-outline"]))
        self.assertEqual(style.reason("rim", -5), "нет светлой обводки или она темнее")

    def test_small_set_is_not_judged(self):
        feats = {f"p{i}": style.features(sticker((120, 90, 230, 255))) for i in range(style.MIN_SET - 1)}
        feats["green"] = style.features(sticker((40, 200, 60, 255)))
        self.assertEqual(style.odd_ones(dict(list(feats.items())[: style.MIN_SET - 1])), {})

    def test_empty_picture(self):
        self.assertIsNone(style.features(Image.new("RGBA", (64, 64), (0, 0, 0, 0))))


class Contrast(unittest.TestCase):
    def test_wcag_ratio(self):
        self.assertAlmostEqual(
            float(contrast.ratio(contrast.luminance([255, 255, 255]), contrast.luminance([0, 0, 0]))), 21.0, 1
        )

    def test_outline_saves_on_dark_not_on_white(self):
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.png")
            sticker((120, 90, 230, 255)).save(p)
            r = contrast.check(p, [("Белый", "#ffffff"), ("Тёмный", "#1e1e24")])
            by = {b["name"]: b for b in r["bgs"]}
            self.assertEqual(by["Тёмный"]["verdict"], "хорошо")
            self.assertEqual(by["Белый"]["verdict"], "плохо видно")
            self.assertEqual(r["worst"]["name"], "Белый")
            Image.new("RGB", (64, 64), (10, 10, 10)).save(os.path.join(tmp, "bg.png"))
            self.assertIsNone(contrast.check(os.path.join(tmp, "bg.png"), [("Белый", "#ffffff")]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class OnLibrary(unittest.TestCase):
    """Временная библиотека с базой: выбивается из набора, контраст через api, авторы и лицензии."""

    def setUp(self):
        self.lib = tempfile.mkdtemp()
        self.proj = tempfile.mkdtemp()
        self.old = {k: getattr(C, k) for k in ("LIB", "CFG")}
        C.LIB = self.lib
        C.CFG = os.path.join(self.lib, "settings.json")
        self.old_db = db.DB
        db.close()
        db.DB = os.path.join(self.lib, "t.db")
        self.set = os.path.join(self.lib, "04 Иконки", "Тест")
        os.makedirs(self.set)
        for i in range(7):
            sticker((120 + i * 6, 90, 230, 255)).save(os.path.join(self.set, f"p{i}.png"))
        sticker((40, 200, 60, 255)).save(os.path.join(self.set, "green.png"))
        cc = os.path.join(self.lib, "07 Паттерны и текстуры", "Чужие")
        os.makedirs(cc)
        sticker((200, 200, 200, 255)).save(os.path.join(cc, "x.png"))
        with open(os.path.join(cc, credits.LICENSE_FILE), "w", encoding="utf-8") as fh:
            fh.write("Автор - https://example.com\nЛицензия: CC BY 4.0 - при публикации указать автора.\n")

    def tearDown(self):
        db.close()
        db.DB = self.old_db
        for k, v in self.old.items():
            setattr(C, k, v)
        shutil.rmtree(self.lib, ignore_errors=True)
        shutil.rmtree(self.proj, ignore_errors=True)

    def test_odd_ones_in_library_and_api(self):
        found = style_check.odd_ones()
        self.assertEqual([os.path.basename(x["path"]) for x in found], ["green.png"])
        r = api.call("odd_ones", {})
        self.assertEqual(r["found"], 1)
        self.assertTrue(r["items"][0]["why"])

    def test_contrast_api(self):
        r = api.call("contrast", {"paths": ["04 Иконки/Тест/p0.png"], "backgrounds": ["#000000"]})
        names = [b["name"] for b in r["items"][0]["backgrounds"]]
        self.assertIn("#000000", names)
        with self.assertRaises(api.ApiError):
            api.call("contrast", {"paths": ["04 Иконки/Тест/p0.png"], "backgrounds": ["чёрный"]})

    def test_credits_lists_exports_and_attribution(self):
        dest = os.path.join(self.proj, "img")
        db.log_export(
            [os.path.join("04 Иконки", "Тест", "p0.png"), os.path.join("07 Паттерны и текстуры", "Чужие", "x.png")],
            dest,
        )
        db.log_export([os.path.join("04 Иконки", "Тест", "p1.png")], os.path.join(self.lib, "..", "другой проект"))
        res = credits.write(self.proj, {})
        self.assertEqual(res["images"], 2)
        self.assertEqual(res["attribution"], ["Автор - https://example.com"])
        with open(res["path"], encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Нужно указать автора", text)
        self.assertIn("p0.png", text)
        self.assertNotIn("p1.png", text)
        # чужой CREDITS.md не переписывается
        with open(res["path"], "w", encoding="utf-8") as fh:
            fh.write("# мои титры\n")
        res2 = credits.write(self.proj, {})
        self.assertTrue(res2["path"].endswith("CREDITS.library.md"))
        with open(os.path.join(self.proj, "CREDITS.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "# мои титры\n")

    def test_credits_api_refuses_library_folder(self):
        with self.assertRaises(api.ApiError):
            api.call("credits", {"project": self.lib})


class Budget(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        tex = os.path.join(self.dir, "textures")
        os.makedirs(tex)
        Image.new("RGB", (1024, 1024)).save(os.path.join(tex, "leaf_diff_1k.png"))
        Image.new("RGB", (1024, 1024)).save(os.path.join(tex, "leaf_nor_gl_1k.png"))
        Image.new("L", (1024, 1024)).save(os.path.join(tex, "leaf_alpha_1k.png"))
        Image.new("L", (1024, 1024)).save(os.path.join(tex, "leaf_disp_1k.png"))
        Image.new("RGB", (512, 512)).save(os.path.join(self.dir, "preview.webp"))
        with open(os.path.join(self.dir, "plant.fbx"), "wb") as fh:
            fh.write(b"x")
        self.a = dict(
            dir=self.dir, id="plant", name="Plant", kind="model", polycount=2_500_000, main=["plant.fbx"], size=10
        )

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_scene_counts_and_advice(self):
        r = budget.scene([self.a])
        x = r["items"][0]
        self.assertEqual(x["textures"], 4)  # превью не в счёт
        # цвет BC1 0.5 + нормаль 1 + маска 1, смещение не нужно; плюс мипы
        self.assertAlmostEqual(x["gpu_mb"], round(1024 * 1024 * 2.5 * 4 / 3 / 2**20, 1), 1)
        self.assertEqual(x["level"], "heavy")
        self.assertIn("маской", x["advice"])
        self.assertEqual(r["total"]["heavy"], 1)
        self.assertEqual(budget.advice(dict(kind="model", polycount=5000))[0], "ok")
        self.assertEqual(budget.advice(dict(kind="model", polycount=300_000, rigged=True))[0], "heavy")

    def test_simplified_copy_is_used_for_import(self):
        with open(os.path.join(self.dir, "plant_100k.fbx"), "wb") as fh:
            fh.write(b"y")
        with open(os.path.join(self.dir, budget.STORE), "w", encoding="utf-8") as fh:
            json.dump([dict(file="plant_100k.fbx", triangles=99_000, ratio=0.04, made="2026-10-11", use=True)], fh)
        self.assertEqual(budget.for_import(self.a)["main"], ["plant_100k.fbx"])
        budget.set_active(self.a, None)
        self.assertIs(budget.for_import(self.a), self.a)
        with self.assertRaises(ValueError):
            budget.simplify(dict(self.a, rigged=True, polycount=None), 1000, blender="нет")

    def test_simplify_refuses_light_model(self):
        with self.assertRaises(ValueError):
            budget.simplify(dict(self.a, polycount=500), 1000, blender="нет")


if __name__ == "__main__":
    unittest.main()
