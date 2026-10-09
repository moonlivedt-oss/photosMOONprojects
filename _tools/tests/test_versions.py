"""История версий картинки: найти прошлые версии в _sources, вернуть любую, отменить возврат."""

import os
import shutil
import sys
import tempfile
import unittest

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import library.common as C  # noqa: E402
from library import db, journal, versions  # noqa: E402


class Versions(unittest.TestCase):
    def setUp(self):
        self.lib = tempfile.mkdtemp()
        self.old = {k: getattr(C, k) for k in ("LIB", "SOURCES", "PARK")}
        C.LIB = self.lib
        C.SOURCES = os.path.join(self.lib, "_sources")
        C.PARK = os.path.join(C.SOURCES, "_undone")
        self.old_db = db.DB
        db.close()
        db.DB = os.path.join(self.lib, "t.db")
        self.cur = self.path("02 Наклейки/Звери/fox.webp")
        os.makedirs(os.path.dirname(self.cur))
        Image.new("RGB", (8, 8), "blue").save(self.cur, lossless=True)
        # две прошлые версии: правка (png) и сжатие того же дня с суффиксом « 2»
        for day, name, color in (("edit 2026-09-01", "fox.png", "red"), ("compress 2026-09-05", "fox 2.png", "green")):
            p = self.path(f"_sources/{day}/02 Наклейки/Звери/{name}")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            Image.new("RGB", (8, 8), color).save(p)
        other = self.path("_sources/edit 2026-09-01/02 Наклейки/Звери/foxglove.png")  # другая картинка
        Image.new("RGB", (8, 8)).save(other)

    def tearDown(self):
        db.close()
        db.DB = self.old_db
        for k, v in self.old.items():
            setattr(C, k, v)
        shutil.rmtree(self.lib, ignore_errors=True)

    def path(self, rel):
        return os.path.join(self.lib, *rel.split("/"))

    def color(self, p):
        with Image.open(p) as im:
            return im.convert("RGB").getpixel((0, 0))

    def test_list(self):
        vs = versions.versions(self.cur)
        self.assertEqual([v["kind"] for v in vs], ["сжатие", "правка"])  # новые первыми
        self.assertFalse(any("foxglove" in v["path"] for v in vs))

    def test_restore_and_undo(self):
        rel = os.path.relpath(self.cur, self.lib)
        db.set_tags([rel], ["лиса"])
        db.set_fav([rel], True)
        old = [v for v in versions.versions(self.cur) if v["kind"] == "правка"][0]["path"]
        new, steps = versions.restore(self.cur, old)
        self.assertEqual(self.color(new), (255, 0, 0))
        self.assertTrue(new.endswith(".png"))  # формат версии
        self.assertTrue(os.path.exists(old))  # версия осталась в истории
        new_rel = os.path.relpath(new, self.lib)
        self.assertEqual(db.tags_of(new_rel), ["лиса"])  # метки и избранное - за картинкой
        self.assertIn(new_rel, db.favs())
        self.assertEqual(len(versions.versions(new)), 3)  # заменённая сама стала версией
        journal.undo_steps(steps, self.lib, C.PARK)
        self.assertTrue(os.path.exists(self.cur))
        self.assertFalse(os.path.exists(new))
        self.assertEqual(self.color(self.cur), (0, 0, 255))
        self.assertEqual(db.tags_of(rel), ["лиса"])
        self.assertIn(rel, db.favs())


if __name__ == "__main__":
    unittest.main()
