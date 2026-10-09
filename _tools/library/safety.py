"""Защита от поломок и простое восстановление (без Qt: окно, командная строка и тесты).

Что ценно и не пересчитывается: метки, заметки, избранное, умные папки, журнал отмены (всё в library.db)
и настройки (settings.json: подборки и заметки Unreal, папки проектов, вид окна). Отпечатки и векторы CLIP
в той же базе - кэш, они пересчитываются сами.

- copies: _tools/_backups/<дата_время>[ причина]/ - library.db (через backup API SQLite: целая копия даже
  при открытой базе) и settings.json; раз в день при запуске окна и перед каждым восстановлением,
  хранятся последние KEEP.
- проверка (check): настройки читаются, база цела (quick_check), таблицы на месте, модели, место на диске,
  забытые временные файлы; у поправимого - fix.
- повреждённое не стирается: файл отодвигается рядом (*.broken-<время>) и берётся последняя целая копия."""

import glob
import json
import os
import shutil
import sqlite3
import time

import library.common as C
from library import db

KEEP = 10  # сколько копий хранить
STAMP = "%Y-%m-%d_%H%M%S"


def backups_dir():
    return os.path.join(C.HERE, "_backups")


def running_flag():
    return os.path.join(C.HERE, "_running.json")


# ---------------------------------------------------------------- копии
def backup(reason=""):
    """Копия базы и настроек. -> папка копии или None (копировать нечего)."""
    name = time.strftime(STAMP) + (f" {reason}" if reason else "")
    dst = os.path.join(backups_dir(), name)
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(backups_dir(), f"{name} {n}")
        n += 1
    tmp = dst + ".part"
    os.makedirs(tmp, exist_ok=True)
    got = False
    try:
        if os.path.exists(db.DB) and db_ok(db.DB):
            src = sqlite3.connect(db.DB, timeout=10)
            out = sqlite3.connect(os.path.join(tmp, "library.db"))
            try:
                src.backup(out)  # согласованная копия, даже если окно и сервер MCP пишут в базу
            finally:
                out.close()
                src.close()
            got = True
        if os.path.exists(C.CFG) and cfg_ok(C.CFG):
            shutil.copy2(C.CFG, os.path.join(tmp, "settings.json"))
            got = True
        if not got:
            shutil.rmtree(tmp, ignore_errors=True)
            return None
        with open(os.path.join(tmp, "backup.json"), "w", encoding="utf-8") as fh:  # точное время - для порядка
            json.dump({"t": time.time(), "reason": reason}, fh, ensure_ascii=False)
        os.replace(tmp, dst)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    prune()
    return dst


def backups():
    """Копии, новые первыми: [(папка, время, что внутри)]."""
    out = []
    for d in glob.glob(os.path.join(backups_dir(), "*")):
        if not os.path.isdir(d) or d.endswith(".part") or os.path.basename(d).startswith("_"):
            continue
        has = [f for f in ("library.db", "settings.json") if os.path.exists(os.path.join(d, f))]
        if has:
            try:
                with open(os.path.join(d, "backup.json"), encoding="utf-8") as fh:
                    t = float(json.load(fh)["t"])
            except (OSError, ValueError, KeyError, TypeError):
                t = os.path.getmtime(d)
            out.append((d, t, has))
    return sorted(out, key=lambda x: -x[1])


def prune(keep=KEEP):
    for d, _t, _h in backups()[keep:]:
        shutil.rmtree(d, ignore_errors=True)
    for d in glob.glob(os.path.join(backups_dir(), "*.part")):  # недописанные копии
        shutil.rmtree(d, ignore_errors=True)


def daily_backup():
    """Копия при запуске, если сегодня ещё не было. -> папка или None."""
    last = backups()
    if last and time.strftime("%Y-%m-%d", time.localtime(last[0][1])) == time.strftime("%Y-%m-%d"):
        return None
    return backup()


