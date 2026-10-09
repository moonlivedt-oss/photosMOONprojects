"""Подборки ассетов Unreal («Моя спальня»): общий файл _tools/_unreal_sets.json для окна и ИИ-помощников.
Раньше подборки жили в настройках окна - окно держит их в памяти и затёрло бы подборку, собранную
помощником; файл читается заново, как только изменился. Без Qt."""

import json
import os

import imaging as K
import library.common as C

_cache = {"path": None, "mt": None, "data": {}}


def path():
    return os.path.join(C.HERE, "_unreal_sets.json")


def load(cfg=None):
    """{имя: [id ассетов]}. Подборки из старых настроек (cfg["ue_sets"]) переезжают сюда один раз.
    Возвращает один и тот же словарь, пока файл не изменился, - окно правит его на месте и зовёт save()."""
    p = path()
    if cfg is not None and cfg.get("ue_sets") and not os.path.exists(p):
        save(dict(cfg.pop("ue_sets")))
    try:
        mt = os.path.getmtime(p)
    except OSError:
        mt = None
    if _cache["path"] != p or _cache["mt"] != mt:
        data = {}
        if mt is not None:
            try:
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as e:
                C.log_error(f"подборки не читаются: {e!r}")
                data = {}
        _cache.update(path=p, mt=mt, data=data if isinstance(data, dict) else {})
    return _cache["data"]


def save(data=None):
    data = _cache["data"] if data is None else data
    p = path()
    K.write_atomic(p, json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    _cache.update(path=p, mt=os.path.getmtime(p), data=data)


def add(name, ids):
    """Добавить ассеты в подборку (создаётся сама). -> сколько добавлено."""
    sets = load()
    lst = sets.setdefault(name, [])
    n = 0
    for i in ids:
        if i not in lst:
            lst.append(i)
            n += 1
    save(sets)
    return n


def remove(name, ids=None):
    """Убрать ассеты из подборки; ids=None или опустевшая подборка - удалить её."""
    sets = load()
    if name not in sets:
        return 0
    before = len(sets[name])
    if ids is not None:
        sets[name] = [i for i in sets[name] if i not in set(ids)]
    if ids is None or not sets[name]:
        del sets[name]
    save(sets)
    return before - len(sets.get(name, []))
