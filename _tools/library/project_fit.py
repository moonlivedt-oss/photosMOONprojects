"""Палитра проекта: цвета сайта или игры (вписать, взять из картинки-скриншота или из CSS) -> какие наборы
библиотеки к ним подходят. Оценка набора - видно ли его на фоне проекта (контраст края по WCAG, imaging.contrast)
и близки ли его цвета к цветам проекта (разница в Lab); плюс ближайшая палитра из Prompts.html и подсказка
«перекрасить в цвета проекта». Палитра запоминается за папкой проекта (база, таблица projects). Без Qt."""

import os
import re
from collections import Counter

import numpy as np
from PIL import Image

import imaging as K
from imaging import contrast
from imaging.style import _lab
from library import common as C
from library import db, prompts

HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
BG_CSS = re.compile(r"(?:--[\w-]*(?:bg|background|base|surface)[\w-]*|background(?:-color)?)\s*:\s*([^;}\n]+)", re.I)
SAMPLE = 8  # картинок набора на оценку
SIDE = 96


def norm(c):
    c = c.strip().lstrip("#").lower()
    if len(c) == 3:
        c = "".join(x * 2 for x in c)
    if not re.fullmatch(r"[0-9a-f]{6}", c):
        raise ValueError(f"не цвет: {c}")
    return "#" + c


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(int(x) for x in rgb)


def from_image(path, n=6):
    """Главные цвета скриншота сайта или игры; фон - самый частый цвет. -> (фон, [цвета])"""
    im = K.load(path).convert("RGB")
    im.thumbnail((256, 256))
    q = im.quantize(colors=n + 2, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    counts = sorted(q.getcolors() or [], reverse=True)
    cols = [_hex(pal[i * 3 : i * 3 + 3]) for _c, i in counts]
    return cols[0], cols[: n + 1]


def from_css(path, n=8):
    """Цвета из CSS / SCSS / HTML: самые частые; фон - из background / --bg у body или :root. -> (фон, [цвета])"""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    found = [norm(m.group(1)) for m in HEX.finditer(text)]
    found += [_hex([min(255, int(x)) for x in m.groups()]) for m in RGB.finditer(text)]
    if not found:
        raise ValueError("в файле нет цветов (#rrggbb или rgb())")
    bg = None
    for m in BG_CSS.finditer(text):
        h = HEX.search(m.group(1)) or None
        if h:
            bg = norm(h.group(1))
            break
    cols = [c for c, _n in Counter(found).most_common(n + 4)]
    bg = bg or cols[0]
    return bg, [bg] + [c for c in cols if c != bg][:n]


def _declarations(text):
    """CSS -> [(контекст блока: селекторы и @media через «|», свойство, значение)] - с учётом вложенности."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out, stack, start = [], [], 0
    for i, ch in enumerate(text):
        if ch == "{":
            stack.append(text[start:i].strip())
            start = i + 1
        elif ch in ";}":
            part = text[start:i].strip()
            if ":" in part and stack:
                prop, val = part.split(":", 1)
                out.append(("|".join(stack), prop.strip().lower(), val.strip()))
            if ch == "}" and stack:
                stack.pop()
            start = i + 1
    return out


def _resolve(val, defs, depth=0):
    """background: var(--paper) -> #edf1ec (переменные по цепочке); не цвет - None."""
    m = re.search(r"var\(\s*(--[\w-]+)", val)
    if m and depth < 8:
        return _resolve(defs.get(m.group(1), ""), defs, depth + 1)
    h = HEX.search(val)
    if h:
        return norm(h.group(1))
    r = RGB.search(val)
    return _hex([min(255, int(x)) for x in r.groups()]) if r else None


def _project_decls(project):
    decls = []
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "dist", "build", "vendor")]
        for f in sorted(files):
            if f.lower().endswith((".css", ".scss")):
                try:
                    with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                        decls += _declarations(fh.read())
                except OSError:
                    pass
    return decls


def css_accents(project, n=6):
    """Частые цвета из CSS проекта (без фонов страницы) - акценты для подбора наборов."""
    found = []
    for _ctx, _prop, val in _project_decls(project):
        found += [norm(m.group(1)) for m in HEX.finditer(val)]
    bgs = {c for _n, c in css_backgrounds(project)}
    return [c for c, _k in Counter(found).most_common(n + len(bgs)) if c not in bgs][:n]


def css_backgrounds(project):
    """Фон страницы из CSS проекта - для светлой и тёмной темы, с переменными (body { background: var(--paper) }).
    -> [(подпись, #цвет)] (пусто - не нашлось)."""
    decls = _project_decls(project)
    light, dark = {}, {}
    for ctx, prop, val in decls:
        if prop.startswith("--"):
            (dark if "dark" in ctx else light).setdefault(prop, val)
    body = next(
        (
            val
            for ctx, prop, val in decls
            if prop in ("background", "background-color")
            and re.search(r"(^|[\s,|])(body|html|:root)\b", ctx)
            and "dark" not in ctx
        ),
        None,
    )
    out = []
    if body:
        lc = _resolve(body, light)
        dc = _resolve(body, {**light, **dark}) if dark else None
        if lc:
            out.append(("Фон сайта" + (" (светлая тема)" if dc and dc != lc else ""), lc))
        if dc and dc != lc:
            out.append(("Фон сайта (тёмная тема)", dc))
    return out


