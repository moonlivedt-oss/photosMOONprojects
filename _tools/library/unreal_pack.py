"""Пакет для проекта: ассеты Unreal одной папкой - файлы, import_to_unreal.py (настройки текстур и
материалы), CREDITS.md (источник, авторы, лицензия каждого) и manifest.json; по желанию - ещё и zip.
Без Qt: окно, сервер MCP и тесты."""

import json
import os
import shutil
import time

from library import unreal_import

KIND_RU = {"tex": "PBR-текстура", "hdri": "HDRI", "model": "3D-модель", "ies": "IES-профиль"}


def credits_md(assets, title):
    """Кто сделал и на каких условиях: CC0 указывать не обязательно, но так честнее и проще найти оригинал."""
    lines = [
        f"# {title}",
        "",
        f"Собрано {time.strftime('%d.%m.%Y')} библиотекой картинок. Лицензии ассетов - ниже; у CC0 указывать автора",
        "не обязательно, список - чтобы знать, откуда что, и найти оригинал.",
        "",
        "| Ассет | Вид | Источник | Авторы | Лицензия |",
        "|---|---|---|---|---|",
    ]
    for a in assets:
        name = a.get("name", "")
        src = a.get("source", "") or "библиотека"
        if a.get("url"):
            src = f"[{src}]({a['url']})"
        authors = ", ".join(x for x in a.get("authors", []) if x != a.get("source")) or "-"
        lic = "CC0" if "CC0" in a.get("license", "") else (a.get("license") or "-")
        lines.append(f"| {name} | {KIND_RU.get(a.get('kind'), a.get('kind', ''))} | {src} | {authors} | {lic} |")
    return "\n".join(lines) + "\n"


def pack(assets, dst, title="Пакет", zip_it=False):
    """Собрать пакет в dst/<title>/. -> путь папки (или zip-архива, если zip_it)."""
    from library.unreal_import import asset_name

    folder = os.path.join(dst, asset_name(title) if title else "Pack")
    os.makedirs(folder, exist_ok=True)
    script = unreal_import.export(assets, folder)
    with open(os.path.join(folder, "CREDITS.md"), "w", encoding="utf-8") as fh:
        fh.write(credits_md(assets, title))
    manifest = {
        "title": title,
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "import_script": os.path.basename(script),
        "assets": [
            {
                k: a.get(k)
                for k in ("id", "name", "kind", "theme", "source", "url", "authors", "license", "res", "main")
                if a.get(k) is not None
            }
            for a in assets
        ],
    }
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    if zip_it:
        arc = shutil.make_archive(folder, "zip", os.path.dirname(folder), os.path.basename(folder))
        return arc
    return folder


def remember_use(cfg, assets, where):
    """«Использовано в»: какой ассет в какой проект ушёл (настройки, ue_used: {id: [папки]})."""
    used = cfg.setdefault("ue_used", {})
    for a in assets:
        lst = used.setdefault(a.get("id", ""), [])
        if where not in lst:
            lst.append(where)
            del lst[:-5]  # последние пять мест
