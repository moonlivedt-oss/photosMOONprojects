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

    def test_unreal_tools_registered(self):
        for name in (
            "ue_overview",
            "ue_search",
            "ue_view",
            "ue_info",
            "ue_plan_room",
            "ue_collection",
            "ue_download",
            "ue_pack",
            "ue_import",
            "ue_blender",
            "versions",
            "restore_version",
        ):
            self.assertIn(name, api.TOOLS, name)
        self.assertTrue(api.TOOLS["ue_import"]["write"])
        self.assertFalse(api.TOOLS["ue_search"]["write"])

    def test_versions_tool(self):
        cur = self.path(f"{SEC}/red-planet.png")
        old = self.path(f"_sources/edit 2026-01-01/{SEC}/red-planet.png")
        os.makedirs(os.path.dirname(old))
        dot((10, 10, 200, 255)).save(old)
        got = api.call("versions", {"path": f"{SEC}/red-planet.png"})["versions"]
        self.assertEqual(len(got), 1)
        res = api.call("restore_version", {"path": f"{SEC}/red-planet.png", "version": got[0]["path"]})
        self.assertTrue(os.path.exists(cur))
        with self.assertRaises(api.ApiError):  # чужой файл - не версия
            api.call("restore_version", {"path": f"{SEC}/red-planet.png", "version": f"{SEC}/blue-moon.png"})
        api.call("undo", {"id": res["journal_id"]})  # отмена возврата - снова прежняя картинка
        self.assertTrue(os.path.exists(cur))

    def test_service_folders_read_only(self):
        os.makedirs(self.path("_docs/screenshots"))
        dot((200, 200, 40, 255)).save(self.path("_docs/screenshots/logo.png"))
        self.assertIn("_docs", api.call("info", {"path": "_docs/screenshots/logo.png"})["path"])  # смотреть можно
        logo = "_docs/screenshots/logo.png"
        for name, args in (
            ("trash", {"paths": [logo]}),
            ("tag", {"paths": [logo], "add": ["x"]}),
            ("rename", {"path": logo, "new_name": "x"}),
        ):
            with self.assertRaises(api.ApiError, msg=name) as e:
                api.call(name, args)
            self.assertIn("служебной", str(e.exception))
        self.assertTrue(os.path.exists(self.path("_docs/screenshots/logo.png")))

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

    def test_rename_to_same_name_keeps_tags(self):
        r = f"{SEC}/red-planet.png"
        api.call("tag", {"paths": [r], "add": ["планета"]})
        api.call("rename", {"path": r, "new_name": "red-planet"})
        self.assertEqual(db.tags_of(api.key(self.path(r))), ["планета"])

    def test_convert_replace_keeps_tags_and_undo_returns_them(self):
        r = f"{SEC}/red-planet.png"
        api.call("tag", {"paths": [r], "add": ["планета"]})
        api.call("favorite", {"paths": [r]})
        api.call("note", {"path": r, "text": "для сайта"})
        res = api.call("convert", {"paths": [r], "format": "webp", "replace": True})
        new = api.key(self.path(f"{SEC}/red-planet.webp"))
        self.assertTrue(os.path.exists(self.path(f"{SEC}/red-planet.webp")))
        self.assertEqual(db.tags_of(new), ["планета"])
        self.assertIn(new, db.favs())
        self.assertEqual(db.note_of(new), "для сайта")
        api.call("undo", {"id": res["journal_id"]})
        old = api.key(self.path(r))
        self.assertTrue(os.path.exists(self.path(r)))
        self.assertEqual(db.tags_of(old), ["планета"])
        self.assertIn(old, db.favs())
        self.assertEqual(db.note_of(old), "для сайта")

    def test_trash_failure_keeps_tags(self):
        from unittest import mock

        r = f"{SEC}/red-planet.png"
        api.call("tag", {"paths": [r], "add": ["планета"]})
        with mock.patch.object(api.shutil, "move", side_effect=PermissionError(13, "занят")):
            res = api.call("trash", {"paths": [r]})
        self.assertEqual(res["removed"], 0)
        self.assertIn("errors", res)
        self.assertEqual(db.tags_of(api.key(self.path(r))), ["планета"])

    def test_read_only_allows_previews_but_not_export(self):
        C.save_cfg({"ai_write": False})
        r = f"{SEC}/red-planet.png"
        pic = api.call("edit", {"paths": [r], "ops": [{"op": "flip", "dir": "h"}]})
        self.assertIsInstance(pic, api.Picture)
        with self.assertRaises(api.ApiError):
            api.call("edit", {"paths": [r], "ops": [{"op": "flip", "dir": "h"}], "mode": "replace"})
        with self.assertRaises(api.ApiError):
            api.call("export", {"paths": [r], "dest": os.path.join(self.lib, "out")})
        self.assertFalse(os.path.exists(os.path.join(self.lib, "out")))

    def test_failed_undo_stays_undoable(self):
        r = f"{SEC}/red-planet.png"
        res = api.call("move", {"paths": [r], "folder": "02 Наклейки/Другое"})
        os.remove(self.path("02 Наклейки/Другое/red-planet.png"))  # файл увели мимо журнала
        with self.assertRaises(api.ApiError):
            api.call("undo", {"id": res["journal_id"]})
        self.assertFalse(journal.get(res["journal_id"])["undone"])

    def test_import_checks_all_files_first(self):
        good = os.path.join(self.lib, "good.png")
        dot((1, 2, 3, 255)).save(good)
        with self.assertRaises(api.ApiError):
            api.call("import_images", {"files": [good, os.path.join(self.lib, "нет.png")]})
        self.assertEqual(C.inbox_files(), [])

    def test_mcp_marks_destructive_tools(self):
        import mcp_server

        hints = {t["name"]: t["annotations"] for t in mcp_server.tool_list(api)}
        self.assertTrue(hints["trash"]["destructiveHint"])
        self.assertFalse(hints["tag"]["destructiveHint"])
        self.assertFalse(hints["export"]["readOnlyHint"])

    def test_undo_older_action_waits_for_newer(self):
        r = f"{SEC}/red-planet.png"
        first = api.call("tag", {"paths": [r], "add": ["планета"]})
        api.call("tag", {"paths": [r], "add": ["красная"]})
        with self.assertRaises(api.ApiError) as e:
            api.call("undo", {"id": first["journal_id"]})
        self.assertIn("ещё менялись", str(e.exception))
        api.call("undo", {"id": first["journal_id"], "force": True})
        self.assertTrue(journal.get(first["journal_id"])["undone"])

    def test_numbered_sibling_is_not_a_version(self):
        from library import versions

        dot((1, 2, 3, 255)).save(self.path(f"{SEC}/red-planet 2.png"))  # другая картинка с номером
        for name in ("red-planet.png", "red-planet 2.png"):
            p = self.path(f"_sources/edit 2026-01-01/{SEC}/{name}")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            dot((10, 10, 200, 255)).save(p)
        got = [os.path.basename(v["path"]) for v in versions.versions(self.path(f"{SEC}/red-planet.png"))]
        self.assertEqual(got, ["red-planet.png"])


if __name__ == "__main__":
    unittest.main()
