"""Скачать модели поиска по смыслу (~225 МБ) в _tools/_models/clip. Запуск: py -3.14 _tools/get_models.py"""

import os
import urllib.request

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_models", "clip")
TEXT = "https://huggingface.co/sentence-transformers/clip-ViT-B-32-multilingual-v1/resolve/main/"
FILES = {
    "vision.onnx": "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
    "text.onnx": TEXT + "onnx/model_quint8_avx2.onnx",
    "vocab.txt": TEXT + "vocab.txt",
    "dense.safetensors": TEXT + "2_Dense/model.safetensors",
}


def main():
    os.makedirs(DIR, exist_ok=True)
    for name, url in FILES.items():
        dst = os.path.join(DIR, name)
        if os.path.exists(dst):
            print("есть:", name)
            continue
        print("качаю:", name)
        urllib.request.urlretrieve(url, dst + ".part")
        os.replace(dst + ".part", dst)
    print("Готово:", DIR)


if __name__ == "__main__":
    main()
