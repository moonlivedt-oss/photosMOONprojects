"""Сборка Gallery.html и done.js по папкам библиотеки."""
import html
import json
import os
import time

from imaging.files import LIB, images_in, size_of, write_atomic

TEMPLATE = os.path.join(LIB, "_tools", "gallery_template.html")


def build_gallery():
    """Пересобрать Gallery.html и done.js (по нему Prompts.html прячет готовые карточки). -> {раздел: число}."""
    secs, files = {}, []
    for f in images_in(LIB):
        rel = os.path.relpath(f, LIB).replace("\\", "/")
        parts = rel.split("/")
        if len(parts) < 2:
            continue
        try:
            st = os.stat(f)                 # файл могли перенести, пока шла сборка
        except OSError:
            continue
        files.append(f)
        sec, grp = parts[0], "/".join(parts[1:-1])
        info = "%d КБ" % max(1, st.st_size // 1024)
        if not f.lower().endswith(".svg"):
            try:
                info = "%dx%d, %s" % (size_of(f) + (info,))
            except Exception:
                pass
        secs.setdefault(sec, {}).setdefault(grp, []).append(
            {"file": rel, "name": html.escape(parts[-1]), "info": info, "t": int(st.st_mtime)})
    data = {"sections": [{"name": html.escape(s), "groups": [{"name": html.escape(g), "items": secs[s][g]} for g in sorted(secs[s])]}
                         for s in sorted(secs)], "built": time.strftime("%d.%m.%Y %H:%M"), "root": LIB}
    with open(TEMPLATE, encoding="utf-8") as fh:
        page = fh.read()
    js = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    write_atomic(os.path.join(LIB, "Gallery.html"), page.replace("/*DATA*/null", js), "utf-8")
    have = {}
    for f in files:
        have.setdefault(os.path.basename(os.path.dirname(f)), []).append(os.path.splitext(os.path.basename(f))[0])
    write_atomic(os.path.join(LIB, "_tools", "done.js"),
                 "window.HAVE = " + json.dumps(have, ensure_ascii=False) + ";\n", "utf-8")
    return {s: sum(len(v) for v in secs[s].values()) for s in sorted(secs)}
