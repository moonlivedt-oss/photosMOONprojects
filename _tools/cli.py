#!/usr/bin/env python3
"""Командная строка библиотеки картинок (её зовут .cmd из папки cli).

py -3.14 cli.py cut sheet.png [more.png ...] [--grid 4x3] [--size 256] [--names a,b,c]
                              [--bg auto|remove|keep] [--outline 0] [--pad 0.06] [--out DIR]
py -3.14 cli.py convert FILES/DIRS [--to webp|avif|png|jpg|ico] [--max 1920] [--replace]
py -3.14 cli.py dupes [DIR]
py -3.14 cli.py gallery
"""

import argparse
import os
import shutil
import sys

import numpy as np
from PIL import Image

import imaging as K
from imaging import neural

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def cmd_cut(a):
    names = [x.strip() for x in a.names.split(",")] if a.names else []
    grid = tuple(int(v) for v in a.grid.lower().replace("х", "x").split("x")) if a.grid else None
    for src in a.files:
        try:
            pieces, _ = K.cut(K.load(src), grid, a.size, a.bg, a.outline, a.pad)
        except Exception as e:
            print(f"{os.path.basename(src)}: не получилось - {e}")
            continue
        stem = os.path.splitext(os.path.basename(src))[0]
        out = a.out or os.path.join(os.path.dirname(os.path.abspath(src)), stem + " - нарезка")
        print(f"{os.path.basename(src)}: найдено {len(pieces)}")
        for i, piece in enumerate(pieces):
            name = names[i] if i < len(names) else f"{stem}_{i + 1:02d}"
            p = os.path.join(out, f"{name}.{a.format}")
            K.save(piece, p, a.format)
            print("  ->", p)


def cmd_convert(a):
    files = []
    for f in a.files:
        files += K.images_in(f) if os.path.isdir(f) else [f]
    for src in files:
        name = os.path.basename(src)
        if src.lower().endswith((".svg", "." + a.to)):
            continue
        if K.is_animated(src):
            print(f"{name}: анимация - пропущено (сохранился бы один кадр)")
            continue
        dst = os.path.splitext(src)[0] + "." + a.to
        try:
            im = K.load(src)
            if a.max and a.to != "ico":
                im = K.resize(im, a.max)
            K.save(im, dst, a.to)
        except Exception as e:
            print(f"{name}: не получилось - {e}")
            continue
        print(
            f"{name} -> {os.path.basename(dst)}  ({os.path.getsize(src) // 1024} КБ -> {os.path.getsize(dst) // 1024} КБ)"
        )
        if a.replace:
            os.remove(src)


