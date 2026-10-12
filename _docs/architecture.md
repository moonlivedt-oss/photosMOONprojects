[Главная](../README.md) | [Возможности](usage.md) | [Unreal](unreal.md) | [ИИ-помощники](ai.md) | [Командная строка](cli.md) | [Вопросы](faq.md) | [Устройство](architecture.md) | [English](en/architecture.md)

# Устройство проекта

## Файлы и модули

```
00 Входящие/            неразобранное (в поиск не попадает)
01 Фоны/ ... 13 .../    разделы; наборы - <раздел>/<набор>/<палитра>/
_sources/               исходные листы (<год-месяц>), оригиналы до сжатия и правки, _undone для Ctrl+Y
_Unreal/                ассеты для Unreal Engine: <вид>/<тема>/<имя>/ (не в git)
_docs/                  страницы документации; screenshots/ - картинки (py -3.14 _tools/docs_screenshots.py, docs_demo.py)
_docs/badges/           бейджи README (число тестов и картинок) - их обновляет хук .githooks/pre-commit
Library.cmd             запуск окна
Prompts.html            промпты для генерации (палитры, карточки, «Имена»)
AGENTS.md               как ИИ-помощнику работать с библиотекой (CLAUDE.md ссылается на него)
.mcp.json               сервер для Claude Code, открытого в этой папке
_tools/
  app.py                вход окна
  mcp_server.py         сервер MCP для ИИ-помощников (stdin/stdout, без сторонних пакетов)
  cli.py                командная строка: cut, convert, dupes, done, nobg, upscale, unreal, repair, api
  get_models.py         скачать модели нейросетей; requirements.txt - пакеты Python
  docs_screenshots.py   снимки окна для README; docs_demo.py - анимация demo.webp
  badges.py             бейджи README; make_release.py - архив релиза (его же собирает release.yml)
  imaging/              ядро без Qt (Pillow + numpy)
    files.py            пути, чтение с поворотом по EXIF, атомарная запись
    cutting.py          удаление фона, обводка, поиск рисунков, нарезка сеткой
    encoding.py         форматы, размер, SSIM «на глаз», сжатие, svg
    editing.py          правка по рецепту (цвет + шаги), перекраска, кисть, тень
    similarity.py       отпечатки (дубли, «уже есть»), главные цвета
    style.py            манера рисунка в числах: цвета, обводка, детали - «выбивается из набора»
    contrast.py         контраст края по WCAG: видно ли иконку на фоне
    clip.py             CLIP через onnxruntime: свой WordPiece, чтение safetensors
    ies.py              IES-профили света для Unreal и их превью «пятно на стене»
    neural.py           удаление фона (BiRefNet) и увеличение (Real-ESRGAN), кэш результатов
    convert_upscalers.py  Real-ESRGAN из .pth в .onnx (один раз, через torch)
    doctor.py           проверка библиотеки
    sprites.py          атлас, svg-спрайт, значки программы, лист превью
    jobs.py             задачи для процессов по ядрам
    done.py             done.js для Prompts.html (что уже есть по папкам)
  library/              модель библиотеки без Qt - её делят окно, командная строка и сервер MCP
    api.py              операции для помощников: описания, схемы параметров, журнал, отмена
    journal.py          журнал действий в базе: история окна и действия помощников, отмена и возврат
    db.py               SQLite: отпечатки, метки, заметки, избранное, умные папки, векторы CLIP, журнал
    batch.py            пакетно по ядрам: сжатие, копии, правка по рецепту, выгрузка
    semantic.py         индекс поиска по смыслу; tagging.py - подсказка меток и раздела
    signatures.py       отпечатки: «уже есть», похожие, цвет, дубли
    sorting.py          заготовки нарезки, метки в имени, запись в разделы
    prompts.py          данные Prompts.html (через node)
    unreal.py           ассеты Unreal: темы, Poly Haven, ambientCG, Kenney, Quaternius, загрузка на место
    unreal_sem.py       поиск по смыслу по ассетам; unreal_extra.py - цвета превью, проверка, повторы, полигоны
    unreal_groups.py    группы, разделы и стили дерева Unreal (общие для окна и помощника)
    unreal_more.py      все текстуры Poly Haven и ambientCG без повторов; сканы Google, Smithsonian, Khronos, NASA
    blender_convert.py  glb / gltf / obj -> FBX через Blender (текстуры рядом, glb для 3D-окна)
    unreal_local.py     разбор скачанных архивов (itch.io и др.); unreal_links.py - страница ссылок на них
    unreal_from_project.py  выгрузка Fab, Megascans и MetaHuman из проекта Unreal в FBX
    mh_view.py          MetaHuman для 3D-просмотра (_view.glb через Blender, с текстурами)
    blender_preview.py  превью моделей, которые Qt Quick 3D не тянет (MetaHuman), рендером Blender
    fbx_meta.py         треугольники, размер в см, скелет и анимации прямо из FBX
    unreal_import.py    копия файлов и import_to_unreal.py (настройки текстур, материал M_<имя>)
    fbx_colors.py       цвета материалов Quaternius из .mtl прямо в FBX
    scene_plan.py       подборка комнаты по описанию; room_layout.py - расстановка мебели (без Qt)
    blender_scene.py    сцена для Blender: скрипт сборки, поиск blender.exe, запуск
    unreal_engine.py    движки и проекты Unreal, импорт в проект коммандлетом
    unreal_pack.py      пакет для проекта; unreal_sets.py - подборки (общий файл окна и помощников)
    budget.py           бюджет сцены (треугольники, видеопамять, Nanite) и упрощение в Blender
    credits.py          авторы и лицензии проекта -> CREDITS.md
    style_check.py      выбивается из набора и контраст на фонах - по всей библиотеке
    scale_check.py      масштаб моделей: настоящие размеры предметов, общий множитель набора
    project_fit.py      палитра проекта (скриншот, CSS с темами) и подходящие наборы
    publish_check.py    проверка проекта перед публикацией -> PUBLISH-CHECK.md
    api_unreal.py       операции ue_* для помощников; versions.py - прошлые версии картинки
    safety.py           резервные копии, проверка и восстановление базы и настроек
    cleanup.py          чистка _sources: что можно убрать в корзину и сколько места вернётся
    ui_bridge.py        связь помощника с открытым окном (показать, что выбрано, ход работы) через файлы
  ui/                   окно (PyQt6)
    main_window.py      главное окно, отмена/возврат, приём файлов, main()
    inbox_tab.py        вкладка «Входящие»
    library_tab.py      вкладка «Библиотека», быстрый просмотр, умные папки, поиск по картинке
    semantic.py, signatures.py - то же, что в library, но досчёт в фоне
    unreal_tab.py       вкладка «Unreal»; unreal_nav.py, unreal_tiles.py, unreal_catalog.py - панель, карточки, каталог
    unreal_panel.py     карточка ассета справа и в «Сведениях» 3D-окна
    compare3d.py + .qml сравнение 2-4 моделей или текстур в 3D
    viewer3d.py + .qml  просмотр в 3D на Qt Quick 3D; room3d.py + .qml - комната; render_previews.py - превью моделей
    tools_dialogs.py    палитра из картинки, сравнение двух картинок, векторизация, оформление
    style_dialogs.py    «Выбивается из набора» и «Контраст на фонах»; budget_dialog.py - бюджет сцены
    project_dialog.py   «Проект»: палитра, подходящие наборы, проверка перед публикацией; scale_dialog.py - масштаб
    scene_dialog.py     подборка по описанию; unreal_import_dialog.py - импорт в Unreal
    command_palette.py  «Найти везде» (Ctrl+P); safety_dialog.py - проверка и восстановление
    agents.py           окно «ИИ-помощники»; ai_drawer.py - лента их действий; help.py - справка
    settings_dialog.py  «Настройки» (Ctrl+,)
    editor.py, compress.py, export.py, dupes.py, weight.py, doctor.py, missing.py - окна действий
    widgets.py, thumbnails.py, animations.py, theme.py, common.py - общее для окна
  tests/                unittest (run-tests.cmd): эталонные листы, нарезка, правка, база, метки, CLIP;
                        test_api.py - операции для помощников и протокол MCP на временной библиотеке;
                        test_checks.py - манера, контраст, авторы, бюджет, масштаб, палитра проекта;
                        test_unreal*.py, test_fbx_*.py, test_mh_view.py, test_scene_plan.py - Unreal без сети
  cli/                  .cmd для перетаскивания файлов
```

