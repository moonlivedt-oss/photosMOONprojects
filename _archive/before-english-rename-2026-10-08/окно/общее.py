"""Общее для всего окна: пути, настройки, фоновые задачи, работа с файлами."""
import json
import multiprocessing
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool

import картинки as K
from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # папка _инструменты

LIB = K.LIB
INBOX = os.path.join(LIB, K.INBOX)
SOURCES = os.path.join(LIB, "_исходники")
PARK = os.path.join(SOURCES, "_отменено")          # отменённые новые файлы ждут тут Ctrl+Y
CFG = os.path.join(HERE, "настройки.json")
SIGS = os.path.join(HERE, "_отпечатки.json")       # кэш отпечатков библиотеки для пометки "уже есть"
UI = os.path.join(HERE, "_оформление")              # стрелки и галочка для стилей
ROLE = Qt.ItemDataRole.UserRole                    # путь файла у плитки
PIX = Qt.ItemDataRole.UserRole + 1                 # миниатюра (QPixmap) - её рисует TileDelegate
SUB = Qt.ItemDataRole.UserRole + 2                 # вторая строка подписи плитки
STAR = Qt.ItemDataRole.UserRole + 3                # в избранном
EXT = Qt.ItemDataRole.UserRole + 4                 # формат (плашка при наведении)
DUPE = Qt.ItemDataRole.UserRole + 5                # кусок уже есть в библиотеке (путь похожего)
RECENT = "::recent"                                 # виртуальные разделы вкладки библиотеки
FAV = "::fav"
HEAVY = "::heavy"
SETS = "::sets"                                     # наборы: папки с подпапками палитр
TAG = "::tag:"                                      # + имя метки
HEAVY_KB = 500                                      # тяжелее этого - кандидат на сжатие
THUMB = 256                                         # плитки библиотеки рисуются один раз, ползунок их только масштабирует


# ---------------------------------------------------------------- настройки
def load_cfg():
    try:
        with open(CFG, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def cfg_text(cfg):
    return json.dumps(cfg, ensure_ascii=False, indent=1)


def save_cfg(cfg):
    """Через временный файл: сбой посреди записи раньше оставлял пустые настройки (и терял избранное)."""
    K.write_atomic(CFG, cfg_text(cfg), "utf-8")


# ---------------------------------------------------------------- журнал ошибок
LOG = os.path.join(HERE, "_ошибки.log")


def log_error(text):
    """Ошибка - в _ошибки.log (окно запускается через pyw, консоли нет). Журнал не растёт бесконечно."""
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 512 * 1024:
            os.replace(LOG, LOG + ".old")
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write("---- %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text.rstrip()))
    except OSError:
        pass


# ---------------------------------------------------------------- фоновые задачи
class Relay(QObject):
    done = pyqtSignal(object, object)       # (что вызвать, результат) - уже в главном потоке


_relay = None


def relay():
    """Мост из фоновых потоков в главный. Создаётся в главном потоке (main() зовёт его первым)."""
    global _relay
    if _relay is None:
        _relay = Relay()
        _relay.done.connect(lambda cb, res: cb(res))
    return _relay


# Окно закрывается: новые фоновые задачи не начинаются, длинные циклы выходят досрочно.
# Без этого Python завершался, пока потоки ещё читали картинки, и процесс падал (access violation).
CLOSING = threading.Event()


def in_main(cb, value):
    """Из фонового потока: вызвать cb(value) в главном (ход работы, подписи)."""
    try:
        relay().done.emit(cb, value)
    except RuntimeError:                    # окно уже закрыто, а фоновая задача ещё доделывалась
        pass


class Task(QRunnable):
    """fn() в фоновом потоке, cb(результат) - в главном."""

    def __init__(self, fn, cb):
        super().__init__()
        self.fn, self.cb = fn, cb

    def run(self):
        if CLOSING.is_set():
            return
        try:
            res = self.fn()
        except Exception as e:
            res = e
        if not CLOSING.is_set():
            in_main(self.cb, res)


def bg(fn, cb):
    if CLOSING.is_set():
        return
    relay()
    QThreadPool.globalInstance().start(Task(fn, cb))


# ---------------------------------------------------------------- работа по ядрам
# Сжатие одной картинки - это 4-6 пробных кодирований; по одному файлу за раз пачка шла долго.
# Тяжёлое (job_* из картинки.py) уходит в отдельные процессы, по одному на ядро.
_procs = None


def procs():
    global _procs
    if _procs is None:
        n = max(1, min(8, (os.cpu_count() or 2) - 1))       # одно ядро остаётся окну
        _procs = ProcessPoolExecutor(n, mp_context=multiprocessing.get_context("spawn"))
    return _procs


def parallel(job, items, stop=None):
    """job(путь, настройки) по ядрам для items = [(путь, настройки)]. Отдаёт (путь, результат)
    по мере готовности; результат - исключение, если файл не удался. stop - [True] прерывает."""
    global _procs
    try:
        futs = {procs().submit(job, p, o): p for p, o in items}
    except BrokenProcessPool:                   # процессы упали (например, на битом файле) - новые
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


def finish_bg():
    """После закрытия окна: убрать из очереди то, что не началось, и дождаться начатого
    (запись файлов доделывается, чтения миниатюр, отпечатки и кодирование бросаются на полпути)."""
    CLOSING.set()
    if _procs is not None:
        _procs.shutdown(wait=False, cancel_futures=True)
        for pr in list((getattr(_procs, "_processes", None) or {}).values()):
            pr.terminate()
    pool = QThreadPool.globalInstance()
    pool.clear()
    pool.waitForDone()


# ---------------------------------------------------------------- файлы
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
    return sorted(os.path.join(INBOX, f) for f in os.listdir(INBOX)
                  if is_image(f) and os.path.isfile(os.path.join(INBOX, f)))


def human(n):
    return "%.1f МБ" % (n / 1048576) if n >= 1048576 else "%d КБ" % max(1, n // 1024)


def short(path):
    """Путь раздела для подписей: не больше двух последних папок."""
    try:
        rel = os.path.relpath(path, LIB).split(os.sep)
    except ValueError:                      # папка на другом диске
        rel = os.path.normpath(path).split(os.sep)
    return " / ".join(rel[-2:])


def archive(path):
    """Убирает разобранный исходник из входящих в _исходники/<год-месяц>. Возвращает новый путь."""
    d = os.path.join(SOURCES, time.strftime("%Y-%m"))
    os.makedirs(d, exist_ok=True)
    dst = unique(os.path.join(d, os.path.basename(path)))
    shutil.move(path, dst)
    return dst


def reveal(path):
    subprocess.Popen('explorer /select,"%s"' % os.path.normpath(path))
