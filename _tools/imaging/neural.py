"""Нейросети для правки (onnxruntime): удаление фона (BiRefNet-lite) и увеличение (Real-ESRGAN).
Модели - в _tools/_models (качает get_models.py); нет модели - *_available() даёт False."""

import hashlib
import os
import threading
from collections import OrderedDict

import numpy as np
from PIL import Image

from imaging.files import LIB

DIR = os.path.join(LIB, "_tools", "_models")
BIREFNET = os.path.join(DIR, "birefnet", "model.onnx")
UPSCALERS = {
    "art": os.path.join(DIR, "upscale", "realesr-animevideov3.onnx"),  # рисунки, наклейки, значки
    "photo": os.path.join(DIR, "upscale", "realesr-general-x4v3.onnx"),  # фоны, фото, иллюстрации
}
BG_SIDE = 1024
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
TILE, OVERLAP = 256, 16

CACHE = 6

_lock = threading.Lock()
_sessions = {}
_cache = OrderedDict()


def cached(name, im, fn):
    """Результат нейросети по содержимому картинки: предпросмотр правки пересчитывает весь рецепт
    при каждом движении ползунка, а фон нейросеть ищет секунды."""
    key = (name, im.size, im.mode, hashlib.md5(im.tobytes()).digest())
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key].copy()
    out = fn(im)
    with _lock:
        _cache[key] = out
        while len(_cache) > CACHE:
            _cache.popitem(last=False)
    return out.copy()


def bg_available():
    return os.path.exists(BIREFNET)


def upscale_available():
    return all(os.path.exists(p) for p in UPSCALERS.values())


def _session(path):
    with _lock:
        if path not in _sessions:
            import onnxruntime as ort

            o = ort.SessionOptions()
            o.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
            o.log_severity_level = 3
            _sessions[path] = ort.InferenceSession(path, o, providers=["CPUExecutionProvider"])
        return _sessions[path]


def _flat_rgb(im, bg=(255, 255, 255)):
    im = im.convert("RGBA")
    base = Image.new("RGBA", im.size, bg + (255,))
    base.alpha_composite(im)
    return base.convert("RGB")


# ---------------------------------------------------------------- фон
def bg_mask(im):
    """Маска объекта 0..255 (L) того же размера, что и картинка."""
    x = np.asarray(_flat_rgb(im).resize((BG_SIDE, BG_SIDE), Image.BILINEAR), np.float32) / 255
    x = ((x - MEAN) / STD).transpose(2, 0, 1)[None]
    logits = _session(BIREFNET).run(None, {"input_image": x})[0][0, 0]
    mask = (255 / (1 + np.exp(-logits))).astype(np.uint8)
    return Image.fromarray(mask, "L").resize(im.size, Image.BILINEAR)


def remove_bg_ai(im):
    """Фон прочь с любой картинки: прозрачность = маска нейросети (и прежняя прозрачность, если была)."""
    im = im.convert("RGBA")
    alpha = np.minimum(np.asarray(im.getchannel("A")), np.asarray(bg_mask(im)))
    out = im.copy()
    out.putalpha(Image.fromarray(alpha, "L"))
    return out


# ---------------------------------------------------------------- увеличение
def _run_tiles(sess, rgb):
    """rgb float32 (H, W, 3) 0..1 -> x4 по плиткам с перекрытием: память не растёт с размером картинки."""
    h, w, _ = rgb.shape
    out = np.zeros((h * 4, w * 4, 3), np.float32)
    for y in range(0, h, TILE):
        for x in range(0, w, TILE):
            y0, x0 = max(0, y - OVERLAP), max(0, x - OVERLAP)
            y1, x1 = min(h, y + TILE + OVERLAP), min(w, x + TILE + OVERLAP)
            tile = rgb[y0:y1, x0:x1].transpose(2, 0, 1)[None]
            up = sess.run(None, {"image": tile})[0][0].transpose(1, 2, 0)
            cy, cx = (y - y0) * 4, (x - x0) * 4
            th, tw = min(TILE, h - y) * 4, min(TILE, w - x) * 4
            out[y * 4 : y * 4 + th, x * 4 : x * 4 + tw] = up[cy : cy + th, cx : cx + tw]
    return np.clip(out, 0, 1)


def upscale(im, scale=4, kind="art"):
    """Увеличить в 2 или 4 раза. kind: art - рисунки (модель для аниме-графики), photo - фоны и фото.
    Прозрачность увеличивается той же сетью (как серая картинка) - край наклейки остаётся чётким."""
    sess = _session(UPSCALERS["art" if kind == "art" else "photo"])
    im = im.convert("RGBA")
    has_alpha = np.asarray(im.getchannel("A")).min() < 255
    rgb = np.asarray(im.convert("RGB"), np.float32) / 255  # цвет под прозрачным - как есть, без подложки
    big = Image.fromarray((_run_tiles(sess, rgb) * 255 + 0.5).astype(np.uint8), "RGB").convert("RGBA")
    if has_alpha:
        a = np.asarray(im.getchannel("A"), np.float32)[..., None].repeat(3, 2) / 255
        big_a = _run_tiles(sess, a).mean(2)
        big.putalpha(Image.fromarray((big_a * 255 + 0.5).astype(np.uint8), "L"))
    if scale != 4:
        big = big.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    return big
