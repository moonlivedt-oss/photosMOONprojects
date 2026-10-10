"""Бегущие числа в подписях карточек (ui.animations.tween_text) - без окна."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.animations import tween_text  # noqa: E402


class TestTween(unittest.TestCase):
    def test_numbers_run_between(self):
        self.assertEqual(tween_text("5583 шт., 15.4 ГБ", "5600 шт., 15.8 ГБ", 0.5), "5592 шт., 15.6 ГБ")
        self.assertEqual(tween_text("за неделю: 1 шт.", "за неделю: 121 шт.", 0.25), "за неделю: 31 шт.")

    def test_other_shape_jumps(self):
        self.assertEqual(tween_text("пусто", "5 шт.", 0.5), "5 шт.")
        self.assertEqual(tween_text("1 шт.", "2 шт., 3 МБ", 0.5), "2 шт., 3 МБ")
        self.assertEqual(tween_text("1 шт.", "9 шт.", 1.0), "9 шт.")
