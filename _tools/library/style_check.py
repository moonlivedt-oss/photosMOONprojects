"""Проверки манеры по библиотеке без Qt: что выбивается из своего набора (imaging.style) и видно ли картинку
на фонах палитры (imaging.contrast). Общие для окна и помощника."""

import os

import imaging as K
from imaging import contrast, style
from library import common as C
from library import prompts


def _imported(rel):
    return any(part in K.IMPORTED for part in rel.split(os.sep))


def job(path, _o=None):
    """Для процессов по ядрам (common.parallel)."""
    return style.features_of(path)


def odd_ones(folder=None, imported=False, stop=None, step=None):
    """Картинки, выбивающиеся из своего набора (папки с картинками). imported - и чужие наборы (Kenney...).
    -> [{path, set, reasons: [(признак, оценка, подпись)], palettes: [папки палитр, где так же]}],
    отсортировано по силе отличия. Если картинка «выбивается» в нескольких палитрах одного набора - одна строка."""
    root = folder or C.LIB
    groups = {}
    for f in K.images_in(root):
        rel = os.path.relpath(f, C.LIB)
        top = rel.split(os.sep)[0]
        if top.startswith(("_", ".")) or top == K.INBOX or f.lower().endswith((".svg", ".ico")):
            continue
        if not imported and _imported(rel):
            continue
        groups.setdefault(os.path.dirname(f), []).append(f)
    files = [f for g in groups.values() if len(g) >= style.MIN_SET for f in g]
    feats = {}
    for i, (p, res) in enumerate(C.parallel(job, [(p, None) for p in files], stop)):
        feats[p] = res if isinstance(res, dict) else None  # исключение из процесса - как пустая
        if step and i % 100 == 0:
            step(i, len(files))
    pals = prompts.pal_by_folder()
    found = {}
    for d, g in groups.items():
        for p, why in style.odd_ones({f: feats.get(f) for f in g}).items():
            pal = os.path.basename(d) if os.path.basename(d) in pals else None
            key = (os.path.dirname(d) if pal else d, os.path.basename(p) if pal else p)
            item = found.get(key)
            reasons = [(n, s, style.reason(n, s)) for n, s in why]
            if item is None:
                found[key] = dict(
                    path=p,
                    set=os.path.relpath(key[0], C.LIB),
                    reasons=reasons,
                    palettes=[pal] if pal else [],
                    score=max(abs(s) for _n, s in why),
                )
            else:
                item["palettes"].append(pal)
                if max(abs(s) for _n, s in why) > item["score"]:
                    item.update(path=p, reasons=reasons, score=max(abs(s) for _n, s in why))
    return sorted(found.values(), key=lambda x: -x["score"])


def backgrounds(path, extra=()):
    """Фоны для проверки контраста: основа палитры папки (если картинка из набора с палитрой), белый,
    тёмная тема и свои. -> [(имя, #цвет)]"""
    out = []
    pals = prompts.pal_by_folder()
    for part in reversed(os.path.relpath(path, C.LIB).split(os.sep)[:-1]):
        if part in pals:
            _id, name, colors = pals[part]
            out.append((f"Палитра «{name}»", colors[0]))
            break
    out += list(contrast.DEFAULT_BGS)
    out += [(c, c) for c in extra]
    seen, uniq = set(), []
    for n, c in out:
        if c.lower() not in seen:
            seen.add(c.lower())
            uniq.append((n, c))
    return uniq


def contrast_of(paths, extra=()):
    """{путь: результат contrast.check или None (нет прозрачности - фон, фото)}"""
    out = {}
    for p in paths:
        try:
            out[p] = contrast.check(p, backgrounds(p, extra))
        except Exception:
            out[p] = None
    return out
