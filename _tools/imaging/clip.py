"""Поиск по смыслу: CLIP ViT-B/32 для картинок и его многоязычный текстовый кодировщик (русский тоже).
Оба дают векторы одного пространства: «кот в космосе» находит картинку без слов в имени.
Модели лежат в _tools/_models/clip (onnxruntime, без torch); нет моделей - available() даёт False."""

import json
import os
import re
import struct
import threading
import unicodedata

import numpy as np
from PIL import Image

from imaging.files import LIB

DIR = os.path.join(LIB, "_tools", "_models", "clip")
FILES = ("vision.onnx", "text.onnx", "vocab.txt", "dense.safetensors")
DIM = 512
SIDE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
MAX_TOKENS = 128

_lock = threading.Lock()
_m = {}


def available():
    return all(os.path.exists(os.path.join(DIR, f)) for f in FILES)


def _session(name):
    import onnxruntime as ort

    o = ort.SessionOptions()
    o.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) // 2))  # окну остаются ядра
    o.log_severity_level = 3
    return ort.InferenceSession(os.path.join(DIR, name), o, providers=["CPUExecutionProvider"])


def _models():
    with _lock:
        if not _m:
            with open(os.path.join(DIR, "vocab.txt"), encoding="utf-8") as fh:
                vocab = {t.rstrip("\n"): i for i, t in enumerate(fh)}
            _m.update(
                vision=_session("vision.onnx"),
                text=_session("text.onnx"),
                vocab=vocab,
                dense=_safetensor(os.path.join(DIR, "dense.safetensors"), "linear.weight"),
            )
        return _m


def _safetensor(path, key):
    with open(path, "rb") as fh:
        n = struct.unpack("<Q", fh.read(8))[0]
        meta = json.loads(fh.read(n))[key]
        a, b = meta["data_offsets"]
        fh.seek(8 + n + a)
        return np.frombuffer(fh.read(b - a), np.float32).reshape(meta["shape"])


def _norm(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-8)


# ---------------------------------------------------------------- картинки
def _pixels(im):
    """Как CLIPFeatureExtractor: короткая сторона 224 (bicubic), середина 224x224, нормировка.
    Прозрачное - на белом: наклейки и значки так и выглядят."""
    im = im.convert("RGBA")
    base = Image.new("RGBA", im.size, (255, 255, 255, 255))
    base.alpha_composite(im)
    im = base.convert("RGB")
    k = SIDE / min(im.size)
    im = im.resize((max(SIDE, round(im.width * k)), max(SIDE, round(im.height * k))), Image.BICUBIC)
    x, y = (im.width - SIDE) // 2, (im.height - SIDE) // 2
    a = np.asarray(im.crop((x, y, x + SIDE, y + SIDE)), np.float32) / 255
    return ((a - MEAN) / STD).transpose(2, 0, 1)


def embed_images(images):
    """[PIL.Image] -> массив (n, 512) единичных векторов."""
    if not images:
        return np.zeros((0, DIM), np.float32)
    batch = np.stack([_pixels(im) for im in images])
    out = _models()["vision"].run(None, {"pixel_values": batch})[0]
    return _norm(out.astype(np.float32))


# ---------------------------------------------------------------- текст
def _is_punct(ch):
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_cjk(cp):
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0x20000 <= cp <= 0x2A6DF
        or 0xF900 <= cp <= 0xFAFF
        or 0x2F800 <= cp <= 0x2FA1F
    )


def _basic(text):
    """BERT BasicTokenizer для cased-модели: без нижнего регистра, знаки и иероглифы - отдельно."""
    out = []
    for ch in text:
        cp = ord(ch)
        if cp == 0 or cp == 0xFFFD or (unicodedata.category(ch).startswith("C") and ch not in "\t\n\r"):
            continue
        out.append(f" {ch} " if _is_cjk(cp) or _is_punct(ch) else (" " if ch.isspace() else ch))
    return "".join(out).split()


def _wordpiece(word, vocab):
    if len(word) > 100:
        return ["[UNK]"]
    pieces, start = [], 0
    while start < len(word):
        end = len(word)
        while end > start:
            sub = word[start:end] if start == 0 else "##" + word[start:end]
            if sub in vocab:
                pieces.append(sub)
                break
            end -= 1
        else:
            return ["[UNK]"]
        start = end
    return pieces


def tokenize(text, vocab):
    tokens = ["[CLS]"]
    for w in _basic(text):
        tokens += _wordpiece(w, vocab)
    tokens = tokens[: MAX_TOKENS - 1] + ["[SEP]"]
    return [vocab.get(t, vocab["[UNK]"]) for t in tokens]


def embed_text(text):
    """Строка запроса -> единичный вектор (512,)."""
    m = _models()
    ids = np.array([tokenize(re.sub(r"\s+", " ", text.strip()), m["vocab"])], np.int64)
    mask = np.ones_like(ids)
    hidden = m["text"].run(None, {"input_ids": ids, "attention_mask": mask})[0][0]
    pooled = hidden.mean(0)
    return _norm(m["dense"] @ pooled)


def rank(query_vec, vecs, top=300, floor=0.18):
    """Индексы vecs по убыванию похожести на запрос и сами оценки (ниже floor - отбрасываются)."""
    if not len(vecs):
        return np.array([], int), np.array([], np.float32)
    s = vecs @ query_vec
    order = np.argsort(-s)[:top]
    order = order[s[order] >= floor]
    return order, s[order]
