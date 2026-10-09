"""Пути, настройки, журнал ошибок и работа с файлами - без Qt.
Их берут окно (ui), командная строка (cli.py) и сервер для ИИ-помощников (mcp_server.py)."""

import json
import multiprocessing
import os
import shutil
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool

import imaging as K

VERSION = "2.3.0"  # вместе с ней - CHANGELOG и бейдж в README
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # папка _tools

LIB = K.LIB
INBOX = os.path.join(LIB, K.INBOX)
SOURCES = os.path.join(LIB, "_sources")
PARK = os.path.join(SOURCES, "_undone")  # отменённые новые файлы ждут тут Ctrl+Y
DELETED = os.path.join(SOURCES, "_deleted")  # «в корзину» от ИИ-помощника: можно вернуть отменой
CFG = os.path.join(HERE, "settings.json")
LOG = os.path.join(HERE, "_errors.log")


def load_cfg():
    try:
        with open(CFG, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def cfg_text(cfg):
    return json.dumps(cfg, ensure_ascii=False, indent=1)


def save_cfg(cfg):
    """Через временный файл: сбой посреди записи не оставит пустые настройки."""
    K.write_atomic(CFG, cfg_text(cfg), "utf-8")


def log_error(text):
    """Ошибка - в _errors.log (окно запускается через pyw, консоли нет). Журнал не растёт бесконечно."""
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 512 * 1024:
            os.replace(LOG, LOG + ".old")
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write("---- {}\n{}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), text.rstrip()))
    except OSError:
        pass


# Окно закрывается: новые фоновые задачи не начинаются, длинные циклы выходят досрочно -
# иначе Python завершается, пока потоки читают картинки, и процесс падает.
CLOSING = threading.Event()

# Сжатие одной картинки - это 4-6 пробных кодирований; по одному файлу за раз пачка шла долго.
# Тяжёлое (job_* из imaging) уходит в отдельные процессы, по одному на ядро.
_procs = None


def procs():
    global _procs
    if _procs is None:
        n = max(1, min(8, (os.cpu_count() or 2) - 1))  # одно ядро остаётся окну
        _procs = ProcessPoolExecutor(n, mp_context=multiprocessing.get_context("spawn"))
    return _procs


def parallel(job, items, stop=None):
    """job(путь, настройки) по ядрам для items = [(путь, настройки)]. Отдаёт (путь, результат)
    по мере готовности; результат - исключение, если файл не удался. stop - [True] прерывает."""
    global _procs
    try:
        futs = {procs().submit(job, p, o): p for p, o in items}
    except BrokenProcessPool:  # процессы упали (например, на битом файле) - новые
        _procs = None
        futs = {procs().submit(job, p, o): p for p, o in items}
    try:
        for f in as_completed(futs):
            if CLOSING.is_set() or (stop and stop[0]):
                break
            try:
                res = f.result()
            except BrokenProcessPool as e:
                _procs = None
                res = e
            except Exception as e:
                res = e
            yield futs[f], res
    finally:
        for f in futs:
            f.cancel()


def stop_procs():
    """Процессы по ядрам - бросить (окно закрывается)."""
    if _procs is not None:
        _procs.shutdown(wait=False, cancel_futures=True)
        for pr in list((getattr(_procs, "_processes", None) or {}).values()):
            pr.terminate()


def clean_name(s):
    return "".join(c for c in s if c not in '\\/:*?"<>|').strip().rstrip(".")


def unique(path):
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(path):
        path = "%s %d%s" % (base, n, ext)
        n += 1
    return path


def is_image(name):
    return name.lower().endswith(K.EXT) and not name.startswith("_")


def inbox_files():
    os.makedirs(INBOX, exist_ok=True)
    return sorted(
        os.path.join(INBOX, f) for f in os.listdir(INBOX) if is_image(f) and os.path.isfile(os.path.join(INBOX, f))
    )


def human(n):
    if n >= 1 << 30:
        return "%.1f ГБ" % (n / (1 << 30))
    return "%.1f МБ" % (n / 1048576) if n >= 1048576 else "%d КБ" % max(1, n // 1024)


def short(path):
    """Путь раздела для подписей: не больше двух последних папок."""
    try:
        rel = os.path.relpath(path, LIB).split(os.sep)
    except ValueError:  # папка на другом диске
        rel = os.path.normpath(path).split(os.sep)
    return " / ".join(rel[-2:])


def archive(path):
    """Убирает разобранный исходник из входящих в _sources/<год-месяц>. Возвращает новый путь."""
    d = os.path.join(SOURCES, time.strftime("%Y-%m"))
    os.makedirs(d, exist_ok=True)
    dst = unique(os.path.join(d, os.path.basename(path)))
    shutil.move(path, dst)
    return dst
