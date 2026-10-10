# Для ИИ-помощников

> **English summary.** This folder is a personal image library (icons, stickers, mascots, backgrounds) with a
> PyQt6 window. To work with the images use the MCP server `_tools/mcp_server.py` (registered in `.mcp.json`)
> or the same operations from the shell: `py -3.14 _tools/cli.py api <tool> '<json>'`. Start with `overview`.
> Do not move, rename or delete image files with shell commands: the tools keep tags, favorites and the undo
> journal consistent, and the user sees every change in the window and can undo it. Folder and file names are
> Russian on purpose; code and identifiers are English.

## Как работать с картинками

Два входа, одни и те же операции (`_tools/library/api.py`):

| Вход | Как |
|---|---|
| **MCP** (Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Cline, Gemini CLI, Codex...) | сервер `_tools/mcp_server.py`; в этой папке он уже прописан в `.mcp.json` |
| **Командная строка** | `py -3.14 _tools/cli.py api` - список; `py -3.14 _tools/cli.py api search '{"query": "ночной город"}'` |

Картинка в ответе (`view`, `edit` с `mode=preview`, `cut_sheet` с `preview=true`) приходит изображением по MCP
или файлом PNG в командной строке (`--out путь.png`).

### Главные операции

| Задача | Операции |
|---|---|
| Понять, что где лежит | `overview`, `list_folder`, `inbox`, `palettes` |
| Найти | `search` (слова, «-слово», `#метка`, описание по смыслу, `color`, `tag`, `folder`, `favorites`), `similar` |
| Посмотреть | `view` (одна крупно или лист с номерами), `info` (размер, цвета, метки, где использована) |
| Подписать | `suggest_tags`, `tag`, `note`, `favorite`, `smart_folder` |
| Разложить | `rename`, `move`, `trash` (не стирает: `_sources/_deleted`), `import_images` |
| Поправить | `edit` (рецепт: цвет + шаги), `remove_background`, `upscale`, `convert` |
| Нарезать лист | `cut_sheet` (сетка 4x3, автопоиск, целиком; повторы пропускаются) |
| Отдать в проект | `export` (форматы, @2x/@3x, атлас, svg-спрайт; запоминается «где использовано») |
| Показать пользователю | `show` (картинки отдельным списком в открытом окне, с заголовком) |
| Отменить | `history`, `undo` |
| Прошлые версии картинки | `versions`, `restore_version` (после правки и сжатия; возврат отменяется) |

### Ассеты для Unreal Engine (вкладка «Unreal»)

| Задача | Операции |
|---|---|
| Что есть | `ue_overview` (виды; группы и разделы как в дереве окна; стили; подборки; Unreal и Blender) |
| Найти и посмотреть | `ue_search` (по смыслу; `group`/`section` - «Природа»/«Деревья»; `style` - `real` или `low`, `Kenney`, `Quaternius`, `KayKit`), `ue_view` (превью листом), `ue_info` |
| Показать пользователю | `ue_show` (ассеты отдельным списком во вкладке «Unreal» открытого окна) |
| Скачанные архивы | `ue_add_archives` (zip с itch.io и т. п. из `_Unreal/_Архивы` - разбираются по группам) |
| Комната по описанию | `ue_plan_room` («уютная спальня в скандинавском стиле» -> вещи, пол, стены, свет с заменами) |
| Подборки | `ue_collection` (видны во вкладке слева) |
| Скачать ещё | `ue_download` (CC0: Poly Haven, ambientCG, Kenney, Quaternius, KayKit; долго - ход работы приходит уведомлениями `progress`, если клиент их просит) |
| В проект | `ue_pack` (папка или zip с авторами и скриптом), `ue_import` (прямо в .uproject, редактор закрыт) |
| Blender | `ue_blender` (сцена или комната в .blend; `render=true` - картинка сцены в ответ) |

Нашли подходящее - покажите пользователю в окне (`show`, `ue_show`): он увидит плитки, выберет и поправит сам.
Окно не обязательно открыто: запрос подождёт 10 минут.

Сценарий «собрать комнату»: `ue_plan_room` -> при желании заменить вещи из `alternatives` -> `ue_collection`
(сохранить) -> `ue_blender` с `room=true` (посмотреть) -> `ue_import` или `ue_pack`.

### Правила

- **Не трогать файлы библиотеки командами оболочки** (`mv`, `rm`, `cp`, PowerShell) - только операциями:
  они переносят метки и избранное вместе с файлом и пишут журнал. Всё сделанное видно в окне всплывающим
  сообщением с кнопкой «Отменить» и в меню «История».
- Перед правкой - `edit` с `mode="preview"` (вернёт «было / стало»), потом `copy` или `replace`. При `replace`
  оригинал уходит в `_sources/edit <дата>`.
- Разделы - по **типам** картинок: `01 Фоны`, `02 Наклейки`, `03 Маскоты`, `04 Иконки`, `05 Логотипы`,
  `06 Иллюстрации`, `07 Паттерны и текстуры`, `10 Рамки и орнаменты`. Наборы - `<раздел>/<набор>/<палитра>/`.
- Метки - строчными, «е» вместо «ё», без `#`; несколько слов можно («для сайта»).
- Имена картинок - короткие и по смыслу; номера версий и «final» не нужны.
- `00 Входящие` - неразобранные листы; папки на `_` (`_sources`, `_tools`, `_docs`) - служебные.
- Если база или настройки сломаны - `py -3.14 _tools/cli.py repair` (проверка), `repair fix`, `repair restore latest`;
  `_tools/_backups` и файлы `*.broken-*` не удалять: это копии данных пользователя.
- Пользователь может запретить изменения («Только чтение» в окне, ИИ-помощники) - тогда работают только поиск
  и просмотр.
- Поиск по смыслу (CLIP) понимает русский и английский; одиночное слово надёжнее по-английски («owl») или
  фразой («сова на ветке»).

### Примеры

```bash
py -3.14 _tools/cli.py api search '{"query": "уютная ночная улица с фонарями", "limit": 10}'
py -3.14 _tools/cli.py api view '{"paths": ["02 Наклейки/Сказочные существа/Фиолетовая ночь/baby-dragon.webp"]}' --out dragon.png
py -3.14 _tools/cli.py api tag '{"paths": ["04 Иконки/Космос/Tokyo Night/rocket.webp"], "add": ["космос", "для сайта"]}'
py -3.14 _tools/cli.py api edit '{"paths": ["..."], "ops": [{"op": "nobg_ai"}, {"op": "outline", "px": 8}], "mode": "preview"}' --out check.png
py -3.14 _tools/cli.py api export '{"paths": ["..."], "dest": "D:/Projects/site/assets", "preset": "Для README (webp, 1280)"}'
py -3.14 _tools/cli.py api undo
```

## Если нужно менять код

- Устройство - в [README.md](README.md) («Структура проекта»). Слои: `imaging/` - обработка картинок
  (Pillow, numpy), `library/` - база, журнал, поиск, операции (без Qt), `ui/` - окно на PyQt6.
  В `imaging/` и `library/` не импортировать Qt.
- Запуск только `py -3.14`. Проверка: `py -3.14 -m ruff check .` и `py -3.14 -m unittest discover -s tests`
  в `_tools` (окно не открывается; тесты операций идут на временной библиотеке).
- `.cmd` - с окончаниями строк CRLF (иначе ломаются после `chcp 65001`).
- Никаких эмодзи - ни в коде, ни в текстах; значки окна - картинки из `04 Иконки` (`lib_icon(имя)`).
- Новая версия: `VERSION` в `library/common.py`, `CHANGELOG.md`, бейдж в `README.md`.
