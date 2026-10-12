[Home](../../README.en.md) | [Features](usage.md) | [Unreal](unreal.md) | [AI assistants](ai.md) | [Command line](cli.md) | [FAQ](faq.md) | [How it is built](architecture.md) | [Русский](../architecture.md)

# How it is built

## Files and modules

Folder and file names of the library are Russian on purpose; code and identifiers are English.

```
00 Входящие/            inbox, not sorted yet (not searched)
01 Фоны/ ... 13 .../    sections; sets - <section>/<set>/<palette>/
_sources/               source sheets (<year-month>), originals before compression and edits, _undone for Ctrl+Y
_Unreal/                assets for Unreal Engine: <kind>/<theme>/<name>/ (not in git)
_docs/                  documentation pages; screenshots/ - pictures (py -3.14 _tools/docs_screenshots.py, docs_demo.py)
_docs/badges/           README badges (tests and pictures) - updated by the .githooks/pre-commit hook
Library.cmd             starts the window
Prompts.html            prompts for generation (palettes, cards, "Names")
AGENTS.md               how an AI assistant should work with the library (CLAUDE.md refers to it)
.mcp.json               the server for Claude Code opened in this folder
_tools/
  app.py                window entry point
  mcp_server.py         MCP server for AI assistants (stdin/stdout, no third-party packages)
  cli.py                command line: cut, convert, dupes, done, nobg, upscale, unreal, repair, api
  get_models.py         download the neural network models; requirements.txt - Python packages
  docs_screenshots.py   README screenshots; docs_demo.py - the demo.webp animation
  badges.py             README badges; make_release.py - release archive (also built by release.yml)
  imaging/              core without Qt (Pillow + numpy)
    files.py            paths, reading with EXIF rotation, atomic writes
    cutting.py          background removal, outline, finding drawings, grid cutting
    encoding.py         formats, size, "by eye" SSIM, compression, svg
    editing.py          recipe edits (color + steps), recoloring, brush, shadow
    similarity.py       fingerprints (duplicates, "already there"), main colors
    style.py            drawing manner as numbers: colors, outline, detail - "odd one out"
    contrast.py         WCAG edge contrast: is an icon visible on a background
    clip.py             CLIP through onnxruntime: own WordPiece, reading safetensors
    ies.py              IES light profiles for Unreal and their "spot on a wall" previews
    neural.py           background removal (BiRefNet) and upscaling (Real-ESRGAN), result cache
    convert_upscalers.py  Real-ESRGAN from .pth to .onnx (once, through torch)
    doctor.py           library check
    sprites.py          atlas, svg sprite, program icons, contact sheet
    jobs.py             jobs for per-core processes
    done.py             done.js for Prompts.html (what already exists by folder)
  library/              library model without Qt - shared by the window, the command line and the MCP server
    api.py              operations for assistants: descriptions, parameter schemas, journal, undo
    journal.py          action journal in the database: window history and assistant actions, undo and redo
    db.py               SQLite: fingerprints, tags, notes, favorites, smart folders, CLIP vectors, journal
    batch.py            batch work on all cores: compression, copies, recipe edits, export
    semantic.py         semantic search index; tagging.py - tag and section suggestions
    signatures.py       fingerprints: "already there", similar, color, duplicates
    sorting.py          cutting presets, tags in names, writing into sections
    prompts.py          Prompts.html data (through node)
    unreal.py           Unreal assets: themes, Poly Haven, ambientCG, Kenney, Quaternius, downloading in place
    unreal_more.py      all Poly Haven and ambientCG textures without repeats; Google, Smithsonian, Khronos, NASA scans
    blender_convert.py  glb / gltf / obj -> FBX via Blender (textures next to it, glb for the 3D window)
    unreal_sem.py       semantic search over assets; unreal_extra.py - preview colors, checks, repeats, polygons, scale
    unreal_groups.py    groups, sections and styles of the Unreal tree (shared by the window and the assistant)
    unreal_local.py     unpacking downloaded archives (itch.io etc.); unreal_links.py - a page with their links
    unreal_from_project.py  exporting Fab, Megascans and MetaHuman from an Unreal project to FBX
    mh_view.py          MetaHuman for the 3D viewer (_view.glb through Blender, with textures)
    blender_preview.py  previews of models Qt Quick 3D cannot handle (MetaHuman), rendered in Blender
    fbx_meta.py         triangles, size in cm, skeleton and animations straight from the FBX
    unreal_import.py    copying files and import_to_unreal.py (texture settings, M_<name> material, scale)
    fbx_colors.py       Quaternius material colors from .mtl straight into the FBX
    scene_plan.py       a room collection from a description; room_layout.py - furniture layout (without Qt)
    blender_scene.py    a Blender scene: build script, finding blender.exe, running it
    unreal_engine.py    Unreal engines and projects, import into a project with a commandlet
    unreal_pack.py      a pack for a project; unreal_sets.py - collections (a file shared by the window and assistants)
    budget.py           scene budget (triangles, GPU memory, Nanite) and simplifying in Blender
    credits.py          project authors and licenses -> CREDITS.md
    style_check.py      odd one out and contrast on backgrounds - across the whole library
    scale_check.py      model scale: real object sizes, one factor per kit
    project_fit.py      project palette (screenshot, CSS with themes) and fitting sets
    publish_check.py    pre-publish project check -> PUBLISH-CHECK.md
    api_unreal.py       ue_* operations for assistants; versions.py - previous versions of a picture
    safety.py           backups, checking and restoring the database and settings
    cleanup.py          cleaning _sources: what can go to the recycle bin and how much space it frees
    ui_bridge.py        link between an assistant and the open window (show, selection, progress) through files
  ui/                   the window (PyQt6)
    main_window.py      main window, undo/redo, receiving files, main()
    inbox_tab.py        the inbox tab
    library_tab.py      the library tab, quick view, smart folders, search by picture
    semantic.py, signatures.py - the same as in library, computed in the background
    unreal_tab.py       the Unreal tab; unreal_nav.py, unreal_tiles.py, unreal_catalog.py - panel, cards, catalog
    unreal_panel.py     the asset card on the right and in the 3D window details
    compare3d.py + .qml comparing 2-4 models or textures in 3D
    viewer3d.py + .qml  3D viewer on Qt Quick 3D; room3d.py + .qml - room; render_previews.py - model previews
    tools_dialogs.py    palette from a picture, comparing two pictures, SVG tracing, theme
    style_dialogs.py    "Odd one out" and "Contrast on backgrounds"; budget_dialog.py - scene budget
    project_dialog.py   "Project": palette, fitting sets, pre-publish check; scale_dialog.py - model scale
    scene_dialog.py     a collection from a description; unreal_import_dialog.py - import into Unreal
    command_palette.py  "Find everywhere" (Ctrl+P); safety_dialog.py - check and restore
    agents.py           the AI assistants window; ai_drawer.py - their action feed; help.py - help
    settings_dialog.py  "Settings" (Ctrl+,)
    editor.py, compress.py, export.py, dupes.py, weight.py, doctor.py, missing.py - action windows
    widgets.py, thumbnails.py, animations.py, theme.py, common.py - shared window code
  tests/                unittest (run-tests.cmd): reference sheets, cutting, edits, database, tags, CLIP;
                        test_api.py - assistant operations and the MCP protocol on a temporary library;
                        test_checks.py - manner, contrast, credits, budget, scale, project palette;
                        test_unreal*.py, test_fbx_*.py, test_mh_view.py, test_scene_plan.py - Unreal without network
  cli/                  .cmd files for drag and drop
```