def restore(src, what=("library.db", "settings.json")):
    """Вернуть копию. Текущее состояние сначала само уходит в копию «перед восстановлением».
    Окно после этого надо перезапустить (база и настройки уже прочитаны)."""
    hold = os.path.join(backups_dir(), "_restoring")  # файлы копии - в сторону: новая копия ниже
    shutil.rmtree(hold, ignore_errors=True)  # запустит чистку старых и могла бы удалить саму src
    os.makedirs(hold)
    try:
        files = {}
        for f in what:
            p = os.path.join(src, f)
            if os.path.exists(p):
                files[f] = shutil.copy2(p, os.path.join(hold, f))
        if not files:
            raise FileNotFoundError(f"в копии нет файлов: {src}")
        backup("перед восстановлением")
        for f, p in files.items():
            if f == "library.db":
                db.close()
                for side in ("-wal", "-shm"):  # журнал WAL от старой базы к копии не относится
                    if os.path.exists(db.DB + side):
                        os.remove(db.DB + side)
                shutil.copy2(p, db.DB)
            else:
                shutil.copy2(p, C.CFG)
        return list(files)
    finally:
        shutil.rmtree(hold, ignore_errors=True)


# ---------------------------------------------------------------- проверка файлов
def cfg_ok(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return isinstance(json.load(fh), dict)
    except (OSError, ValueError):
        return False


def db_ok(path):
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            return c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            c.close()
    except sqlite3.Error:
        return False


def set_aside(path):
    """Повреждённый файл - не стирать, а отодвинуть рядом: вдруг из него ещё что-то достанут."""
    dst = f"{path}.broken-{time.strftime(STAMP)}"
    os.replace(path, dst)
    C.log_error(f"повреждённый файл отодвинут: {dst}")
    return dst


def recover_cfg():
    """Настройки не читаются: отодвинуть и взять из последней целой копии. -> настройки (dict)."""
    if os.path.exists(C.CFG):
        set_aside(C.CFG)
    for d, _t, has in backups():
        p = os.path.join(d, "settings.json")
        if "settings.json" in has and cfg_ok(p):
            shutil.copy2(p, C.CFG)
            C.log_error(f"настройки восстановлены из копии {os.path.basename(d)}")
            with open(C.CFG, encoding="utf-8") as fh:
                return json.load(fh)
    return {}


def recover_db():
    """База повреждена: отодвинуть и взять последнюю целую копию (или начать пустую). -> откуда взята."""
    db.close()
    for side in ("", "-wal", "-shm"):
        if os.path.exists(db.DB + side):
            if side:
                os.remove(db.DB + side)
            else:
                set_aside(db.DB)
    for d, _t, has in backups():
        p = os.path.join(d, "library.db")
        if "library.db" in has and db_ok(p):
            shutil.copy2(p, db.DB)
            C.log_error(f"база восстановлена из копии {os.path.basename(d)}")
            return os.path.basename(d)
    C.log_error("целой копии базы нет - начата новая (отпечатки и векторы пересчитаются сами)")
    return None


# ---------------------------------------------------------------- проверка целиком
def check():
    """[{name, ok, text, fix}] - fix: имя поправки для fix() или None."""
    out = []

    def row(name, ok, text, fix=None):
        out.append(dict(name=name, ok=ok, text=text, fix=None if ok else fix))

    if not os.path.exists(C.CFG):
        row("Настройки", True, "ещё не создавались - будут по умолчанию")
    else:
        ok = cfg_ok(C.CFG)
        row("Настройки", ok, "читаются" if ok else "файл повреждён - взять из копии", "cfg")
    if not os.path.exists(db.DB):
        row("База", True, "ещё не создана - появится при работе")
    else:
        ok = db_ok(db.DB)
        size = os.path.getsize(db.DB)
        row("База", ok, f"цела, {C.human(size)}" if ok else "повреждена - взять из копии", "db")
        if ok:
            try:
                with sqlite3.connect(f"file:{db.DB}?mode=ro", uri=True) as c:
                    n = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("tags", "notes", "fav")}
                row("Метки и заметки", True, f"меток {n['tags']}, заметок {n['notes']}, в избранном {n['fav']}")
            except sqlite3.Error as e:
                row("Метки и заметки", False, f"таблицы не читаются ({e}) - взять базу из копии", "db")
    bk = backups()
    if bk:
        age = (time.time() - bk[0][1]) / 86400
        row(
            "Резервные копии",
            age < 8,
            f"{len(bk)} шт., последняя - {time.strftime('%d.%m %H:%M', time.localtime(bk[0][1]))}"
            + ("" if age < 8 else " (давно - сделать новую)"),
            "backup",
        )
    else:
        row("Резервные копии", False, "ни одной - сделать сейчас", "backup")
    free = shutil.disk_usage(C.HERE).free
    row("Место на диске", free > 1 << 30, f"свободно {C.human(free)}" + ("" if free > 1 << 30 else " - мало"))
    junk = leftovers()
    row("Временные файлы", not junk, "нет" if not junk else f"забыто после сбоя: {len(junk)} - убрать", "junk")
    try:
        from imaging import clip, neural

        miss = [
            n
            for n, ok in (
                ("поиск по смыслу", clip.available()),
                ("фон", neural.bg_available()),
                ("увеличение", neural.upscale_available()),
            )
            if not ok
        ]
        row(
            "Модели нейросетей",
            not miss,
            "на месте" if not miss else "нет: " + ", ".join(miss) + " (py -3.14 _tools/get_models.py)",
        )
    except Exception as e:
        row("Модели нейросетей", False, f"не проверить: {e}")
    return out


