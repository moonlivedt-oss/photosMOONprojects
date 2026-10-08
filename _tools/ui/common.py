"""Общее для окна: роли плиток, фоновые задачи в Qt. Пути, настройки и файлы - в library.common (без Qt)."""
import os
import subprocess

from PyQt6.QtCore import QFile, QObject, QRunnable, Qt, QThreadPool, pyqtSignal

from library import journal
from library.common import (  # noqa: F401 - окно берёт их отсюда
    CFG,
    CLOSING,
    DELETED,
    HERE,
    INBOX,
    LIB,
    LOG,
    PARK,
    SOURCES,
    VERSION,
    archive,
    cfg_text,
    clean_name,
    human,
    inbox_files,
    is_image,
    load_cfg,
    log_error,
    parallel,
    procs,
    save_cfg,
    short,
    stop_procs,
    unique,
)

UI = os.path.join(HERE, "_ui")              # стрелки и галочка для стилей
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
SMART = "::smart:"                                  # + имя умной папки (сохранённого поиска)
TAG = "::tag:"                                      # + имя метки
HEAVY_KB = 500                                      # тяжелее этого - кандидат на сжатие
THUMB = 256                                         # плитки библиотеки рисуются один раз, ползунок их только масштабирует


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


def finish_bg():
    """После закрытия окна: убрать из очереди то, что не началось, и дождаться начатого
    (запись файлов доделывается, чтения миниатюр, отпечатки и кодирование бросаются на полпути)."""
    CLOSING.set()
    stop_procs()
    pool = QThreadPool.globalInstance()
    pool.clear()
    pool.waitForDone()


def reveal(path):
    subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')


def to_trash(paths):
    """В корзину Windows так, чтобы Ctrl+Z вернул файл, а с ним метки, заметку и избранное.
    -> (сколько ушло, шаги для истории)."""
    steps, n = [], 0
    for p in paths:
        ok, where = QFile.moveToTrash(p)        # where - путь в корзине, по нему файл вернётся
        if not ok:
            continue
        n += 1
        if where:
            steps.append(["move", p, where])
        try:
            steps += journal.forget_steps(os.path.relpath(p, LIB))
        except ValueError:                      # не из библиотеки (другой диск)
            pass
    return n, steps
