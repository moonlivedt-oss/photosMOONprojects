"""Ассеты для Unreal: IES-профили, разбор asset.json, подбор по темам (без сети - каталог подменяется)."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from imaging import ies  # noqa: E402
from library import unreal as U  # noqa: E402


class TestIes(unittest.TestCase):
    def test_format(self):
        for name in ies.PROFILES:
            lines = ies.ies_text(name).splitlines()
            self.assertEqual(lines[0], "IESNA:LM-63-2002")
            i = lines.index("TILT=NONE")
            head = lines[i + 1].split()
            nv, nh = int(head[3]), int(head[4])
            nums = " ".join(lines[i + 3 :]).split()
            self.assertEqual(len(nums), nv + nh + nv * nh, name)  # углы и вся таблица на месте
            vals = [float(x) for x in nums[nv + nh :]]
            self.assertGreater(max(vals), 0, name)
            self.assertGreaterEqual(min(vals), 0, name)
            ies.ies_text(name).encode("ascii")  # внутри - только латиница

    def test_preview(self):
        im = ies.preview("Узкий луч", 64, 48)
        self.assertEqual(im.size, (64, 48))
        self.assertGreater(im.convert("L").getextrema()[1], 120)  # пятно видно

    def test_write_and_scan(self):
        tmp = tempfile.mkdtemp()
        try:
            dirs = ies.write_all(tmp)
            self.assertEqual(len(dirs), len(ies.PROFILES))
            found = U.assets(tmp)
            self.assertEqual(len(found), len(ies.PROFILES))
            for a in found:
                self.assertEqual(a["kind"], "ies")
                self.assertTrue(os.path.exists(os.path.join(a["dir"], a["main"][0])))
                self.assertTrue(a["main"][0].isascii())  # имя ассета в Unreal - латиницей
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestThemes(unittest.TestCase):
    CAT = {
        "brick_wall": {"name": "Brick Wall", "categories": ["brick", "wall"], "tags": [], "download_count": 5},
        "street_brick": {"name": "Street Bricks", "categories": ["brick"], "tags": ["road"], "download_count": 1},
        "floor_out": {"name": "Floor", "categories": ["floor", "outdoor"], "tags": [], "download_count": 99},
        "tiles": {"name": "Tiles 01", "categories": ["floor", "tiles"], "tags": [], "download_count": 2},
    }

    def test_match_and_order(self):
        with (
            mock.patch.object(U, "catalog", return_value=self.CAT),
            mock.patch.object(U, "acg_candidates", return_value=[]),
        ):
            got = [c["id"] for c in U.candidates("tex", "Город")]
            self.assertEqual(got[0], "street_brick")  # два совпадения важнее популярности
            self.assertIn("brick_wall", got)
            self.assertNotIn("tiles", got)
            inside = [c["id"] for c in U.candidates("tex", "Интерьер")]
            self.assertEqual(inside, ["tiles"])  # уличный пол в интерьер не попал
            self.assertEqual(U.candidates("tex", "Город", have={"street_brick", "brick_wall"}), [])

    def test_themes_cover_kinds(self):
        for th, spec in U.THEMES.items():
            self.assertTrue(any(spec.get(k) for k in ("tex", "hdri", "model", "kenney", "quaternius", "kaykit")), th)


class TestHomeSections(unittest.TestCase):
    def test_new_sections_by_words(self):
        for name, sec in (
            ("Rusted Hacksaw", "Инструменты"),
            ("Wooden Axe 02", "Инструменты"),
            ("Plastic Broom", "Хозяйство и уборка"),
            ("Trashcan small 1", "Хозяйство и уборка"),
            ("Baseball Bat", "Спорт и хобби"),
            ("Ukulele 01", "Спорт и хобби"),
            ("Rubber Boots", "Одежда и аксессуары"),
            ("Coat rack standing", "Одежда и аксессуары"),
            ("Antique Katana 01", "Декор"),
            ("Hood modern", "Кухня и посуда"),
            ("Bed double", "Кровати"),
            ("Table lamp", "Свет"),
            ("Kitchencounter straight a", "Кухня и посуда"),  # слитные имена KayKit
            ("Pictureframe small a", "Декор"),
        ):
            self.assertEqual(U.home_section({"name": name}), sec, name)
        self.assertEqual(U.home_section({"name": "Ocean Buoy"}), U.HOME_OTHER)
        self.assertEqual(U.home_section({"name": "Carton"}), U.HOME_OTHER)  # короткие слова не режутся (car)
        for sec, _keys in U.HOME_SECTIONS:
            self.assertIn(sec, U.HOME_ORDER)

    def test_classify_only_when_sure(self):
        import numpy as np

        from library import unreal_sem as S

        prompts = {"Кровати": "a bed", "Свет": "a lamp", "Инструменты": "a hand tool"}
        basis = {f"a photo of {t}": np.eye(3, dtype=np.float32)[i] for i, t in enumerate(prompts.values())}

        class Sem:
            data = {}

        sem = Sem()
        sure = {"name": "x", "dir": "a"}
        unsure = {"name": "y", "dir": "b"}
        sem.data[S.key_of(sure)] = (np.float32([0, 1, 0]), np.float32([0, 1, 0]))  # и картинка, и имя - лампа
        sem.data[S.key_of(unsure)] = (np.float32([1, 0, 0]), np.float32([0, 0, 1]))  # картинка и имя спорят
        with mock.patch.object(S.clip, "embed_text", side_effect=lambda t: basis[t]):
            got = S.classify(sem, [sure, unsure, {"name": "z", "dir": "c"}], prompts)
        self.assertEqual(got, {"a": "Свет"})


class TestMaterials(unittest.TestCase):
    def test_round_robin_without_repeats(self):
        from library import unreal_sem as S

        tex = {n: {"name": n, "dir": n} for n in ("linen", "velvet", "leather", "oak")}

        class Sem:
            def rank(self, q, items):
                found = {"fabric upholstery": ["linen", "velvet", "leather"], "leather": ["leather", "linen"]}[q]
                return [(tex[n], 1.0) for n in found]

        got = S.materials_for(Sem(), "Диваны", list(tex.values()), top=3)
        self.assertEqual([a["name"] for a in got], ["linen", "leather", "velvet"])  # ткань, кожа, ткань
        self.assertIn("Диваны", S.MATERIALS)


class TestCatalog(unittest.TestCase):
    def test_guess_theme(self):
        self.assertEqual(
            U.guess_theme("model", {"categories": ["furniture", "seating"], "tags": ["chair"]}), "Дом - мебель"
        )
        self.assertEqual(U.guess_theme("model", {"categories": ["rocks"], "tags": ["boulder"]}), "Пустыня и скалы")
        self.assertEqual(U.guess_theme("model", {"categories": ["xyz"], "tags": []}), "Разное")

    def test_browse_sorted(self):
        cat = {"a": {"name": "A", "download_count": 1}, "b": {"name": "B", "download_count": 9}}
        with mock.patch.object(U, "catalog", return_value=cat):
            got = U.browse("model")
        self.assertEqual([c["id"] for c in got], ["b", "a"])
        self.assertTrue(all(c["thumb"].startswith("https://") for c in got))

    def test_refetch_only_known_sources(self):
        self.assertFalse(U.can_refetch({"source": "Kenney", "kind": "model"}))
        self.assertTrue(U.can_refetch({"source": "Poly Haven", "kind": "tex"}))
        with self.assertRaises(ValueError):
            U.refetch({"source": "Kenney", "kind": "model", "id": "x", "name": "x", "dir": "."}, "2k")


class TestImport(unittest.TestCase):
    def test_script_and_same_names(self):
        import ast
        import json

        from library import unreal_import

        tmp = tempfile.mkdtemp()
        try:
            src = []
            for pack in ("a", "b"):  # одно имя в двух наборах
                d = os.path.join(tmp, "src", pack)
                os.makedirs(d)
                open(os.path.join(d, "Stool.fbx"), "w").close()
                src.append({"name": "Stool", "kind": "model", "dir": d, "main": ["Stool.fbx"]})
            dst = os.path.join(tmp, "out")
            script = unreal_import.export(src, dst)
            self.assertEqual(sorted(os.listdir(dst)), ["Stool", "Stool_2", "import_to_unreal.py"])
            with open(script, encoding="utf-8") as fh:
                text = fh.read()
            compile(text, script, "exec")  # скрипт для Unreal - правильный Python
            jobs = json.loads(ast.literal_eval(text.split("JOBS = json.loads(", 1)[1].split(")\n", 1)[0]))
            self.assertEqual([j["dest"] for j in jobs], ["/Game/Library/Models/Stool", "/Game/Library/Models/Stool_2"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestPack(unittest.TestCase):
    def test_pack_folder_and_zip(self):
        import json
        import zipfile

        from library import unreal_pack

        tmp = tempfile.mkdtemp()
        try:
            d = os.path.join(tmp, "src", "oak")
            os.makedirs(d)
            open(os.path.join(d, "oak_diff_2k.jpg"), "wb").close()
            a = {
                "id": "oak",
                "name": "Oak Floor",
                "kind": "tex",
                "dir": d,
                "main": ["oak_diff_2k.jpg"],
                "source": "Poly Haven",
                "authors": ["Rico Cilliers"],
                "url": "https://polyhaven.com/a/oak",
                "license": "CC0 1.0",
            }
            folder = unreal_pack.pack([a], os.path.join(tmp, "out"), "Моя спальня")
            names = set(os.listdir(folder))
            self.assertTrue({"CREDITS.md", "manifest.json", "import_to_unreal.py", "Oak_Floor"} <= names)
            with open(os.path.join(folder, "CREDITS.md"), encoding="utf-8") as fh:
                credits = fh.read()
            self.assertIn("Rico Cilliers", credits)
            self.assertIn("CC0", credits)
            with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["assets"][0]["id"], "oak")
            arc = unreal_pack.pack([a], os.path.join(tmp, "out2"), "Моя спальня", zip_it=True)
            with zipfile.ZipFile(arc) as zf:
                self.assertTrue(any(n.endswith("CREDITS.md") for n in zf.namelist()))
            cfg = {}
            for _ in range(7):
                unreal_pack.remember_use(cfg, [a], "D:/Proj")
            self.assertEqual(cfg["ue_used"]["oak"], ["D:/Proj"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestFiles(unittest.TestCase):
    def test_inside(self):
        root = os.path.join("C:\\", "lib", "a")
        self.assertEqual(U.inside(root, "textures/x.jpg"), os.path.join(root, "textures", "x.jpg"))
        for bad in ("../x.jpg", "textures/../../x.jpg", "C:/Windows/x.dll", "/etc/x", ""):
            with self.assertRaises(OSError, msg=bad):
                U.inside(root, bad)

    def test_put_in_place_replaces(self):
        tmp = tempfile.mkdtemp()
        try:
            dst, new = os.path.join(tmp, "Chair"), os.path.join(tmp, "Chair.part")
            os.makedirs(dst)
            os.makedirs(new)
            open(os.path.join(dst, "old.fbx"), "w").close()
            open(os.path.join(new, "new.fbx"), "w").close()
            U.put_in_place(new, dst)
            self.assertEqual(sorted(os.listdir(tmp)), ["Chair"])  # ни .part, ни .old не осталось
            self.assertEqual(os.listdir(dst), ["new.fbx"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestKenneyKits(unittest.TestCase):
    """Новые наборы Kenney: общая текстура Textures/colormap.png, мелкие превью не берутся, своя категория."""

    def setUp(self):
        import zipfile

        from PIL import Image

        self.tmp = tempfile.mkdtemp()
        self.packs = mock.patch.object(U, "PACKS", self.tmp)
        self.packs.start()
        buf = os.path.join(self.tmp, "p.png")
        Image.new("RGB", (64, 64), "red").save(buf)
        with zipfile.ZipFile(os.path.join(self.tmp, "castle-kit.zip"), "w") as zf:
            zf.writestr("Models/FBX format/tower-square.fbx", b"Kaydara FBX Binary")
            zf.writestr("Models/FBX format/Textures/colormap.png", b"png")
            zf.write(buf, "Previews/tower-square.png")

    def tearDown(self):
        self.packs.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fetch_with_colormap(self):
        th = "Средневековье - Kenney low-poly"
        self.assertIn("castle-kit", U.THEMES[th]["kenney"])
        self.assertTrue(U.has_kind(th, "model"))
        self.assertFalse(U.has_kind(th, "tex"))
        cands = U.kenney_candidates("castle-kit", ["medieval"])
        self.assertEqual([c["name"] for c in cands], ["Tower square"])
        dst = os.path.join(self.tmp, "out")
        os.makedirs(dst)
        meta = U.fetch_kenney(cands[0], dst)
        self.assertEqual(meta["extra"], ["Textures/colormap.png"])
        self.assertEqual(meta["categories"], ["medieval"])
        self.assertTrue(os.path.exists(os.path.join(dst, "Textures", "colormap.png")))
        self.assertFalse(os.path.exists(os.path.join(dst, "preview.webp")))  # 64x64 - нарисует 3D-сцена

    def test_import_copies_colormap(self):
        from library import unreal_import

        src = os.path.join(self.tmp, "asset")
        os.makedirs(os.path.join(src, "Textures"))
        open(os.path.join(src, "tower.fbx"), "w").close()
        open(os.path.join(src, "Textures", "colormap.png"), "w").close()
        a = {"name": "Tower", "kind": "model", "dir": src, "main": ["tower.fbx"], "extra": ["Textures/colormap.png"]}
        unreal_import.plan([a], os.path.join(self.tmp, "dst"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "dst", "Tower", "Textures", "colormap.png")))


class TestQuaterniusFolders(unittest.TestCase):
    """Папки набора Quaternius находятся по странице: FBX - в любой вложенной папке, кроме Blends/OBJ/glTF."""

    TREE = {
        "root": [("Buildings", "b", True), ("Blends", "x", True), ("License.txt", "l", False)],
        "b": [("FBX", "bf", True), ("OBJ", "bo", True)],
        "bf": [("House_1.fbx", "h1", False), ("Notes.txt", "n", False)],
        "bo": [("House_1.obj", "o1", False), ("House_1.mtl", "m1", False)],
        "x": [("House_1.fbx", "WRONG", False)],
    }

    def test_walk_and_cache(self):
        tmp = tempfile.mkdtemp()
        page = b'<a href="https://drive.google.com/drive/folders/root?usp=sharing">Download</a>'
        try:
            with (
                mock.patch.object(U, "QFOLDERS", os.path.join(tmp, "q.json")),
                mock.patch.object(U, "get", return_value=page),
                mock.patch.object(U, "drive_entries", side_effect=lambda f: self.TREE.get(f, [])) as de,
            ):
                info = U.quaternius_folders("medievalvillage")
                self.assertEqual([list(x) for x in info["fbx"]], [["House_1.fbx", "h1"]])  # копия из Blends не взята
                self.assertEqual(info["mtl"], {"House_1": "m1"})
                calls = de.call_count
                again = U.quaternius_folders("medievalvillage")  # из кэша, без Google Drive
                self.assertEqual(de.call_count, calls)
                self.assertEqual([list(x) for x in again["fbx"]], [["House_1.fbx", "h1"]])
                cands = U.quaternius_candidates("medievalvillage", ["medieval"])
                self.assertEqual([(c["name"], c["categories"]) for c in cands], [("House 1", ["medieval"])])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestGroups(unittest.TestCase):
    """Раскладка для дерева окна и ue_search: группа, раздел, стиль."""

    def test_group_section_style(self):
        from library import unreal_groups as G

        car = {"kind": "model", "name": "Police car", "theme": "Город - Kenney low-poly", "source": "Kenney"}
        tree = {"kind": "model", "name": "Pine tree 2", "theme": "Лес и природа", "source": "Poly Haven"}
        bed = {"kind": "model", "name": "bedDouble", "theme": "Дом - Kenney low-poly", "source": "Kenney"}
        plat = {
            "kind": "model",
            "name": "Block grass",
            "theme": "Прототипы и уровни - Kenney low-poly",
            "source": "Kenney",
            "tags": ["low-poly", "kenney", "platformer"],
        }
        floor = {"kind": "tex", "name": "Oak", "theme": "Дом - полы", "source": "Poly Haven"}
        G.annotate([car, tree, bed, plat, floor])
        self.assertEqual((car["_g"], car["_s"]), ("Город и транспорт", "Транспорт"))
        self.assertEqual((tree["_g"], tree["_s"]), ("Природа", "Деревья"))
        self.assertEqual((bed["_g"], bed["_s"]), ("Дом", "Кровати"))
        self.assertEqual(plat["_s"], "Платформер")
        self.assertEqual((floor["_g"], floor["_s"]), ("Дом", "Полы"))
        self.assertEqual(G.style_of(car), "Kenney")
        self.assertTrue(G.style_ok(car, "low") and not G.style_ok(car, "real"))
        self.assertTrue(G.style_ok(tree, "real") and not G.style_ok(tree, "KayKit"))
        self.assertEqual(G.group_of("Средневековье - KayKit low-poly"), "Средневековье и фэнтези")
        self.assertEqual(G.group_of("Что-то новое"), "Разное")


class TestDuplicates(unittest.TestCase):
    """Повтор - то же имя и то же превью; разные модели с одним именем или одно превью у разных - не повтор."""

    def test_same_name_and_preview(self):
        from PIL import Image, ImageDraw

        from library import unreal_extra as X

        tmp = tempfile.mkdtemp()
        try:

            def asset(sub, name, color, aid, size=10):
                d = os.path.join(tmp, sub)
                os.makedirs(d)
                im = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
                ImageDraw.Draw(im).rectangle((20, 30, 100, 110), fill=color)
                im.save(os.path.join(d, "preview.webp"))
                return {"dir": d, "name": name, "kind": "model", "id": aid, "size": size, "_pt": 1.0}

            a = asset("a", "Grass", (40, 200, 60, 255), "kenney-x-grass", 5)
            b = asset("b", "grass", (40, 200, 60, 255), "local-pack-grass", 50)
            c = asset("c", "Grass", (200, 40, 40, 255), "kenney-y-grass")  # то же имя, другой цвет
            e = asset("e", "Rock", (40, 200, 60, 255), "kenney-rock")  # то же превью, другое имя
            with (
                mock.patch.object(X, "SIGS_STORE", os.path.join(tmp, "sigs.json")),
                mock.patch.object(X, "ROOT", tmp),
            ):
                groups = X.duplicates([a, b, c, e])
                self.assertEqual([[x["id"] for x in g] for g in groups], [["kenney-x-grass", "local-pack-grass"]])
                why = dict((x["id"], w) for x, w in X.check([a, b, c, e]) if x is not None)
                self.assertIn("повтор", why["local-pack-grass"])  # скачанное из сети остаётся, из архива - повтор
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class TestFromProject(unittest.TestCase):
    """Модели из проекта Unreal: путь /Game, отбор частей MetaHuman, лицензия не CC0."""

    def test_paths_parts_license(self):
        from library import unreal_from_project as P

        proj = os.path.join("C:\\", "P", "Game", "Game.uproject")
        self.assertEqual(
            P.game_path(proj, os.path.join("C:\\", "P", "Game", "Content", "MetaHumans", "Emanuel")),
            "/Game/MetaHumans/Emanuel",
        )
        with self.assertRaises(ValueError):
            P.game_path(proj, os.path.join("C:\\", "Other"))
        self.assertTrue(P.mh_skip("Hair_S_AfroFade_CardsMesh_Group0_LOD3"))
        self.assertTrue(P.mh_skip("SKM_Face_Preview"))
        self.assertFalse(P.mh_skip("Hair_S_AfroFade_CardsMesh_Group0_LOD0"))
        order = sorted(["Emanuel_FaceMesh", "m_top_hoodie", "m_med_nrw_body"], key=P.mh_order)
        self.assertEqual(order[0], "m_med_nrw_body")
        self.assertFalse(U.is_cc0({"license": P.METAHUMAN_LICENSE}))  # в тексте есть «не CC0»
        self.assertTrue(U.is_cc0({"license": U.LICENSE}))


class TestRoomLayout(unittest.TestCase):
    def test_chandeliers_hang(self):
        from library import room_layout as R

        models = [{"name": "Sofa 03"}, {"name": "Chandelier 01"}, {"name": "Ceiling Fan"}, {"name": "Chair"}]
        items, w, _d = R.layout(models)
        hang = [it for it in items if it.get("hang")]
        self.assertEqual({it["a"]["name"] for it in hang}, {"Chandelier 01", "Ceiling Fan"})
        self.assertEqual(len(items), 4)  # люстры не пропадают и не занимают место на полу
        for it in hang:
            self.assertLess(abs(it["x"]), w / 2)


class TestAgentKit(unittest.TestCase):
    """ue_kit / ue_similar / ue_compare на подставных ассетах и подставном поиске по смыслу."""

    def setUp(self):
        from PIL import Image

        self.tmp = tempfile.mkdtemp()
        self.items = []
        for i, (name, kind) in enumerate(
            [("Palm A", "model"), ("Palm B", "model"), ("Fern", "model"), ("Moss", "tex"), ("Sky", "hdri")]
        ):
            d = os.path.join(self.tmp, name)
            os.makedirs(d)
            im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
            im.paste((40, 160, 90, 255), (90, 90, 110, 110))  # маленький рисунок посередине пустого поля
            im.save(os.path.join(d, "preview.webp"))
            self.items.append(
                {
                    "id": name.lower().replace(" ", "_"),
                    "name": name,
                    "kind": kind,
                    "dir": d,
                    "theme": "Лес и природа",
                    "source": "Poly Haven",
                    "polycount": 100 * (i + 1),
                    "size": 2**20,
                    "_g": "Природа",
                    "_s": "Деревья",
                }
            )

        class Sem:
            def rank(self, query, items, gap=None):
                return [(a, 9.0 - k) for k, a in enumerate(items)]

            def similar(self, a, items, top=60):
                return [(x, 0.9) for x in items if x["dir"] != a["dir"]][:top]

        self.patches = [
            mock.patch("library.api_unreal._items", lambda: self.items),
            mock.patch("library.api_unreal._sem", lambda: Sem()),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_kit_parts_without_repeats(self):
        from library import api_unreal as A

        pic = A.ue_kit("джунгли", per_part=2)
        self.assertIn("1. Palm A", pic.text)
        names = [line.split(". ", 1)[1].split(" (")[0] for line in pic.text.splitlines() if line[:1].isdigit()]
        self.assertEqual(len(names), len(set(names)))  # ассет - только в одной части
        self.assertIn("Moss", names)
        self.assertIn("Sky", names)
        self.assertGreater(pic.im.width, 300)

    def test_similar_compare_and_trim(self):
        from library import api_unreal as A

        pic = A.ue_similar("palm_a")
        self.assertIn("образец", pic.text)
        self.assertNotIn("Moss", pic.text)  # тот же вид, что у образца
        table = A.ue_compare(["palm_a", "fern"]).text
        self.assertIn("| 2 | Fern |", table)
        im = A._preview(self.items[0])
        self.assertLess(im.width, 60)  # пустые поля превью обрезаны
