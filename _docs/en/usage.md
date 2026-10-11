[Home](../../README.en.md) | [Features](usage.md) | [Unreal](unreal.md) | [AI assistants](ai.md) | [Command line](cli.md) | [FAQ](faq.md) | [How it is built](architecture.md) | [Русский](../usage.md)

# Features and how to use

The interface is in Russian; names in quotes are given as they appear in the window, with a translation.

| Feature | Details |
|---|---|
| **Inbox** ("Входящие") | a sheet from the `00 Входящие` folder, drag and drop or Ctrl+V; watching the generator folder - new pictures arrive by themselves; a background or an illustration is saved whole, a single drawing is cut out |
| **"Looks like: section"** | from the meaning of the pieces the window suggests where similar pictures live in the library - a click selects that section |
| **Cutting** | a 4x3 grid (neighbors stuck together by the outline are split), auto-detection of drawings, "whole"; removing a flat background, white outline, padding, side, format; frames are edited by hand: drag an edge, Shift - a new one, "Merge" / "Split" |
| **Tag in the name** | a file `Космос [ic tokyo]` picks the cutting, section and palette itself and takes the 12 piece names from `Prompts.html`; such files can be filed right away, without the window |
| **"Already there"** | the fingerprint of every piece is compared with the library and with the neighboring sheets of the batch - repeats are not checked |
| **Semantic search** | the globe button (Ctrl+M): "cat in space", "sad mascot", "potted plant" - in Russian and English, without the words in the file name; if names give nothing, the search shows similar pictures by meaning |
| **AI assistants** | Claude, Cursor and others over MCP or the command line: search, view, tags, move, edit, background, upscaling, cutting sheets, export; actions pop up in the window with an "Undo" button; a read-only mode |
| **Search by picture** | drop a file from Explorer or a tile into the search field - similar by meaning; "Similar" and "Similar by meaning" in the tile menu |
| **Tags** | suggestions by meaning in the inbox and for the selected picture, a "set them myself" box for batch filing; tags and notes are searchable, tags are in the tree |
| **Neural networks in the editor** | "Remove background with a neural network" - any background, not only a flat one (BiRefNet-lite); "x2" / "x4" - sharp upscaling (Real-ESRGAN: the drawing model keeps outlines, the photo model keeps textures, transparency is upscaled with the picture); in the command line - `nobg`, `upscale`, `cut --bg ai` |
| **Batch tags** | "Set suggested tags" for a section or a selection: first you see which tags and how many, then one click; an extra tag is removed from all pictures with a right click in the tree |
| **Where used** | export (Ctrl+E) remembers the project folder; under the picture path - "Exported to: VSCodeLauncher / assets" |
| **Smart folders** | save a search (words, color, meaning) - the folder in the tree fills itself |
| **Search by color** | 10 colors by the main colors of the picture; the palette of the selected picture, a click copies HEX |
| **Sets** | a folder with palette subfolders - as one cover; "What is missing" - a table of prompt cards by palette and recoloring from a ready one |
| **Editor** (Ctrl+R) | crop, rotate, color, recolor into a palette, remove background and fringe, brush, outline, shadow, glow, rounding, size; recipes; one edit for many files |
| **Compression** (Ctrl+K) | picking the "no visible difference" quality (SSIM + color shift), "the lightest format", a size limit, a before/after slider, on all cores |
| **Export** (Ctrl+E) | to a project folder: format, size, @1x/@2x/@3x, limit, svg (vtracer), png+json+css atlas, svg sprite |
| **Doctor and duplicates** | empty, cut off, with background leftovers, with a fringe, with a piece of a neighbor; identical pictures go to `_duplicates` |
| **Undo** | Ctrl+Z / Ctrl+Y, the "History" menu and the "Undo" button in a message - for saving, moving, renaming, trash, compression, edits and assistant actions; history survives a restart; originals wait in `_sources` |
| **Help** (F1) | sections and search; "What is new" after an update, "Where to start" on the first run |
| **Unreal** (Ctrl+3) | PBR textures, HDRI skies, 3D models and IES light profiles by theme; a 3D viewer; "Download more..." from Poly Haven and ambientCG (CC0); a tile can be dragged straight into the Content Browser - see [Unreal](unreal.md) |
| **Filters** | orientation, transparent background, size, format; remembered |
| **Picture versions** | after an edit or compression a "VERSIONS" row on the right: compare with the current one or restore it (Ctrl+Z undoes) |
| **Find everywhere** (Ctrl+P) | window commands, sections, pictures (by name, and if nothing - by meaning) and Unreal assets in one line |

