"""База библиотеки (SQLite, _tools/library.db): отпечатки, метки, заметки, избранное, умные папки,
векторы CLIP, журнал действий. Её одновременно открывают окно и сервер для ИИ - WAL это позволяет.
Пути - относительно корня библиотеки, как у избранного в настройках."""

import os
import sqlite3
import threading
import time
from collections import Counter

import numpy as np

from library.common import HERE, log_error

DB = os.path.join(HERE, "library.db")
_lock = threading.RLock()
_conn = None


def conn():
    global _conn
    with _lock:
        if _conn is None:
            try:
                _conn = _open()
            except sqlite3.DatabaseError as e:  # «file is not a database», «malformed» - не падать, а чинить
                from library import safety

                log_error(f"база не открылась: {e!r} - беру последнюю целую копию")
                safety.recover_db()
                _conn = _open()
        return _conn


def _open():
    c = sqlite3.connect(DB, check_same_thread=False, timeout=10)
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
                CREATE TABLE IF NOT EXISTS sigs(rel TEXT PRIMARY KEY, mt REAL, ratio REAL, vec BLOB, col TEXT, ver INT);
                CREATE TABLE IF NOT EXISTS tags(rel TEXT, tag TEXT, PRIMARY KEY(rel, tag));
                CREATE TABLE IF NOT EXISTS notes(rel TEXT PRIMARY KEY, text TEXT);
                CREATE INDEX IF NOT EXISTS tags_tag ON tags(tag);
                CREATE TABLE IF NOT EXISTS clip(rel TEXT PRIMARY KEY, mt REAL, vec BLOB);
                CREATE TABLE IF NOT EXISTS smart(name TEXT PRIMARY KEY, query TEXT, color TEXT, sem INT);
                CREATE TABLE IF NOT EXISTS exports(rel TEXT, dest TEXT, t REAL, PRIMARY KEY(rel, dest));
                CREATE TABLE IF NOT EXISTS fav(rel TEXT PRIMARY KEY, t REAL);
                CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, who TEXT,
                                                   text TEXT, steps TEXT, undone INT DEFAULT 0);
            """)
    except sqlite3.DatabaseError:
        c.close()
        raise
    return c


def close():
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def load_sigs():
    """{rel: [mt, ratio, vec (uint8, 432), цвета, версия]}"""
    with _lock:
        rows = conn().execute("SELECT rel, mt, ratio, vec, col, ver FROM sigs").fetchall()
    return {r[0]: [r[1], r[2], np.frombuffer(r[3], np.uint8), r[4] or "", r[5]] for r in rows}


def save_sigs(new, old):
    """Записать только разницу между old и new."""
    up = [
        (rel, v[0], v[1], np.asarray(v[2], np.uint8).tobytes(), v[3], v[4])
        for rel, v in new.items()
        if rel not in old or old[rel][0] != v[0] or old[rel][4] != v[4]
    ]
    gone = [(rel,) for rel in old if rel not in new]
    if not up and not gone:
        return
    with _lock:
        c = conn()
        with c:
            c.executemany("INSERT OR REPLACE INTO sigs VALUES (?,?,?,?,?,?)", up)
            c.executemany("DELETE FROM sigs WHERE rel=?", gone)


def clean_tag(t):
    return " ".join(t.strip().lower().replace("ё", "е").lstrip("#").split())


def tags_of(rel):
    with _lock:
        return [r[0] for r in conn().execute("SELECT tag FROM tags WHERE rel=? ORDER BY tag", (rel,))]


def set_tags(rels, tags, mode="set"):
    """mode: set - заменить, add - добавить, remove - убрать. rels - один путь или список."""
    rels = [rels] if isinstance(rels, str) else list(rels)
    tags = [t for t in (clean_tag(x) for x in tags) if t]
    with _lock:
        c = conn()
        with c:
            for rel in rels:
                if mode == "set":
                    c.execute("DELETE FROM tags WHERE rel=?", (rel,))
                if mode == "remove":
                    c.executemany("DELETE FROM tags WHERE rel=? AND tag=?", [(rel, t) for t in tags])
                else:
                    c.executemany("INSERT OR IGNORE INTO tags VALUES (?,?)", [(rel, t) for t in tags])


def all_tags():
    """Counter {метка: сколько картинок}."""
    with _lock:
        return Counter(dict(conn().execute("SELECT tag, COUNT(*) FROM tags GROUP BY tag")))


def with_tag(tag):
    with _lock:
        return [r[0] for r in conn().execute("SELECT rel FROM tags WHERE tag=? ORDER BY rel", (tag,))]


def note_of(rel):
    with _lock:
        r = conn().execute("SELECT text FROM notes WHERE rel=?", (rel,)).fetchone()
    return r[0] if r else ""


def set_note(rel, text):
    with _lock:
        c = conn()
        with c:
            if text.strip():
                c.execute("INSERT OR REPLACE INTO notes VALUES (?,?)", (rel, text))
            else:
                c.execute("DELETE FROM notes WHERE rel=?", (rel,))


def search_text():
    """{rel: «метки заметка»} - чтобы поиск находил и по ним."""
    out = {}
    with _lock:
        c = conn()
        for rel, tag in c.execute("SELECT rel, tag FROM tags"):
            out[rel] = out.get(rel, "") + " " + tag
        for rel, text in c.execute("SELECT rel, text FROM notes"):
            out[rel] = out.get(rel, "") + " " + text.lower().replace("ё", "е")
    return out


def moved(a, b):
    """Файл переехал или переименован - метки и заметка едут с ним."""
    with _lock:
        c = conn()
        with c:
            c.execute("UPDATE OR IGNORE tags SET rel=? WHERE rel=?", (b, a))
            c.execute("DELETE FROM tags WHERE rel=?", (a,))
            c.execute("UPDATE OR REPLACE notes SET rel=? WHERE rel=?", (b, a))
            c.execute("UPDATE OR REPLACE clip SET rel=? WHERE rel=?", (b, a))
            c.execute("UPDATE OR REPLACE exports SET rel=? WHERE rel=?", (b, a))
            c.execute("UPDATE OR REPLACE fav SET rel=? WHERE rel=?", (b, a))


def forget(rel):
    """Файл в корзине - метки и заметку убрать."""
    with _lock:
        c = conn()
        with c:
            c.execute("DELETE FROM tags WHERE rel=?", (rel,))
            c.execute("DELETE FROM notes WHERE rel=?", (rel,))
            c.execute("DELETE FROM fav WHERE rel=?", (rel,))


def load_clip():
    """{rel: (mt, вектор float16 из 512)}"""
    with _lock:
        rows = conn().execute("SELECT rel, mt, vec FROM clip").fetchall()
    return {r[0]: (r[1], np.frombuffer(r[2], np.float16)) for r in rows}


def save_clip(rows, gone=()):
    """rows = [(rel, mt, вектор)]; gone - пути, которых больше нет."""
    with _lock:
        c = conn()
        with c:
            c.executemany(
                "INSERT OR REPLACE INTO clip VALUES (?,?,?)",
                [(rel, mt, np.asarray(v, np.float16).tobytes()) for rel, mt, v in rows],
            )
            c.executemany("DELETE FROM clip WHERE rel=?", [(r,) for r in gone])


def smart_folders():
    """[(имя, запрос, цвет, по смыслу)] - сохранённые поиски."""
    with _lock:
        return [
            (n, q, col or "", bool(sem))
            for n, q, col, sem in conn().execute("SELECT name, query, color, sem FROM smart ORDER BY name")
        ]


def save_smart(name, query, color, sem):
    with _lock:
        c = conn()
        with c:
            c.execute("INSERT OR REPLACE INTO smart VALUES (?,?,?,?)", (name, query, color, int(sem)))


def delete_smart(name):
    with _lock:
        c = conn()
        with c:
            c.execute("DELETE FROM smart WHERE name=?", (name,))


def delete_tag(tag):
    """Убрать метку у всех картинок. Возвращает, у скольких она была."""
    with _lock:
        c = conn()
        with c:
            return c.execute("DELETE FROM tags WHERE tag=?", (tag,)).rowcount


def log_export(rels, dest):
    """Картинки ушли в папку проекта - запомнить где (панель справа показывает «Выгружено в»)."""
    with _lock:
        c = conn()
        with c:
            c.executemany("INSERT OR REPLACE INTO exports VALUES (?,?,?)", [(r, dest, time.time()) for r in rels])


def exports_of(rel):
    """[(папка, время)] - куда выгружалась картинка, свежие сначала."""
    with _lock:
        return conn().execute("SELECT dest, t FROM exports WHERE rel=? ORDER BY t DESC", (rel,)).fetchall()


def favs():
    """Избранное: множество путей. Раньше жило в settings.json - его переносит окно (take_old_favs)."""
    with _lock:
        return {r[0] for r in conn().execute("SELECT rel FROM fav")}


def set_fav(rels, on=True):
    rels = [rels] if isinstance(rels, str) else list(rels)
    with _lock:
        c = conn()
        with c:
            if on:
                c.executemany("INSERT OR IGNORE INTO fav VALUES (?,?)", [(r, time.time()) for r in rels])
            else:
                c.executemany("DELETE FROM fav WHERE rel=?", [(r,) for r in rels])
