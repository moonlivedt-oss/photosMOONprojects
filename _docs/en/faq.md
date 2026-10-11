[Home](../../README.en.md) | [Features](usage.md) | [Unreal](unreal.md) | [AI assistants](ai.md) | [Command line](cli.md) | [FAQ](faq.md) | [How it is built](architecture.md) | [Русский](../faq.md)

# FAQ and troubleshooting

**`Library.cmd` says packages are missing although everything is installed.**
Most likely the `.cmd` has LF line endings instead of CRLF: after `chcp 65001` the console mixes up lines, and a
cut `ONTWRITEBYTECODE` shows up in the output. The repository pins this in `.gitattributes`; if the file was edited
by hand, save it with CRLF line endings. If the packages really are missing - run `Установить.cmd` (release) or
`py -3.14 -m pip install -r _tools/requirements.txt`.

**No globe button and no tag suggestions.**
No models: `py -3.14 _tools/get_models.py`. Check: four files in `_tools/_models/clip`.

**"Поиск по смыслу: учу картинки…" (semantic search: learning pictures) at the bottom of the window.**
The window computes vectors of new pictures. Search works once the counter reaches the end.

**The assistant does not see the library.**
The AI assistants window shows which assistants are installed and connected; restart the client after connecting
it. Check the server without an assistant: `py -3.14 _tools/cli.py api overview`.

**The assistant did the wrong thing.**
"History" at the bottom of the window or the "Undo" button in the message; the AI assistants window lists all of
its actions.

**The window behaved strangely or closed.**
Errors are written to `_tools/_errors.log` - attach it to an issue. If the window crashed, on the next start it
says so and offers a check; after two crashes in a row a safe mode turns on (live 3D in the Unreal tab is off).

**Tags, notes or settings are gone; something broke.**
"Инструменты" (Tools) -> **"Проверка и восстановление"** (check and restore), or Ctrl+P -> "Проверка": the state of
settings, database, backups, models and disk space, "Fix" with one button and a list of backups with "Restore
selected".

How it works:

| What | How it is protected |
|---|---|
| Tags, notes, favorites, smart folders, the undo journal (`library.db`) and settings (`settings.json`) | a backup once a day at start in `_tools/_backups/`, the last 10 are kept; the database is copied through the SQLite backup API, consistent even with the window and the MCP server open |
| Damaged settings | the window does not start with empty ones (it would write them over): the file is moved to `settings.json.broken-<time>` and the last good backup is used |
| Damaged database | the same: `library.db.broken-<time>` and the last good backup; with no backups - a new database (fingerprints and vectors are recomputed) |
| Writing files | through a temporary file and `fsync`: a crash or a power cut does not leave an empty file |
| Restoring a backup | the current state first goes into a "before restore" backup - you can change your mind |

**The window does not start at all.**
Double click `_tools/repair.cmd` - a check and a fix without the window. The same from the console:

```bash
py -3.14 _tools/cli.py repair                 # check
py -3.14 _tools/cli.py repair fix             # fix what can be fixed
py -3.14 _tools/cli.py repair list            # backups
py -3.14 _tools/cli.py repair restore latest  # restore the latest one
```

**A picture is lying on its side.**
Some jpg files store rotated pixels and an EXIF "rotate" flag. The window reads everything with the flag; if it is
sideways in another program, that is the other program.

---

[Home](../../README.en.md) | [Features](usage.md) | [Unreal](unreal.md) | [AI assistants](ai.md) | [Command line](cli.md) | [FAQ](faq.md) | [How it is built](architecture.md)