Not in the repository (`.gitignore`): `_tools/_models` (models), `_tools/_thumbs` (thumbnail cache),
`_tools/library.db` (this computer's database), `_tools/settings.json`, `_tools/done.js`, `_tools/_ui` (style
arrows drawn in the theme color), `_Unreal/` and the `_tools/_unreal_*` caches, `_tools/_backups` (backups with
your tags and settings), moved-aside `*.broken-*`, `dist/` (release archive).

## Why the core is separate from the window

`imaging/` and `library/` know nothing about Qt: they are used by the window, the command line, the assistant
server, the per-core processes (a batch compresses ~5x faster) and the tests. The window and an assistant share
one database (SQLite in WAL mode): a tag set by an assistant shows up in the window at once, and its action is
undone in the window like the window's own.

## Why a database and not json

Fingerprints of 4000 pictures used to live in a 7 MB json rewritten after every save. In SQLite only changed rows
are written; tags, notes, smart folders and CLIP vectors (float16, ~1 KB per picture) live there too.

## Privacy

Library pictures **never leave the computer**: tags, semantic search and edits are all computed locally. The
network is used only for downloads: `get_models.py` fetches the models once (Hugging Face, GitHub), and the
"Unreal" tab fetches assets from Poly Haven, ambientCG, Kenney, KayKit (GitHub) and Quaternius' public Google Drive
folders when you press its download buttons (`unreal more` - also Google Scanned Objects, Smithsonian 3D, Khronos
and NASA on GitHub). itch.io archives you download yourself; Unreal and Quixel Bridge
exports happen on this computer. Nothing from the library is sent anywhere.

The assistant server is local too and sends nothing by itself, but whatever an assistant views (`view`, edit
previews) or reads (names, tags) goes to its model - like any file you show it. If the pictures must not be shown
to external services, do not connect an assistant with a cloud model.

## Limitations

- Windows and Python 3.14 (started with `py -3.14`); on other systems the core and tests work, `.cmd` files do not.
- The interface is in Russian.
- CLIP ViT-B/32 is a small model: it catches the general meaning well, small details and text - worse.
- Tag suggestions use a vocabulary (~115 common tags) plus tags already set.

---

[Home](../../README.en.md) | [Features](usage.md) | [Unreal](unreal.md) | [AI assistants](ai.md) | [Command line](cli.md) | [FAQ](faq.md) | [How it is built](architecture.md)
