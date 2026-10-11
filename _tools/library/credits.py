"""Авторы и лицензии проекта: всё, что из библиотеки ушло в папку проекта - картинки (выгрузка, «где
использовано») и ассеты Unreal (импорт, пакет, manifest.json пакетов в самой папке), - одним CREDITS.md.
Без Qt: окно, сервер MCP и командная строка.

Лицензия картинки - из ближайшего файла «_авторы и лицензия.txt» вверх по папкам (наборы Kenney, Hero Patterns);
нет такого - картинка своя (сгенерирована для библиотеки). CC BY требует указать автора при публикации -
такие строки помечаются отдельно."""

import json
import os
import time

from library import common as C
from library import db

MARK = "<!-- собрано библиотекой картинок: credits.py -->"  # свой файл можно переписывать, чужой - нет
LICENSE_FILE = "_авторы и лицензия.txt"


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def inside(path, folder):
    path, folder = _norm(path), _norm(folder)
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def license_of(rel, cache=None):
    """Картинка (путь от корня библиотеки) -> {name, license, attribution, file} по ближайшему файлу лицензии."""
    cache = {} if cache is None else cache
    d = os.path.dirname(os.path.join(C.LIB, rel))
    while inside(d, C.LIB):
        if d in cache:
            return cache[d]
        f = os.path.join(d, LICENSE_FILE)
        if os.path.exists(f):
            with open(f, encoding="utf-8", errors="replace") as fh:
                lines = [x.strip() for x in fh if x.strip()]
            lic = next((x.split(":", 1)[1].strip() for x in lines if x.lower().startswith("лицензия")), "")
            info = dict(
                name=lines[0] if lines else os.path.basename(d),
                license=lic,
                attribution="CC BY" in lic.upper() and "CC0" not in lic.upper(),
                file=os.path.relpath(f, C.LIB),
            )
            cache[d] = info
            return info
        if _norm(d) == _norm(C.LIB):
            break
        d = os.path.dirname(d)
    return dict(name="своя", license="своя картинка библиотеки", attribution=False, file="")


def _manifests(folder):
    """id ассетов из manifest.json пакетов внутри папки проекта (пакеты, собранные до учёта в базе)."""
    out = set()
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "Intermediate", "Saved", "DerivedDataCache")]
        if "manifest.json" in files:
            try:
                with open(os.path.join(root, "manifest.json"), encoding="utf-8") as fh:
                    data = json.load(fh)
                out.update(a["id"] for a in data.get("assets", []) if a.get("id"))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                pass
    return out


def collect(project, cfg=None, items=None):
    """Что из библиотеки в проекте. -> {images: [...], assets: [...], groups: [...]}"""
    lic_cache, images = {}, []
    for rel, dest in db.all_exports():
        if inside(dest, project) and os.path.exists(os.path.join(C.LIB, rel)):
            images.append(dict(path=rel.replace(os.sep, "/"), dest=dest, **license_of(rel, lic_cache)))
    seen, uniq = set(), []
    for x in images:
        if x["path"] not in seen:
            seen.add(x["path"])
            uniq.append(x)
    ids = {i for i, dest in db.ue_uses() if inside(dest, project)}
    for i, places in ((cfg or {}).get("ue_used") or {}).items():
        if any(inside(p, project) for p in places):
            ids.add(i)
    ids |= _manifests(project)
    assets = []
    if ids:
        from library import unreal as U

        items = U.assets() if items is None else items
        for a in items:
            k = a.get("id") or os.path.relpath(a["dir"], U.ROOT).replace(os.sep, "/")
            if k in ids:
                assets.append(a)
    groups = {}
    for x in uniq:
        g = groups.setdefault(x["name"], dict(name=x["name"], license=x["license"], attribution=x["attribution"]))
        g["count"] = g.get("count", 0) + 1
    return dict(
        images=uniq, assets=assets, groups=sorted(groups.values(), key=lambda g: (g["name"] == "своя", g["name"]))
    )


def markdown(project, found):
    from library import unreal as U
    from library.unreal_pack import KIND_RU

    title = os.path.basename(os.path.normpath(project))
    attr = [g for g in found["groups"] if g["attribution"]] + [
        a for a in found["assets"] if not U.is_cc0(a) and "CC BY" in (a.get("license") or "").upper()
    ]
    lines = [
        MARK,
        f"# Авторы и лицензии: {title}",
        "",
        f"Собрано {time.strftime('%d.%m.%Y')}. Картинок: {len(found['images'])}, ассетов Unreal: {len(found['assets'])}.",
        "",
    ]
    if attr:
        lines += [
            "> **Нужно указать автора** при публикации (CC BY): "
            + ", ".join(x.get("name", "") for x in attr)
            + ". Строку из таблицы ниже - в титры, README или страницу «Об авторах».",
            "",
        ]
    if found["groups"]:
        lines += ["## Картинки", "", "| Набор | Сколько | Лицензия |", "|---|---|---|"]
        for g in found["groups"]:
            lines.append(f"| {g['name']} | {g['count']} | {g['license'] or '-'} |")
        lines.append("")
        lines += ["<details><summary>Все картинки</summary>", ""]
        for x in found["images"]:
            lines.append(f"- `{x['path']}` - {x['name']}")
        lines += ["", "</details>", ""]
    if found["assets"]:
        lines += ["## Ассеты Unreal", "", "| Ассет | Вид | Источник | Авторы | Лицензия |", "|---|---|---|---|---|"]
        for a in sorted(found["assets"], key=lambda a: (U.is_cc0(a), a.get("name", ""))):
            src = a.get("source", "") or "библиотека"
            if a.get("url"):
                src = f"[{src}]({a['url']})"
            authors = ", ".join(x for x in a.get("authors", []) if x != a.get("source")) or "-"
            lic = "CC0" if U.is_cc0(a) else (a.get("license") or "не указана - проверить на странице источника")
            lines.append(
                f"| {a.get('name', '')} | {KIND_RU.get(a.get('kind'), a.get('kind', ''))} | {src} | {authors} | {lic} |"
            )
        lines.append("")
        other = [a for a in found["assets"] if not U.is_cc0(a)]
        if other:
            lines += [
                f"Не CC0: {len(other)} шт. (Fab, Megascans, MetaHuman и т. п.) - условия у каждого свои, "
                "перед публикацией проверить по ссылке.",
                "",
            ]
    if not found["images"] and not found["assets"]:
        lines += ["Из библиотеки в эту папку пока ничего не выгружалось.", ""]
    return "\n".join(lines)


def write(project, cfg=None):
    """CREDITS.md в папке проекта (чужой CREDITS.md не трогается - тогда CREDITS.library.md).
    -> {path, images, assets, attribution, not_cc0}"""
    from library import unreal as U

    if not os.path.isdir(project):
        raise ValueError(f"нет папки {project}")
    found = collect(project, cfg)
    path = os.path.join(project, "CREDITS.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            if MARK not in fh.read(4096):
                path = os.path.join(project, "CREDITS.library.md")
    text = markdown(project, found)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return dict(
        path=path,
        images=len(found["images"]),
        assets=len(found["assets"]),
        attribution=[g["name"] for g in found["groups"] if g["attribution"]],
        not_cc0=[a.get("name") for a in found["assets"] if not U.is_cc0(a)],
    )
