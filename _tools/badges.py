#!/usr/bin/env python3
"""Бейджи README, которые не надо править руками: число тестов и картинок -> _docs/badges/*.json
(формат shields.io endpoint). Запускается git-хуком перед каждым коммитом (.githooks/pre-commit),
так что бейджи на GitHub всегда свежие, а коммиты остаются авторскими - без бота в CI.

    py -3.14 _tools/badges.py          # пересчитать
    py -3.14 _tools/badges.py --stage  # и добавить изменённые файлы в коммит (для хука)"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(os.path.dirname(HERE), "_docs", "badges")


def count_tests():
    """Сколько проверок соберёт unittest (с унаследованными), без запуска."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    suite = unittest.defaultTestLoader.discover(os.path.join(HERE, "tests"), top_level_dir=os.path.join(HERE, "tests"))
    return suite.countTestCases()


def count_images():
    """Картинок в разделах библиотеки (без входящих и служебных папок)."""
    import imaging as K
    from library.common import LIB

    return sum(1 for f in K.images_in(LIB) if not os.path.relpath(f, LIB).startswith(("_", ".")))


def badge(label, message, color):
    return {"schemaVersion": 1, "label": label, "message": message, "color": color}


def write(name, data):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name + ".json")
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == text:
                return None
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def main():
    changed = [
        write("tests", badge("тестов", str(count_tests()), "a6e3a1")),
        write("images", badge("картинок", str(count_images()), "89b4fa")),
    ]
    changed = [p for p in changed if p]
    for p in changed:
        print("бейдж:", os.path.relpath(p, os.path.dirname(HERE)))
    if "--stage" in sys.argv and changed:
        subprocess.run(["git", "add", "--", *changed], cwd=os.path.dirname(HERE), check=False)


if __name__ == "__main__":
    main()