def _lab_of(hexes):
    return _lab(np.array([K.hex_rgb(h) for h in hexes], np.float64))


# ---------------------------------------------------------------- наборы
def sets(root=None):
    """Наборы для подбора: папки с картинками (от 3), без служебных и входящих. -> {папка: [файлы]}"""
    out = {}
    for f in K.images_in(root or C.LIB):
        if f.lower().endswith((".svg", ".ico")):
            continue
        rel = os.path.relpath(f, C.LIB)
        if rel.split(os.sep)[0].startswith(("_", ".")):
            continue
        out.setdefault(os.path.dirname(f), []).append(f)
    return {d: sorted(fs) for d, fs in out.items() if len(fs) >= 3}


def set_stats(folder, files):
    """Для процессов: силуэты (у картинок с прозрачностью) и цвета рисунка в Lab - по выборке набора."""
    step = max(1, len(files) // SAMPLE)
    edges, colors, alpha = [], [], 0
    for f in files[::step][:SAMPLE]:
        try:
            im = K.load(f)
        except Exception:
            continue
        prep = contrast.prepare(im, side=128)  # силуэт для контраста (маленький - процессы передают его целиком)
        if prep is not None:
            alpha += 1
            edges.append(prep)
        im.thumbnail((SIDE, SIDE))
        a = np.asarray(im.convert("RGBA"), np.float64)
        px = a[..., :3][a[..., 3] > 128]
        if len(px):
            colors.append(px[:: max(1, len(px) // 300)])
    if not colors:
        return None
    return dict(
        edges=edges,
        lab=_lab(np.concatenate(colors)),
        alpha=alpha / max(1, min(len(files), SAMPLE)),
    )


def job(folder, files):
    """Для процессов (common.parallel_own)."""
    return set_stats(folder, files)


def score(stats, bg, colors):
    """-> {contrast, harmony, total} от 0 до 1 (contrast None - у набора нет прозрачности: это фоны).
    bg - фон или список фонов (светлая и тёмная тема): видно должно быть на каждом - берётся худший."""
    cont = None
    if stats["edges"] and stats["alpha"] >= 0.5:  # средняя по картинкам доля края, видного на фоне
        per = []
        for b in [bg] if isinstance(bg, str) else bg:
            vis = [contrast.measure(p, b) for p in stats["edges"]]
            per.append(float(np.mean([0.7 * v[0] + 0.3 * v[3] for v in vis])))
        cont = min(per)
    proj = _lab_of(colors)
    lab = stats["lab"]
    d = np.sqrt(((lab[:, None, :] - proj[None, :, :]) ** 2).sum(-1)).min(1)  # до ближайшего цвета проекта
    harmony = float(np.exp(-np.median(d) / 28))
    total = harmony if cont is None else 0.6 * cont + 0.4 * harmony
    return dict(contrast=None if cont is None else round(cont, 2), harmony=round(harmony, 2), total=round(total, 3))


def nearest_palette(colors):
    """Ближайшая палитра Prompts.html к цветам проекта -> (имя, папка, цвета, расстояние) или None."""
    proj = _lab_of(colors)
    best = None
    for _i, name, folder, cols in prompts.palettes():
        try:
            lab = _lab_of(cols)
        except Exception:
            continue
        d = float(np.sqrt(((lab[:, None, :] - proj[None, :, :]) ** 2).sum(-1)).min(1).mean())
        if best is None or d < best[3]:
            best = (name, folder, cols, d)
    return best


def fit(bg, colors, root=None, stop=None, step=None, limit=60, only="all"):
    """Наборы под палитру проекта, лучшие сверху. only: all | art (с прозрачностью: иконки, наклейки) | bg (фоны,
    узоры). -> {"sets": [...], "palette": ближайшая палитра}"""
    bgs = [norm(b) for b in ([bg] if isinstance(bg, str) else bg)]
    colors = [norm(c) for c in colors] or bgs
    bg = bgs[0] if len(bgs) == 1 else bgs
    groups = sets(root)
    stats = {}
    # свои процессы, а не общий пул окна: при запуске тот занят пакетной работой, а потоки в окне делят GIL
    # с анимациями - подбор шёл бы втрое дольше
    for i, (d, res) in enumerate(C.parallel_own(job, list(groups.items()), stop)):
        stats[d] = res if isinstance(res, dict) else None
        if step and i % 20 == 0:
            step(i, len(groups))
    out = []
    for d, st in stats.items():
        if not st:
            continue
        s = score(st, bg, colors)
        if (only == "art" and s["contrast"] is None) or (only == "bg" and s["contrast"] is not None):
            continue
        out.append(dict(folder=d, set=os.path.relpath(d, C.LIB), count=len(groups[d]), sample=groups[d][:4], **s))
    out.sort(key=lambda x: -x["total"])
    pal = nearest_palette(colors)
    return dict(
        sets=out[:limit],
        palette=None if pal is None else dict(name=pal[0], folder=pal[1], colors=pal[2], distance=round(pal[3], 1)),
    )


# ---------------------------------------------------------------- запомнить за проектом
def save(project, bg, colors):
    db.save_project(os.path.abspath(project), norm(bg), [norm(c) for c in colors])


def load(project):
    """-> (фон, [цвета]) или None"""
    return db.project_palette(os.path.abspath(project))
