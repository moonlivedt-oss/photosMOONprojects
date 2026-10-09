"""Подключение помощников: запись сервера в чужие файлы настроек не портит их."""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ui import agents as A  # noqa: E402


class TestConnect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_keeps_other_servers(self):
        path = os.path.join(self.tmp, "cfg.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}, fh)
        A.connect(path, "mcpServers")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["theme"], "dark")
        self.assertIn("other", data["mcpServers"])
        self.assertTrue(A.connected(path, "mcpServers"))
        self.assertTrue(os.path.exists(path + ".bak"))

    def test_new_file_and_vscode_shape(self):
        path = os.path.join(self.tmp, "sub", "mcp.json")
        A.connect(path, "servers", A.vscode_entry)
        with open(path, encoding="utf-8") as fh:
            entry = json.load(fh)["servers"][A.NAME]
        self.assertEqual(entry["type"], "stdio")
        self.assertEqual(entry["command"], "py")

    def test_jsonc_untouched(self):
        path = os.path.join(self.tmp, "settings.json")
        text = '{\n  // comment\n  "a": 1\n}\n'
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        with self.assertRaises(ValueError):
            A.connect(path, "mcpServers")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)

    def test_clients_well_formed(self):
        names = [c[0] for c in A.CLIENTS]
        self.assertEqual(len(names), len(set(names)))
        for _title, path, key, entry, _home in A.CLIENTS:
            self.assertTrue(path.endswith(".json"))
            self.assertIn(key, ("mcpServers", "servers"))
            self.assertEqual(entry()["command"], "py")


if __name__ == "__main__":
    unittest.main()
