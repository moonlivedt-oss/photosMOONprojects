"""Журнал действий: что сделано с библиотекой и как это отменить. Общий для окна и ИИ-помощников:
окно видит действия помощника (и может их отменить Ctrl+Z), помощник видит и отменяет свои.

Шаги действия (как раньше в истории окна, теперь в базе, в JSON):
  ["new", путь]                         - появился файл; отмена уносит его в _sources/_undone
  ["move", было, стало]                 - перенос, переименование, корзина; отмена возвращает
  ["tags", rel, до, после]              - метки картинки (списки)
  ["note", rel, до, после]              - заметка
  ["fav", rel, до, после]               - избранное (да/нет)
"""

import json
import os
import shutil
import time

from library import db
from library.common import PARK, unique

WINDOW = "окно"


def record(who, text, steps):
    """Записать действие. -> id или None, если шагов нет."""
    if not steps:
        return None
    with db._lock:
        c = db.conn()
        with c:
            cur = c.execute(
                "INSERT INTO journal(t, who, text, steps) VALUES (?,?,?,?)",
                (time.time(), who, text, json.dumps(steps, ensure_ascii=False)),
            )
            return cur.lastrowid


def set_steps(jid, steps):
    """Дописать действие (заметка набирается по буквам - одна запись на всю правку, а не на каждую паузу)."""
    with db._lock:
        c = db.conn()
        with c:
            c.execute("UPDATE journal SET steps=? WHERE id=?", (json.dumps(steps, ensure_ascii=False), jid))


def _row(r):
    return dict(id=r[0], t=r[1], who=r[2], text=r[3], steps=json.loads(r[4] or "[]"), undone=bool(r[5]))


def entries(limit=30, since=0, who=None, undone=None):
    """Последние действия, свежие сначала. since - только с id больше этого; who - только этого автора."""
    q, args = "SELECT id, t, who, text, steps, undone FROM journal WHERE id > ?", [since]
    if who:
        q += " AND who = ?"
        args.append(who)
    if undone is not None:
        q += " AND undone = ?"
        args.append(int(undone))
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with db._lock:
        return [_row(r) for r in db.conn().execute(q, args)]


def get(jid):
    with db._lock:
        r = db.conn().execute("SELECT id, t, who, text, steps, undone FROM journal WHERE id=?", (jid,)).fetchone()
    return _row(r) if r else None


def last_id():
    with db._lock:
        return db.conn().execute("SELECT COALESCE(MAX(id), 0) FROM journal").fetchone()[0]


def undone_among(ids):
    """Какие из этих действий уже отменены (например, помощник отменил своё, пока окно открыто)."""
    ids = [i for i in ids if i]
    if not ids:
        return set()
    with db._lock:
        q = "SELECT id FROM journal WHERE undone=1 AND id IN (%s)" % ",".join("?" * len(ids))
        return {r[0] for r in db.conn().execute(q, ids)}


def mark(jid, undone=True):
    if not jid:
        return
    with db._lock:
        c = db.conn()
        with c:
            c.execute("UPDATE journal SET undone=? WHERE id=?", (int(undone), jid))


def forget_steps(rel):
    """Картинка уходит (корзина): метки, заметка и избранное снимаются, а шаги вернут их при отмене."""
    tags, note, fav = db.tags_of(rel), db.note_of(rel), rel in db.favs()
    db.forget(rel)
    out = []
    if tags:
        out.append(["tags", rel, tags, []])
    if note:
        out.append(["note", rel, note, ""])
    if fav:
        out.append(["fav", rel, True, False])
    return out


def follow(old, new, lib):
    """Картинка сменила файл (другой формат после правки или сжатия): метки, заметка и избранное -
    за ней. -> шаги, чтобы отмена вернула их старому файлу."""
    try:
        a, b = os.path.relpath(old, lib), os.path.relpath(new, lib)
    except ValueError:  # другой диск
        return []
    if a == b or a.startswith("..") or b.startswith(".."):
        return []
    tags, note, fav = db.tags_of(a), db.note_of(a), a in db.favs()
    db.moved(a, b)
    out = []
    if tags:
        out += [["tags", a, tags, []], ["tags", b, [], tags]]
    if note:
        out += [["note", a, note, ""], ["note", b, "", note]]
    if fav:
        out += [["fav", a, True, False], ["fav", b, False, True]]
    return out


def _rel_meta(kind, rel, value):
    if kind == "tags":
        db.set_tags([rel], value, "set")
    elif kind == "note":
        db.set_note(rel, value or "")
    elif kind == "fav":
        db.set_fav([rel], bool(value))


def _move(src, dst, lib, on_move, meta=True):
    """Перенос с метками. meta=False - новый файл уходит при отмене: его метки остаются на месте
    (после отмены правки там снова лежит оригинал, и метки - его)."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    _forget_trash_info(src)
    if not meta:
        a = b = None
    else:
        try:
            a, b = os.path.relpath(src, lib), os.path.relpath(dst, lib)
        except ValueError:  # другой диск (корзина Windows) - метки там не живут
            a = b = None
    if a and b and not a.startswith("..") and not b.startswith(".."):
        db.moved(a, b)
    if on_move:
        on_move(src, dst)


def _forget_trash_info(path):
    """Файл вернули из корзины Windows ($Recycle.Bin/<sid>/$Rxxxx.png): рядом лежит его описание
    $Ixxxx.png - без него корзина не показывает пустую запись."""
    base = os.path.basename(path)
    if "$recycle.bin" in path.lower() and base.startswith("$R"):
        try:
            os.remove(os.path.join(os.path.dirname(path), "$I" + base[2:]))
        except OSError:
            pass


def undo_steps(steps, lib, park=PARK, on_move=None):
    """Откатить шаги действия. Новые файлы уезжают в park (а не в корзину), чтобы их можно было вернуть.
    on_move(было, стало) - после каждого переноса (окно так узнаёт, что файл вернулся во входящие).
    -> (сделанное - для redo_steps, сколько не получилось)."""
    done, bad = [], 0
    for step in reversed(steps):
        kind = step[0]
        try:
            if kind == "new":
                if os.path.exists(step[1]):
                    dst = unique(os.path.join(park, os.path.basename(step[1])))
                    _move(step[1], dst, lib, on_move, meta=False)
                    done.append(["mv", step[1], dst])
            elif kind == "move":
                if os.path.exists(step[2]):
                    back = step[1] if not os.path.exists(step[1]) else unique(step[1])
                    _move(step[2], back, lib, on_move)
                    done.append(["mv", step[2], back])
                else:
                    bad += 1
            elif kind in ("tags", "note", "fav"):
                _rel_meta(kind, step[1], step[2])
                done.append([kind, step[1], step[3]])
        except Exception:
            bad += 1
    return done, bad


def redo_steps(done, lib, on_move=None):
    """Вернуть отменённое: переносы в обратную сторону, метки и заметки - как было после действия."""
    bad = 0
    for d in reversed(done):
        try:
            if d[0] == "mv":
                a, b = d[1], d[2]
                if not os.path.exists(b) or os.path.exists(a):
                    bad += 1
                    continue
                _move(b, a, lib, on_move)
            else:
                _rel_meta(d[0], d[1], d[2])
        except Exception:
            bad += 1
    return bad
