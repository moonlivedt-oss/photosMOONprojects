"""Просмотровая копия MetaHuman: отбор частей и подготовка текстур (без Blender)."""

import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from library import mh_view as V


class ViewParts(unittest.TestCase):
    def test_foreign_body_and_duplicates_dropped(self):
        files = [
            "m_med_nrw_body.fbx",
            "Emanuel_FaceMesh.fbx",
            "m_med_nrw_btm_cargopants_Cinematic.fbx",
            "m_med_nrw_top_hoodie_nrm.fbx",
            "m_med_nrw_top_hoodie_nrm_Cinematic.fbx",
            "m_tal_nrw_btm_cargopants_Cinematic.fbx",
            "m_tal_nrw_shs_runningshoes_Cinematic.fbx",
        ]
        got = V.view_parts(files)
        self.assertEqual(
            got,
            [
                "m_med_nrw_body.fbx",
                "Emanuel_FaceMesh.fbx",
                "m_med_nrw_btm_cargopants_Cinematic.fbx",
                "m_med_nrw_top_hoodie_nrm.fbx",
                "m_tal_nrw_shs_runningshoes_Cinematic.fbx",  # своей обуви нет - чужая лучше, чем босиком
            ],
        )


class Textures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roughness_from_red_channel(self):
        src = os.path.join(self.tmp, "r.png")
        Image.new("RGBA", (8, 8), (200, 0, 0, 255)).save(src)
        out = V.prep_gray(src, os.path.join(self.tmp, "r.jpg"))
        self.assertGreater(np.asarray(Image.open(out)).mean(), 190)

    def test_normal_green_flipped(self):
        src = os.path.join(self.tmp, "n.png")
        Image.new("RGB", (8, 8), (128, 40, 255)).save(src)
        out = V.prep_normal(src, os.path.join(self.tmp, "n.jpg"))
        self.assertGreater(np.asarray(Image.open(out))[..., 1].mean(), 200)

    def test_cards_alpha_from_red(self):
        src = os.path.join(self.tmp, "a.png")
        im = Image.new("RGB", (8, 8), (0, 0, 0))
        im.putpixel((2, 2), (255, 128, 0))
        im.save(src)
        out = Image.open(V.prep_cards(src, (0.02, 0.02, 0.02), os.path.join(self.tmp, "a_out.png")))
        self.assertEqual(out.mode, "RGBA")
        self.assertEqual(out.getpixel((2, 2))[3], 255)
        self.assertEqual(out.getpixel((0, 0))[3], 0)

    def test_collect_textures_downscaled_to_png(self):
        from library import unreal_from_project as P

        src = os.path.join(self.tmp, "out", "textures", "Bryan", "Face")
        os.makedirs(src)
        Image.new("RGB", (4096, 1024), (10, 20, 30)).save(os.path.join(src, "FaceColor_MAIN.tga"))
        root = os.path.join(self.tmp, "lib")
        self.assertEqual(P.collect_textures(os.path.join(self.tmp, "out"), root), 1)
        with Image.open(os.path.join(root, "Bryan", "Face", "FaceColor_MAIN.png")) as im:
            self.assertEqual(im.size, (2048, 512))
        self.assertTrue(V.has_textures("Bryan", root))
        self.assertFalse(V.has_textures("Ada", root))

    def test_pick_strict_own_folder(self):
        idx = {"facecolor_main": [os.path.join("x", "Other", "Face", "FaceColor_MAIN.png")]}
        self.assertEqual(V.pick(idx, "FaceColor_MAIN", "Emanuel", strict=True), "")
        self.assertTrue(V.pick(idx, "FaceColor_MAIN", "Emanuel"))


if __name__ == "__main__":
    unittest.main()
