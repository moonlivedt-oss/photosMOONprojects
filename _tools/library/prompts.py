"""Данные страницы Prompts.html: палитры (с цветами), карточки (наборы и одиночные), готовые промпты.
Страница - это JS; его выполняет node (так имена, маршруты и тексты совпадают со страницей до буквы).
Результат кэшируется в _prompts_cache.json по времени изменения страницы. Без node - только палитры
(их хватает перекраске), а «чего не хватает» просит поставить node."""

import json
import os
import re
import shutil
import subprocess

from library.common import HERE, LIB, clean_name, log_error

PAGE = os.path.join(LIB, "Prompts.html")
CACHE = os.path.join(HERE, "_prompts_cache.json")

# Выполняет код страницы до раздела «отрисовка» (там уже DOM) и печатает данные одним JSON.
NODE = r"""
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
let code = scripts[scripts.length - 1];
code = code.split("// ---------------- отрисовка")[0];
const ctx = {window: {}, console};
vm.createContext(ctx);
vm.runInContext(code + `
;var OUT = {pals: PAL, cards: []};
S.forEach(function (sec) { sec[3].forEach(function (it) {
  if (!it[1].n) it[1].n = it[1].k + "-" + slug(it[0], 3);
  OUT.cards.push({sec: sec[0], title: it[0], k: it[1].k, r: it[1].r, n: it[1].n, p: it[1].p,
                  ratio: it[2], pal: it[3] || sec[2], avoid: N[it[4] || sec[1]]});
}); });`, ctx);
process.stdout.write(JSON.stringify(ctx.OUT));
"""

_data = {"mt": None, "v": None}


def set_name(title):
    """Как setName() на странице: «Интерфейс: основное» -> «Интерфейс - основное»."""
    t = re.sub(r"\s*\(.*?\)", "", title)
    if re.match(r"^(Новый год|Хэллоуин|Весна|Лето|Осень|День рождения):", t):
        return t.split(":")[0]
    return t.replace(": ", " - ")


def _regex_pals(text):
    out = []
    for m in re.finditer(r'^\s*\["(\w+)","([^"]+)","([^"]*)",\[(.*?)\]\]', text, re.M):
        out.append([m.group(1), m.group(2), m.group(3), re.findall(r'"(#[0-9a-fA-F]{6})"', m.group(4))])
    return out


def load():
    """{pals: [[id, имя, описание, [цвета]]], cards: [...], node: bool} или None, если страницы нет."""
    try:
        mt = os.path.getmtime(PAGE)
    except OSError:
        return None
    if _data["mt"] == mt:
        return _data["v"]
    v = None
    try:
        with open(CACHE, encoding="utf-8") as fh:
            c = json.load(fh)
        if c.get("mt") == mt:
            v = c["data"]
    except Exception:
        pass
    if v is None:
        node = shutil.which("node")
        if node:
            try:
                r = subprocess.run(
                    [node, "-e", NODE, PAGE],
                    capture_output=True,
                    timeout=30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                v = json.loads(r.stdout.decode("utf-8"))
                v["node"] = True
            except Exception as e:
                log_error(f"Prompts.html не прочиталась через node: {e}")
        if v is None:
            with open(PAGE, encoding="utf-8") as fh:
                v = {"pals": _regex_pals(fh.read()), "cards": [], "node": False}
        try:
            with open(CACHE, "w", encoding="utf-8") as fh:
                json.dump({"mt": mt, "data": v}, fh, ensure_ascii=False)
        except OSError:
            pass
    _data.update(mt=mt, v=v)
    return v


def palettes():
    """[(id, имя, папка, [цвета])] - только настоящие палитры (без «Как задумано»)."""
    d = load() or {"pals": []}
    return [(p[0], p[1], clean_name(p[1]), p[3]) for p in d["pals"] if p[3]]


def pal_by_folder():
    return {f: (i, n, c) for i, n, f, c in palettes()}


def cards():
    return (load() or {}).get("cards", [])


def prompt(card, pal):
    """Полный текст, как кнопка «Копировать» на странице."""
    pals = {p[0]: p for p in (load() or {"pals": []})["pals"]}
    p = pals.get(pal) or pals.get(card["pal"])
    return card["p"].replace("{P}", p[2] if p else "") + "\nAvoid: " + card["avoid"] + "."


def file_label(card, pal):
    """Имя файла с меткой, как кнопка «Имена»: «Космос [ic tokyo]»."""
    return (set_name(card["title"]) if card["k"] == "sheet" else card["n"]) + " [{} {}]".format(card["r"], pal)


def names(card):
    return [x for x in card["n"].split(", ") if x]


def dest(card, pal):
    """Папка, куда ляжет карточка в этой палитре (как route() у файла с меткой), или None."""
    from library.sorting import ROUTES

    if card["r"] not in ROUTES:
        return None
    pals = {p[0]: p for p in (load() or {"pals": []})["pals"]}
    tpl = ROUTES[card["r"]][0]
    text = set_name(card["title"]) if card["k"] == "sheet" else card["n"]
    rel = tpl.format(set=clean_name(text), pal=clean_name(pals[pal][1] if pal in pals else pal))
    return os.path.join(LIB, *rel.split("/"))


def has_pal(card):
    from library.sorting import ROUTES

    return card["r"] in ROUTES and "{pal}" in ROUTES[card["r"]][0]


def status(card, pal):
    """(сделано имён, всего) в папке этой палитры. Лист готов при 2/3 - как на странице."""
    d = dest(card, pal)
    want = names(card)
    if not d or not os.path.isdir(d):
        return 0, len(want)
    stems = [os.path.splitext(f)[0] for f in os.listdir(d)]
    got = sum(1 for n in want if any(s == n or s.startswith(n + "_") for s in stems))
    return got, len(want)


def done(got, total):
    return got * 3 >= total * 2 if total > 1 else got == 1
