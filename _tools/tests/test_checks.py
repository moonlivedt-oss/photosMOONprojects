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

    def test_outline_lost_on_white_but_drawing_visible(self):
        """Белая обводка на белом сливается, но тёмный рисунок за ней виден - «хорошо» с пометкой;
        бледная фигура без контура на белом - «плохо видно», средняя - «так себе»."""
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "s.png")
            sticker((120, 90, 230, 255)).save(p)
            r = contrast.check(p, [("Белый", "#ffffff"), ("Тёмный", "#1e1e24")])
            by = {b["name"]: b for b in r["bgs"]}
            self.assertEqual(by["Тёмный"]["verdict"], "хорошо")
            self.assertEqual(by["Белый"]["verdict"], "хорошо")
            self.assertIn("обводка", by["Белый"]["note"])
            for name, fill, want in (
                ("pale", (220, 214, 255, 255), "плохо видно"),
                ("mid", (170, 160, 240, 255), "так себе"),
            ):
                q = os.path.join(tmp, name + ".png")
                im = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
                ImageDraw.Draw(im).ellipse((10, 10, 118, 118), fill=fill)
                im.save(q)
                self.assertEqual(contrast.check(q, [("Белый", "#ffffff")])["worst"]["verdict"], want)
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


class Scale(unittest.TestCase):
    def kit(self, names, dims, url="https://kenney.nl/assets/furniture-kit"):
        return [
            dict(id=f"k-{n}", name=n, kind="model", source="Kenney", url=url, dims_cm=d, dir=f"/x/{n}")
            for n, d in zip(names, dims)
        ]

    def test_pack_factor_found(self):
        from library import scale_check

        items = self.kit(
            ["Chair", "Table", "Bed single", "Sofa", "Lamp round floor", "Door"],
            [[200, 200, 470], [841, 447, 380], [571, 1125, 375], [700, 400, 450], [152, 175, 860], [400, 40, 1100]],
        )
        r = scale_check.check(items)
        self.assertEqual(len(r["packs"]), 1)
        self.assertEqual(r["packs"][0]["factor"], 0.2)
        self.assertEqual(r["items"], [])

    def test_parts_and_false_friends_skipped(self):
        from library import scale_check

        for name in ("Wheel truck", "Warning orange", "Debris door", "Flower bed", "Platform center plate"):
            self.assertIsNone(scale_check._rule(name), name)
        self.assertEqual(scale_check._rule("Chair desk")[0], "h")

    def test_single_item_and_real_sizes(self):
        from library import scale_check

        ok = self.kit(["Chair", "Table", "Door"], [[45, 45, 95], [120, 80, 75], [90, 10, 210]], url="u")
        odd = self.kit(["Mug"], [[30, 30, 27]], url="u")
        r = scale_check.check(ok + odd)
        self.assertEqual([x["name"] for x in r["items"]], ["Mug"])
        self.assertEqual(r["items"][0]["factor"], 0.5)
        # у Poly Haven размеры настоящие - не проверяются
        ph = dict(self.kit(["Chair"], [[200, 200, 470]])[0], dimensions_mm=[2000, 2000, 4700])
        self.assertEqual(scale_check.check([ph])["items"], [])

    def test_scale_store_applies_to_dims_and_import(self):
        from library import unreal_extra as X
        from library import unreal_import

        tmp = tempfile.mkdtemp()
        old = X.SCALE_STORE, X.META_STORE, X.ROOT
        try:
            X.ROOT = tmp
            X.SCALE_STORE = os.path.join(tmp, "scale.json")
            X.META_STORE = os.path.join(tmp, "meta.json")
            d = os.path.join(tmp, "Chair")
            os.makedirs(d)
            with open(os.path.join(d, "chair.fbx"), "wb") as fh:
                fh.write(b"x")
            a = dict(id="k-chair", name="Chair", kind="model", dir=d, main=["chair.fbx"], _t=1.0)
            with open(X.META_STORE, "w", encoding="utf-8") as fh:
                json.dump({X._meta_key(a): {"triangles": 10, "dims_cm": [200, 200, 470]}}, fh)
            self.assertEqual(X.set_scale([a], 0.2), 1)
            got = X.apply_meta([dict(a)])[0]
            self.assertEqual(got["dims_cm"], [40.0, 40.0, 94.0])
            jobs = unreal_import.plan([a], os.path.join(tmp, "out"))
            self.assertEqual(jobs[0]["scale"], 0.2)
            X.set_scale([a], 1)
            self.assertEqual(X.scale_of(a), 1.0)
        finally:
            X.SCALE_STORE, X.META_STORE, X.ROOT = old
            shutil.rmtree(tmp, ignore_errors=True)


