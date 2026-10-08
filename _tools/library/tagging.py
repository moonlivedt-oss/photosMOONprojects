"""Подсказка меток для кусков во входящих: CLIP сравнивает куски со словарём меток и с соседями в библиотеке."""

import os
import threading

import numpy as np

from imaging import clip
from library import db
from library.common import LIB

# Частые метки библиотеки. Свои метки (из базы) добавляются к ним сами. «е» вместо «ё» - как в clean_tag.
VOCAB = (
    "кот",
    "собака",
    "птица",
    "рыба",
    "дракон",
    "лиса",
    "сова",
    "медведь",
    "кролик",
    "насекомые",
    "динозавр",
    "морские жители",
    "монстр",
    "призрак",
    "робот",
    "маскот",
    "персонаж",
    "фея",
    "единорог",
    "слайм",
    "природа",
    "лес",
    "горы",
    "море",
    "озеро",
    "цветы",
    "растения",
    "деревья",
    "небо",
    "облака",
    "закат",
    "звезды",
    "луна",
    "солнце",
    "снег",
    "зима",
    "лето",
    "осень",
    "весна",
    "дождь",
    "погода",
    "космос",
    "планеты",
    "ракета",
    "галактика",
    "город",
    "улица",
    "дом",
    "интерьер",
    "комната",
    "кафе",
    "библиотека",
    "замок",
    "руины",
    "поезд",
    "транспорт",
    "ночь",
    "уют",
    "магия",
    "фэнтези",
    "киберпанк",
    "ретро",
    "хэллоуин",
    "новый год",
    "праздник",
    "тайна",
    "милое",
    "смешное",
    "грустное",
    "радость",
    "любовь",
    "еда",
    "напитки",
    "сладости",
    "фрукты",
    "книги",
    "инструменты",
    "оружие",
    "броня",
    "зелья",
    "сокровища",
    "монеты",
    "кристаллы",
    "ключи",
    "свечи",
    "часы",
    "время",
    "музыка",
    "игры",
    "спорт",
    "награды",
    "медали",
    "письмо",
    "документы",
    "файлы",
    "компьютер",
    "техника",
    "телефон",
    "код",
    "программирование",
    "сеть",
    "интерфейс",
    "кнопки",
    "стрелки",
    "курсоры",
    "рамки",
    "узоры",
    "текстура",
    "градиент",
    "пейзаж",
    "люди",
    "эмоции",
    "жесты",
    "неон",
    "пиксель-арт",
    "акварель",
)
TOP = 6
FLOOR = 0.6  # z-оценка: насколько метка подходит сильнее, чем в среднем по библиотеке
SHARE = 0.5  # и не слабее половины лучшей - иначе к точным меткам липнут случайные
NEIGHBORS = 12
NEAR = 0.8  # соседи ближе этого (косинус) делятся своими метками


class Tagger:
    """Векторы меток считаются один раз (в фоне), словарь пополняется метками из базы."""

    def __init__(self, sem):
        self.sem = sem
        self.words, self.vecs = [], np.zeros((0, clip.DIM), np.float32)
        self.bias = self.sd = None
        self.lock = threading.Lock()         # зовут из разных фоновых потоков

    def _vocab(self):
        try:
            own = list(db.all_tags())
        except Exception:
            own = []
        words = list(dict.fromkeys(list(VOCAB) + own))
        if words != self.words:
            known = dict(zip(self.words, self.vecs))
            self.vecs = np.stack([known[w] if w in known else clip.embed_text(w) for w in words])
            self.words, self.bias = words, None
        if self.bias is None:
            lib = self.sem.mat @ self.vecs.T if len(self.sem.mat) > 50 else None
            self.bias = lib.mean(0) if lib is not None else np.zeros(len(words))
            self.sd = np.maximum(lib.std(0), 1e-3) if lib is not None else np.full(len(words), 0.02)

    def suggest(self, pieces, skip=()):
        """Куски (PIL) -> [метка] по убыванию уверенности. Вызывать из фонового потока."""
        if not self.sem.ok or not pieces:
            return []
        return self.suggest_vecs(clip.embed_images(list(pieces)[:24]), skip)

    def suggest_vecs(self, v, skip=()):
        """То же по готовым векторам CLIP (картинки библиотеки уже посчитаны). skip - уже стоящие метки."""
        if not len(v):
            return []
        with self.lock:
            self._vocab()
            words, vecs, bias, sd = self.words, self.vecs, self.bias, self.sd
        v = np.asarray(v, np.float32)
        # z-оценка каждой метки по каждому куску: у листа из 12 разных предметов наверх выходят
        # метки, подходящие многим кускам сразу (у будильника и песочных часов - «время»)
        z = (v @ vecs.T - bias) / sd
        score = dict(zip(words, np.clip(z, 0, None).mean(0)))
        for tag, w in self._from_neighbors(v).items():
            score[tag] = score.get(tag, 0) + w
        best = sorted((t for t in score if t not in skip), key=score.get, reverse=True)
        if not best:
            return []
        cut = max(FLOOR, SHARE * score[best[0]])
        return [t for t in best if score[t] >= cut][:TOP]

    def _from_neighbors(self, v):
        """Метки почти одинаковых картинок, что уже лежат в библиотеке."""
        if not self.sem.ready():
            return {}
        sim = v @ self.sem.mat.T
        votes = {}
        for row in sim:
            for i in np.argsort(-row)[:NEIGHBORS]:
                if row[i] < NEAR:
                    break
                for tag in db.tags_of(self.sem.paths[i]):
                    votes[tag] = votes.get(tag, 0) + 2 * float(row[i]) / len(sim)
        return votes


def tag_saved(paths, tags):
    """Поставить метки только что сохранённым файлам."""
    if tags:
        db.set_tags([os.path.relpath(p, LIB) for p in paths], tags, "add")
