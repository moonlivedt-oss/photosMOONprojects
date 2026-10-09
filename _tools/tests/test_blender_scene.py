"""Сцена для Blender: что строить (без самого Blender - он в CI не стоит)."""

import ast
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from library import blender_scene as B  # noqa: E402


class BlenderScene(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def asset(self, name, kind, files, theme="Дом - мебель", **kw):
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        for f in files:
            open(os.path.join(d, f), "wb").close()
        return {"name": name, "kind": kind, "dir": d, "main": [files[0]], "theme": theme, **kw}

    def test_room_jobs(self):
        bed = self.asset("Bed", "model", ["bed.fbx"], dimensions_mm=[2000, 1600, 900])
        lamp = self.asset("Chandelier 01", "model", ["chandelier.fbx"], section="Свет")
        floor = self.asset("Oak", "tex", ["oak_diff_2k.jpg", "oak_nor_dx_2k.jpg", "oak_arm_2k.jpg"], "Дом - полы")
        sky = self.asset("Sky", "hdri", ["sky.hdr"], "Студия")
        j = B.jobs([bed, lamp, floor, sky], room=True)
        self.assertGreater(j["room"]["w"], 3)  # метры, а не сантиметры
        names = {m["name"]: m for m in j["models"]}
        self.assertTrue(names["Chandelier 01"]["hang"])  # люстра - под потолок
        self.assertFalse(names["Bed"]["hang"])
        self.assertAlmostEqual(names["Bed"]["size"], 2.0, places=1)  # настоящий размер Poly Haven
        self.assertTrue(j["floor"]["normal_dx"].endswith("oak_nor_dx_2k.jpg"))
        self.assertTrue(j["floor"]["arm"])
        self.assertEqual(j["textures"], [])  # пол ушёл в комнату, а не на шар
        self.assertTrue(j["hdri"].endswith("sky.hdr"))

    def test_room_tiles_on_walls_and_pictures(self):
        sofa = self.asset("Sofa", "model", ["sofa.fbx"])
        frame = self.asset("Hanging Picture Frame 01", "model", ["frame.fbx"])
        floor = self.asset("Parquet", "tex", ["p_diff_2k.jpg"], "Дом - полы")
        tiles = self.asset("Interior Tiles", "tex", ["t_diff_2k.jpg"], "Дом - плитка и камень")
        extra = self.asset("Fabric", "tex", ["f_diff_2k.jpg"], "Дом - ткани и кожа")
        j = B.jobs([sofa, frame, floor, tiles, extra], room=True)
        self.assertEqual(j["floor"]["name"], "Parquet")
        self.assertEqual(j["wall"]["name"], "Interior Tiles")  # плитка - на стены, а не шаром в комнату
        self.assertEqual(j["textures"], [])
        on = {m["name"]: m["on_wall"] for m in j["models"]}
        self.assertTrue(on["Hanging Picture Frame 01"])
        self.assertFalse(on["Sofa"])

    def test_row_jobs_and_script(self):
        chair = self.asset("Chair", "model", ["chair.fbx"])
        tex = self.asset("Brick", "tex", ["brick_diff_1k.jpg"])
        j = B.jobs([chair, tex])
        self.assertIsNone(j["room"])
        self.assertEqual(len(j["textures"]), 1)
        script, blend = B.write_script([chair, tex], os.path.join(self.tmp, "out"), "Моя сцена")
        with open(script, encoding="utf-8") as fh:
            ast.parse(fh.read())  # скрипт для Blender - правильный Python
        self.assertTrue(blend.endswith(".blend"))


if __name__ == "__main__":
    unittest.main()
