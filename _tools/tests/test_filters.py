"""Фильтры библиотеки: размер и прозрачность в отпечатках, переход старой базы, отбор картинок."""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from library import db  # noqa: E402
from library.signatures import VERSION, build_sigs, has_alpha  # noqa: E402
from ui.library_tab import FILTER_DEFAULT, passes  # noqa: E402


class Filters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_db = db.DB
        db.close()
        db.DB = os.path.join(self.tmp, "t.db")

    def tearDown(self):
        db.close()
        db.DB = self.old_db
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_alpha_kinds(self):
        rgba = Image.new("RGBA", (8, 8), (255, 0, 0, 0))
        self.assertEqual(has_alpha(rgba), 1)
        self.assertEqual(has_alpha(Image.new("RGBA", (8, 8), (255, 0, 0, 255))), 0)
        self.assertEqual(has_alpha(Image.new("RGB", (8, 8))), 0)
        p = rgba.convert("P")
        p.info["transparency"] = 0  # палитровый PNG: прозрачность - в info (значки Kenney)
        self.assertEqual(has_alpha(p), 1)

    def test_sigs_store_size_and_alpha(self):
        lib = os.path.join(self.tmp, "lib", "01 Фоны")
        os.makedirs(lib)
        Image.new("RGB", (300, 100), "red").save(os.path.join(lib, "wide.png"))
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(os.path.join(lib, "icon.png"))
        new = build_sigs({}, os.path.dirname(lib))
        db.save_sigs(new, {})
        got = db.load_sigs()
        wide = got[os.path.join("01 Фоны", "wide.png")]
        icon = got[os.path.join("01 Фоны", "icon.png")]
        self.assertEqual((wide[4], wide[5], wide[6], wide[7]), (VERSION, 300, 100, 0))
        self.assertEqual(icon[5:8], [64, 64, 1])

    def test_old_db_gets_columns(self):
        c = sqlite3.connect(db.DB)
        c.execute("CREATE TABLE sigs(rel TEXT PRIMARY KEY, mt REAL, ratio REAL, vec BLOB, col TEXT, ver INT)")
        c.execute("INSERT INTO sigs VALUES ('a.png', 1, 1, ?, 'r', 2)", (bytes(432),))
        c.commit()
        c.close()
        got = db.load_sigs()  # старая база открывается, новых значений пока нет
        self.assertEqual(got["a.png"][4:8], [2, None, None, None])

    def test_passes(self):
        f = dict(FILTER_DEFAULT)
        self.assertTrue(passes("a.png", f, (800, 400, 0)))
        f["orient"] = "land"
        self.assertTrue(passes("a.png", f, (800, 400, 0)))
        self.assertFalse(passes("a.png", f, (400, 800, 0)))
        self.assertTrue(passes("a.png", f, None))  # ещё не посчитано - не прятать
        f = dict(FILTER_DEFAULT, alpha="yes", size="small", fmt="png")
        self.assertTrue(passes("x.png", f, (64, 64, 1)))
        self.assertFalse(passes("x.webp", f, (64, 64, 1)))
        self.assertFalse(passes("x.png", f, (64, 64, 0)))
        self.assertFalse(passes("x.png", f, (512, 512, 1)))
        self.assertTrue(passes("x.jpeg", dict(FILTER_DEFAULT, fmt="jpg"), None))


if __name__ == "__main__":
    unittest.main()
