"""Проверка проекта перед публикацией одной кнопкой: лицензии (что из библиотеки там есть и кому нужно указать
авторство), вес картинок (что тяжело и сколько даст webp), контраст выгруженных иконок на фоне проекта, бюджет
сцены ассетов Unreal. -> разделы с уровнем ok | warn | bad и отчёт PUBLISH-CHECK.md. Без Qt."""

import io
import os
import time

import imaging as K
from library import budget, credits, project_fit
from library import common as C

IMG = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tga", ".avif")
SKIP_DIRS = {".git", "node_modules", "Intermediate", "Saved", "DerivedDataCache", "Binaries", ".venv", "__pycache__"}
HEAVY_KB = 300  # для сайта картинка тяжелее - уже заметно на мобильном
ESTIMATE = 12  # сколько самых тяжёлых пережимать в webp для оценки выгоды
REPORT = "PUBLISH-CHECK.md"


def _images(project):
    out = []
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.lower().endswith(IMG):
                p = os.path.join(root, f)
                try:
                    out.append((p, os.path.getsize(p)))
                except OSError:
                    pass
    return out


def _webp_size(path):
    """Сколько весила бы картинка в webp (качество 82 - на глаз неотличимо для большинства картинок)."""
    try:
        im = K.load(path)
        return len(K.encode(im, "webp", quality=82))
    except Exception:
        return None


