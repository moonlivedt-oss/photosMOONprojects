[Главная](../README.md) | [Возможности](usage.md) | [Unreal](unreal.md) | [ИИ-помощники](ai.md) | [Командная строка](cli.md) | [Вопросы](faq.md) | [Устройство](architecture.md) | [English](en/cli.md)

# Командная строка

```bash
py -3.14 _tools/cli.py cut лист.png --grid 4x3 --names a,b,c --outline 8 --bg auto
py -3.14 _tools/cli.py convert папка --to webp --max 1920 [--replace]
py -3.14 _tools/cli.py dupes [папка]       # одинаковые - в _duplicates, не удаляются
py -3.14 _tools/cli.py done                    # done.js для Prompts.html
py -3.14 _tools/cli.py nobg картинка.jpg                 # -> «картинка без фона.png»
py -3.14 _tools/cli.py upscale иконка.png --x 4 --kind art   # -> «иконка x4.png»
py -3.14 _tools/cli.py unreal get hdri все --count 3     # ассеты для Unreal Engine (CC0)
py -3.14 _tools/cli.py unreal more all                   # ещё: все текстуры без повторов, сканы и PBR-модели
py -3.14 _tools/cli.py repair                            # проверить и починить базу и настройки без окна
py -3.14 _tools/cli.py api                               # операции для помощников и скриптов, ответ - JSON
py -3.14 _tools/cli.py api search '{"query": "уютная ночная улица"}'
```

Для перетаскивания файлов мышью - `.cmd` в `_tools/cli/`: нарезать лист, наклейки с обводкой,
частицы на чёрном, в WebP / PNG / ICO, найти дубли.

Тесты: `_tools\run-tests.cmd` (окно не открывается). Бейджи README: `py -3.14 _tools/badges.py` (его же
запускает хук `.githooks/pre-commit`). Архив релиза: `py -3.14 _tools/make_release.py`.

---

[Главная](../README.md) | [Возможности](usage.md) | [Unreal](unreal.md) | [ИИ-помощники](ai.md) | [Командная строка](cli.md) | [Вопросы](faq.md) | [Устройство](architecture.md)
