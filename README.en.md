<div align="center">

[Русский](README.md) · **English**

<img src="_docs/screenshots/logo.png" alt="Picture Library logo: an image file with mountains and a sun" width="120">

# Picture Library

### A personal library of icons, stickers and backgrounds with a sorting window: cuts generated sheets, files them, searches by meaning

4x3 sheet cutting with preview · filing by section and palette · semantic search in Russian and English<br>
tag suggestions · smart folders · neural background removal and x4 upscaling · fully local, no network

[![CI](https://github.com/moonlivedt-oss/photosMOONprojects/actions/workflows/ci.yml/badge.svg)](https://github.com/moonlivedt-oss/photosMOONprojects/actions/workflows/ci.yml)
![version](https://img.shields.io/badge/version-2.1.0-cba6f7)
![python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![qt](https://img.shields.io/badge/PyQt6-window-41CD52?logo=qt&logoColor=white)
![tests](https://img.shields.io/badge/tests-36%20ok-a6e3a1)
![images](https://img.shields.io/badge/pictures-4160-89b4fa)
![license](https://img.shields.io/badge/code-MIT-green)

<img src="_docs/screenshots/hero.webp" alt="Library window: section tree on the left, sticker tiles in the middle, a baby dragon preview with colors and a tag suggestion on the right" width="880">

<sub>One folder · PyQt6 window · Pillow and numpy core · semantic search on onnxruntime</sub>

</div>

---

## Quick start

```bash
py -3.14 -m pip install PyQt6 pillow numpy onnxruntime
py -3.14 _tools/get_models.py      # neural models, ~460 MB, once (or by part: clip, bg, upscale)
```

Then run **`Library.cmd`** - a window opens with two tabs: "Входящие" (Inbox) and "Библиотека" (Library).
The interface is in Russian.

```bash
_tools\run-tests.cmd                            # all tests (32 checks, no window)
py -3.14 _tools/cli.py gallery                  # rebuild Gallery.html - the whole library in a browser
py -3.14 _tools/cli.py cut sheet.png --grid 4x3  # cut a sheet without the window
```

> Without the models the window works as before; only semantic search and tag suggestions are hidden.
> The prompts page (`Prompts.html`) and the "what is missing" table need node.

## What it is

Pictures for projects (icons, stickers, mascots, backgrounds) are generated as sheets of 12 and
tend to scatter across project folders. **Picture Library** keeps them in one place **by type**,
not by project, and takes over the routine: a sheet dropped into the inbox is cut by grid, its
pieces are named from the prompt list, pieces already in the library are marked, tags are
suggested, and everything is filed into the right section and palette.

| | Plain folder | Asset managers (Eagle etc.) | Picture Library |
|---|---|---|---|
| Cutting a sheet into pieces | by hand | no | **yes - grid or auto search, preview, manual boxes** |
| Filing into sections | by hand | by hand | **yes - automatically from a tag in the file name** |
| "Already have it" | no | no | **yes - fingerprints, repeats are not saved** |
| Search by meaning | no | paid AI features | **yes - local, Russian and English** |
| Search by image | no | partly | **yes - drop a file onto the search field** |
| Tag suggestions | no | no | **yes - from piece meaning, one click** |
| Smart folders | no | yes | **yes - saved search: words, color, meaning** |
| Perceptual compression | no | no | **yes - SSIM-based quality, lightest format** |
| Export to a project | by hand | partly | **yes - format, size, @2x/@3x, atlas, svg sprite** |
| Where data lives | on disk | own database | **on disk, plain files and folders** |

---

## Features

| Feature | Details |
|---|---|
| **Inbox** | sheets from `00 Входящие`, drag and drop or Ctrl+V; watching the generator folder |
| **Cutting** | 4x3 grid (neighbours touching by outline are split), auto search, whole picture; background removal, white outline, padding, size, format; hand-editable boxes |
| **Tag in the name** | a file `Космос [ic tokyo]` picks the cutting, section and palette itself and takes the 12 piece names from `Prompts.html` |
| **Semantic search** | crystal-ball button (Ctrl+M): "cat in space", "sad mascot" - no words in file names needed |
| **Search by image** | drop a file or a tile onto the search field; "Similar" and "Similar by meaning" in the tile menu |
| **Tags** | suggestions in the inbox and for the selected picture, optional auto-tagging for batch filing; tags and notes are searchable |
| **Neural editing** | remove any background (BiRefNet-lite), sharp x2/x4 upscaling (Real-ESRGAN, separate models for art and photos); CLI `nobg`, `upscale`, `cut --bg ai` |
| **Bulk tags, usage log** | apply suggested tags to a whole section; export (Ctrl+E) remembers which project folder a picture went to |
| **Smart folders** | save a search (words, color, meaning) - the folder in the tree fills itself |
| **Color search, sets** | 10 colors by dominant colors; sets with palette subfolders shown as one cover |
| **Editor** (Ctrl+R) | crop, rotate, color, recolor to palette, remove background and fringe, brush, outline, shadow, glow, rounding, resize; recipes; batch edit |
| **Compression** (Ctrl+K) | "no visible difference" quality (SSIM + color drift), lightest format, KB budget, before/after slider, all CPU cores |
| **Export** (Ctrl+E) | format, size, @1x/@2x/@3x, budget, svg (vtracer), png+json+css atlas, svg sprite |
| **Doctor and duplicates** | empty, cut off, leftover background, fringe, neighbour piece; duplicates go to `_duplicates` |
| **Undo** | Ctrl+Z / Ctrl+Y and a history menu; originals wait in `_sources` |

<div align="center">
<img src="_docs/screenshots/inbox.webp" alt="Inbox tab: a 4x3 sheet with piece boxes, pieces marked as already present, cutting settings and tag suggestions on the right" width="820">
<br><sub>Inbox: the sheet is cut by grid, repeats are marked, suggested tags on the right</sub>
</div>

<div align="center">
<img src="_docs/screenshots/semantic.webp" alt="Semantic search for a cozy night street with lanterns: 17 night scenes" width="820">
<br><sub>Semantic search: none of the query words are in the file names</sub>
</div>

---

## Semantic search

Runs entirely on this computer with `onnxruntime` (no torch):

- **images** - CLIP ViT-B/32, quantized ONNX
  [`Xenova/clip-vit-base-patch32`](https://huggingface.co/Xenova/clip-vit-base-patch32);
- **text** - multilingual encoder
  [`sentence-transformers/clip-ViT-B-32-multilingual-v1`](https://huggingface.co/sentence-transformers/clip-ViT-B-32-multilingual-v1)
  (50+ languages in the same space as the images).

The models (~225 MB) are not in the repository - GitHub rejects files over 100 MB - and are
downloaded once with `py -3.14 _tools/get_models.py`. Image vectors are computed in the background
and stored in the database. Similarity to the average library picture (or to generic words, for
text) is subtracted, so small flat UI parts do not float to the top of every query.

## Command line

```bash
py -3.14 _tools/cli.py cut sheet.png --grid 4x3 --names a,b,c --outline 8 --bg auto
py -3.14 _tools/cli.py convert folder --to webp --max 1920 [--replace]
py -3.14 _tools/cli.py dupes [folder]
py -3.14 _tools/cli.py gallery
```

## Project layout

`_tools/imaging/` - Qt-free core (cutting, encoding, editing, similarity, CLIP, doctor, sprites);
`_tools/ui/` - the PyQt6 window; `_tools/tests/` - unittest; `_sources/` - original sheets;
`_docs/` - README images. Full tree with comments: [README.md](README.md#структура-проекта).

## Privacy

The window **never goes online**: pictures, tags and semantic search are all computed locally.
The network is needed once, for `get_models.py` to download the models from Hugging Face.

## License

Code (`_tools/`, `Library.cmd`, `Prompts.html`) - MIT, see [LICENSE](LICENSE).
Library pictures are not covered by MIT: Kenney sets - CC0, Hero Patterns - CC BY 4.0
(see `_авторы и лицензия.txt` in their folders), the rest belong to the repository author.

Changes: [CHANGELOG.md](CHANGELOG.md).

---

<div align="center">
  <sub><b>Picture Library</b> - generate a sheet, drop it into the inbox, find it by meaning.</sub>
  <br>
  <sub>Found a bug or have an idea? - <a href="https://github.com/moonlivedt-oss/photosMOONprojects/issues">Issues</a></sub>
</div>
