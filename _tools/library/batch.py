"""Пакетные действия с файлами без Qt: сжатие, копии в другом формате, правка по рецепту, выгрузка
в проект. Работают по ядрам процессора; возвращают шаги для отмены (журнал, Ctrl+Z).
Их зовут окно, командная строка и сервер для ИИ-помощников."""

import os
import shutil
import time

import imaging as K
import library.common as C
from library import journal
from library.common import parallel, unique


def run(job, items, stop=None):
    """job по файлам: пара файлов - прямо здесь (процессы по ядрам запускаются дольше), больше - по ядрам."""
    if len(items) > 2:
        yield from parallel(job, items, stop)
        return
    for p, o in items:
        try:
            yield p, job(p, o)
        except Exception as e:
            yield p, e


def keep_path(arch, p):
    """Куда убрать оригинал: та же раскладка папок внутри arch (файл не из библиотеки - по имени)."""
    try:
        rel = os.path.relpath(p, C.LIB)
    except ValueError:  # другой диск
        rel = ""
    if not rel or rel.startswith(".."):
        rel = os.path.basename(p)
    dst = unique(os.path.join(arch, rel))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    return dst


# ---------------------------------------------------------------- сжатие и копии
CAN = ("webp", "avif", "png", "jpg")  # во что умеем пережимать


def section(path):
    """Раздел верхнего уровня - для итогов «где сэкономлено»."""
    return os.path.relpath(path, C.LIB).split(os.sep)[0]


def compress_files(paths, o, report):
    """В фоне: сжать файлы по настройкам, по ядрам процессора. Оригиналы уезжают в
    _sources/compress <дата>, так что Ctrl+Z всё возвращает. report((i, n, имя, было, стало, путь)) -
    ход работы. Возвращает (шаги для отмены, итоги; в итогах sections - {раздел: [было, стало]})."""
    arch = os.path.join(C.SOURCES, "compress " + time.strftime("%Y-%m-%d"))
    steps, done, skipped, before, after, sections = [], 0, {}, 0, 0, {}
    items = []
    for p in paths:
        src_fmt = K.fmt_of(p)
        fmt = src_fmt if o["fmt"] in ("", "clean") else o["fmt"]
        if src_fmt == "svg" or (fmt not in CAN and o["fmt"] not in ("clean", K.BEST)):
            skipped["не поддерживается"] = skipped.get("не поддерживается", 0) + 1
            continue
        if K.is_animated(p):  # из анимации остался бы один кадр
            skipped["анимация"] = skipped.get("анимация", 0) + 1
            continue
        items.append(
            (p, {k: v for k, v in o.items() if k != "stop"} | dict(fmt=fmt if o["fmt"] != "clean" else "clean"))
        )
    for i, (p, res) in enumerate(run(K.job_compress, items, o.get("stop"))):
        report((i, len(items), os.path.basename(p), before, after, p))
        try:
            if isinstance(res, Exception):
                raise res
            data, info = res
            was = os.path.getsize(p)
            if data is None or (o.get("smaller", True) and len(data) >= was):
                skipped["не стало меньше"] = skipped.get("не стало меньше", 0) + 1
                continue
            new = os.path.splitext(p)[0] + "." + info["fmt"]
            keep = keep_path(arch, p)
            shutil.move(p, keep)
            steps.append(("move", p, keep))
            if os.path.exists(new):
                new = unique(new)
            K.write_atomic(new, data)
            steps.append(("new", new))
            steps += journal.follow(p, new, C.LIB)  # формат сменился - метки и избранное за картинкой
            done += 1
            before += was
            after += len(data)
            sec = sections.setdefault(section(p), [0, 0])
            sec[0] += was
            sec[1] += len(data)
        except Exception as e:
            skipped[f"ошибка: {e}"] = skipped.get(f"ошибка: {e}", 0) + 1
    return steps, dict(done=done, before=before, after=after, skipped=skipped, total=len(paths), sections=sections)


COPY_FORMATS = [
    ("webp", "webp"),
    ("avif", "avif"),
    ("png", "png"),
    ("jpg", "jpg"),
    ("ico", "ico"),
    (K.BEST, "самый лёгкий"),
    ("svg", "svg - контуры"),
]


