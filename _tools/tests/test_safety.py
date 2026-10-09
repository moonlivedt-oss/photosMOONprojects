"""Защита от поломок: испорченные настройки и база чинятся из копии, ценное не теряется."""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import library.common as C  # noqa: E402
from library import db, safety  # noqa: E402


class Safety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = {k: getattr(C, k) for k in ("HERE", "CFG", "LOG")}
        self.old_db = db.DB
        db.close()
        C.HERE = self.tmp
        C.CFG = os.path.join(self.tmp, "settings.json")
        C.LOG = os.path.join(self.tmp, "_errors.log")
        db.DB = os.path.join(self.tmp, "library.db")

    def tearDown(self):
        db.close()
        db.DB = self.old_db
        for k, v in self.old.items():
            setattr(C, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tag(self, rel="a.png", tag="кот"):
        with db.conn() as c:
            c.execute("INSERT OR REPLACE INTO tags VALUES (?, ?)", (rel, tag))

    def tags(self):
        return [r[0] for r in db.conn().execute("SELECT tag FROM tags").fetchall()]

    def test_broken_settings_come_back_from_copy(self):
        C.save_cfg({"ue_sets": {"Спальня": ["x"]}})
        safety.backup()
        with open(C.CFG, "w", encoding="utf-8") as fh:
            fh.write('{"ue_sets": {"Спаль')  # оборвалось посреди записи
        cfg = C.load_cfg()
        self.assertEqual(cfg["ue_sets"], {"Спальня": ["x"]})  # не пустые - иначе окно затёрло бы их
        broken = [f for f in os.listdir(self.tmp) if f.startswith("settings.json.broken-")]
        self.assertEqual(len(broken), 1)  # испорченный не стёрт, а отодвинут

    def test_missing_settings_are_empty(self):
        self.assertEqual(C.load_cfg(), {})

    def test_broken_db_comes_back_from_copy(self):
        self.tag()
        safety.backup()
        db.close()
        with open(db.DB, "wb") as fh:
            fh.write(b"not a database at all" * 100)
        self.assertEqual(self.tags(), ["кот"])  # открылась копия, метка на месте
        self.assertTrue(any(f.startswith("library.db.broken-") for f in os.listdir(self.tmp)))

    def test_broken_db_without_copy_starts_fresh(self):
        with open(db.DB, "wb") as fh:
            fh.write(b"garbage" * 100)
        self.assertEqual(self.tags(), [])
        self.assertTrue(safety.db_ok(db.DB))

    def test_backup_rotation_and_restore(self):
        self.tag(tag="первая")
        safety.backup()
        first_t = safety.backups()[0][1]
        for _ in range(safety.KEEP + 2):
            safety.backup()
        self.assertEqual(len(safety.backups()), safety.KEEP)
        self.assertGreater(min(t for _d, t, _h in safety.backups()), first_t)  # старые уходят
        keep = safety.backups()[-1][0]
        self.tag(tag="вторая")
        safety.restore(keep)
        self.assertEqual(self.tags(), ["первая"])
        self.assertTrue(any("перед восстановлением" in d for d, _t, _h in safety.backups()))

    def test_daily_backup_once(self):
        C.save_cfg({"a": 1})
        self.assertIsNotNone(safety.daily_backup())
        self.assertIsNone(safety.daily_backup())

    def test_check_and_fix(self):
        C.save_cfg({"a": 1})
        self.tag()
        names = {r["name"]: r for r in safety.check()}
        self.assertTrue(names["Настройки"]["ok"])
        self.assertTrue(names["База"]["ok"])
        self.assertEqual(names["Резервные копии"]["fix"], "backup")
        safety.fix("backup")
        self.assertTrue({r["name"]: r for r in safety.check()}["Резервные копии"]["ok"])
        junk = os.path.join(self.tmp, "x.tmp1-2")
        open(junk, "w").close()
        os.utime(junk, (1, 1))
        self.assertIn("Временные файлы", [r["name"] for r in safety.check() if not r["ok"]])
        safety.fix("junk")
        self.assertFalse(os.path.exists(junk))

    def test_crash_counter(self):
        self.assertEqual(safety.start_run(), 0)
        self.assertEqual(safety.start_run(), 1)  # прошлый не закрылся
        self.assertEqual(safety.start_run(), 2)
        safety.end_run()
        self.assertEqual(safety.start_run(), 0)
        with open(safety.running_flag(), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["crashes"], 0)


if __name__ == "__main__":
    unittest.main()
