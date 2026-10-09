"""Чистка _sources (library/cleanup.py): виды папок, даты по именам, отбор старых - на временной папке."""

import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import library.common as C
from library import cleanup


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.old = {k: getattr(C, k) for k in ("SOURCES", "PARK", "DELETED")}
        C.SOURCES = os.path.join(self.root, "_sources")
        C.PARK = os.path.join(C.SOURCES, "_undone")
        C.DELETED = os.path.join(C.SOURCES, "_deleted")

    def tearDown(self):
        for k, v in self.old.items():
            setattr(C, k, v)
        shutil.rmtree(self.root, ignore_errors=True)

    def put(self, rel, size=10):
        p = os.path.join(C.SOURCES, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(b"x" * size)
        return p

    def test_kinds_and_dates(self):
        self.assertEqual(cleanup.kind_of("edit 2026-01-02"), "edit")
        self.assertEqual(cleanup.kind_of("compress 2026-01-02"), "compress")
        self.assertEqual(cleanup.kind_of("2026-09"), "sheets")
        self.assertEqual(cleanup.kind_of("_deleted"), "deleted")
        self.assertEqual(cleanup.kind_of("_undone"), "undone")
        self.assertEqual(cleanup.kind_of("04 Иконки"), "other")
        day = cleanup.folder_time("edit 2026-01-02")
        self.assertEqual(time.localtime(day)[:3], (2026, 1, 2))
        month = cleanup.folder_time("2026-12")  # месяц кончается 31 декабря, не 1-го
        self.assertEqual(time.localtime(month)[:3], (2026, 12, 31))
        self.assertIsNone(cleanup.folder_time("без даты"))

    def test_pick_old_by_folder_date(self):
        old = self.put("edit 2020-01-01/04 Иконки/a.png", 100)
        new = self.put("edit " + time.strftime("%Y-%m-%d") + "/04 Иконки/b.png", 100)
        sheet = self.put("2020-01/лист.png", 1000)
        gone = self.put("_deleted/2020-01-01/02 Наклейки/c.png", 50)
        files = cleanup.scan()
        self.assertEqual(cleanup.summary(files)["edit"], [200, 2])
        picked = {f[0] for f in cleanup.pick(files, cleanup.DEFAULT, 60)}
        self.assertEqual(picked, {old, gone})  # свежий оригинал и листы (не по умолчанию) остаются
        self.assertNotIn(new, picked)
        self.assertIn(sheet, {f[0] for f in cleanup.pick(files, ["sheets"], 60)})

    def test_drop_empty_dirs_keeps_service(self):
        p = self.put("edit 2020-01-01/04 Иконки/a.png")
        os.makedirs(C.DELETED)
        os.remove(p)
        cleanup.drop_empty_dirs()
        self.assertFalse(os.path.exists(os.path.join(C.SOURCES, "edit 2020-01-01")))
        self.assertTrue(os.path.isdir(C.DELETED))
        self.assertTrue(os.path.isdir(C.SOURCES))


if __name__ == "__main__":
    unittest.main()