def copy_files(paths, fmt, report, stop=None):
    """Копии рядом с оригиналами в другом формате, качество подбирается на глаз, по ядрам.
    Возвращает (шаги для Ctrl+Z, сделано, не вышло)."""
    items = [
        (p, dict(fmt=fmt, q=0, target=0.99, kind="auto"))
        for p in paths
        if not p.lower().endswith(".svg") and K.fmt_of(p) != fmt and not K.is_animated(p)
    ]
    steps, bad = [], 0
    for i, (p, res) in enumerate(run(K.job_compress, items, stop)):
        report((i, len(items), os.path.basename(p)))
        if isinstance(res, Exception) or res[0] is None:
            bad += 1
            continue
        data, info = res
        new = unique(os.path.splitext(p)[0] + "." + info["fmt"])
        try:
            with open(new, "wb") as fh:
                fh.write(data)
        except OSError:  # нет места или прав - остальные копии всё равно делаем
            bad += 1
            continue
        steps.append(("new", new))
    return steps, len(steps), bad


# ---------------------------------------------------------------- правка
def save_edits(paths, ops, adj, copy, report, target=None):
    """В фоне, по ядрам: рецепт ко всем файлам. target - папка, куда положить новые файлы с теми же
    именами (перекраска в другую палитру); copy - новый файл рядом; иначе оригинал уезжает
    в _sources/edit <дата>. Возвращает (шаги для Ctrl+Z, [(было, стало)], [ошибки])."""
    arch = os.path.join(C.SOURCES, "edit " + time.strftime("%Y-%m-%d"))
    steps, done, bad = [], [], []
    items = [(p, dict(ops=ops, adj=adj)) for p in paths]
    if target:
        os.makedirs(target, exist_ok=True)
    for i, (p, res) in enumerate(run(K.job_edit, items)):
        report((i, len(items), os.path.basename(p)))
        try:
            if isinstance(res, Exception):
                raise res
            data, fmt, _size = res
            stem = os.path.splitext(p)[0]
            if target:
                new = unique(os.path.join(target, os.path.basename(stem) + "." + fmt))
            elif copy:
                new = unique(stem + " правка." + fmt)
            else:
                keep = keep_path(arch, p)
                shutil.move(p, keep)
                steps.append(("move", p, keep))
                new = stem + "." + fmt
                if os.path.exists(new):
                    new = unique(new)
            K.write_atomic(new, data)
            steps.append(("new", new))
            if not copy and not target:
                steps += journal.follow(p, new, C.LIB)
            done.append((p, new))
        except Exception as e:
            bad.append(f"{os.path.basename(p)}: {e}")
    return steps, done, bad


# ---------------------------------------------------------------- выгрузка
# заготовки выгрузки: имя, настройки (fmt "" - как есть, "iconset" - набор значков, q 0 - подобрать на глаз)
EXPORT_PRESETS = [
    ("Своя настройка", None),
    ("Фон для VS Code (webp, 1920)", dict(fmt="webp", q=0, size=1920, fit="fit")),
    ("Для README (webp, 1280)", dict(fmt="webp", q=0, size=1280, fit="fit")),
    ("Для сайта (avif, 1600)", dict(fmt="avif", q=0, size=1600, fit="fit")),
    (
        "Для телеграма (png 512, квадрат)",
        dict(fmt="png", q=100, size=512, fit="square"),
    ),
    (
        "Аватар (png 256, обрезать в квадрат)",
        dict(fmt="png", q=100, size=256, fit="fill"),
    ),
    (
        "Значок программы (ico + png 256 + favicon)",
        dict(fmt="iconset", q=100, size=0, fit="square"),
    ),
    ("Для сайта: набор @1x @2x @3x (webp)", dict(fmt="webp", q=0, size=0, fit="fit", retina=True)),
    ("Под лимит Discord (самый лёгкий, до 8 МБ)", dict(fmt="best", q=0, size=0, fit="fit", budget=8000)),
    (
        "Наклейка для телеграма (webp 512, до 64 КБ)",
        dict(fmt="webp", q=0, size=512, fit="square", trim=True, budget=64),
    ),
    ("Значок в svg (контуры)", dict(fmt="svg", q=0, size=0, fit="fit", trim=True)),
    ("Атлас для игры или сайта (клетка 128)", dict(fmt="atlas", q=0, size=128, fit="fit")),
    ("SVG-спрайт для сайта (symbol + use)", dict(fmt="svgsprite", q=0, size=0, fit="fit", trim=True)),
]


