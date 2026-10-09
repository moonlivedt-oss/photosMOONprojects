"""Unreal на компьютере: движок для проекта, плагин Python, куда класть файлы перед импортом."""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from library import unreal_engine as E  # noqa: E402


class Engine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.proj = os.path.join(self.tmp, "Game", "Game.uproject")
        os.makedirs(os.path.dirname(self.proj))
        with open(self.proj, "w", encoding="utf-8") as fh:
            json.dump(
                {"FileVersion": 3, "EngineAssociation": "5.6", "Plugins": [{"Name": "Water", "Enabled": True}]}, fh
            )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_engine_for(self):
        known = {"5.6": "C:/UE_5.6", "5.8": "D:/UE_5.8"}
        self.assertEqual(E.engine_for(self.proj, known), "C:/UE_5.6")  # по EngineAssociation
        self.assertEqual(E.engine_for(self.proj, {"5.8": "D:/UE_5.8", "5.10": "D:/UE_5.10"}), "D:/UE_5.10")
        self.assertIsNone(E.engine_for(self.proj, {}))

    def test_enable_python(self):
        self.assertFalse(E.python_enabled(self.proj))
        E.enable_python(self.proj)
        self.assertTrue(E.python_enabled(self.proj))
        self.assertTrue(os.path.exists(self.proj + ".bak"))  # старый - копией
        with open(self.proj, encoding="utf-8") as fh:
            names = [p["Name"] for p in json.load(fh)["Plugins"]]
        self.assertEqual(names, ["Water", "PythonScriptPlugin", "EditorScriptingUtilities"])  # чужие на месте

    def test_import_folder_outside_content(self):
        f = E.import_folder(self.proj)
        self.assertIn(os.path.join("Saved", "LibraryImport"), f)
        self.assertNotIn("Content", f)

    def test_projects_extra(self):
        self.assertIn(self.proj, E.projects([self.proj]))


if __name__ == "__main__":
    unittest.main()
