[Home](../../README.en.md) | [Features](usage.md) | [Unreal](unreal.md) | [AI assistants](ai.md) | [Command line](cli.md) | [FAQ](faq.md) | [How it is built](architecture.md) | [Русский](../cli.md)

# Command line

```bash
py -3.14 _tools/cli.py cut sheet.png --grid 4x3 --names a,b,c --outline 8 --bg auto
py -3.14 _tools/cli.py convert folder --to webp --max 1920 [--replace]
py -3.14 _tools/cli.py dupes [folder]                   # identical ones go to _duplicates, nothing is deleted
py -3.14 _tools/cli.py done                             # done.js for Prompts.html
py -3.14 _tools/cli.py nobg picture.jpg                 # -> "picture без фона.png" (without background)
py -3.14 _tools/cli.py upscale icon.png --x 4 --kind art   # -> "icon x4.png"
py -3.14 _tools/cli.py unreal get hdri все --count 3    # Unreal Engine assets (CC0); "все" - all themes
py -3.14 _tools/cli.py unreal more all                  # more: all textures without repeats, scans and PBR models
py -3.14 _tools/cli.py repair                           # check and fix the database and settings without the window
py -3.14 _tools/cli.py api                              # operations for assistants and scripts, the answer is JSON
py -3.14 _tools/cli.py api search '{"query": "cozy night street"}'
```

For drag and drop there are `.cmd` files in `_tools/cli/`: cut a sheet, stickers with an outline, particles on
black, to WebP / PNG / ICO, find duplicates.

Tests: `_tools\run-tests.cmd` (the window does not open). README badges: `py -3.14 _tools/badges.py` (also run by
the `.githooks/pre-commit` hook). Release archive: `py -3.14 _tools/make_release.py`.

---

[Home](../../README.en.md) | [Features](usage.md) | [Unreal](unreal.md) | [AI assistants](ai.md) | [Command line](cli.md) | [FAQ](faq.md) | [How it is built](architecture.md)
