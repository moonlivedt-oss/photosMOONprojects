"""Ещё ассеты Unreal: раздел текстуры по материалу, повторы по превью, отбор моделей Smithsonian (без сети)."""

import os
import sys
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from library import unreal_groups as G  # noqa: E402
from library import unreal_more as M  # noqa: E402


def noise(seed, color=(120, 110, 100), size=256):
    """Плавный «камень»: шум, размытый до пятен (у ровных квадратов разностный хэш случаен)."""
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 255, (size, size), dtype=np.uint8)
    g = np.asarray(Image.fromarray(a).filter(ImageFilter.GaussianBlur(8)), dtype=float)
    g = (g - g.mean()) / (g.std() + 1e-6) * 40
    return Image.fromarray(np.clip(np.asarray(color)[None, None, :] + g[..., None], 0, 255).astype(np.uint8))


class TestTexSection(unittest.TestCase):
    def test_sections(self):
        cases = {
            "Wood Floor 041": "Полы",
            "Fabric 085": "Ткани и кожа",
            "Paving Stones 128": "Брусчатка",
            "Bricks 076": "Кирпич",
            "Diamond Plate 004": "Металл",
            "Roofing Tiles 012": "Крыши",  # не «Плитка»: крыши проверяются раньше
            "Rock 030": "Камни и скалы",
            "Snow 006": "Снег и лёд",
            "Plastic 010": M.TEX_OTHER,
        }
        for name, sec in cases.items():
            self.assertEqual(M.tex_section({"name": name}), sec, name)

    def test_name_before_tags(self):
        # имя точнее меток: «Wood Floor» с меткой fabric - всё равно пол
        self.assertEqual(M.tex_section({"name": "Wood Floor 01", "tags": ["fabric"]}), "Полы")
        # без подсказки в имени - по категориям
        self.assertEqual(M.tex_section({"name": "Ground 054", "categories": ["terrain"]}), "Земля и трава")
        self.assertEqual(M.tex_section({"name": "Aerial Rocks 02"}), "Камни и скалы")

    def test_theme(self):
        self.assertEqual(M.tex_theme({"name": "Bricks 090"}), "Город")
        self.assertEqual(M.tex_theme({"name": "Wood 096"}), M.MATERIALS)
        self.assertEqual(M.tex_theme({"name": "Fingerprints 004"}), M.MATERIALS)

    def test_tree_section(self):
        a = {"kind": "tex", "theme": "Город", "name": "Asphalt 02"}
        self.assertEqual(G.section_of(a), "Асфальт и дороги")
        self.assertEqual(G.group_of({"kind": "tex", "theme": M.MATERIALS}), "Материалы")
        self.assertIn("Металл", G.section_order("Космос и sci-fi"))


