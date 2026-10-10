"""Скачанные вручную архивы моделей (library/unreal_local.py): тема по имени, FBX без копий для Unity,
текстуры, которые называет FBX, - рядом с моделью. Без сети, на временной папке."""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from library import unreal as U  # noqa: E402
from library import unreal_local as L  # noqa: E402

FBX = b"Kaydara FBX Binary  \x00RelativeFilename\x00Textures\\palette.png\x00 more"


class Archives(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [
            mock.patch.object(U, "ROOT", os.path.join(self.tmp, "_Unreal")),
            mock.patch.object(L, "UNPACK", os.path.join(self.tmp, "unpack")),
            mock.patch.object(L, "DROP", os.path.join(self.tmp, "_Unreal", "_Архивы")),
            mock.patch.object(L, "DONE", os.path.join(self.tmp, "_Unreal", "_Архивы", "_разобрано")),
        ]
        for p in self.patches:
            p.start()
        self.zip = os.path.join(self.tmp, "KayKit_Forest_Nature_Pack_1.0_FREE.zip")
        with zipfile.ZipFile(self.zip, "w") as zf:
            zf.writestr("Pack/Assets/fbx/Tree_1.fbx", FBX)
            zf.writestr("Pack/Assets/fbx/Rock_A.fbx", b"Kaydara FBX Binary  \x00no textures")
            zf.writestr("Pack/Assets/fbx(unity)/Tree_1.fbx", FBX)  # копия для Unity - не брать
            zf.writestr("Pack/Assets/obj/Tree_1.obj", b"o")
            zf.writestr("Pack/Assets/texture/palette.png", b"png")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_guess(self):
        self.assertEqual(L.guess("KayKit_Forest_Nature_Pack_1.0_FREE.zip")[::2], ("KayKit", "Лес и природа"))
        self.assertEqual(L.guess("Stylized Nature MegaKit[Standard].zip")[0], "Quaternius")
        self.assertEqual(L.guess("Medieval Village MegaKit.zip")[2], "Средневековье")
        self.assertEqual(L.guess("что-то.zip"), (None, "", "Разное"))
        self.assertEqual(L.theme_of("Лес и природа", "KayKit"), "Лес и природа - KayKit low-poly")

    def test_import_with_textures(self):
        res = L.import_archives([self.zip], log=lambda _s: None)
        self.assertEqual(res["added"], 2, res)
        self.assertEqual(res["themes"], {"Лес и природа - KayKit low-poly": 2})
        tree = os.path.join(U.ROOT, "Модели", "Лес и природа - KayKit low-poly", "Tree 1")
        self.assertTrue(os.path.exists(os.path.join(tree, "Tree_1.fbx")))
        self.assertTrue(os.path.exists(os.path.join(tree, "palette.png")))  # рядом
        self.assertTrue(os.path.exists(os.path.join(tree, "Textures", "palette.png")))  # и по пути из FBX
        a = {x["name"]: x for x in U.assets(U.ROOT)}
        self.assertEqual(a["Tree 1"]["source"], "KayKit")
        self.assertEqual(a["Tree 1"]["authors"], ["Kay Lousberg"])
        self.assertNotIn("extra", a["Rock a"])
        again = L.import_archives([self.zip], log=lambda _s: None)  # повторно - ничего нового
        self.assertEqual(again["added"], 0)

    def test_dropped_archive_moves_to_done(self):
        os.makedirs(L.DROP)
        dropped = shutil.copy(self.zip, L.DROP)
        self.assertEqual(L.dropped(), [dropped])
        L.import_archives(L.dropped(), log=lambda _s: None)
        self.assertEqual(L.dropped(), [])
        self.assertTrue(os.listdir(L.DONE))


if __name__ == "__main__":
    unittest.main()