def weight(project):
    imgs = _images(project)
    total = sum(s for _p, s in imgs)
    heavy = sorted([(p, s) for p, s in imgs if s > HEAVY_KB * 1024], key=lambda x: -x[1])
    rows, save = [], 0
    for p, s in heavy[:ESTIMATE]:
        w = None if p.lower().endswith((".webp", ".gif")) else _webp_size(p)
        if w is not None and w < s:
            save += s - w
        rows.append(dict(path=os.path.relpath(p, project), kb=s // 1024, webp_kb=None if w is None else w // 1024))
    level = "ok" if not heavy else "warn" if len(heavy) < 10 and total < 20 * 2**20 else "bad"
    return dict(
        level=level,
        images=len(imgs),
        total_mb=round(total / 2**20, 1),
        heavy=len(heavy),
        heavy_items=rows,
        webp_saves_mb=round(save / 2**20, 1),
    )


def licenses(project, cfg=None):
    found = credits.collect(project, cfg)
    attr = [g["name"] for g in found["groups"] if g["attribution"]]
    from library import unreal as U

    not_cc0 = [a.get("name", "") for a in found["assets"] if not U.is_cc0(a)]
    have = any(os.path.exists(os.path.join(project, f)) for f in ("CREDITS.md", "CREDITS.library.md"))
    level = "ok"
    if (attr or not_cc0) and not have:
        level = "bad"
    elif attr or not_cc0:
        level = "warn"
    return dict(
        level=level,
        images=len(found["images"]),
        assets=len(found["assets"]),
        attribution=attr,
        not_cc0=not_cc0,
        credits_file=have,
        _found=found,
    )


def project_bgs(project):
    """Фоны проекта: сохранённая палитра (project_palette) или фон страницы из его CSS (светлая и тёмная тема).
    -> [(подпись, #цвет)] (пусто - неизвестен)"""
    pal = project_fit.load(project)
    if pal:
        return [("Фон проекта", pal[0])]
    try:
        return project_fit.css_backgrounds(project)
    except Exception:
        return []


def readability(project, found):
    """Выгруженные в проект иконки и наклейки - на фонах проекта; фон неизвестен - на белом и тёмном, и тогда
    «плохо видно» - только если плохо на обоих."""
    from imaging import contrast

    known = project_bgs(project)
    bgs = known or list(contrast.DEFAULT_BGS)
    bad = []
    checked = 0
    for x in found["images"][:200]:
        p = os.path.join(C.LIB, x["path"])
        try:
            r = contrast.check(p, bgs)
        except Exception:
            continue
        if r is None:
            continue
        checked += 1
        best = max(r["bgs"], key=lambda b: b["share"])
        if (known and r["worst"]["verdict"] == "плохо видно") or (not known and best["verdict"] == "плохо видно"):
            bad.append(dict(path=x["path"], background=r["worst"]["name"], ratio=r["worst"]["ratio"]))
    level = "ok" if not bad else "warn" if len(bad) <= max(2, checked // 5) else "bad"
    return dict(level=level, checked=checked, bad=bad, backgrounds=known)


def scene_budget(found):
    if not found["assets"]:
        return dict(level="ok", assets=0)
    from library import unreal_extra as X

    r = budget.scene(X.apply_meta(found["assets"]))
    t = r["total"]
    level = "bad" if t["heavy"] else "warn" if t["nanite"] or t["gpu_mb"] > budget.POOL_MB else "ok"
    return dict(level=level, assets=t["assets"], total=t, notes=r["notes"])


def check(project, cfg=None):
    """Все проверки -> {licenses, weight, readability, budget, level, when}"""
    if not os.path.isdir(project):
        raise ValueError(f"нет папки {project}")
    lic = licenses(project, cfg)
    found = lic.pop("_found")
    out = dict(
        project=project,
        when=time.strftime("%Y-%m-%d %H:%M"),
        licenses=lic,
        weight=weight(project),
        readability=readability(project, found),
        budget=scene_budget(found),
    )
    levels = [out[k]["level"] for k in ("licenses", "weight", "readability", "budget")]
    out["level"] = "bad" if "bad" in levels else "warn" if "warn" in levels else "ok"
    return out


MARK = {"ok": "[ok]", "warn": "[!]", "bad": "[!!]"}


def markdown(r):
    lic, w, rd, b = r["licenses"], r["weight"], r["readability"], r["budget"]
    say = {"ok": "всё в порядке", "warn": "есть что поправить", "bad": "нужно поправить до публикации"}
    buf = io.StringIO()
    p = buf.write
    p(f"# Проверка перед публикацией: {os.path.basename(os.path.normpath(r['project']))}\n\n")
    p(f"{r['when']}, итог: **{say[r['level']]}**.\n\n")
    p(f"## {MARK[lic['level']]} Лицензии\n\n")
    p(f"Из библиотеки: картинок {lic['images']}, ассетов Unreal {lic['assets']}. ")
    p(
        "CREDITS.md "
        + ("есть.\n" if lic["credits_file"] else "нет - создать: «Инструменты» -> «Авторы и лицензии проекта».\n")
    )
    if lic["attribution"]:
        p(f"- Нужно указать автора (CC BY): {', '.join(lic['attribution'])}\n")
    if lic["not_cc0"]:
        p(f"- Не CC0 - проверить условия: {', '.join(lic['not_cc0'][:20])}\n")
    p(f"\n## {MARK[w['level']]} Вес картинок\n\n")
    p(f"Картинок {w['images']}, всего {w['total_mb']} МБ, тяжелее {HEAVY_KB} КБ: {w['heavy']}.")
    if w["webp_saves_mb"]:
        p(f" В webp самые тяжёлые станут легче на ~{w['webp_saves_mb']} МБ.")
    p("\n\n")
    for x in w["heavy_items"]:
        tail = f" -> webp ~{x['webp_kb']} КБ" if x["webp_kb"] is not None else ""
        p(f"- `{x['path']}` - {x['kb']} КБ{tail}\n")
    p(f"\n## {MARK[rd['level']]} Видно ли иконки\n\n")
    bgs = rd["backgrounds"]
    where = "на " + ", ".join(f"{n} {c}" for n, c in bgs) if bgs else "фон проекта неизвестен - на белом и тёмном"
    p(f"Проверено с прозрачностью: {rd['checked']}, {where}.\n")
    for x in rd["bad"]:
        p(f"- `{x['path']}` - плохо видно на «{x['background']}» ({x['ratio']}:1, нужно 3:1)\n")
    p(f"\n## {MARK[b['level']]} Сцена Unreal\n\n")
    if not b["assets"]:
        p("Ассетов из библиотеки нет.\n")
    else:
        t = b["total"]
        p(
            f"{t['assets']} шт., {t['triangles']:,} треугольников, текстуры ~{t['gpu_mb']} МБ видеопамяти.\n".replace(
                ",", " "
            )
        )
        for n in b["notes"]:
            p(f"- {n}\n")
    return buf.getvalue()


def write(project, cfg=None):
    r = check(project, cfg)
    path = os.path.join(project, REPORT)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(markdown(r))
    r["report"] = path
    return r