class TestDuplicates(unittest.TestCase):
    def test_same_and_different(self):
        a = M.tex_sig(noise(1))
        same = M.tex_sig(noise(1).resize((100, 100)))  # та же съёмка в другом размере
        other = M.tex_sig(noise(2))  # другой камень того же цвета
        recolor = M.tex_sig(noise(1, (60, 90, 160)))  # тот же рисунок, другой цвет - не повтор
        self.assertTrue(M.same_tex(a, same))
        self.assertFalse(M.same_tex(a, other))
        self.assertFalse(M.same_tex(a, recolor))

    def test_dedupe_keeps_first(self):
        sig = {"acg:a": M.tex_sig(noise(3)), "acg:b": M.tex_sig(noise(3)), "acg:c": M.tex_sig(noise(4))}
        cands = [{"src": "acg", "id": "a", "name": "Rock 01 A"}, {"src": "acg", "id": "b", "name": "Rock 01 B"}]
        cands.append({"src": "acg", "id": "c", "name": "Rock 01 C"})
        kept, dropped = M.dedupe(cands, sig)
        self.assertEqual([c["id"] for c in kept], ["a", "c"])
        self.assertEqual(dropped, [("Rock 01 B", "Rock 01 A")])

    def test_family_and_drape(self):
        self.assertEqual(M.family("Planks 037 B"), "planks 037")
        self.assertEqual(M.family("Brick Wall 02"), "brick wall 02")
        # те же складки у двух разных тканей Poly Haven - не повтор, даже при одинаковом отпечатке
        sig = {"ph:a": M.tex_sig(noise(6)), "ph:b": M.tex_sig(noise(6))}
        cands = [{"src": "ph", "id": k, "name": k.upper(), "info": {"categories": ["fabric"]}} for k in "ab"]
        kept, _ = M.dedupe(cands, sig)
        self.assertEqual(len(kept), 2)
        # слегка другой вариант той же съёмки (A и B) - повтор; у разных материалов так же близко - нет
        near = M.tex_sig(Image.blend(noise(7), noise(9), 0.3))
        sig = {"acg:a": M.tex_sig(noise(7)), "acg:b": near, "acg:c": near}
        cands = [{"src": "acg", "id": "a", "name": "Planks 037 A"}, {"src": "acg", "id": "b", "name": "Planks 037 B"}]
        cands.append({"src": "acg", "id": "c", "name": "Wood 090"})
        kept, dropped = M.dedupe(cands, sig)
        self.assertEqual([c["id"] for c in kept], ["a", "c"])

    def test_map_sig(self):
        import tempfile

        d = tempfile.mkdtemp()
        try:
            noise(8).save(os.path.join(d, "a_Color.jpg"), quality=90)
            noise(8).resize((180, 180)).save(os.path.join(d, "b_diff_1k.jpg"), quality=80)
            items = [
                {"kind": "tex", "id": "a", "dir": d, "main": ["a_Color.jpg"], "added": "1"},
                {"kind": "tex", "id": "b", "dir": d, "main": ["b_diff_1k.jpg"], "added": "2"},
            ]
            with mock.patch.object(M.U, "CACHE", os.path.join(d, "cache.json")):
                groups = M.tex_duplicates(items)
            self.assertEqual([[a["id"] for a in g] for g in groups], [["a", "b"]])
        finally:
            import shutil

            shutil.rmtree(d, ignore_errors=True)

    def test_dedupe_against_downloaded(self):
        sig = {"have:x": M.tex_sig(noise(5)), "acg:b": M.tex_sig(noise(5))}
        kept, dropped = M.dedupe([{"src": "acg", "id": "b", "name": "Rock 01 B"}], sig, [{"id": "x", "name": "Rock 01 A"}])
        self.assertEqual(kept, [])


class TestSmithsonian(unittest.TestCase):
    def test_wanted(self):
        self.assertEqual(M.si_wanted("1903 Wright Flyer"), (True, None))
        self.assertEqual(M.si_wanted("Pongo abelii: Fibula Left")[0], False)  # отдельная кость
        self.assertEqual(M.si_wanted("Gorilla gorilla gorilla: Cranium"), (True, "Gorilla"))
        self.assertEqual(M.si_wanted("Unio poeyanus"), (True, "Unio"))
        self.assertFalse(M.si_wanted("Crab Nebula")[0])  # модели туманностей - не предметы
        self.assertFalse(M.si_wanted(": 2nd Floor")[0])
        self.assertFalse(M.si_wanted("")[0])

    def test_pick(self):
        files = [
            ["https://x/resources/a-150k-4096.glb", "Low_resolution", "Download3D"],
            ["https://x/a-150k-4096-high.glb", "High", "Web3D"],
            ["https://x/a-150k-2048-medium.glb", "Medium", "Web3D"],
        ]
        self.assertEqual(M.si_pick(files), ["https://x/a-150k-2048-medium.glb"])
        self.assertEqual(M.si_pick(files[:1]), [])  # ссылки resources у Smithsonian битые
        parts = [["https://x/p/https://cdn.x/w-wings-2048-medium.glb", "Medium", "Web3D"]]
        parts.append(["https://x/p/https://cdn.x/w-engine-2048-medium.glb", "Medium", "Web3D"])
        self.assertEqual(M.si_pick(parts), ["https://x/p/w-engine-2048-medium.glb", "https://x/p/w-wings-2048-medium.glb"])


class TestNames(unittest.TestCase):
    def test_base(self):
        self.assertEqual(M._base("Abraham Lincoln's Patent Model"), "Abraham_Lincoln_s_Patent_Model")
        self.assertEqual(M._base("(A)"), "A")
        self.assertEqual(M._base("..."), "model")

    def test_quote(self):
        self.assertEqual(M.quote("https://a/b c/(d),e.glb"), "https://a/b%20c/%28d%29%2Ce.glb")

    def test_license(self):
        lic, who = M.kh_license([{"spdx": "CC0-1.0", "license": "CC0-1.0", "artist": "Eric"}])
        self.assertTrue(lic.startswith("CC0"))
        lic, who = M.kh_license([{"spdx": "CC-BY-4.0", "license": "CC-BY 4.0", "artist": "Rico"}])
        self.assertFalse(lic.startswith("CC0"))
        self.assertIn("Rico", lic)


if __name__ == "__main__":
    unittest.main()