Не в репозитории (`.gitignore`): `_tools/_models` (модели), `_tools/_thumbs` (кэш миниатюр),
`_tools/library.db` (база этого компьютера), `_tools/settings.json`, `_tools/done.js`,
`_tools/_ui` (стрелки стилей - окно пишет их цветом темы), `_Unreal/` и кэши `_tools/_unreal_*`,
`_tools/_backups` (резервные копии - в них ваши метки и настройки), отодвинутые `*.broken-*`, `dist/` (архив релиза).


## Почему ядро отдельно от окна

`imaging/` и `library/` не знают про Qt: их зовут и окно, и командная строка, и сервер для
помощников, и процессы по ядрам (сжатие пачки идёт ~5x быстрее), и тесты. Окно и помощник
работают с одной базой (SQLite в режиме WAL): метка, поставленная помощником, сразу видна в окне,
а его действие отменяется в окне так же, как своё.

## Почему база, а не json

Отпечатки 4000 картинок раньше жили в 7-мегабайтном json, который переписывался после каждого
сохранения. В SQLite меняются только изменившиеся строки; там же метки, заметки, умные папки и
векторы CLIP (float16, ~1 КБ на картинку).


## Приватность

Картинки библиотеки **не уходят в сеть**: метки, поиск по смыслу, правка - всё считается на этом компьютере.
Сеть нужна в двух случаях, и оба - только скачивание: `get_models.py` один раз качает модели с Hugging Face
и GitHub, а вкладка «Unreal» по кнопкам «Скачать ещё...», «Каталог...» и «Перекачать» берёт ассеты с Poly Haven,
ambientCG, Kenney, KayKit (GitHub), открытых папок Quaternius на Google Drive, а `unreal more` - ещё с Google
Scanned Objects (Gazebo Fuel), Smithsonian 3D, GitHub Khronos и NASA. Архивы с itch.io вы качаете сами;
выгрузка из Unreal и Quixel Bridge идёт с этого компьютера. Ничего из библиотеки не отправляется.

Сервер для помощников тоже работает локально и сам ничего не отправляет. Но то, что помощник
смотрит (`view`, предпросмотр правки) или читает (имена, метки), уходит его модели - как любой
файл, который вы ему показываете. Если картинки нельзя показывать внешним сервисам, не подключайте
помощника с облачной моделью.

## Ограничения

- Windows и Python 3.14 (запуск через `py -3.14`); на других ОС ядро и тесты работают, `.cmd` - нет.
- Интерфейс - на русском.
- CLIP ViT-B/32 - небольшая модель: общий смысл ловит хорошо, мелкие детали и надписи - хуже.
- Подсказка меток идёт по словарю (~115 частых меток) плюс уже поставленные метки.

---

[Главная](../README.md) | [Возможности](usage.md) | [Unreal](unreal.md) | [ИИ-помощники](ai.md) | [Командная строка](cli.md) | [Вопросы](faq.md) | [Устройство](architecture.md)
