"""Пути библиотеки, чтение и запись файлов картинок."""

import os
import threading

from PIL import Image, ImageOps

LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".ico", ".svg", ".avif")
INBOX = "00 Входящие"  # неразобранное: в галерею и в поиск дублей не попадает


def images_in(root):
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith("_") and x != INBOX)
        for f in sorted(files):
            if f.lower().endswith(EXT) and not f.startswith("_"):
                out.append(os.path.join(d, f))
    return out


ORIENT = 274  # тег EXIF «как повернуть при показе»


def upright(im):
    """Картинка так, как её показывают просмотрщик Windows и браузер: с поворотом по EXIF.
    Некоторые jpg хранят пиксели боком и флаг «поверни»; без этого они видны лёжа."""
    try:
        if im.getexif().get(ORIENT, 1) != 1:
            return ImageOps.exif_transpose(im)
    except Exception:
        pass
    return im


def size_of(path):
    """Размер картинки с учётом поворота по EXIF, без чтения пикселей."""
    with Image.open(path) as im:
        w, h = im.size
        try:
            if im.getexif().get(ORIENT, 1) in (5, 6, 7, 8):
                w, h = h, w
        except Exception:
            pass
    return w, h


def load(path):
    # with: у многокадровых (gif, анимированный webp) Pillow держит файл открытым после load(),
    # и Windows не даёт его потом перенести или убрать в корзину
    with Image.open(path) as im:
        im.load()
        return upright(im).convert("RGBA")


def is_animated(path):
    """Многокадровая картинка: сжатие и чистка взяли бы только первый кадр."""
    try:
        with Image.open(path) as im:
            return bool(getattr(im, "is_animated", False))
    except Exception:
        return False


def write_atomic(path, data, encoding=None):
    """Запись через временный файл: браузер или второй поток не увидят файл наполовину,
    а сбой посреди записи не оставит пустышку вместо старого."""
    tmp = "%s.tmp%d-%d" % (path, os.getpid(), threading.get_ident())  # у каждого потока свой
    with open(tmp, "w" if encoding else "wb", **({"encoding": encoding} if encoding else {})) as fh:
        fh.write(data)
    os.replace(tmp, path)


def fmt_of(path):
    e = os.path.splitext(path)[1][1:].lower()
    return {"jpeg": "jpg"}.get(e, e)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
