#!/usr/bin/env python3
"""Архив релиза для GitHub: py -3.14 _tools/make_release.py [--out папка] -> dist/Library-<версия>.zip.

В архиве - программа без картинок автора: код (_tools, только то, что в git, без тестов), Library.cmd,
Установить.cmd, Prompts.html и документация, пустые разделы библиотеки. Картинки автора не входят - у них
своя лицензия (LICENSES.md). Тот же скрипт запускает workflow release.yml на каждый тег v*."""

import os
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from library.common import VERSION  # noqa: E402

ROOT_FILES = [
    "Library.cmd",
    "Prompts.html",
    "Prompts.md",
    "README.md",
    "README.en.md",
    "LICENSE",
    "LICENSES.md",
    "CHANGELOG.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".mcp.json",
]
SKIP = ("_tools/tests/", "_tools/docs_", "_tools/make_release.py", "_tools/badges.py")
SECTIONS = [
    "00 Входящие",
    "01 Фоны",
    "02 Наклейки",
    "03 Маскоты",
    "04 Иконки",
    "05 Логотипы",
    "06 Иллюстрации",
    "07 Паттерны и текстуры",
    "08 Интерфейс",
    "10 Рамки и орнаменты",
    "13 Экраны ошибок и пустоты",
]

INSTALL = r"""@echo off
chcp 65001 >nul
rem Установка Библиотеки картинок: пакеты Python и (по желанию) модели нейросетей. Повторный запуск безопасен.
cd /d "%~dp0"
py -3.14 -c "import sys" 2>nul
if errorlevel 1 (
  echo Нужен Python 3.14: https://www.python.org/downloads/
  echo При установке оставьте галку «py launcher», потом запустите этот файл ещё раз.
  pause
  exit /b 1
)
echo Ставлю пакеты: PyQt6, Pillow, numpy, onnxruntime, vtracer...
py -3.14 -m pip install --upgrade -r _tools\requirements.txt
if errorlevel 1 (
  echo Пакеты не поставились - посмотрите сообщение выше.
  pause
  exit /b 1
)
echo.
choice /c YN /m "Скачать модели нейросетей (~460 МБ: поиск по смыслу, удаление фона, увеличение)"
if errorlevel 2 goto done
py -3.14 _tools\get_models.py
:done
echo.
echo Готово. Окно библиотеки - Library.cmd
pause
"""


def tracked(prefix):
    out = subprocess.run(
        ["git", "-c", "core.quotepath=off", "ls-files", "-z", prefix],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p]


def build(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    name = f"Library-{VERSION}"
    path = os.path.join(out_dir, name + ".zip")
    files = [p for p in tracked("_tools") if not p.startswith(SKIP)]
    files += [p for p in tracked("_docs") if p.endswith((".md", ".webp", ".png"))]
    files += [p for p in ROOT_FILES if os.path.exists(os.path.join(ROOT, p))]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(set(files)):
            z.write(os.path.join(ROOT, p), f"{name}/{p}")
        z.writestr(f"{name}/Установить.cmd", INSTALL.replace("\n", "\r\n").encode("utf-8"))
        for s in SECTIONS:
            z.writestr(f"{name}/{s}/", "")
    print(f"{path}: {len(files)} файлов, {os.path.getsize(path) // 1024} КБ")
    return path


if __name__ == "__main__":
    out = os.path.join(ROOT, "dist")
    if "--out" in sys.argv:
        out = os.path.abspath(sys.argv[sys.argv.index("--out") + 1])
    build(out)
