"""Связь ИИ-помощника с открытым окном, без Qt. Сервер MCP и окно - разные процессы, поэтому через два
маленьких файла в _tools:
  _ui_request.json   - «покажи в окне»: помощник нашёл картинки или ассеты и выводит их пользователю
                       на экран (окно опрашивает файл раз в 2 с, вместе с журналом действий);
  _unreal_changed    - отметка времени: помощник скачал, импортировал или поменял подборки Unreal -
                       вкладка Unreal перечитывает ассеты сама.
Окно не открыто - запрос просто лежит; откроется окно - покажет только свежий (не старше SHOW_TTL)."""

import json
import os
import time

import imaging as K
from library.common import HERE

REQUEST = os.path.join(HERE, "_ui_request.json")
UE_CHANGED = os.path.join(HERE, "_unreal_changed")
SHOW_TTL = 600  # запрос «показать» старше 10 минут окно при запуске уже не показывает


def request(where, items, title, who):
    """where: "library" (пути картинок от корня) или "unreal" (id ассетов). -> id запроса."""
    rid = time.time()
    data = {"id": rid, "where": where, "items": list(items), "title": title, "who": who}
    K.write_atomic(REQUEST, json.dumps(data, ensure_ascii=False), "utf-8")
    return rid


def pending(seen):
    """Новый запрос (id больше seen) или None."""
    try:
        with open(REQUEST, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    rid = data.get("id", 0)
    if rid <= seen or time.time() - rid > SHOW_TTL:
        return None
    return data


def ue_changed():
    """Отметить: ассеты Unreal поменялись не в окне."""
    try:
        with open(UE_CHANGED, "w", encoding="utf-8") as fh:
            fh.write(str(time.time()))
    except OSError:
        pass


def ue_stamp():
    try:
        return os.path.getmtime(UE_CHANGED)
    except OSError:
        return 0
