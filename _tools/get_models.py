"""Скачать модели в _tools/_models. Запуск: py -3.14 _tools/get_models.py [clip] [bg] [upscale]
clip - поиск по смыслу и подсказка меток (~225 МБ); bg - удаление любого фона (~225 МБ);
upscale - увеличение x2/x4 (~7 МБ, для перевода в ONNX один раз нужны torch и onnx).
Без аргументов - всё."""

import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "_models")
TEXT = "https://huggingface.co/sentence-transformers/clip-ViT-B-32-multilingual-v1/resolve/main/"
ESRGAN = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
GROUPS = {
    "clip": {
        "clip/vision.onnx": "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
        "clip/text.onnx": TEXT + "onnx/model_quint8_avx2.onnx",
        "clip/vocab.txt": TEXT + "vocab.txt",
        "clip/dense.safetensors": TEXT + "2_Dense/model.safetensors",
    },
    "bg": {
        "birefnet/model.onnx": "https://huggingface.co/onnx-community/BiRefNet_lite-ONNX/resolve/main/onnx/model.onnx"
    },
    "upscale": {
        "upscale/realesr-animevideov3.pth": ESRGAN + "realesr-animevideov3.pth",
        "upscale/realesr-general-x4v3.pth": ESRGAN + "realesr-general-x4v3.pth",
    },
}


def fetch(rel, url):
    dst = os.path.join(MODELS, *rel.split("/"))
    if os.path.exists(dst):
        print("есть:", rel)
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    print("качаю:", rel)
    urllib.request.urlretrieve(url, dst + ".part")
    os.replace(dst + ".part", dst)


def main(names):
    for name in names or list(GROUPS):
        for rel, url in GROUPS[name].items():
            fetch(rel, url)
        if name == "upscale":
            sys.path.insert(0, HERE)
            try:
                from imaging.convert_upscalers import main as convert

                convert(os.path.join(MODELS, "upscale"))
            except ImportError as e:
                print(f"Увеличение: нужен перевод в ONNX - поставьте torch и onnx ({e.name}) и запустите ещё раз")
    print("Готово:", MODELS)


if __name__ == "__main__":
    main(sys.argv[1:])
