"""Подборка по описанию: тип комнаты, стиль без смешения, без повторов, пол и стены разные."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from library import scene_plan as P  # noqa: E402


def asset(name, kind="model", theme="Дом - мебель", source="Poly Haven", section=""):
    return {
        "name": name,
        "kind": kind,
        "theme": theme,
        "source": source,
        "dir": name + "|" + source,
        "section": section,
    }


class Sem:
    """Поиск по смыслу без модели: выше тот, в чьём имени есть слово запроса."""

    def rank(self, query, items):
        words = query.lower().split()
        scored = [(a, sum(w in a["name"].lower() for w in words)) for a in items]
        return [(a, s) for a, s in sorted(scored, key=lambda x: -x[1]) if s > 0]


class ScenePlan(unittest.TestCase):
    def test_room_by_words(self):
        self.assertEqual(P.room_of("уютная спальня"), "спальня")
        self.assertEqual(P.room_of("industrial kitchen"), "кухня")
        self.assertEqual(P.room_of("светлая просторная комната"), P.DEFAULT_ROOM)
        self.assertTrue(P.low_poly_wanted("low-poly кухня"))
        self.assertFalse(P.low_poly_wanted("старинный кабинет"))

    def test_plan(self):
        items = [
            asset("Oak Bed", section="Кровати"),
            asset("Bed", source="Kenney", theme="Дом - Kenney low-poly", section="Кровати"),
            asset("Oak Cabinet", section="Шкафы и полки"),
            asset("Oak Cabinet 2", section="Шкафы и полки"),  # та же вещь из другого набора
            asset("Old Shelf", section="Шкафы и полки"),
            asset("Pine Shelf", section="Шкафы и полки"),
            asset("Oak Floor", kind="tex", theme="Дом - плитка и камень"),
            asset("Stone Tiles", kind="tex", theme="Дом - плитка и камень"),
            asset("Sky", kind="hdri", theme="Студия"),
        ]
        p = P.plan(Sem(), items, "oak bedroom", lambda a: a["section"])
        self.assertEqual(p["room"], "спальня")
        first = [s["choices"][0]["name"] for s in p["slots"]]
        self.assertEqual(first[0], "Oak Bed")  # стиль запроса наверху
        self.assertNotIn("Bed", first)  # low-poly не смешивается с реализмом
        shelves = [s["choices"][0]["name"] for s in p["slots"] if s["section"] == "Шкафы и полки"]
        self.assertEqual(len(shelves), 2)
        self.assertNotIn("Oak Cabinet 2", shelves)  # без повторов
        self.assertEqual(p["floor"][0]["name"], "Oak Floor")
        self.assertNotEqual(p["wall"][0]["name"], p["floor"][0]["name"])  # стены - не тем же, что пол
        self.assertEqual(len(P.chosen(p)), len(p["slots"]) + 3)

    def test_mixed_style_when_own_is_scarce(self):
        items = [asset("Plunger", section="Ванная")] + [
            asset(n, source="Quaternius", theme="Дом - Quaternius low-poly", section="Ванная")
            for n in ("Bathtub", "Sink", "Toilet")
        ]
        p = P.plan(Sem(), items, "bathroom", lambda a: a["section"])
        names = {s["choices"][0]["name"] for s in p["slots"] if s["section"] == "Ванная"}
        self.assertTrue(names & {"Bathtub", "Sink", "Toilet"})


if __name__ == "__main__":
    unittest.main()
