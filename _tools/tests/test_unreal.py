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


class TestCatalog(unittest.TestCase):
    def test_guess_theme(self):
        self.assertEqual(U.guess_theme("model", {"categories": ["furniture", "seating"], "tags": ["chair"]}),
                         "Дом - мебель")
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


if __name__ == "__main__":
    unittest.main()