class Project(unittest.TestCase):
    def setUp(self):
        self.proj = tempfile.mkdtemp()
        css = os.path.join(self.proj, "css")
        os.makedirs(css)
        with open(os.path.join(css, "tokens.css"), "w", encoding="utf-8") as fh:
            fh.write(
                ":root { --paper: #edf1ec; --accent: #3ea2ff; }\n"
                "@media (prefers-color-scheme: dark) { :root:not([data-theme=light]) { --paper: #0e1412; } }\n"
                ":root[data-theme=dark] { --paper: #0e1412; }\n"
            )
        with open(os.path.join(css, "base.css"), "w", encoding="utf-8") as fh:
            fh.write("body { background: var(--paper); color: #222; }\n.btn { background: var(--accent); }\n")

    def tearDown(self):
        shutil.rmtree(self.proj, ignore_errors=True)

    def test_css_backgrounds_both_themes(self):
        from library import project_fit as P

        self.assertEqual([c for _n, c in P.css_backgrounds(self.proj)], ["#edf1ec", "#0e1412"])
        self.assertIn("#3ea2ff", P.css_accents(self.proj))

    def test_from_css_file_and_norm(self):
        from library import project_fit as P

        _bg, cols = P.from_css(os.path.join(self.proj, "css", "tokens.css"))
        self.assertIn("#3ea2ff", cols)
        self.assertEqual(P.norm("#ABC"), "#aabbcc")
        with self.assertRaises(ValueError):
            P.norm("красный")

    def test_score_takes_worst_background(self):
        from library import project_fit as P

        folder = os.path.join(self.proj, "set")
        os.makedirs(folder)
        files = []
        for i in range(4):
            f = os.path.join(folder, f"{i}.png")
            im = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse((8, 8, 88, 88), fill=(10, 10, 10, 255))  # чёрное - на тёмной теме пропадает
            im.save(f)
            files.append(f)
        st = P.set_stats(folder, files)
        self.assertGreater(P.score(st, "#ffffff", ["#ffffff"])["contrast"], 0.9)
        self.assertLess(P.score(st, ["#ffffff", "#0e1412"], ["#ffffff"])["contrast"], 0.3)


class Publish(OnLibrary):
    def test_publish_check_sections(self):
        from library import publish_check as PC

        dest = os.path.join(self.proj, "img")
        os.makedirs(dest)
        Image.new("RGB", (900, 900)).save(os.path.join(dest, "big.png"))
        db.log_export([os.path.join("07 Паттерны и текстуры", "Чужие", "x.png")], dest)
        r = PC.check(self.proj, {})
        self.assertEqual(r["licenses"]["attribution"], ["Автор - https://example.com"])
        self.assertEqual(r["licenses"]["level"], "bad")  # CC BY, а CREDITS.md нет
        self.assertEqual(r["weight"]["images"], 1)
        self.assertIn("Лицензии", PC.markdown(r))
        credits.write(self.proj, {})
        self.assertEqual(PC.check(self.proj, {})["licenses"]["level"], "warn")
        res = api.call("publish_check", {"project": self.proj, "save": True})
        self.assertTrue(os.path.exists(res["report"]))


if __name__ == "__main__":
    unittest.main()
