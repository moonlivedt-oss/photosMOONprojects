"""Старые оригиналы в _sources: что там копится и что можно убрать. Без Qt - сам перенос в корзину
Windows делает окно (QFile.moveToTrash), отсюда только список.

Что лежит в _sources:
  edit <дата>      - оригиналы до правки (это «версии» картинок: убрать - значит потерять откат)
  compress <дата>  - оригиналы до сжатия (тоже версии)
  <год-месяц>      - разобранные листы из входящих (по ним можно нарезать заново)
  _deleted/<дата>  - убранное ИИ-помощником
  _undone          - отменённое Ctrl+Z, что ещё можно вернуть Ctrl+Y
"""

import os
import re
import time

import library.common as C

KINDS = (
    ("edit", "Оригиналы до правки", "версии картинок - после чистки «Вернуть версию» их не найдёт"),
    ("compress", "Оригиналы до сжатия", "версии картинок до сжатия"),
    ("sheets", "Разобранные листы", "исходники из входящих - по ним можно нарезать заново"),
    ("deleted", "Убранное ИИ-помощником", "trash помощника; undo вернуть их уже не сможет"),
    ("undone", "Отменённое (Ctrl+Z)", "новые файлы, которые отменили"),
    ("other", "Прочее", "старые папки без даты"),
)
DEFAULT = ("edit", "compress", "deleted", "undone")  # листы по умолчанию не трогаем

_DAY = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?")


def kind_of(name):
    """Вид папки верхнего уровня в _sources."""
    if name.startswith("edit "):
        return "edit"
    if name.startswith("compress "):
        return "compress"
    if re.fullmatch(r"\d{4}-\d{2}", name):
        return "sheets"
    if name == os.path.basename(C.DELETED):
        return "deleted"
    if name == os.path.basename(C.PARK):
        return "undone"
    return "other"


def folder_time(name):
    """Дата из имени папки («edit 2026-10-08», «2026-09», «2026-10-08») -> время или None.
    Месяц считается законченным в его последний день: лист сентября не «старый» уже 1 сентября."""
    m = _DAY.search(name)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), m.group(3)
    try:
        if d:
            return time.mktime((y, mo, int(d), 0, 0, 0, 0, 0, -1))
        y2, mo2 = (y + 1, 1) if mo == 12 else (y, mo + 1)
        return time.mktime((y2, mo2, 1, 0, 0, 0, 0, 0, -1)) - 1
    except (OverflowError, ValueError):
        return None


def scan():
    """Все файлы _sources: [(путь, вид, байт, время)]. Время - дата папки, иначе дата файла:
    оригинал, отложенный сегодня, старый по mtime, но убирать его рано."""
    out = []
    if not os.path.isdir(C.SOURCES):
        return out
    for name in os.listdir(C.SOURCES):
        top = os.path.join(C.SOURCES, name)
        if not os.path.isdir(top):
            continue
        kind = kind_of(name)
        base_t = folder_time(name)
        for d, _dirs, files in os.walk(top):
            first = os.path.relpath(d, top).split(os.sep)[0]
            sub_t = folder_time(first) if kind == "deleted" else None  # _deleted/<дата>/<раздел>/...
            for f in files:
                p = os.path.join(d, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                t = sub_t or base_t or st.st_mtime
                out.append((p, kind, st.st_size, t))
    return out


def summary(files):
    """{вид: [байт, файлов]}."""
    out = {}
    for _p, kind, n, _t in files:
        s = out.setdefault(kind, [0, 0])
        s[0] += n
        s[1] += 1
    return out


def pick(files, kinds, days, now=None):
    """Файлы этих видов старше days дней."""
    edge = (now or time.time()) - days * 86400
    return [f for f in files if f[1] in kinds and f[3] < edge]


def drop_empty_dirs():
    """После чистки - пустые папки прочь (сама _sources и её служебные остаются)."""
    keep = {os.path.normcase(x) for x in (C.SOURCES, C.DELETED, C.PARK)}
    for d, _dirs, _files in sorted(os.walk(C.SOURCES), key=lambda x: -len(x[0])):
        if os.path.normcase(d) in keep:
            continue
        try:
            os.rmdir(d)  # только пустую
        except OSError:
            pass
