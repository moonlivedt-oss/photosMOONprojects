"""Задачи для процессов по ядрам: на входе путь и словарь настроек, на выходе байты."""
import io

from PIL import Image

from imaging.encoding import BEST, clean, compress, flat, resize, ssim, to_svg, trim
from imaging.files import fmt_of, load


def job_compress(path, o):
    """Файл -> (байты или None, сведения)."""
    if o.get("fmt") == "clean":
        return clean(path), dict(fmt=fmt_of(path), clean=True)
    if o.get("fmt") == "svg":
        return to_svg(load(path)), dict(fmt="svg")
    return compress(load(path), o)


def job_image(im, o):
    """Уже открытая картинка (кусок листа) -> (байты, сведения)."""
    return compress(im, o)


RETINA = (("", 1), ("@2x", 2), ("@3x", 3))


def job_export(path, o):
    """Выгрузка одного файла -> [(хвост имени, формат, байты)]. o как у compress, плюс
    retina - набор name / name@2x / name@3x (size - для @1x; не задан - треть исходника)."""
    im = load(path)
    if o.get("fmt") == "svg":
        return [("", "svg", to_svg(trim(im)[0] if o.get("trim") else im))]
    fmt = o.get("fmt") or fmt_of(path)
    if fmt not in ("webp", "avif", "png", "jpg", "ico", BEST):
        fmt = "png"
    q = o.get("q", 0)
    base = dict(o, fmt=fmt, q=q, lossless=q >= 100)
    if not o.get("retina"):
        data, info = compress(im, base)
        return [("", info["fmt"], data)]
    if o.get("trim"):
        im = trim(im)[0]
    side = o.get("size") or max(1, max(im.size) // 3)
    out, last = [], None
    for tail, k in RETINA:
        data, info = compress(im, dict(base, size=side * k, trim=False))
        if tuple(info["size"]) == last:          # исходник меньше - крупнее не будет, копию не пишем
            break
        last = tuple(info["size"])
        out.append((tail, info["fmt"], data))
    return out


def job_variant(path, o):
    """Для сравнения форматов: байты, сведения и оценка похожести на исходник (score)."""
    src = load(path)
    data, info = compress(src, o)
    out = Image.open(io.BytesIO(data))
    out.load()
    ref = resize(trim(src)[0] if o.get("trim") else src, o.get("size", 0), o.get("fit", "fit"))
    if info["fmt"] == "jpg":
        ref = flat(ref, o.get("matte", "white"))
    info["score"] = ssim(ref, out) if out.size == ref.size else None
    return data, info