def export(paths, folder, o, report=None):
    """Копии картинок в folder по настройкам o (как у compress + retina). Как есть и без размера -
    простое копирование; пережатие идёт по ядрам. Возвращает число выгруженных картинок."""
    os.makedirs(folder, exist_ok=True)
    n, todo = 0, []
    fmt = o.get("fmt", "")
    if fmt == "atlas":
        return export_atlas(paths, folder, o)
    if fmt == "svgsprite":
        return export_sprite(paths, folder, o, report)
    plain = (
        not fmt
        and not o.get("size")
        and o.get("fit", "fit") == "fit"
        and not (o.get("trim") or o.get("retina") or o.get("budget"))
    )
    for p in paths:
        stem, ext = os.path.splitext(os.path.basename(p))
        if p.lower().endswith(".svg") or plain:
            shutil.copy2(p, unique(os.path.join(folder, stem + ext)))
            n += 1
        elif fmt == "iconset":
            K.icon_set(K.load(p), folder, stem)
            n += 1
        else:
            todo.append((p, dict(o)))
    for i, (p, res) in enumerate(run(K.job_export, todo)):
        if report:
            report((n + i, len(paths), os.path.basename(p)))
        if isinstance(res, Exception):
            continue
        stem = os.path.splitext(os.path.basename(p))[0]
        for tail, f, data in res:
            with open(unique(os.path.join(folder, stem + tail + "." + f)), "wb") as fh:
                fh.write(data)
        n += 1
    return n


def export_atlas(paths, folder, o):
    """Спрайт-лист png (клетка = «Размер», по умолчанию 128) + JSON (кадры, как у TexturePacker) + CSS."""
    paths = [p for p in paths if not p.lower().endswith(".svg")]
    cell = o.get("size") or 128
    sheet, frames = K.atlas(paths, cell)
    png = unique(os.path.join(folder, "атлас.png"))
    stem = os.path.splitext(png)[0]
    sheet.save(png, "PNG", optimize=True)
    js, css = K.atlas_files(os.path.basename(png), frames, sheet.size)
    with open(stem + ".json", "w", encoding="utf-8") as fh:
        fh.write(js)
    with open(stem + ".css", "w", encoding="utf-8") as fh:
        fh.write(css)
    return len(frames)


def export_sprite(paths, folder, o, report=None):
    """Все значки контурами (vtracer) в один svg с <symbol id=...> и страница-шпаргалка с примерами <use>."""
    paths = [p for p in paths if not p.lower().endswith(".svg")]
    names = K.frame_ids(paths)
    by_path = dict(zip(paths, names))
    items = []
    for i, (p, res) in enumerate(run(K.job_svg, [(p, dict(o)) for p in paths])):
        if report:
            report((i, len(paths), os.path.basename(p)))
        if not isinstance(res, Exception):
            items.append((by_path[p], res))
    items.sort(key=lambda x: names.index(x[0]))
    svg = unique(os.path.join(folder, "спрайт.svg"))
    with open(svg, "w", encoding="utf-8") as fh:
        fh.write(K.svg_sprite(items))
    demo = [
        '<!doctype html><meta charset="utf-8"><title>Спрайт</title>',
        "<style>body{font:14px system-ui;background:#15151c;color:#e8e6f0;padding:20px}"
        ".g{display:grid;grid-template-columns:repeat(auto-fill,120px);gap:12px}"
        ".i{background:#1f1f29;border-radius:10px;padding:10px;text-align:center}"
        "svg.ic{width:64px;height:64px}code{font-size:11px;color:#9a98a8;word-break:break-all}</style>",
        f"<p>Вставьте содержимое {os.path.basename(svg)} в страницу (или подключите файлом) и пишите "
        '<code>&lt;svg&gt;&lt;use href="#имя"/&gt;&lt;/svg&gt;</code></p><div class="g">',
    ]
    for name, _d in items:
        i = K.css_id(name)
        demo.append(
            f'<div class="i"><svg class="ic"><use href="{os.path.basename(svg)}#{i}"/></svg><br><code>#{i}</code></div>'
        )
    demo.append("</div>")
    with open(os.path.splitext(svg)[0] + " - шпаргалка.html", "w", encoding="utf-8") as fh:
        fh.write("\n".join(demo))
    return len(items)
