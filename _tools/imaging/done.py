"""done.js для Prompts.html: какие картинки уже есть по папкам - страница прячет готовые карточки."""

import json
import os

from imaging.files import LIB, images_in, write_atomic


def build_done():
    """Пересобрать _tools/done.js (window.HAVE = {папка: [имена без расширения]}). -> сколько картинок."""
    have, n = {}, 0
    for f in images_in(LIB):
        rel = os.path.relpath(f, LIB).replace("\\", "/")
        if "/" not in rel:
            continue
        have.setdefault(os.path.basename(os.path.dirname(f)), []).append(os.path.splitext(os.path.basename(f))[0])
        n += 1
    write_atomic(
        os.path.join(LIB, "_tools", "done.js"), "window.HAVE = " + json.dumps(have, ensure_ascii=False) + ";\n", "utf-8"
    )
    return n