<div align="center">
<img src="../screenshots/inbox.webp" alt="Inbox tab: a 4x3 sheet of fairy creatures with piece frames, ten pieces marked as already there, two new ones checked, cutting settings, tag suggestions and a suggested section on the right" width="820">
<br><sub>Inbox: the sheet is cut by grid, repeats are marked "already there", suggested tags on the right</sub>
</div>

<div align="center">
<img src="../screenshots/semantic.webp" alt="Semantic search for a cozy night street with lanterns: a strip of five fitting Unreal assets on top, 17 night scenes below, a rainy neon street on the right with tag suggestions" width="820">
<br><sub>Semantic search: neither "cozy" nor "street" is in the file names; fitting Unreal assets on top</sub>
</div>

<div align="center">
<img src="../screenshots/sets.webp" alt="Sets view: sets as covers of 12 pictures, the number of palettes and pictures in the caption" width="820">
<br><sub>Sets: every set as one cover, palettes and the number of pictures in the caption</sub>
</div>

<div align="center">
<img src="../screenshots/light.webp" alt="Light theme: the same library on a light background, sea creature stickers, a clownfish on the right" width="820">
<br><sub>Light theme and an accent of your choice: "Settings" (Ctrl+,), applied at once</sub>
</div>

---

## How to use

1. Take a prompt in `Prompts.html`: pick a palette, "Copy", for a sheet - "Names".
2. Generate the picture and name the file with comma-separated names or a tag (`Космос [ic tokyo]`).
3. Put it into `00 Входящие` or drag it into the window.
4. Check the cutting, add the suggested tags if you like and save (Ctrl+S).
   The source sheet moves to `_sources/<year-month>` - it can be cut again.
5. Search in the library tab by name, tag, color or meaning; export to a project - Ctrl+E.

More about prompts, sheets and palettes: [Prompts.md](../../Prompts.md) (in Russian).

### Tools

The "Инструменты" (Tools) button at the top and a right click on a picture -> "Tools": find duplicates, doctor,
"what is missing", section weight, **palette from a picture** (and recoloring others into it), **comparing two
versions** (slider, difference, SSIM), **SVG tracing** (three variants side by side).

- **Odd one out** - pictures that differ from their neighbors in manner rather than meaning: other colors or hue,
  no light outline, more or less detail, sparser drawing. The reason is shown in words under the tile; the same
  picture in several palettes of a set is one tile. Third-party sets (Kenney, Hero Patterns) - with a checkbox.
- **Contrast on backgrounds** (right click -> "Tools") - selected icons on their palette background, white, dark
  and a color of your choice: WCAG edge contrast (icons need 3:1) and a verdict "good / so-so / hard to see". If a
  white sticker outline blends into the background, the drawing right behind it is checked.
- **Project authors and licenses** - writes `CREDITS.md` into a project folder: which pictures were exported there
  and which Unreal assets were imported or packed for it, with licenses. What requires attribution (CC BY) and what
  is not CC0 is listed apart. The project's own `CREDITS.md` is not touched - then `CREDITS.library.md`.
- **Project palette: fitting sets** - site or game colors (typed, from a screenshot or from the project CSS: the
  page background of the light and dark theme is resolved through `var(--bg)` variables) -> which library sets fit:
  visible on every project background and close in color. The nearest `Prompts.html` palette and "Recolor into the
  project colors" as copies. The palette is remembered for the project folder.