def leftovers():
    """Временные файлы, забытые после сбоя (*.tmp*, *.part старше часа) - в служебной папке."""
    now, out = time.time(), []
    for pat in ("*.tmp*", "*.part"):
        for p in glob.glob(os.path.join(C.HERE, pat)):
            try:
                if now - os.path.getmtime(p) > 3600:
                    out.append(p)
            except OSError:
                pass
    return out


def fix(kind):
    """Поправить одну проблему из check(). -> текст для пузыря."""
    if kind == "cfg":
        recover_cfg()
        return "Настройки взяты из копии - перезапустите окно"
    if kind == "db":
        src = recover_db()
        return ("База взята из копии " + src if src else "Начата новая база") + " - перезапустите окно"
    if kind == "backup":
        d = backup()
        return "Копия сделана: " + os.path.basename(d) if d else "Копировать нечего"
    if kind == "junk":
        n = 0
        for p in leftovers():
            try:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
                n += 1
            except OSError:
                pass
        return f"Убрано временных файлов: {n}"
    raise ValueError(kind)


# ---------------------------------------------------------------- сбои при запуске
def start_run():
    """Окно запускается. -> сколько прошлых запусков подряд не закрылись нормально (0 - всё хорошо)."""
    crashes = 0
    try:
        with open(running_flag(), encoding="utf-8") as fh:
            crashes = int(json.load(fh).get("crashes", 0)) + 1
    except (OSError, ValueError, TypeError):
        crashes = 0
    try:
        with open(running_flag(), "w", encoding="utf-8") as fh:
            json.dump({"t": time.time(), "crashes": crashes, "pid": os.getpid()}, fh)
    except OSError:
        pass
    return crashes


def end_run():
    """Окно закрылось нормально. Отметку снимает только тот, кто её поставил: при перезапуске новое
    окно успевает отметиться раньше, чем старое закроется."""
    try:
        with open(running_flag(), encoding="utf-8") as fh:
            if json.load(fh).get("pid", os.getpid()) != os.getpid():
                return
        os.remove(running_flag())
    except (OSError, ValueError, AttributeError):
        pass
