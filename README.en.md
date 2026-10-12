<div align="center">

[Русский](README.md) | **English**

<img src="_docs/screenshots/logo.png" alt="Image Library logo: a picture file with mountains and the sun" width="120">

# Image Library

### A personal library of icons, stickers and backgrounds with a sorting window: cuts generated sheets, files them, searches by meaning

4x3 sheet cutting with preview, filing by section and palette, semantic search in Russian and English<br>
tag and folder suggestions, smart folders, neural background removal and x4 upscaling<br>
AI assistants (Claude, Cursor) search, view and edit pictures - every change shows up in the window and can be undone<br>
an "Unreal" tab: textures, HDRIs, models and lights for Unreal Engine with a 3D viewer<br>
project checks: model scale, scene budget, contrast on the site background, licenses before publishing

[![CI](https://github.com/moonlivedt-oss/photosMOONprojects/actions/workflows/ci.yml/badge.svg)](https://github.com/moonlivedt-oss/photosMOONprojects/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/moonlivedt-oss/photosMOONprojects?label=version&color=cba6f7)](https://github.com/moonlivedt-oss/photosMOONprojects/releases/latest)
![python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![qt](https://img.shields.io/badge/PyQt6-window-41CD52?logo=qt&logoColor=white)
![tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmoonlivedt-oss%2FphotosMOONprojects%2Fmain%2F_docs%2Fbadges%2Ftests.json)
![images](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmoonlivedt-oss%2FphotosMOONprojects%2Fmain%2F_docs%2Fbadges%2Fimages.json)
![unreal](https://img.shields.io/badge/Unreal-CC0%20assets-313244)
![mcp](https://img.shields.io/badge/MCP-AI%20assistants-d97757)
![license](https://img.shields.io/badge/code-MIT-green)

<img src="_docs/screenshots/demo.webp" alt="Animation: a sheet of 12 icons in the inbox is cut into a grid and repeats are marked as already in the library, then semantic search for a night city finds pictures without these words in their names, and in the Unreal tab a chair rotates in 3D" width="880">

<sub>One folder, a PyQt6 window, a Pillow and numpy core, semantic search through onnxruntime. The interface is in Russian.</sub>

</div>

---

## Download

**[Latest release](https://github.com/moonlivedt-oss/photosMOONprojects/releases/latest)** - `Library-<version>.zip`:
the program without the author's pictures, empty sections and `Установить.cmd` (install). It needs
[Python 3.14](https://www.python.org/downloads/) (keep the "py launcher" box checked). Unzip, run `Установить.cmd`
(installs the packages and offers to download the neural network models), then `Library.cmd`.

## Quick start from the repository

```bash
py -3.14 -m pip install -r _tools/requirements.txt
py -3.14 _tools/get_models.py      # neural network models, ~460 MB, once (or in parts: clip, bg, upscale)
```

Then run **`Library.cmd`** - a window with three tabs opens: "Входящие" (inbox), "Библиотека" (library) and "Unreal".
To connect an AI assistant (Claude Code, Claude Desktop, Cursor) use the **"ИИ-помощники"** button
([details](_docs/en/ai.md)); Claude Code opened in this folder finds the library by itself.

> Without the models the window works, only the neural network buttons are hidden. `Prompts.html` and "what is missing" need node.

## What it is

Pictures for projects (icons, stickers, mascots, backgrounds) are generated in sheets of 12 and get scattered
across project folders: the same picture lives in three places, finding "that owl in the purple palette" means
browsing everything, and every sheet still has to be cut by hand.

**Image Library** keeps everything in one place **by type** rather than by project and does the routine: a sheet
lands in the inbox - the window cuts it into a grid, names the pieces from the prompt list, marks what is already
there, suggests tags and files the pieces into the right section and palette.

| | Plain folder | Image managers (Eagle etc.) | Image Library |
|---|---|---|---|
| Cutting a sheet into pieces | by hand | no | **yes - grid or auto-detection, preview, frames by hand** |
| Filing by section | by hand | by hand | **yes - by a tag in the file name** |
| "Already have it" | no | no | **yes - fingerprints, a repeat is not saved** |
| Semantic search | no | paid AI features | **yes - local, in Russian and English ("cozy night street")** |
| Tag suggestions | no | no | **yes - by the meaning of the pieces, one click** |
| Background from any picture, x4 upscaling | no | no | **yes - BiRefNet and Real-ESRGAN, local** |
| AI assistants | no | no | **yes - an MCP server: search, view, edit, file; everything can be undone** |
| Undo | recycle bin | partly | **yes - any action, even after a restart** |
| Export to a project | by hand | partly | **yes - format, size, @2x/@3x, atlas, svg sprite; "where used"** |
| Project checks | no | no | **yes - licenses, weight, contrast on the site background, before publishing** |
| Where the data is | on disk | own database | **on disk, plain files and folders** |

## Features in short

- **Inbox** - a 4x3 sheet is cut by grid or auto-detection, pieces are named from the prompt, repeats are marked
  "already there", the window suggests tags and a section; a tag in the name (`Космос [ic tokyo]`) files it by itself.
- **Library** - search by words, tags, color and meaning ("cat in space"), by picture, smart folders, sets by
  palette, editor, "visually lossless" compression, export to a project, doctor and duplicates, undo for everything.
- **Checks** - what stands out from its set by manner, icon contrast on backgrounds, project palette and fitting
  sets, authors and licenses, a pre-publish check.
- **Unreal** - textures, HDRIs, models and IES profiles (Poly Haven, ambientCG, Kenney, Quaternius, KayKit, Google
  scans, Smithsonian, Khronos, NASA),
  a 3D viewer, a room from a description, Blender, one-click import into a project, scene budget, model scale.
- **AI assistants** - 61 operations over MCP: find, view, tag, edit, cut, gather a kit for Unreal; every action
  shows up in the window and can be undone.

Documentation:

| Page | About |
|---|---|
| [Features and how to use](_docs/en/usage.md) | every window feature, tools, hotkeys, neural networks |
| [Assets for Unreal Engine](_docs/en/unreal.md) | the "Unreal" tab, 3D, rooms, Blender, import, budget and scale |
| [AI assistants](_docs/en/ai.md) | connecting, all operations, safety |
| [Command line](_docs/en/cli.md) | `cli.py`: cutting, compression, neural networks, Unreal, assistant operations |
| [FAQ and troubleshooting](_docs/en/faq.md) | what to do if the window does not start or tags are gone |
| [How it is built](_docs/en/architecture.md) | files and modules, privacy, limitations |

<div align="center">
<img src="_docs/screenshots/inbox.webp" alt="Inbox tab: a 4x3 sheet of fairy creatures with piece frames, ten pieces marked as already there, two new ones checked, cutting settings and tag suggestions on the right" width="49%">
<img src="_docs/screenshots/semantic.webp" alt="Semantic search for a cozy night street with lanterns: Unreal assets on top, 17 night scenes below, a rainy neon street on the right with tag suggestions" width="49%">
<img src="_docs/screenshots/unreal.webp" alt="Unreal tab: kind cards, the Home tree with sections, brass vases and bronze statues, a bronze whale on the right with sizes next to a 180 cm person" width="49%">
<img src="_docs/screenshots/viewer-model.webp" alt="3D viewer: a leather lounge chair under studio light, texture try-on, light, polygons and sizes on the right" width="49%">
<br><sub>Inbox and semantic search; the Unreal tab and the 3D viewer</sub>
</div>

## Privacy

Pictures **never leave the computer**: tags, semantic search and edits are computed locally. The network is used only
to download the neural network models and Unreal assets. Whatever an assistant views goes to its model - like any
file you show it. Details: [How it is built](_docs/en/architecture.md#privacy).

## Changes and license

All changes are in [CHANGELOG.md](CHANGELOG.md) (in Russian). Code (`_tools/`, `Library.cmd`, `Prompts.html`) - MIT,
see [LICENSE](LICENSE); library pictures are not covered by MIT - what is under which license: [LICENSES.md](LICENSES.md).

---

<div align="center">
  <sub><b>Image Library</b> - generate a sheet, drop it into the inbox, find it by meaning.</sub>
  <br>
  <sub>Found a bug or have an idea? - <a href="https://github.com/moonlivedt-oss/photosMOONprojects/issues">Issues</a></sub>
</div>