def cmd_dupes(a):
    """Одна картинка в разных размерах или форматах: самая крупная остаётся, остальные ПЕРЕНОСЯТСЯ в _duplicates."""
    root = os.path.abspath(a.dir or K.LIB)
    paths, ratios, vecs, rank = [], [], [], []
    for f in K.images_in(root):
        if f.lower().endswith(".svg"):
            continue
        try:
            with Image.open(f) as im:
                im.load()
                im = K.upright(im).copy()
        except Exception:
            continue
        r, v = K.signature(im)
        paths.append(f)
        ratios.append(r)
        vecs.append(v.ravel())
        rank.append((im.width * im.height, os.path.getsize(f)))
    if not paths:
        print("Картинок нет.")
        return
    ratios, vecs = np.array(ratios), np.array(vecs)
    gone, moved = np.zeros(len(paths), bool), 0
    for i in range(len(paths)):
        if gone[i]:
            continue
        same = (np.abs(ratios - ratios[i]) / ratios < K.SAME_RATIO) & (np.abs(vecs - vecs[i]).mean(1) < K.SAME_DIFF)
        same[: i + 1] = False
        same &= ~gone
        group = [i] + list(np.flatnonzero(same))
        if len(group) < 2:
            continue
        group.sort(key=lambda j: rank[j], reverse=True)
        print("оставлено:", os.path.relpath(paths[group[0]], root))
        for j in group[1:]:
            gone[j] = True
            rel = os.path.relpath(paths[j], root)
            dst = os.path.join(root, "_duplicates", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.move(paths[j], dst)
            except OSError as e:
                print("   не перенесено:", rel, "-", e)
                continue
            moved += 1
            print("   в _duplicates:", rel)
    print(f"Перенесено в _duplicates: {moved}" if moved else "Дублей нет.")


def cmd_gallery(_a):
    counts = K.build_gallery()
    print(f"Галерея: {sum(counts.values())} картинок")
    for s, n in counts.items():
        print(f"  {s}: {n}")


def _neural(a, ready, tail, fn):
    """Нейросеть по файлам: результат - png рядом с исходником, исходник не трогается."""
    if not ready():
        print("Нет модели: py -3.14 _tools/get_models.py")
        return
    for src in a.files:
        try:
            out = fn(K.load(src))
        except Exception as e:
            print(f"{os.path.basename(src)}: не получилось - {e}")
            continue
        dst = f"{os.path.splitext(src)[0]} {tail}.png"
        K.save(out, dst, "png")
        print(f"{os.path.basename(src)} -> {os.path.basename(dst)}  {out.width}x{out.height}")


def cmd_upscale(a):
    def run(im):
        kind = ("art" if K.is_art(im) else "photo") if a.kind == "auto" else a.kind
        return neural.upscale(im, a.x, kind)

    _neural(a, neural.upscale_available, f"x{a.x}", run)


def cmd_nobg(a):
    _neural(a, neural.bg_available, "без фона", neural.remove_bg_ai)


def main():
    p = argparse.ArgumentParser(description="Инструменты библиотеки картинок")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cut", help="лист с рисунками -> отдельные квадратные картинки")
    c.add_argument("files", nargs="+")
    c.add_argument("--grid", help="строго по сетке, например 4x3 (иначе рисунки ищутся сами)")
    c.add_argument("--size", type=int, default=256, help="сторона результата, 0 - не менять")
    c.add_argument("--format", default="webp", choices=["webp", "png"])
    c.add_argument("--names", help="имена по порядку через запятую")
    c.add_argument(
        "--bg",
        default="auto",
        choices=["auto", "remove", "ai", "keep"],
        help="фон листа: однотонный убрать (auto/remove), любой - нейросетью (ai), оставить (keep)",
    )
    c.add_argument("--outline", type=int, default=0, help="белая обводка, px")
    c.add_argument("--pad", type=float, default=0.06, help="поля вокруг рисунка, доля стороны")
    c.add_argument("--out", help="папка результата (иначе '<лист> - нарезка' рядом)")
    k = sub.add_parser("convert", help="перевод формата и уменьшение; ico - сразу 16..256 px")
    k.add_argument("files", nargs="+")
    k.add_argument("--to", default="webp", choices=["webp", "avif", "png", "jpg", "ico"])
    k.add_argument("--max", type=int, default=0, help="длинная сторона не больше")
    k.add_argument(
        "--replace",
        action="store_true",
        help="удалить исходник после удачной конвертации",
    )
    d = sub.add_parser("dupes", help="одинаковые картинки -> _duplicates (не удаляются)")
    d.add_argument("dir", nargs="?")
    sub.add_parser("gallery", help="пересобрать Gallery.html")
    u = sub.add_parser("upscale", help="увеличить нейросетью (Real-ESRGAN) -> '<имя> x4.png' рядом")
    u.add_argument("files", nargs="+")
    u.add_argument("--x", type=int, default=4, choices=[2, 4])
    u.add_argument("--kind", default="auto", choices=["auto", "art", "photo"], help="рисунок или фото")
    n = sub.add_parser("nobg", help="убрать любой фон нейросетью (BiRefNet) -> '<имя> без фона.png' рядом")
    n.add_argument("files", nargs="+")
    a = p.parse_args()
    {
        "cut": cmd_cut,
        "convert": cmd_convert,
        "dupes": cmd_dupes,
        "gallery": cmd_gallery,
        "upscale": cmd_upscale,
        "nobg": cmd_nobg,
    }[a.cmd](a)


if __name__ == "__main__":
    main()