- **Pre-publish check** - one button for a project folder: licenses (who needs attribution, is there a CREDITS.md),
  picture weight (heavy ones and how much webp saves), whether exported icons are visible on the project
  backgrounds, Unreal scene budget. A verdict and a `PUBLISH-CHECK.md` report.

<div align="center">
<img src="../screenshots/palette.webp" alt="Palette from a picture: a night lantern market sample and its six colors on the left, twelve forest animals recolored into these purple and pink colors on the right" width="760">
<br><sub>Palette from a picture: the colors of a night scene, and the forest animals are recolored at once</sub>
</div>

### Find everywhere (Ctrl+P)

One line for the whole window: commands ("compress", "theme", "duplicates"), sections, pictures and Unreal assets.
If picture names give nothing, the search goes by meaning: "кит" (whale) finds `whale.webp`. Enter runs the
command or opens the result in its place.

<div align="center">
<img src="../screenshots/find.webp" alt="Find everywhere: the query for a whale in Russian finds whale from the sea stickers first, with similar pictures below" width="620">
<br><sub>Find everywhere: in Russian, though the file is called whale</sub>
</div>

### Hotkeys (all of them are in the help, F1)

| Keys | Action |
|---|---|
| `Ctrl+S` | save the checked pieces into a section |
| `Ctrl+Z` / `Ctrl+Y` | undo / redo |
| `Ctrl+V` | paste a picture or files from the clipboard into the inbox |
| `Ctrl+F` / `Ctrl+M` | search / semantic search |
| `Space` | in the inbox - check a piece; in the library - full-window preview |
| `Ctrl+R` / `Ctrl+K` / `Ctrl+E` | edit / compress / export |
| `Ctrl+D` | favorite |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | tabs: inbox / library / Unreal |
| `Ctrl+I` | section weight |
| `F2` | rename; several selected - one name with numbers |
| `Ctrl+P` | find everywhere: commands, sections, pictures and Unreal assets in one line |
| `F1` | help: everything the window can do, with search |

## Neural networks

### Semantic search and tags

Runs entirely on this computer through `onnxruntime` (no torch needed):

- **pictures** - CLIP ViT-B/32, the quantized ONNX version
  [`Xenova/clip-vit-base-patch32`](https://huggingface.co/Xenova/clip-vit-base-patch32);
- **text** - the multilingual encoder
  [`sentence-transformers/clip-ViT-B-32-multilingual-v1`](https://huggingface.co/sentence-transformers/clip-ViT-B-32-multilingual-v1):
  Russian and 50+ more languages in the same space as the pictures.

The models (~225 MB) are not in the repository - GitHub does not accept files over 100 MB - and are downloaded
once: `py -3.14 _tools/get_models.py`. The window computes picture vectors in the background and keeps them in
the database; the first run over ~4000 pictures takes a couple of minutes, then only new ones are added.

Small flat interface details look like "everything at once" and would climb to the top of any query, so the
similarity of a picture to the average picture of the library is subtracted (for text - to a set of generic
words). Tag suggestions compare z-scores over the tag vocabulary: for a sheet of 12 different objects the tags
shared by many pieces come out on top.

### Background removal and upscaling

- **background** - [`onnx-community/BiRefNet_lite-ONNX`](https://huggingface.co/onnx-community/BiRefNet_lite-ONNX) (MIT, 224 MB): an object mask on any background, ~5-10 s per picture on the CPU;
- **upscaling** - [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (BSD-3): `realesr-animevideov3` for drawings and `realesr-general-x4v3` for photos, 2-5 MB each, a 256 px piece -> 1024 px in under a second; the picture is cut into tiles, so memory does not grow with size.

Real-ESRGAN is published only for PyTorch: `get_models.py` downloads the weights and converts them to ONNX once
(`imaging/convert_upscalers.py`, needs `torch` and `onnx`); the window does not need torch. Neural network
results are cached: the edit preview does not wait for them again on every slider move.

---

[Home](../../README.en.md) | [Features](usage.md) | [Unreal](unreal.md) | [AI assistants](ai.md) | [Command line](cli.md) | [FAQ](faq.md) | [How it is built](architecture.md)
