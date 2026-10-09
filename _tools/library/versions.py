"""Прошлые версии картинки: правка и сжатие не стирают оригинал, а откладывают его в
_sources/edit <дата> и _sources/compress <дата> с той же раскладкой папок (batch.keep_path). Отсюда -
список версий и возврат любой из них (тоже отменяемый). Без Qt."""

import glob
import os
import re
import shutil
import time

import imaging as K
import library.common as C
from library import journal

KINDS = (("edit ", "правка"), ("compress ", "сжатие"))


def versions(path):
    """Прошлые версии картинки, новые первыми: [{path, kind, date, t, size}].
    Формат мог смениться (png -> webp при сжатии) - сравнивается имя без расширения."""
    try:
        rel = os.path.relpath(path, C.LIB)
    except ValueError:
        return []
    if rel.startswith(".."):
        return []
    sub, name = os.path.split(rel)
    stem = os.path.splitext(name)[0]
    same = re.compile(re.escape(stem) + r"( \d+)?$", re.IGNORECASE)  # keep_path добавляет « 2» при повторе
    out = []
    for prefix, kind in KINDS:
        for d in glob.glob(os.path.join(C.SOURCES, glob.escape(prefix) + "*")):
            folder = os.path.join(d, sub)
            if not os.path.isdir(folder):
                continue
            for f in os.listdir(folder):
                p = os.path.join(folder, f)
                if os.path.isfile(p) and f.lower().endswith(K.EXT) and same.match(os.path.splitext(f)[0]):
                    t = os.path.getmtime(p)
                    out.append(
                        {
                            "path": p,
                            "kind": kind,
                            "date": os.path.basename(d)[len(prefix) :],
                            "t": t,
                            "size": os.path.getsize(p),
                        }
                    )
    return sorted(out, key=lambda v: (v["date"], v["t"]), reverse=True)


def restore(path, version):
    """Вернуть версию на место картинки. Текущая сама становится версией (уходит в _sources/edit <сегодня>),
    метки и избранное остаются за картинкой. -> (новый путь, шаги для журнала)."""
    from library.batch import keep_path

    if not os.path.isfile(version):
        raise FileNotFoundError(version)
    keep = keep_path(os.path.join(C.SOURCES, "edit " + time.strftime("%Y-%m-%d")), path)
    stem = os.path.splitext(path)[0]
    new = stem + os.path.splitext(version)[1].lower()
    steps = []
    shutil.move(path, keep)
    steps.append(["move", path, keep])
    if os.path.exists(new):  # другой файл с тем же именем и форматом версии - не затирать
        new = C.unique(new)
    shutil.copy2(version, new)
    steps.append(["new", new])
    steps += journal.follow(path, new, C.LIB)  # формат сменился - метки, заметка и избранное за картинкой
    return new, steps
