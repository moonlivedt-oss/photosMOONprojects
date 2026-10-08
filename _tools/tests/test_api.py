"""Операции для ИИ-помощников (library/api.py) и сервер MCP - на временной библиотеке, настоящая не трогается.
Каждое изменение должно попасть в журнал и честно отменяться."""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PIL import Image, ImageDraw
from test_imaging import sticker_sheet

import imaging as K
import library.common as C
from library import api, db, journal

SEC = "02 Наклейки/Тест"


def dot(color, size=96):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((8, 8, size - 8, size - 8), fill=color)
    return im


class Api(unittest.TestCase):
    def setUp(self):
        self.lib = tempfile.mkdtemp()
        self.old = {k: getattr(C, k) for k in ("LIB", "INBOX", "SOURCES", "PARK", "DELETED", "CFG")}
        C.LIB = self.lib
        C.INBOX = os.path.join(self.lib, "00 Входящие")
        C.SOURCES = os.path.join(self.lib, "_sources")
        C.PARK = os.path.join(C.SOURCES, "_undone")
        C.DELETED = os.path.join(C.SOURCES, "_deleted")
        C.CFG = os.path.join(self.lib, "settings.json")
        self.old_db = db.DB
        db.close()
        db.DB = os.path.join(self.lib, "t.db")
        os.makedirs(os.path.join(self.lib, *SEC.split("/")))
        os.makedirs(C.INBOX)
        for name, col in (
            ("red-planet", (220, 40, 40, 255)),
            ("blue-moon", (40, 80, 220, 255)),
            ("green-leaf", (40, 200, 90, 255)),
        ):
            dot(col).save(self.path(f"{SEC}/{name}.png"))
        api.AGENT["who"] = "ИИ (тест)"

    def tearDown(self):
        db.close()
        db.DB = self.old_db
        for k, v in self.old.items():
            setattr(C, k, v)
        shutil.rmtree(self.lib, ignore_errors=True)

    def path(self, rel):
        return os.path.join(self.lib, *rel.split("/"))

    def test_overview_and_search(self):
        o = api.call("overview")
        self.assertEqual(o["images"], 3)
        self.assertEqual(o["sections"][0]["path"], "02 Наклейки")
        r = api.call("search", {"query": "moon", "semantic": "false"})
        self.assertEqual([x["path"] for x in r["items"]], [f"{SEC}/blue-moon.png"])
        r = api.call("search", {"query": "-moon", "semantic": "false"})
        self.assertEqual(r["total"], 2)
        r = api.call("search", {"color": "r"})
        self.assertEqual([x["name"] for x in r["items"]], ["red-planet"])

    def test_bad_input_is_explained(self):
        with self.assertRaises(api.ApiError) as e:
            api.call("info", {"path": f"{SEC}/blue-mon.png"})
        self.assertIn("Нет файла", str(e.exception))
        with self.assertRaises(api.ApiError):
            api.call("info", {"path": "../outside.png"})
        with self.assertRaises(api.ApiError):
            api.call("search", {"qery": "x"})
        with self.assertRaises(api.ApiError):
            api.call("move", {"paths": [f"{SEC}/red-planet.png"], "folder": "_sources"})

    def test_tags_undo(self):
        p = f"{SEC}/red-planet.png"
        r = api.call("tag", {"paths": [p], "add": ["Космос", "#планета"]})
        self.assertEqual(db.tags_of(p.replace("/", os.sep)), ["космос", "планета"])
        self.assertEqual(api.call("search", {"query": "космос"})["total"], 1)
        api.call("undo", {"id": r["journal_id"]})
        self.assertEqual(db.tags_of(p.replace("/", os.sep)), [])
        with self.assertRaises(api.ApiError):
            api.call("undo", {"id": r["journal_id"]})

    def test_rename_move_trash_and_undo(self):
        p = f"{SEC}/blue-moon.png"
        api.call("tag", {"paths": [p], "add": ["луна"]})
        api.call("favorite", {"paths": [p]})
        r = api.call("rename", {"path": p, "new_name": "moon"})
        self.assertEqual(r["path"], f"{SEC}/moon.png")
        r = api.call("move", {"paths": [f"{SEC}/moon.png"], "folder": "04 Иконки/Ночь"})
        self.assertEqual(r["moved"], ["04 Иконки/Ночь/moon.png"])
        self.assertEqual(db.tags_of(os.path.join("04 Иконки", "Ночь", "moon.png")), ["луна"])
        r = api.call("trash", {"paths": ["04 Иконки/Ночь/moon.png"]})
        self.assertFalse(os.path.exists(self.path("04 Иконки/Ночь/moon.png")))
        self.assertEqual(db.all_tags(), {})
        api.call("undo")  # корзина - назад вместе с меткой и избранным
        rel = os.path.join("04 Иконки", "Ночь", "moon.png")
        self.assertTrue(os.path.exists(self.path("04 Иконки/Ночь/moon.png")))
        self.assertEqual(db.tags_of(rel), ["луна"])
        self.assertIn(rel, db.favs())
        api.call("undo")  # перенос
        api.call("undo")  # переименование
        self.assertTrue(os.path.exists(self.path(p)))
        self.assertEqual(db.tags_of(p.replace("/", os.sep)), ["луна"])
        self.assertTrue(r["journal_id"])

    def test_edit_preview_copy_replace(self):
        p = f"{SEC}/green-leaf.png"
        pic = api.call("edit", {"paths": [p], "ops": [{"op": "outline", "px": 4}]})
        self.assertIsInstance(pic, api.Picture)
        self.assertEqual(len(os.listdir(self.path(SEC))), 3)  # предпросмотр ничего не пишет
        r = api.call("edit", {"paths": [p], "adj": {"hue": 90}, "mode": "copy"})
        self.assertEqual(r["saved"], [f"{SEC}/green-leaf правка.png"])
        size0 = os.path.getsize(self.path(p))
        r = api.call("edit", {"paths": [p], "ops": [{"op": "resize", "size": 48}], "mode": "replace"})
        self.assertEqual(K.size_of(self.path(p)), (48, 48))
        api.call("undo", {"id": r["journal_id"]})
        self.assertEqual(os.path.getsize(self.path(p)), size0)
        with self.assertRaises(api.ApiError):
            api.call("edit", {"paths": [p], "ops": [{"op": "blur"}]})

    def test_cut_sheet_skips_existing(self):
        src = os.path.join(C.INBOX, "кружки.png")
        sticker_sheet().save(src)
        pic = api.call("cut_sheet", {"path": "00 Входящие/кружки.png", "preview": True, "size": 64})
        self.assertIn("Кусков: 12", pic.text)
        r = api.call(
            "cut_sheet",
            {
                "path": "00 Входящие/кружки.png",
                "folder": "02 Наклейки/Кружки",
                "size": 64,
                "format": "png",
                "tags": ["кружок"],
            },
        )
        self.assertEqual(len(r["saved"]), 12)
        self.assertFalse(os.path.exists(src))  # исходник ушёл в _sources
        self.assertEqual(len(db.with_tag("кружок")), 12)
        sticker_sheet().save(src)
        r2 = api.call("cut_sheet", {"path": src, "folder": "02 Наклейки/Кружки", "size": 64, "format": "png"})
        self.assertEqual((len(r2["saved"]), r2["skipped_existing"]), (0, 12))
        api.call("undo", {"id": r["journal_id"]})
        self.assertEqual(len(os.listdir(self.path("02 Наклейки/Кружки"))), 0)
        self.assertTrue(os.path.exists(src) or os.listdir(C.INBOX))

    def test_duplicates_and_check(self):
        dot((220, 40, 40, 255)).resize((200, 200)).save(self.path(f"{SEC}/red-planet big.png"))
        r = api.call("duplicates")
        self.assertEqual(r["groups"], 1)
        self.assertEqual([x["name"] for x in r["duplicates"][0]], ["red-planet big", "red-planet"])
        Image.new("RGBA", (96, 96), (0, 0, 0, 0)).save(self.path(f"{SEC}/empty.png"))
        r = api.call("check")
        self.assertIn("Пустая или почти прозрачная", r["items"][0]["problems"])

    def test_view_and_read_only(self):
        pic = api.call("view", {"paths": [f"{SEC}/red-planet.png", f"{SEC}/blue-moon.png"]})
        self.assertIn("1. " + SEC, pic.text)
        self.assertGreater(len(pic.png()), 1000)
        C.save_cfg({"ai_write": False})
        with self.assertRaises(api.ApiError) as e:
            api.call("tag", {"paths": [f"{SEC}/red-planet.png"], "add": ["x"]})
        self.assertIn("запрещено", str(e.exception))
        self.assertEqual(api.call("search", {"query": "planet"})["total"], 1)

    def test_journal_seen_by_window(self):
        """Окно берёт действия помощника из журнала: автор, текст, шаги - и может их отменить."""
        since = journal.last_id()
        api.call("tag", {"paths": [f"{SEC}/red-planet.png"], "add": ["марс"]})
        new = journal.entries(10, since=since)
        self.assertEqual((new[0]["who"], new[0]["steps"][0][0]), ("ИИ (тест)", "tags"))
        done, bad = journal.undo_steps(new[0]["steps"], C.LIB, C.PARK)
        self.assertEqual(bad, 0)
        self.assertEqual(db.all_tags(), {})
        journal.redo_steps(done, C.LIB)
        self.assertEqual(db.all_tags(), {"марс": 1})

    def test_mcp_protocol(self):
        import mcp_server

        r = mcp_server.handle(
            api,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "probe"}},
            },
        )
        self.assertEqual(r["protocolVersion"], "2025-06-18")
        self.assertEqual(api.AGENT["who"], "ИИ (probe)")
        tools = mcp_server.handle(api, {"id": 2, "method": "tools/list"})["tools"]
        self.assertIn("search", {t["name"] for t in tools})
        self.assertTrue(all(t["inputSchema"]["type"] == "object" for t in tools))
        r = mcp_server.handle(
            api,
            {
                "id": 3,
                "method": "tools/call",
                "params": {"name": "view", "arguments": {"paths": [f"{SEC}/red-planet.png"]}},
            },
        )
        self.assertEqual(r["content"][0]["type"], "image")
        r = mcp_server.handle(
            api, {"id": 4, "method": "tools/call", "params": {"name": "info", "arguments": {"path": "nope.png"}}}
        )
        self.assertTrue(r["isError"])
        r = mcp_server.handle(api, {"id": 5, "method": "tools/call", "params": {"name": "overview", "arguments": {}}})
        self.assertEqual(json.loads(r["content"][0]["text"])["images"], 3)
        self.assertIsNone(mcp_server.handle(api, {"method": "notifications/initialized"}))


if __name__ == "__main__":
    unittest.main()
