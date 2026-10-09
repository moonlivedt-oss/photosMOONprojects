"""Ассеты для Unreal: IES-профили, разбор asset.json, подбор по темам (без сети - каталог подменяется)."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from imaging import ies  # noqa: E402
from library import unreal as U  # noqa: E402


class TestIes(unittest.TestCase):
    def test_format(self):
        for name in ies.PROFILES:
            lines = ies.ies_text(name).splitlines()
            self.assertEqual(lines[0], "IESNA:LM-63-2002")
            i = lines.index("TILT=NONE")
            head = lines[i + 1].split()
            nv, nh = int(head[3]), int(head[4])
            nums = " ".join(lines[i + 3 :]).split()
            self.assertEqual(len(nums), nv + nh + nv * nh, name)  # углы и вся таблица на месте
            vals = [float(x) for x in nums[nv + nh :]]
            self.assertGreater(max(vals), 0, name)
            self.assertGreaterEqual(min(vals), 0, name)
            ies.ies_text(name).encode("ascii")  # внутри - только латиница

    def test_preview(self):
        im = ies.preview("Узкий луч", 64, 48)
        self.assertEqual(im.size, (64, 48))
        self.assertGreater(im.convert("L").getextrema()[1], 120)  # пятно видно

    def test_write_and_scan(self):
        tmp = tempfile.mkdtemp()
        try:
            dirs = ies.write_all(tmp)
            self.assertEqual(len(dirs), len(ies.PROFILES))
            found = U.assets(tmp)
            self.assertEqual(len(found), len(ies.PROFILES))
            for a in found:
                self.assertEqual(a["kind"], "ies")
                self.assertTrue(os.path.exists(os.path.join(a["dir"], a["main"][0])))
                self.assertTrue(a["main"][0].isascii())  # имя ассета в Unreal - латиницей
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestThemes(unittest.TestCase):
    CAT = {
        "brick_wall": {"name": "Brick Wall", "categories": ["brick", "wall"], "tags": [], "download_count": 5},
        "street_brick": {"name": "Street Bricks", "categories": ["brick"], "tags": ["road"], "download_count": 1},
        "floor_out": {"name": "Floor", "categories": ["floor", "outdoor"], "tags": [], "download_count": 99},
        "tiles": {"name": "Tiles 01", "categories": ["floor", "tiles"], "tags": [], "download_count": 2},
    }

    def test_match_and_order(self):
        with (
            mock.patch.object(U, "catalog", return_value=self.CAT),
            mock.patch.object(U, "acg_candidates", return_value=[]),
        ):
            got = [c["id"] for c in U.candidates("tex", "Город")]
            self.assertEqual(got[0], "street_brick")  # два совпадения важнее популярности
            self.assertIn("brick_wall", got)
            self.assertNotIn("tiles", got)
            inside = [c["id"] for c in U.candidates("tex", "Интерьер")]
            self.assertEqual(inside, ["tiles"])  # уличный пол в интерьер не попал
            self.assertEqual(U.candidates("tex", "Город", have={"street_brick", "brick_wall"}), [])

    def test_themes_cover_kinds(self):
        for th, spec in U.THEMES.items():
            self.assertTrue(any(spec.get(k) for k in ("tex", "hdri", "model", "kenney", "quaternius")), th)


class TestHomeSections(unittest.TestCase):
    def test_new_sections_by_words(self):
        for name, sec in (
            ("Rusted Hacksaw", "Инструменты"),
            ("Wooden Axe 02", "Инструменты"),
            ("Plastic Broom", "Хозяйство и уборка"),
            ("Trashcan small 1", "Хозяйство и уборка"),
            ("Baseball Bat", "Спорт и хобби"),
            ("Ukulele 01", "Спорт и хобби"),
            ("Rubber Boots", "Одежда и аксессуары"),
            ("Coat rack standing", "Одежда и аксессуары"),
            ("Antique Katana 01", "Декор"),
            ("Hood modern", "Кухня и посуда"),
            ("Bed double", "Кровати"),
            ("Table lamp", "Свет"),
        ):
            self.assertEqual(U.home_section({"name": name}), sec, name)
        self.assertEqual(U.home_section({"name": "Ocean Buoy"}), U.HOME_OTHER)
        for sec, _keys in U.HOME_SECTIONS:
            self.assertIn(sec, U.HOME_ORDER)

    def test_classify_only_when_sure(self):
        import numpy as np

        from library import unreal_sem as S

        prompts = {"Кровати": "a bed", "Свет": "a lamp", "Инструменты": "a hand tool"}
        basis = {f"a photo of {t}": np.eye(3, dtype=np.float32)[i] for i, t in enumerate(prompts.values())}

        class Sem:
            data = {}

        sem = Sem()
        sure = {"name": "x", "dir": "a"}
        unsure = {"name": "y", "dir": "b"}
        sem.data[S.key_of(sure)] = (np.float32([0, 1, 0]), np.float32([0, 1, 0]))  # и картинка, и имя - лампа
        sem.data[S.key_of(unsure)] = (np.float32([1, 0, 0]), np.float32([0, 0, 1]))  # картинка и имя спорят
        with mock.patch.object(S.clip, "embed_text", side_effect=lambda t: basis[t]):
            got = S.classify(sem, [sure, unsure, {"name": "z", "dir": "c"}], prompts)
        self.assertEqual(got, {"a": "Свет"})


class TestMaterials(unittest.TestCase):
    def test_round_robin_without_repeats(self):
        from library import unreal_sem as S

        tex = {n: {"name": n, "dir": n} for n in ("linen", "velvet", "leather", "oak")}

        class Sem:
            def rank(self, q, items):
                found = {"fabric upholstery": ["linen", "velvet", "leather"], "leather": ["leather", "linen"]}[q]
                return [(tex[n], 1.0) for n in found]

        got = S.materials_for(Sem(), "Диваны", list(tex.values()), top=3)
        self.assertEqual([a["name"] for a in got], ["linen", "leather", "velvet"])  # ткань, кожа, ткань
        self.assertIn("Диваны", S.MATERIALS)


class TestCatalog(unittest.TestCase):
    def test_guess_theme(self):
        self.assertEqual(
            U.guess_theme("model", {"categories": ["furniture", "seating"], "tags": ["chair"]}), "Дом - мебель"
        )
        self.assertEqual(U.guess_theme("model", {"categories": ["rocks"], "tags": ["boulder"]}), "Пустыня и скалы")
        self.assertEqual(U.guess_theme("model", {"categories": ["xyz"], "tags": []}), "Разное")

    def test_browse_sorted(self):
        cat = {"a": {"name": "A", "download_count": 1}, "b": {"name": "B", "download_count": 9}}
        with mock.patch.object(U, "catalog", return_value=cat):
            got = U.browse("model")
        self.assertEqual([c["id"] for c in got], ["b", "a"])
        self.assertTrue(all(c["thumb"].startswith("https://") for c in got))

    def test_refetch_only_known_sources(self):
        self.assertFalse(U.can_refetch({"source": "Kenney", "kind": "model"}))
        self.assertTrue(U.can_refetch({"source": "Poly Haven", "kind": "tex"}))
        with self.assertRaises(ValueError):
            U.refetch({"source": "Kenney", "kind": "model", "id": "x", "name": "x", "dir": "."}, "2k")


class TestImport(unittest.TestCase):
    def test_script_and_same_names(self):
        import ast
        import json

        from library import unreal_import

        tmp = tempfile.mkdtemp()
        try:
            src = []
            for pack in ("a", "b"):  # одно имя в двух наборах
                d = os.path.join(tmp, "src", pack)
                os.makedirs(d)
                open(os.path.join(d, "Stool.fbx"), "w").close()
                src.append({"name": "Stool", "kind": "model", "dir": d, "main": ["Stool.fbx"]})
            dst = os.path.join(tmp, "out")
            script = unreal_import.export(src, dst)
            self.assertEqual(sorted(os.listdir(dst)), ["Stool", "Stool_2", "import_to_unreal.py"])
            with open(script, encoding="utf-8") as fh:
                text = fh.read()
            compile(text, script, "exec")  # скрипт для Unreal - правильный Python
            jobs = json.loads(ast.literal_eval(text.split("JOBS = json.loads(", 1)[1].split(")\n", 1)[0]))
            self.assertEqual([j["dest"] for j in jobs], ["/Game/Library/Models/Stool", "/Game/Library/Models/Stool_2"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestPack(unittest.TestCase):
    def test_pack_folder_and_zip(self):
        import json
        import zipfile

        from library import unreal_pack

        tmp = tempfile.mkdtemp()
        try:
            d = os.path.join(tmp, "src", "oak")
            os.makedirs(d)
            open(os.path.join(d, "oak_diff_2k.jpg"), "wb").close()
            a = {
                "id": "oak",
                "name": "Oak Floor",
                "kind": "tex",
                "dir": d,
                "main": ["oak_diff_2k.jpg"],
                "source": "Poly Haven",
                "authors": ["Rico Cilliers"],
                "url": "https://polyhaven.com/a/oak",
                "license": "CC0 1.0",
            }
            folder = unreal_pack.pack([a], os.path.join(tmp, "out"), "Моя спальня")
            names = set(os.listdir(folder))
            self.assertTrue({"CREDITS.md", "manifest.json", "import_to_unreal.py", "Oak_Floor"} <= names)
            with open(os.path.join(folder, "CREDITS.md"), encoding="utf-8") as fh:
                credits = fh.read()
            self.assertIn("Rico Cilliers", credits)
            self.assertIn("CC0", credits)
            with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["assets"][0]["id"], "oak")
            arc = unreal_pack.pack([a], os.path.join(tmp, "out2"), "Моя спальня", zip_it=True)
            with zipfile.ZipFile(arc) as zf:
                self.assertTrue(any(n.endswith("CREDITS.md") for n in zf.namelist()))
            cfg = {}
            for _ in range(7):
                unreal_pack.remember_use(cfg, [a], "D:/Proj")
            self.assertEqual(cfg["ue_used"]["oak"], ["D:/Proj"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestFiles(unittest.TestCase):
    def test_inside(self):
        root = os.path.join("C:\\", "lib", "a")
        self.assertEqual(U.inside(root, "textures/x.jpg"), os.path.join(root, "textures", "x.jpg"))
        for bad in ("../x.jpg", "textures/../../x.jpg", "C:/Windows/x.dll", "/etc/x", ""):
            with self.assertRaises(OSError, msg=bad):
                U.inside(root, bad)

    def test_put_in_place_replaces(self):
        tmp = tempfile.mkdtemp()
        try:
            dst, new = os.path.join(tmp, "Chair"), os.path.join(tmp, "Chair.part")
            os.makedirs(dst)
            os.makedirs(new)
            open(os.path.join(dst, "old.fbx"), "w").close()
            open(os.path.join(new, "new.fbx"), "w").close()
            U.put_in_place(new, dst)
            self.assertEqual(sorted(os.listdir(tmp)), ["Chair"])  # ни .part, ни .old не осталось
            self.assertEqual(os.listdir(dst), ["new.fbx"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
