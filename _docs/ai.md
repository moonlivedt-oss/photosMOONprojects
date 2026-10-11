[Главная](../README.md) | [Возможности](usage.md) | [Unreal](unreal.md) | [ИИ-помощники](ai.md) | [Командная строка](cli.md) | [Вопросы](faq.md) | [Устройство](architecture.md) | [English](en/ai.md)

# ИИ-помощники

<div align="center">
<img src="screenshots/ai.webp" alt="Библиотека: плитки космических иконок, внизу всплыло сообщение «ИИ (claude-code): Метки (+космос, +для сайта): 12 шт.» с кнопкой «Отменить»" width="820">
<br><sub>Помощник поставил метки - окно сразу показывает это и предлагает отменить</sub>
</div>

**Вкладка «Unreal» для помощников**: `ue_search` (по смыслу), `ue_view` (превью листом), `ue_info`,
`ue_plan_room` (комната по описанию с заменами), `ue_collection` (подборки - видны в окне),
`ue_download`, `ue_pack`, `ue_import` (прямо в проект) и `ue_blender` - сцена в Blender, рендер
приходит помощнику картинкой. Например: «собери кабинет с тёмным деревом, покажи в Blender и импортируй
в проект training». У картинок - ещё `versions` и `restore_version`.

Claude, Cursor и другие помощники работают с библиотекой как с инструментом: «найди наклейки с
котами и поставь им метку коты», «убери фон у этих трёх и положи копии в 02 Наклейки/Котики»,
«нарежь лист из входящих», «выгрузи иконки космоса в D:/site/assets в webp 128».

**Что они делают** - кнопка «ИИ-помощники» вверху: точка на значке пульсирует, пока помощник работает, щелчок открывает
справа ленту его действий с «Отменить» и «Только чтение».

**Подключить** - в той же ленте «Подключить помощников...»: Claude Desktop, Cursor, VS Code (Copilot), Windsurf, Cline, Roo Code, LM Studio и Gemini CLI - одной кнопкой
(сервер дописывается в их файл настроек, старый остаётся копией `.bak`); для Claude Code и Codex CLI -
готовая команда, для остальных (Zed, Continue...) - блок настроек. В этой папке Claude Code находит сервер сам
(`.mcp.json`). Без MCP - те же операции из командной строки: `py -3.14 _tools/cli.py api`.

| Что | Операции |
|---|---|
| Понять, что где | `overview`, `list_folder`, `inbox`, `palettes`, `history`, `selection` (что выбрано в окне) |
| Найти | `search` (слова, метки, цвет, смысл), `similar`, `duplicates`, `check` (доктор), `index` (досчитать отпечатки и поиск по смыслу) |
| Посмотреть | `view` - картинка или лист с номерами приходит помощнику изображением; `info`, `show` (показать в окне) |
| Подписать | `suggest_tags`, `tag`, `note`, `favorite`, `smart_folder` |
| Разложить | `rename`, `move`, `trash`, `import_images`, `cut_sheet` |
| Поправить | `edit` (рецепт как в редакторе, сначала предпросмотр), `remove_background`, `upscale`, `convert`, `versions`, `restore_version` |
| Проверить манеру | `odd_ones` (что выбивается из набора), `contrast` (видно ли на фоне) |
| Отдать в проект | `export` (форматы, @2x/@3x, атлас, svg-спрайт), `credits` (CREDITS.md) |
| Проект пользователя | `project_palette`, `fit_sets` (подходящие наборы), `publish_check` (перед публикацией) |
| Unreal | `ue_overview`, `ue_search`, `ue_kit`, `ue_similar`, `ue_compare`, `ue_views`, `ue_view`, `ue_info`, `ue_show`, `ue_plan_room`, `ue_collection`, `ue_download`, `ue_pack`, `ue_import`, `ue_blender`, `ue_budget`, `ue_simplify`, `ue_scale_check`, `ue_set_scale`, `ue_check`, `ue_add_archives`, `ue_from_project`, `ue_from_megascans` |
| Вернуть | `undo` |

Все операции с описаниями - `py -3.14 _tools/cli.py api`; как помощнику работать с библиотекой - [AGENTS.md](../AGENTS.md).

**Безопасно.** Каждое действие помощника записывается в журнал: в окне оно всплывает сообщением с
кнопкой «Отменить» и попадает в «Историю» (Ctrl+Z). Удалённое помощником не стирается, а лежит в
`_sources/_deleted`; при замене оригинал уходит в `_sources/edit <дата>`. Помощнику можно разрешить
только поиск и просмотр. Как помощнику вести себя с библиотекой - в [AGENTS.md](../AGENTS.md).

<div align="center">
<img src="screenshots/agents.webp" alt="Окно «ИИ-помощники»: что разрешено, восемь помощников с кнопкой «Подключить» в две колонки, команды для Claude Code и Codex CLI, список действий помощников" width="640">
<br><sub>Окно «ИИ-помощники»: подключение, права и всё, что помощники сделали</sub>
</div>

---

[Главная](../README.md) | [Возможности](usage.md) | [Unreal](unreal.md) | [ИИ-помощники](ai.md) | [Командная строка](cli.md) | [Вопросы](faq.md) | [Устройство](architecture.md)
