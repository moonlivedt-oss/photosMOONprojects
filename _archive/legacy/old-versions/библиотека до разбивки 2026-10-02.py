#!/usr/bin/env python3
# ============================================================
#  Окно библиотеки картинок (PyQt6). Запуск: Библиотека.cmd в корне библиотеки.
#
#  Вкладка "Входящие": всё, что лежит в "00 Входящие" (или перетащено в окно,
#  или вставлено Ctrl+V), режется с предпросмотром и раскладывается по разделам.
#  Исходный лист уезжает в "_исходники/<год-месяц>", чтобы его можно было перерезать.
#  Куски, которые уже есть в библиотеке, помечаются "уже есть" и не отмечаются.
#  Вкладка "Библиотека": просмотр разделов, поиск, сортировка, просмотр справа,
#  переименование, перенос, корзина, копирование пути и самой картинки,
#  перетаскивание картинок из окна в другие программы.
#  Ctrl+Z отменяет последнее сохранение, переименование или перенос.
#
#  Вся работа с картинками - в картинки.py, здесь только интерфейс.
#  Значки кнопок берутся из "04 Иконки" самой библиотеки (нет файла - кнопка без значка).
# ============================================================
import io
import hashlib
import json
import os
import re
from collections import OrderedDict
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image
from PyQt6.QtCore import (QFile, QFileSystemWatcher, QMimeData, QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool,
                          QTimer, QUrl, pyqtSignal)
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QCheckBox, QScrollArea, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QSlider,
                             QSpinBox, QSplitter, QStackedWidget, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import картинки as K  # noqa: E402

LIB = K.LIB
INBOX = os.path.join(LIB, K.INBOX)
SOURCES = os.path.join(LIB, "_исходники")
CFG = os.path.join(HERE, "настройки.json")
SIGS = os.path.join(HERE, "_отпечатки.json")       # кэш отпечатков библиотеки для пометки "уже есть"
UI = os.path.join(HERE, "_оформление")              # стрелки и галочка для стилей
ROLE = Qt.ItemDataRole.UserRole
RECENT = "::recent"                                 # виртуальные разделы вкладки библиотеки
FAV = "::fav"
HEAVY = "::heavy"
HEAVY_KB = 500                                      # тяжелее этого - кандидат на сжатие
THUMB = 192                                         # плитки библиотеки рисуются один раз, ползунок их только масштабирует

# Разделы, которых пока нет на диске: папка создаётся при первом сохранении в неё.
PLANNED = ["08 Градиенты", "09 Эффекты и частицы", "10 Рамки и орнаменты", "11 Аватары",
           "12 Медали и достижения", "13 Экраны ошибок и пустоты"]

# имя, настройки нарезки, раздел по умолчанию
PRESETS = [
    ("Лист 4x3 (обводка уже есть)", dict(mode="grid", fon="auto", obv=0, pad=6, size=256, fmt="webp"), "04 Иконки"),
    ("Наклейки (добавить белую обводку)", dict(mode="grid", fon="auto", obv=8, pad=6, size=256, fmt="webp"), "02 Наклейки"),
    ("Иконки (автопоиск рисунков)", dict(mode="auto", fon="auto", obv=0, pad=6, size=256, fmt="webp"), "04 Иконки"),
    ("Частицы на чёрном фоне", dict(mode="auto", fon="ostavit", obv=0, pad=6, size=256, fmt="webp"), "09 Эффекты и частицы"),
    ("Фон или иллюстрация целиком", dict(mode="whole", fon="ostavit", obv=0, pad=0, size=1920, fmt="webp"), "01 Фоны"),
    ("Логотип в ICO", dict(mode="whole", fon="ostavit", obv=0, pad=0, size=0, fmt="ico"), "05 Логотипы"),
]

SVG = {
    "down": '<path d="M2.5 4l3.5 3.5 3.5-3.5" fill="none" stroke="#b9b6c8" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round"/>',
    "up": '<path d="M2.5 8l3.5-3.5 3.5 3.5" fill="none" stroke="#b9b6c8" stroke-width="1.6" '
          'stroke-linecap="round" stroke-linejoin="round"/>',
    "right": '<path d="M4.5 2.5l3.5 3.5-3.5 3.5" fill="none" stroke="#8a879a" stroke-width="1.6" '
             'stroke-linecap="round" stroke-linejoin="round"/>',
    "check": '<path d="M2.6 6.3l2.3 2.3 4.5-5" fill="none" stroke="#15151c" stroke-width="1.9" '
             'stroke-linecap="round" stroke-linejoin="round"/>',
}

QSS = """
QWidget{background:#15151c;color:#e8e6f0;font:10pt "Segoe UI"}
QToolTip{background:#23232f;color:#e8e6f0;border:1px solid #3a3560;border-radius:4px;padding:4px 6px}
QListWidget,QTreeWidget,QLineEdit,QSpinBox,QComboBox{background:#1f1f29;border:1px solid #2a2a36;border-radius:6px;padding:3px}
QListWidget,QTreeWidget{outline:0}
QLineEdit,QSpinBox,QComboBox{padding:4px 8px;min-height:20px}
QLineEdit:hover,QSpinBox:hover,QComboBox:hover{border-color:#3a3a4c}
QLineEdit:focus,QSpinBox:focus,QComboBox:focus{border-color:#6f62c0}
QLineEdit:disabled,QSpinBox:disabled,QComboBox:disabled{color:#5d5b6a;background:#1a1a22}
QComboBox::drop-down{border:0;width:26px}
QComboBox::down-arrow{image:url(@UI/down.svg);width:12px;height:12px}
QComboBox QAbstractItemView{background:#1f1f29;border:1px solid #2a2a36;selection-background-color:#3a3560;outline:0;padding:3px}
QSpinBox{padding-right:26px}
QSpinBox::up-button,QSpinBox::down-button{subcontrol-origin:border;width:24px;border:0;border-left:1px solid #2a2a36;background:transparent}
QSpinBox::up-button{subcontrol-position:top right;border-top-right-radius:6px}
QSpinBox::down-button{subcontrol-position:bottom right;border-bottom-right-radius:6px}
QSpinBox::up-button:hover,QSpinBox::down-button:hover{background:#2a2a36}
QSpinBox::up-arrow{image:url(@UI/up.svg);width:12px;height:12px}
QSpinBox::down-arrow{image:url(@UI/down.svg);width:12px;height:12px}
QSpinBox::up-arrow:disabled,QSpinBox::up-arrow:off,QSpinBox::down-arrow:disabled,QSpinBox::down-arrow:off{image:none}
QPushButton{background:#1f1f29;border:1px solid #2a2a36;border-radius:6px;padding:6px 12px}
QPushButton:hover{border-color:#9d8cff}
QPushButton:pressed{background:#2a2a36}
QPushButton:disabled{color:#6b6978;border-color:#23232e}
QPushButton#primary{background:#9d8cff;color:#15151c;font-weight:600;border-color:#9d8cff;padding:8px 12px}
QPushButton#primary:hover{background:#b3a6ff;border-color:#b3a6ff}
QPushButton#primary:disabled{background:#2c2945;color:#7d7a99;border-color:#2c2945}
QPushButton#flat{background:transparent;border-color:transparent;padding:3px 8px;color:#9a98a8}
QPushButton#flat:hover{color:#e8e6f0;border-color:#2a2a36}
QPushButton#undo{background:#2c2945;border-color:#3a3560;padding:2px 10px}
QCheckBox{spacing:8px;background:transparent}
QCheckBox::indicator,QListWidget::indicator{width:15px;height:15px;border:1px solid #4a4860;border-radius:4px;background:#1f1f29}
QCheckBox::indicator:hover,QListWidget::indicator:hover{border-color:#9d8cff}
QCheckBox::indicator:checked,QListWidget::indicator:checked{background:#9d8cff;border-color:#9d8cff;image:url(@UI/check.svg)}
QGroupBox{border:1px solid #2a2a36;border-radius:8px;margin-top:10px;padding-top:10px}
QGroupBox::title{subcontrol-origin:margin;left:10px;color:#9a98a8}
QTabWidget::pane{border:0}
QTabBar::tab{padding:7px 16px;background:transparent;border-bottom:2px solid transparent;color:#9a98a8}
QTabBar::tab:hover{color:#e8e6f0}
QTabBar::tab:selected{border-bottom-color:#9d8cff;color:#e8e6f0}
QListWidget::item{border-radius:8px;padding:4px}
QTreeWidget::item{padding:3px 2px;border-radius:4px}
QListWidget::item:hover,QTreeWidget::item:hover{background:#262633}
QListWidget::item:selected,QTreeWidget::item:selected{background:#3a3560;color:#fff}
QTreeView::branch,QTreeView::branch:selected,QTreeView::branch:hover{background:transparent}
QTreeView::branch:has-children:closed{image:url(@UI/right.svg)}
QTreeView::branch:has-children:open{image:url(@UI/down.svg)}
QScrollBar:vertical{background:transparent;width:10px;margin:2px 1px}
QScrollBar:horizontal{background:transparent;height:10px;margin:1px 2px}
QScrollBar::handle{background:#34344a;border-radius:4px;min-height:28px;min-width:28px}
QScrollBar::handle:hover{background:#6f62c0}
QScrollBar::add-line,QScrollBar::sub-line{width:0;height:0;border:0}
QScrollBar::add-page,QScrollBar::sub-page{background:transparent}
QSlider{background:transparent}
QSlider::groove:horizontal{height:4px;background:#2a2a36;border-radius:2px}
QSlider::sub-page:horizontal{background:#6f62c0;border-radius:2px}
QSlider::handle:horizontal{width:14px;height:14px;margin:-5px 0;border-radius:7px;background:#9d8cff}
QSplitter::handle{background:#15151c}
QSplitter::handle:hover{background:#3a3560}
QStatusBar{background:#111117;color:#9a98a8;border-top:1px solid #23232e}
QStatusBar::item{border:0}
QStatusBar QLabel{background:transparent;color:#9a98a8;padding:0 6px}
QLabel#dim{color:#9a98a8;background:transparent}
QLabel#title{font-size:15pt;font-weight:600;background:transparent}
QLabel#big{font-size:11pt;font-weight:600;background:transparent}
QLabel#pic{background:#1a1a22;border:1px solid #23232e;border-radius:10px}
QFrame#drop{border:2px dashed #34344a;border-radius:16px;background:#17171f}
QFrame#drop QLabel{background:transparent}
QLabel#overlay{background:rgba(21,21,28,225);border:3px dashed #9d8cff;border-radius:18px;color:#e8e6f0;font-size:16pt;font-weight:600}
QMenu{border:1px solid #2a2a36;padding:4px}QMenu::item{padding:5px 18px;border-radius:4px}QMenu::item:selected{background:#3a3560}
QMenu::separator{height:1px;background:#2a2a36;margin:4px 6px}
"""

HELP = """<b>Горячие клавиши</b><table cellspacing=4>
<tr><td>Ctrl+S</td><td>сохранить отмеченные куски в раздел</td></tr>
<tr><td>Ctrl+Z</td><td>отменить последнее сохранение, переименование или перенос</td></tr>
<tr><td>Ctrl+V</td><td>вставить картинку или файлы из буфера во входящие</td></tr>
<tr><td>Ctrl+1 / Ctrl+2</td><td>вкладки Входящие / Библиотека</td></tr>
<tr><td>Ctrl+F</td><td>поиск по библиотеке</td></tr>
<tr><td>Пробел</td><td>во входящих - отметить / снять выделенные куски</td></tr>
<tr><td>Щелчок по рамке на листе</td><td>отметить / снять этот кусок</td></tr>
<tr><td>Двойной щелчок по куску</td><td>переименовать</td></tr>
<tr><td>F2 / Del / Ctrl+C</td><td>переименовать / в корзину / копировать путь</td></tr>
<tr><td>Ctrl+Shift+C</td><td>копировать саму картинку</td></tr>
<tr><td>Ctrl+колесо</td><td>размер плиток в библиотеке</td></tr>
<tr><td>Пробел</td><td>в библиотеке - просмотр на всё окно (стрелки листают, B - подложка)</td></tr>
<tr><td>Ctrl+D</td><td>в избранное / убрать</td></tr>
<tr><td>Метка в имени</td><td>«Космос [ic tokyo]» (кнопка «Имена» в промптах) - окно само выберет нарезку и папку</td></tr>
<tr><td>Ctrl+K</td><td>сжать и конвертировать (шторка до/после, подбор качества на глаз)</td></tr>
<tr><td>Ctrl+E</td><td>выгрузить выбранное в папку проекта (формат и размер)</td></tr>
</table><p>Картинки из библиотеки можно перетаскивать мышью прямо в другие программы.</p>"""


def ui_files():
    """Пишет svg-стрелки для стилей (один раз) и возвращает путь к ним в виде для QSS."""
    os.makedirs(UI, exist_ok=True)
    for name, body in SVG.items():
        text = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">%s</svg>' % body
        p = os.path.join(UI, name + ".svg")
        try:
            with open(p, encoding="utf-8") as fh:
                if fh.read() == text:
                    continue
        except OSError:
            pass
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    return UI.replace("\\", "/")


# ---------------------------------------------------------------- настройки
def load_cfg():
    try:
        with open(CFG, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_cfg(cfg):
    with open(CFG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- фоновые задачи
class Relay(QObject):
    done = pyqtSignal(object, object)       # (что вызвать, результат) - уже в главном потоке


RELAY = None


class Task(QRunnable):
    """fn() в фоновом потоке, cb(результат) - в главном."""

    def __init__(self, fn, cb):
        super().__init__()
        self.fn, self.cb = fn, cb

    def run(self):
        try:
            res = self.fn()
        except Exception as e:
            res = e
        RELAY.done.emit(self.cb, res)


def bg(fn, cb):
    QThreadPool.globalInstance().start(Task(fn, cb))


# ---------------------------------------------------------------- картинки -> Qt
def backdrop(w, h, mode):
    """Подложка под превью: шахматка (видно прозрачность), белая или чёрная."""
    if mode == "light":
        return Image.new("RGBA", (w, h), (255, 255, 255, 255))
    if mode == "dark":
        return Image.new("RGBA", (w, h), (0, 0, 0, 255))
    y, x = np.mgrid[0:h, 0:w]
    odd = ((x // 8 + y // 8) % 2)[..., None] == 1
    a = np.where(odd, np.uint8([42, 42, 54, 255]), np.uint8([31, 31, 41, 255])).astype(np.uint8)
    return Image.fromarray(a).copy()


def to_qimage(im):
    im = im.convert("RGBA")
    q = QImage(im.tobytes("raw", "RGBA"), im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888)
    return q.copy()                         # copy: буфер PIL не переживёт выход из функции


def to_pix(im):
    return QPixmap.fromImage(to_qimage(im))


def tile(im, side, mode=None):
    """Квадратная плитка side x side: картинка по центру, под ней подложка (mode=None - прозрачно)."""
    im = im.convert("RGBA")
    im.thumbnail((side, side), Image.LANCZOS)
    bg_ = backdrop(side, side, mode) if mode else Image.new("RGBA", (side, side), (0, 0, 0, 0))
    bg_.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return to_pix(bg_)


def badge(pm, text, color="#e8a948"):
    """Плашка с надписью в правом верхнем углу плитки."""
    pm = QPixmap(pm)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = p.font()
    f.setPointSizeF(7.5)
    f.setBold(True)
    p.setFont(f)
    w = p.fontMetrics().horizontalAdvance(text) + 10
    r = QRectF(pm.width() - w - 4, 4, w, 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(r, 4, 4)
    p.setPen(QColor("#15151c"))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pm


def with_star(pm):
    """Плитка с маленькой звездой в левом верхнем углу - картинка в избранном."""
    pm = QPixmap(pm)
    p = QPainter(pm)
    p.drawPixmap(4, 4, lib_pix("star", 44))
    p.end()
    return pm


def swatch(color, side=14):
    pm = QPixmap(side, side)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#4a4860"), 1))
    p.setBrush(QColor(color))
    p.drawEllipse(1, 1, side - 2, side - 2)
    p.end()
    return QIcon(pm)


_thumbs = OrderedDict()                 # плитки в памяти, самые давние выбрасываются
THUMBS_MAX = 2500
THUMBS_DIR = os.path.join(HERE, "_миниатюры")


def raw_thumb(path, side):
    """Уменьшенная копия с прозрачностью. Маленькие хранятся на диске: большой раздел открывается сразу.
    Можно звать из фонового потока (только PIL)."""
    st = os.stat(path)
    cache = None
    if side <= 256:
        key = hashlib.sha1(("%s|%d|%d|%d" % (path, st.st_mtime_ns, st.st_size, side)).encode("utf-8")).hexdigest()
        cache = os.path.join(THUMBS_DIR, key[:2], key + ".webp")
        if os.path.exists(cache):
            try:
                with Image.open(cache) as im:
                    im.load()
                    return im.convert("RGBA")
            except Exception:
                pass
    with Image.open(path) as im:
        im.draft("RGB", (side * 2, side * 2))      # jpg открывается сразу уменьшенным
        im = im.convert("RGBA")
    im.thumbnail((side, side), Image.LANCZOS)
    if cache:
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            im.save(cache, "WEBP", quality=88, method=2)
        except OSError:
            pass
    return im


def tile_image(path, side, mode):
    """Готовая плитка как QImage - тоже можно строить в фоне."""
    im = raw_thumb(path, side)
    back = backdrop(side, side, mode) if mode else Image.new("RGBA", (side, side), (0, 0, 0, 0))
    back.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return to_qimage(back)


def remember(key, pm):
    _thumbs[key] = pm
    _thumbs.move_to_end(key)
    while len(_thumbs) > THUMBS_MAX:
        _thumbs.popitem(last=False)
    return pm


def thumb_key(path, side, mode):
    try:
        return (path, os.path.getmtime(path), side, mode)
    except OSError:
        return None


def thumb(path, side, mode=None):
    key = thumb_key(path, side, mode)
    if key is None:
        return QPixmap()
    if key in _thumbs:
        _thumbs.move_to_end(key)
    else:
        try:
            if path.lower().endswith(".svg"):
                src = QIcon(path).pixmap(side, side)
                pm = to_pix(backdrop(side, side, mode)) if mode else QPixmap(side, side)
                if not mode:
                    pm.fill(QColor(0, 0, 0, 0))
                p = QPainter(pm)
                p.drawPixmap((side - src.width()) // 2, (side - src.height()) // 2, src)
                p.end()
            else:
                pm = QPixmap.fromImage(tile_image(path, side, mode))
        except Exception:
            pm = QPixmap()
        remember(key, pm)
    return _thumbs[key]


_icons = None


def lib_pix(name, side=48):
    """Значок из "04 Иконки" библиотеки по имени файла без расширения."""
    global _icons
    if _icons is None:
        _icons = {}
        for p in K.images_in(os.path.join(LIB, "04 Иконки")):      # иконки лежат по подпапкам
            _icons.setdefault(os.path.splitext(os.path.basename(p))[0], p)
    p = _icons.get(name)
    return thumb(p, side) if p else QPixmap()


def lib_icon(name):
    pm = lib_pix(name)
    return QIcon(pm) if not pm.isNull() else QIcon()


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
    rel = os.path.relpath(path, LIB).split(os.sep)
    return " / ".join(rel[-2:])


def process(path, o):
    """Исходник + настройки -> (лист, готовые картинки, рамки на листе)."""
    im = K.load(path)
    if o["mode"] == "whole":
        out = K.remove_bg(im) if o["fon"] == "ubrat" else im
        if o["size"] and max(out.size) > o["size"]:
            k = o["size"] / max(out.size)
            out = out.resize((round(out.width * k), round(out.height * k)), Image.LANCZOS)
        return im, [out], []
    setka = (o["cols"], o["rows"]) if o["mode"] == "grid" else None
    pieces, boxes = K.cut(im, setka, o["size"], o["fon"], o["obv"], o["pad"] / 100)
    return im, pieces, boxes


# ---------------------------------------------------------------- раскладка по метке в имени файла
# Кнопка «Имена» в Промпты.html даёт имя вида «Космос [ic tokyo]» или «bg-cozy-lofi-study [bd mocha]»:
# вид картинки и палитра. По ним окно само выбирает нарезку и папку, а 12 имён кусков листа берёт
# из самой страницы промптов (так имя файла остаётся коротким).
PROMPTS = os.path.join(LIB, "Промпты.html")
TAG = re.compile(r"^(.*?)\s*\[([a-z]{2}) ([a-z]+)\]$")
GRID = dict(mode="grid", cols=4, rows=3, fon="auto", obv=0, pad=6, size=256, fmt="webp")


def whole(size, fmt="webp"):
    return dict(mode="whole", cols=4, rows=3, fon="ostavit", obv=0, pad=0, size=size, fmt=fmt)


# вид: (папка, нарезка). {set} - набор (лист), {pal} - папка палитры.
ROUTES = {
    "ic": ("04 Иконки/{set}/{pal}", GRID),
    "st": ("02 Наклейки/{set}/{pal}", GRID),
    "po": ("03 Маскоты/{set}", GRID),
    "md": ("12 Медали и достижения/{set}/{pal}", GRID),
    "av": ("11 Аватары/{set}/{pal}", GRID),
    "ma": ("03 Маскоты/Новый стиль", whole(1024)),
    "sc": ("06 Иллюстрации/Онбординг", whole(1024)),
    "sp": ("06 Иллюстрации/Заставки", whole(1920)),
    "bd": ("01 Фоны/Ночные сцены/{pal}", whole(1920)),
    "bl": ("01 Фоны/Светлые/{pal}", whole(1920)),
    "pa": ("07 Паттерны и текстуры/{pal}", whole(0)),
    "gr": ("08 Градиенты/{pal}", whole(1920)),
    "em": ("13 Экраны ошибок и пустоты/{pal}", whole(768)),
    "me": ("12 Медали и достижения/{pal}", whole(512)),
    "aa": ("11 Аватары/{pal}", whole(512)),
    "fx": ("09 Эффекты и частицы/{pal}", dict(GRID, rows=4)),
    "fr": ("10 Рамки и орнаменты/{pal}", whole(1920)),
    "lo": ("05 Логотипы", whole(0, "ico")),
    "co": ("06 Иллюстрации/Обложки", whole(1920)),
}
STOP = set("a an the of with and in on at to for from by under over near into its is no very that".split())
_prompts = {"mt": None, "pals": {}, "sets": {}}


def js_slug(s, n=3):
    """Как slug() в Промпты.html: первые слова без служебных, через дефис."""
    w = [x for x in re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split() if x not in STOP]
    return "-".join(w[:n])


def set_name(title):
    """Как setName() в Промпты.html: «Интерфейс: основное» -> «Интерфейс - основное», «Новый год: лист» -> «Новый год»."""
    t = re.sub(r"\s*\(.*?\)", "", title)
    if re.match(r"^(Новый год|Хэллоуин|Весна|Лето|Осень|День рождения):", t):
        return t.split(":")[0]
    return t.replace(": ", " - ")


def prompt_data():
    """Палитры и имена кусков листов из Промпты.html (перечитывается, когда страница меняется)."""
    try:
        mt = os.path.getmtime(PROMPTS)
    except OSError:
        return {}, {}
    if _prompts["mt"] != mt:
        with open(PROMPTS, encoding="utf-8") as fh:
            text = fh.read()
        pals = dict(re.findall(r'^\s*\["(\w+)","([^"]+)","', text, re.M))
        sets = {}
        for m in re.finditer(r'\["([^"]+)",\s*(?:as\()?(sheet|zoo|poses)\(\[(.*?)\](?:,\s*\[(.*?)\])?', text, re.S):
            title, fn, a, b = m.groups()
            items = re.findall(r'"([^"]*)"', b if fn == "poses" and b else a)
            names = items if fn == "poses" else [js_slug(x) for x in items]
            key = set_name(title)
            sets[key] = names
            sets[({"sheet": "ic", "zoo": "st", "poses": "po"}[fn], key)] = names
        _prompts.update(mt=mt, pals=pals, sets=sets)
    return _prompts["pals"], _prompts["sets"]


def sheet_names(kind, text):
    _pals, sets = prompt_data()
    return sets.get((kind, text)) or sets.get(text)


def route(path):
    """Метка в имени файла -> dict(dest, o, names, text) или None."""
    m = TAG.match(os.path.splitext(os.path.basename(path))[0])
    if not m or m.group(2) not in ROUTES:
        return None
    text, kind, pal = m.groups()
    pals, _sets = prompt_data()
    tpl, o = ROUTES[kind]
    rel = tpl.format(set=clean_name(text), pal=clean_name(pals.get(pal, pal)))
    names = sheet_names(kind, text) if o["mode"] == "grid" and kind != "fx" else None
    return dict(dest=os.path.join(LIB, *rel.split("/")), o=dict(o), names=names, text=text)


def default_names(path, n, text=""):
    """Имена по порядку: из метки листа, список через запятую, общий префикс или имя листа."""
    stem = os.path.splitext(os.path.basename(path))[0]
    for src in (text.strip(), stem):
        m = TAG.match(src)
        if m:
            listed = sheet_names(m.group(2), m.group(1))
            if listed and len(listed) == n and (src == text.strip() or not text):
                return [clean_name(x) for x in listed]
            if src == text.strip():
                text = m.group(1)
            else:
                stem = m.group(1)
    if not text and stem.count(",") == n - 1 and n > 1:
        text = stem             # лист назван списком имён (кнопка «Имена» в Промпты.html) - берём их
    listed = [clean_name(x) for x in text.split(",")] if "," in text else []
    prefix = clean_name(text) if text and not listed else stem
    out = []
    for i in range(n):
        if i < len(listed) and listed[i]:
            out.append(listed[i])
        else:
            out.append(prefix if n == 1 else "%s_%02d" % (prefix, i + 1))
    return out


def store(path, o, pieces, names, dest):
    """Пишет картинки в раздел. Нетронутый файл нужного формата копируется без пережатия."""
    os.makedirs(dest, exist_ok=True)
    same = (o["mode"] == "whole" and o["fon"] != "ubrat" and len(pieces) == 1
            and os.path.splitext(path)[1].lower() == "." + o["fmt"])
    if same:
        with Image.open(path) as src:
            same = src.size == pieces[0].size
    saved = []
    for im, name in zip(pieces, names):
        p = unique(os.path.join(dest, (clean_name(name) or "без имени") + "." + o["fmt"]))
        if same:
            shutil.copy2(path, p)
        else:
            K.save(im, p, o["fmt"])
        saved.append(p)
    return saved


def archive(path):
    """Убирает разобранный исходник из входящих в _исходники/<год-месяц>. Возвращает новый путь."""
    d = os.path.join(SOURCES, time.strftime("%Y-%m"))
    os.makedirs(d, exist_ok=True)
    dst = unique(os.path.join(d, os.path.basename(path)))
    shutil.move(path, dst)
    return dst


def reveal(path):
    subprocess.Popen('explorer /select,"%s"' % os.path.normpath(path))


# ---------------------------------------------------------------- отпечатки библиотеки ("уже есть")
def build_sigs(old):
    """В фоне: отпечатки всех картинок библиотеки, неизменённые берутся из кэша."""
    new = {}
    for f in K.images_in(LIB):
        if f.lower().endswith(".svg"):
            continue
        rel = os.path.relpath(f, LIB)
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        o = old.get(rel)
        if o and o[0] == mt and len(o) > 3:
            new[rel] = o
            continue
        try:
            with Image.open(f) as im:
                ratio = im.width / im.height
                im.draft("RGB", (96, 96))
                _r, v = K.signature(im)
                col = K.colors(im)
        except Exception:
            continue
        new[rel] = [mt, round(ratio, 4), np.rint(v).astype(int).ravel().tolist(), col]
    return new


class SigIndex:
    def __init__(self):
        self.data, self.busy, self.again = {}, False, False
        self.paths, self.ratio, self.vec = [], np.zeros(0), np.zeros((0, 432))
        try:
            with open(SIGS, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except Exception:
            pass
        self._arrays()

    def _arrays(self):
        items = [(k, v) for k, v in self.data.items() if len(v[2]) == 432]
        self.paths = [k for k, _v in items]
        self.ratio = np.array([v[1] for _k, v in items], dtype=float)
        self.vec = np.array([v[2] for _k, v in items], dtype=float).reshape(-1, 432)
        self.col = {k: (v[3] if len(v) > 3 else "") for k, v in items}

    def has_color(self, path, code):
        return code in self.col.get(os.path.relpath(path, LIB), "")

    def similar(self, path, n=48):
        """Самые похожие картинки по отпечатку (рисунок и пропорции), без самой картинки."""
        rel = os.path.relpath(path, LIB)
        if rel not in self.data or not len(self.paths):
            return []
        o = self.data[rel]
        v, r = np.array(o[2], dtype=float), o[1]
        d = np.abs(self.vec - v).mean(1) + 40 * np.abs(np.log(self.ratio / r))
        out = []
        for i in np.argsort(d):
            p = os.path.join(LIB, self.paths[i])
            if self.paths[i] != rel and os.path.exists(p):
                out.append(p)
            if len(out) >= n:
                break
        return out

    def refresh(self):
        if self.busy:
            self.again = True
            return
        self.busy = True
        old = dict(self.data)
        bg(lambda: build_sigs(old), self._built)

    def _built(self, res):
        self.busy = False
        if isinstance(res, dict):
            self.data = res
            self._arrays()
            try:
                tmp = SIGS + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(res, fh, separators=(",", ":"))
                os.replace(tmp, SIGS)
            except OSError:
                pass
        if self.again:
            self.again = False
            self.refresh()

    def find(self, im):
        """Путь похожей картинки из библиотеки (относительно LIB) или None."""
        paths, ratio, vec = self.paths, self.ratio, self.vec        # разом: индекс могут обновить из другого потока
        if not len(paths):
            return None
        r, v = K.signature(im)
        near = np.flatnonzero(np.abs(ratio - r) / r < K.SAME_RATIO)
        if not len(near):
            return None
        d = np.abs(vec[near] - v.ravel()).mean(1)
        i = int(d.argmin())
        return paths[near[i]] if d[i] < K.SAME_DIFF else None

    def groups(self):
        """Группы одинаковых картинок (тот же рисунок в другом размере или формате)."""
        paths, ratio, vec = self.paths, self.ratio, self.vec
        up = list(range(len(paths)))

        def root(i):
            while up[i] != i:
                up[i] = up[up[i]]
                i = up[i]
            return i

        for i in range(len(paths) - 1):
            d = np.abs(vec[i + 1:] - vec[i]).mean(1)
            ok = (d < K.SAME_DIFF) & (np.abs(ratio[i + 1:] - ratio[i]) / ratio[i] < K.SAME_RATIO)
            for j in np.flatnonzero(ok):
                up[root(i + 1 + int(j))] = root(i)
        out = {}
        for i, rel in enumerate(paths):
            p = os.path.join(LIB, rel)
            if os.path.exists(p):
                out.setdefault(root(i), []).append(p)
        return [g for g in out.values() if len(g) > 1]


# ---------------------------------------------------------------- дерево разделов
def fill_tree(tree, planned=True, recent=False):
    keep = tree.currentItem().data(0, ROLE) if tree.currentItem() else None
    tree.clear()
    folder, star, plus = lib_icon("folder"), lib_icon("folder-star"), lib_icon("plus-circle")

    if recent:
        for text, role, icon in (("Недавние", RECENT, "hourglass"), ("Избранное", FAV, "star"),
                                 ("Тяжёлые", HEAVY, "zip-archive")):
            it = QTreeWidgetItem(tree, [text])
            it.setData(0, ROLE, role)
            it.setIcon(0, lib_icon(icon))

    def add(parent, path, depth):
        n = len(K.images_in(path))
        it = QTreeWidgetItem(parent, ["%s  (%d)" % (os.path.basename(path), n)])
        it.setData(0, ROLE, path)
        it.setIcon(0, star if depth == 1 else folder)
        it.setToolTip(0, os.path.relpath(path, LIB))
        if depth < 3:
            for d in sorted(os.listdir(path)):
                sub = os.path.join(path, d)
                if os.path.isdir(sub) and not d.startswith("_"):
                    add(it, sub, depth + 1)
        return it

    names = [d for d in os.listdir(LIB) if os.path.isdir(os.path.join(LIB, d))
             and not d.startswith(("_", ".")) and d != K.INBOX]
    for d in sorted(set(names) | (set(PLANNED) if planned else set())):
        path = os.path.join(LIB, d)
        if os.path.isdir(path):
            add(tree.invisibleRootItem(), path, 1)
        else:
            it = QTreeWidgetItem(tree, [d + "  (новый)"])
            it.setData(0, ROLE, path)
            it.setIcon(0, plus)
            it.setToolTip(0, "Папки пока нет - появится при первом сохранении в неё")
            it.setForeground(0, QColor("#7d7a8c"))
    select_path(tree, keep)


def select_path(tree, path):
    if not path:
        return False

    def walk(it):
        for i in range(it.childCount()):
            c = it.child(i)
            if c.data(0, ROLE) == path:
                tree.setCurrentItem(c)
                return True
            if walk(c):
                return True
        return False

    return walk(tree.invisibleRootItem())


def make_tree():
    t = QTreeWidget()
    t.setHeaderHidden(True)
    t.setIndentation(16)
    t.setIconSize(QSize(18, 18))
    t.setAnimated(True)
    return t


def icon_list(side, cls=QListWidget):
    w = cls()
    w.setViewMode(QListWidget.ViewMode.IconMode)
    w.setResizeMode(QListWidget.ResizeMode.Adjust)
    w.setMovement(QListWidget.Movement.Static)
    w.setSpacing(4)
    w.setWordWrap(True)
    w.setUniformItemSizes(True)
    set_side(w, side)
    return w


def set_side(w, side):
    w.setIconSize(QSize(side, side))
    w.setGridSize(QSize(side + 22, side + 40))


def key(seq, parent, fn, local=True):
    """Горячая клавиша; local - только когда фокус внутри parent, а не во всём окне."""
    s = QShortcut(QKeySequence(seq), parent, fn)
    if local:
        s.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    return s


def flat(text, fn, tip=""):
    b = QPushButton(text, objectName="flat")
    b.clicked.connect(fn)
    b.setToolTip(tip)
    return b


# ---------------------------------------------------------------- предпросмотр листа
class Sheet(QWidget):
    """Исходный лист с рамками найденных рисунков и их номерами. Щелчок по рамке - отметить/снять кусок."""
    toggled = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.pm, self.boxes, self.full, self.on, self.hover = None, [], (1, 1), [], -1
        self.setMinimumHeight(160)
        self.setMouseTracking(True)

    def show_sheet(self, im, boxes, mode):
        self.full, self.boxes = im.size, boxes
        small = im.copy()
        small.thumbnail((1400, 1400), Image.LANCZOS)
        back = backdrop(small.width, small.height, mode)
        back.alpha_composite(small.convert("RGBA"))
        self.pm = to_pix(back)
        self.update()

    def clear(self):
        self.pm, self.boxes, self.on, self.hover = None, [], [], -1
        self.update()

    def frame(self):
        k = min(self.width() / self.pm.width(), self.height() / self.pm.height())
        w, h = self.pm.width() * k, self.pm.height() * k
        return (self.width() - w) / 2, (self.height() - h) / 2, w, h

    def rects(self):
        x0, y0, w, h = self.frame()
        kx, ky = w / self.full[0], h / self.full[1]
        return [QRectF(x0 + a * kx, y0 + b * ky, (c - a) * kx, (d - b) * ky) for a, b, c, d in self.boxes]

    def box_at(self, pos):
        if not self.pm:
            return -1
        for i, r in enumerate(self.rects()):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        i = self.box_at(e.position())
        if i != self.hover:
            self.hover = i
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        i = self.box_at(e.position())
        if i >= 0 and e.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit(i)

    def paintEvent(self, _e):
        if not self.pm:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        x0, y0, w, h = self.frame()
        p.drawPixmap(int(x0), int(y0), int(w), int(h), self.pm)
        for i, r in enumerate(self.rects()):
            on = self.on[i] if i < len(self.on) else True
            col = QColor("#9d8cff" if on else "#6b6978")
            if not on:
                p.fillRect(r, QColor(21, 21, 28, 160))
            elif i == self.hover:
                p.fillRect(r, QColor(157, 140, 255, 40))
            p.setPen(QPen(col, 3 if i == self.hover else 2))
            p.drawRect(r)
            lab = QRectF(r.x(), r.y(), 22, 18)
            p.fillRect(lab, col)
            p.setPen(QColor("#15151c"))
            p.drawText(lab, Qt.AlignmentFlag.AlignCenter, str(i + 1))
        p.end()


class Sig(QObject):
    done = pyqtSignal(int, object, object, object, str)


class Job(QRunnable):
    """Нарезка в фоновом потоке: большой лист не должен подвешивать окно."""

    def __init__(self, gen, path, opts, sig):
        super().__init__()
        self.gen, self.path, self.opts, self.sig = gen, path, opts, sig

    def run(self):
        try:
            im, pieces, boxes = process(self.path, self.opts)
            self.sig.done.emit(self.gen, im, pieces, boxes, "")
        except Exception as e:
            self.sig.done.emit(self.gen, None, [], [], str(e))


# ---------------------------------------------------------------- вкладка "Входящие"
class InboxTab(QWidget):
    changed = pyqtSignal()          # в библиотеку что-то записано

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.gen, self.path, self.pieces, self.loading, self.dupe = 0, None, [], False, {}
        self.pool = QThreadPool.globalInstance()
        self.sig = Sig()
        self.sig.done.connect(self.on_done)
        self.timer = QTimer(self, singleShot=True, interval=250)     # ждём, пока докрутят настройку
        self.timer.timeout.connect(self.run)

        # слева - входящие
        self.files = icon_list(96)
        self.files.currentItemChanged.connect(self.pick)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self.files_menu)
        self.files.itemDoubleClicked.connect(lambda it: os.startfile(it.data(ROLE)))
        add = QPushButton(lib_icon("plus-circle"), "Добавить файлы...")
        add.clicked.connect(self.add_files)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.count = QLabel("Листы", objectName="dim")
        for w in (self.count, self.files, add):
            lv.addWidget(w)

        # центр - лист и результат (или пустая заглушка)
        self.sheet = Sheet()
        self.sheet.toggled.connect(self.toggle_piece)
        self.out = icon_list(112)
        self.out.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.out.setEditTriggers(QListWidget.EditTrigger.DoubleClicked | QListWidget.EditTrigger.EditKeyPressed)
        self.out.itemChanged.connect(self.checks_changed)
        self.info = QLabel("Выберите лист слева", objectName="dim")
        self.info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # длинное имя листа не раздвигает окно
        self.bg = QComboBox()
        for t, v in (("Фон: шахматка", "chk"), ("Фон: светлый", "light"), ("Фон: тёмный", "dark")):
            self.bg.addItem(t, v)
        self.bg.setCurrentIndex(max(0, self.bg.findData(self.cfg.get("bg", "chk"))))
        self.bg.currentIndexChanged.connect(self.repaint_preview)
        top = QHBoxLayout()
        top.addWidget(self.info, 1)
        top.addWidget(flat("Отметить все", lambda: self.check_all(True)))
        top.addWidget(flat("Снять все", lambda: self.check_all(False)))
        top.addWidget(self.bg)
        self.mid = QSplitter(Qt.Orientation.Vertical)
        self.mid.addWidget(self.sheet)
        self.mid.addWidget(self.out)
        self.mid.setSizes(self.cfg.get("split_mid", [300, 360]))
        work = QWidget()
        cv = QVBoxLayout(work)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addLayout(top)
        cv.addWidget(self.mid, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty_page())
        self.stack.addWidget(work)

        # справа - настройки и раздел
        self.preset = QComboBox()
        for name, _o, _s in PRESETS:
            self.preset.addItem(name)
        self.mode = QComboBox()
        for t, v in (("Найти рисунки автоматически", "auto"), ("Резать по сетке", "grid"), ("Не резать (целиком)", "whole")):
            self.mode.addItem(t, v)
        self.cols = QSpinBox(minimum=1, maximum=20, value=4)
        self.rows = QSpinBox(minimum=1, maximum=20, value=3)
        grid = QHBoxLayout()
        grid.addWidget(self.cols, 1)
        grid.addWidget(QLabel("x", objectName="dim"))
        grid.addWidget(self.rows, 1)
        self.fon = QComboBox()
        for t, v in (("Убрать, если однотонный", "auto"), ("Убрать всегда", "ubrat"), ("Оставить", "ostavit")):
            self.fon.addItem(t, v)
        self.obv = QSpinBox(minimum=0, maximum=40, suffix=" px")
        self.pad = QSpinBox(minimum=0, maximum=30, suffix=" %")
        self.size = QSpinBox(minimum=0, maximum=8192, singleStep=64, suffix=" px", specialValueText="не менять")
        self.size_label = QLabel()
        self.fmt = QComboBox()
        self.fmt.addItems(["webp", "png", "jpg", "ico"])
        self.names = QLineEdit(placeholderText="префикс или список: кот, сова, лиса")
        self.names.setClearButtonEnabled(True)
        self.obv.setToolTip("Белая обводка вокруг рисунка, как у наклеек")
        self.pad.setToolTip("Пустые поля вокруг рисунка, доля стороны")
        self.names.setToolTip("Пусто - имена из названия листа. Одно слово - префикс с номерами. Через запятую - по порядку.")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setVerticalSpacing(7)
        form.addRow("Заготовка", self.preset)
        form.addRow("Нарезка", self.mode)
        form.addRow("Сетка", grid)
        form.addRow("Фон листа", self.fon)
        form.addRow("Обводка", self.obv)
        form.addRow("Поля", self.pad)
        form.addRow(self.size_label, self.size)
        form.addRow("Формат", self.fmt)
        form.addRow("Имена", self.names)
        for c in (self.preset, self.mode, self.fon):          # длинные пункты не раздвигают правую панель
            c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(14)
        box1 = QGroupBox("Нарезка")
        box1.setLayout(form)

        self.tree = make_tree()
        self.tree.currentItemChanged.connect(lambda *_: self.update_save())
        self.tree.itemClicked.connect(self.tree_clicked)
        self.route, self.manual, self.auto_busy = None, False, False
        self.no_auto = set()                # вернулись во входящие по Ctrl+Z - сами не раскладывать
        self.route_lbl = QLabel(objectName="dim", wordWrap=True)
        self.route_lbl.hide()
        newdir = QPushButton(lib_icon("folder"), "Новая папка...")
        newdir.clicked.connect(lambda: new_folder(self, self.tree))
        self.auto = QCheckBox("Помеченные раскладывать сразу")
        self.auto.setToolTip("Картинки с меткой в имени (кнопка «Имена» в промптах, например «Космос [ic tokyo]»)\n"
                             "нарезаются и раскладываются сами, как только попадают во входящие. Ctrl+Z отменяет.")
        self.auto.setChecked(self.cfg.get("auto_route", False))
        self.auto.toggled.connect(self.auto_toggled)
        self.auto_timer = QTimer(self, singleShot=True, interval=900)
        self.auto_timer.timeout.connect(self.auto_sort)
        self.keep = QCheckBox("Исходник убрать в _исходники")
        self.keep.setChecked(self.cfg.get("archive", True))
        self.save_btn = QPushButton("Сохранить в раздел", objectName="primary")
        self.save_btn.setToolTip("Ctrl+S")
        self.save_btn.clicked.connect(self.save_current)
        self.all_btn = QPushButton("Разобрать все входящие")
        self.all_btn.setToolTip("Помеченные - по своим папкам, остальные - с текущими настройками в выбранный раздел")
        self.all_btn.clicked.connect(self.save_all)
        b2 = QVBoxLayout()
        for w in (self.route_lbl, self.tree, newdir, self.auto, self.keep, self.save_btn, self.all_btn):
            b2.addWidget(w)
        box2 = QGroupBox("Куда")
        box2.setLayout(b2)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(box1)
        rv.addWidget(box2, 1)

        self.split = QSplitter()
        for w in (left, self.stack, right):
            self.split.addWidget(w)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes(self.cfg.get("split_in", [230, 640, 340]))
        lay = QVBoxLayout(self)
        lay.addWidget(self.split)

        self.preset.currentIndexChanged.connect(self.apply_preset)
        for c in (self.mode, self.fon, self.fmt):
            c.currentIndexChanged.connect(self.touched)
        for s in (self.cols, self.rows, self.obv, self.pad, self.size):
            s.valueChanged.connect(self.touched)
        self.names.textChanged.connect(self.rename_pieces)
        key("Ctrl+S", self, self.save_current)
        key("Space", self.out, self.toggle_selected)
        key("Delete", self.files, self.trash_file)

        fill_tree(self.tree)
        self.preset.setCurrentIndex(min(self.cfg.get("preset", 0), len(PRESETS) - 1))
        self.apply_preset()
        self.reload()

    def empty_page(self):
        f = QFrame(objectName="drop")
        v = QVBoxLayout(f)
        v.addStretch(1)
        ic = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        ic.setPixmap(lib_pix("download-arrow", 96))
        t = QLabel("Входящих нет", objectName="title", alignment=Qt.AlignmentFlag.AlignCenter)
        s = QLabel("Перетащите листы в окно, вставьте картинку из буфера (Ctrl+V)\n"
                   "или положите файлы в папку «%s»" % K.INBOX, objectName="dim", alignment=Qt.AlignmentFlag.AlignCenter,
                   wordWrap=True)
        self.gen_hint = QLabel(objectName="dim", alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
        row = QHBoxLayout()
        row.addStretch(1)
        for text, icon, fn in (("Добавить файлы...", "plus-circle", self.add_files),
                               ("Вставить из буфера", "clipboard", self.win.paste),
                               ("Открыть папку", "folder", lambda: os.startfile(INBOX))):
            b = QPushButton(lib_icon(icon), text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        for w in (ic, t, s):
            v.addWidget(w)
        v.addSpacing(10)
        v.addLayout(row)
        v.addSpacing(6)
        v.addWidget(self.gen_hint)
        v.addStretch(2)
        return f

    # --- настройки
    def opts(self):
        return dict(mode=self.mode.currentData(), cols=self.cols.value(), rows=self.rows.value(),
                    fon=self.fon.currentData(), obv=self.obv.value(), pad=self.pad.value(),
                    size=self.size.value(), fmt=self.fmt.currentText())

    def apply_preset(self):
        _name, o, section = PRESETS[self.preset.currentIndex()]
        self.loading = True
        self.mode.setCurrentIndex(self.mode.findData(o["mode"]))
        self.fon.setCurrentIndex(self.fon.findData(o["fon"]))
        self.obv.setValue(o["obv"])
        self.pad.setValue(o["pad"])
        self.size.setValue(o["size"])
        self.fmt.setCurrentText(o["fmt"])
        self.loading = False
        last = self.cfg.get("dest", {}).get(str(self.preset.currentIndex()))     # куда сохраняли с этой заготовкой
        if not (last and os.path.isdir(last) and select_path(self.tree, last)):
            select_path(self.tree, os.path.join(LIB, section))
        self.touched()

    def touched(self):
        if self.loading:
            return
        mode = self.mode.currentData()
        for w in (self.cols, self.rows):
            w.setEnabled(mode == "grid")
        for w in (self.obv, self.pad):
            w.setEnabled(mode != "whole")
        self.size_label.setText("Длинная сторона" if mode == "whole" else "Сторона")
        self.timer.start()

    # --- список входящих
    def reload(self):
        keep = self.path
        self.files.blockSignals(True)
        self.files.clear()
        for p in inbox_files():
            it = QListWidgetItem(QIcon(thumb(p, 96, "chk")), os.path.basename(p))
            it.setData(ROLE, p)
            it.setToolTip(p)
            self.files.addItem(it)
        self.files.blockSignals(False)
        rows = [i for i in range(self.files.count()) if self.files.item(i).data(ROLE) == keep]
        n = self.files.count()
        if n:
            self.files.setCurrentRow(rows[0] if rows else 0)
        else:
            self.pick(None)
        self.stack.setCurrentIndex(1 if n else 0)
        self.count.setText("Листов во входящих: %d" % n if n else "Листов нет")
        self.all_btn.setEnabled(n > 1)
        self.win.tabs.setTabText(0, "Входящие (%d)" % n)
        if self.auto.isChecked() and n:
            self.auto_timer.start()

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Добавить во входящие", self.cfg.get("add_dir", ""),
                                                "Картинки (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.avif)")
        if files:
            self.cfg["add_dir"] = os.path.dirname(files[0])
        self.win.take(files)

    def files_menu(self, pos):
        it = self.files.itemAt(pos)
        if not it:
            return
        p = it.data(ROLE)
        m = QMenu(self)
        m.addAction("Открыть", lambda: os.startfile(p))
        m.addAction("Показать в проводнике", lambda: reveal(p))
        m.addSeparator()
        m.addAction("В корзину\tDel", self.trash_file)
        m.exec(self.files.mapToGlobal(pos))

    def trash_file(self):
        it = self.files.currentItem()
        if not it:
            return
        p = it.data(ROLE)
        if QMessageBox.question(self, "В корзину", "Убрать лист в корзину: %s?" % os.path.basename(p)) \
                == QMessageBox.StandardButton.Yes and QFile.moveToTrash(p):
            self.path = None
            self.reload()
            self.win.say("Лист в корзине: " + os.path.basename(p))

    def pick(self, item, _prev=None):
        path = item.data(ROLE) if item else None
        if path == self.path and path:
            return
        self.path = path
        self.route, self.manual = (route(path) if path else None), False
        self.show_route()
        if not path:
            self.gen += 1
            self.pieces, self.dupe = [], {}
            self.sheet.clear()
            self.out.clear()
            self.info.setText("Входящих нет")
            self.update_save()
            return
        if self.route:                       # метка в имени: нарезка и папка - по ней
            o = self.route["o"]
            self.loading = True
            self.mode.setCurrentIndex(self.mode.findData(o["mode"]))
            self.cols.setValue(o["cols"])
            self.rows.setValue(o["rows"])
            self.fon.setCurrentIndex(self.fon.findData(o["fon"]))
            self.obv.setValue(o["obv"])
            self.pad.setValue(o["pad"])
            self.size.setValue(o["size"])
            self.fmt.setCurrentText(o["fmt"])
            self.loading = False
            self.touched()
            self.timer.stop()
            select_path(self.tree, self.route["dest"])
        self.run()

    def show_route(self):
        r = self.route
        if r and not self.manual:
            new = "" if os.path.isdir(r["dest"]) else "  (папка появится при сохранении)"
            self.route_lbl.setText("По имени файла: %s%s\nЩёлкните раздел ниже, чтобы выбрать другой." % (short(r["dest"]), new))
        self.route_lbl.setVisible(bool(r and not self.manual))
        self.update_save()

    def tree_clicked(self, *_):
        if self.route:
            self.manual = True                  # раздел выбран руками - метка больше не решает
            self.show_route()

    def auto_toggled(self, on):
        self.cfg["auto_route"] = on
        if on:
            self.auto_timer.start()

    def auto_sort(self):
        """Помеченные картинки из входящих - сразу в свои папки (в фоне)."""
        if self.auto_busy or not self.auto.isChecked():
            return
        files = [(f, route(f)) for f in inbox_files()]
        files = [(f, r) for f, r in files if r and f not in self.no_auto]
        if not files:
            return
        self.auto_busy = True
        keep_src, sigs = self.keep.isChecked(), self.win.sigs

        def work():
            steps, total, skipped, bad, where = [], 0, 0, [], set()
            for f, r in files:
                try:
                    _im, pieces, _b = process(f, dict(r["o"]))
                    names = default_names(f, len(pieces))
                    keep = [i for i, pc in enumerate(pieces) if not sigs.find(pc)]
                    skipped += len(pieces) - len(keep)
                    saved = store(f, r["o"], [pieces[i] for i in keep], [names[i] for i in keep], r["dest"])
                    total += len(saved)
                    steps += [("new", x) for x in saved]
                    where.add(short(r["dest"]))
                    if keep_src:
                        steps.append(("move", f, archive(f)))
                except Exception as e:
                    bad.append("%s: %s" % (os.path.basename(f), e))
            return steps, total, skipped, bad, where

        bg(work, self.auto_done)

    def auto_done(self, res):
        self.auto_busy = False
        if isinstance(res, Exception):
            self.win.say("Автораскладка не удалась: %s" % res)
            return
        steps, total, skipped, bad, where = res
        text = "Разложено само: %d шт. в %s" % (total, ", ".join(sorted(where))) if total else "Новых кусков нет"
        if skipped:
            text += ", повторов пропущено: %d" % skipped
        if bad:
            text += ", не получилось: " + "; ".join(bad)
        self.win.push(text, steps)
        self.path = None
        self.reload()
        fill_tree(self.tree)
        self.changed.emit()
        self.win.say(text)
        QApplication.alert(self.win)

    # --- нарезка
    def run(self):
        if not self.path:
            return
        self.gen += 1
        self.info.setText("Режу...")
        self.save_btn.setEnabled(False)
        self.pool.start(Job(self.gen, self.path, self.opts(), self.sig))

    def on_done(self, gen, im, pieces, boxes, err):
        if gen != self.gen:                 # пока резали, настройки уже поменяли
            return
        if err:
            self.pieces, self.dupe = [], {}
            self.sheet.clear()
            self.out.clear()
            self.info.setText("Не получилось: " + err)
            self.update_save()
            return
        self.im, self.pieces, self.boxes = im, pieces, boxes
        self.dupe = {}
        self.out.clear()                    # новый результат: отметки и имена прошлой нарезки не переносим
        for i, piece in enumerate(pieces):
            hit = self.win.sigs.find(piece)
            if hit:
                self.dupe[i] = hit
        self.repaint_preview()

    def repaint_preview(self):
        mode = self.bg.currentData()
        self.cfg["bg"] = mode
        if not self.pieces or not self.path:
            return
        self.sheet.show_sheet(self.im, self.boxes, mode)
        old = {self.out.item(i).data(ROLE): self.out.item(i) for i in range(self.out.count())}
        same = len(old) == len(self.pieces)            # сменили только подложку - отметки и имена не трогаем
        states = {i: (it.checkState(), it.text()) for i, it in old.items()} if same else {}
        self.out.blockSignals(True)
        self.out.clear()
        names = default_names(self.path, len(self.pieces), self.names.text())
        for i, (im, name) in enumerate(zip(self.pieces, names)):
            pm = tile(im.copy(), 112, mode)
            if i in self.dupe:
                pm = badge(pm, "уже есть")
            it = QListWidgetItem(QIcon(pm), name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            check = Qt.CheckState.Unchecked if i in self.dupe else Qt.CheckState.Checked
            if i in states:
                check, name = states[i]
                it.setText(name)
            it.setCheckState(check)
            it.setData(ROLE, i)
            if i in self.dupe:
                it.setToolTip("Похожая картинка уже есть:\n" + self.dupe[i])
            self.out.addItem(it)
        self.out.blockSignals(False)
        self.checks_changed()

    def rename_pieces(self):
        if not self.path:
            return
        names = default_names(self.path, self.out.count(), self.names.text())
        self.out.blockSignals(True)
        for i, name in enumerate(names):
            self.out.item(i).setText(name)
        self.out.blockSignals(False)

    # --- отметки
    def checked(self):
        return [self.out.item(i) for i in range(self.out.count())
                if self.out.item(i).checkState() == Qt.CheckState.Checked]

    def checks_changed(self, *_):
        self.sheet.on = [self.out.item(i).checkState() == Qt.CheckState.Checked for i in range(self.out.count())]
        self.sheet.update()
        if self.path and self.pieces:
            name = os.path.basename(self.path)
            self.info.setToolTip(name)
            name = name if len(name) <= 48 else name[:45] + "..."
            text = "Отмечено %d из %d" % (len(self.checked()), len(self.pieces))      # главное - в начале, хвост может не влезть
            if self.dupe:
                text += "   уже есть: %d" % len(self.dupe)
            self.info.setText(text + "   %dx%d   %s" % (self.im.width, self.im.height, name))
        self.update_save()

    def set_checks(self, items, on):
        self.out.blockSignals(True)
        for it in items:
            it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.out.blockSignals(False)
        self.checks_changed()

    def check_all(self, on):
        self.set_checks([self.out.item(i) for i in range(self.out.count())], on)

    def toggle_piece(self, i):
        it = self.out.item(i)
        if it:
            self.set_checks([it], it.checkState() != Qt.CheckState.Checked)
            self.out.scrollToItem(it)

    def toggle_selected(self):
        sel = self.out.selectedItems()
        if sel:
            self.set_checks(sel, any(it.checkState() != Qt.CheckState.Checked for it in sel))

    def update_save(self):
        d = self.dest_path()
        n = len(self.checked()) if self.pieces else 0
        if d and n:
            self.save_btn.setText("Сохранить %d шт. в «%s»" % (n, short(d)))
        else:
            self.save_btn.setText("Сохранить в раздел")
        self.save_btn.setEnabled(bool(self.path and n and d))

    # --- сохранение
    def dest_path(self):
        if self.route and not self.manual:
            return self.route["dest"]
        it = self.tree.currentItem()
        return it.data(0, ROLE) if it else None

    def dest(self):
        d = self.dest_path()
        if not d:
            QMessageBox.information(self, "Куда сохранить", "Выберите раздел справа.")
        return d

    def save_current(self):
        if not self.path or not self.pieces:
            return
        dest = self.dest()
        picked = self.checked()
        if not dest or not picked:
            return
        try:
            saved = store(self.path, self.opts(), [self.pieces[it.data(ROLE)] for it in picked],
                          [it.text() for it in picked], dest)
            steps = [("new", p) for p in saved]
            if self.keep.isChecked():
                steps.append(("move", self.path, archive(self.path)))
        except Exception as e:
            QMessageBox.warning(self, "Не сохранилось", str(e))
            return
        text = "Сохранено: %d шт. в «%s»" % (len(saved), os.path.relpath(dest, LIB))
        self.win.push(text, steps)
        self.finish(text, dest)

    def save_all(self):
        files = inbox_files()
        routes = {f: route(f) for f in files}
        plain = [f for f in files if not routes[f]]
        it = self.tree.currentItem()
        dest = it.data(0, ROLE) if it else None
        if not files or (plain and not dest):
            if plain and not dest:
                QMessageBox.information(self, "Куда сохранить", "Выберите раздел справа.")
            return
        text = "Листов: %d." % len(files)
        if len(plain) < len(files):
            text += "\nС меткой в имени: %d - уйдут по своим папкам." % (len(files) - len(plain))
        if plain:
            text += "\nБез метки: %d - с текущими настройками в «%s»." % (len(plain), os.path.relpath(dest, LIB))
        ask = QMessageBox.question(self, "Разобрать все входящие",
                                   text + "\nКуски, которые уже есть в библиотеке, будут пропущены. Продолжить?")
        if ask != QMessageBox.StandardButton.Yes:
            return
        total, skipped, bad, steps = 0, 0, [], []
        for n, path in enumerate(files):
            self.win.say("Режу %d из %d: %s" % (n + 1, len(files), os.path.basename(path)))
            QApplication.processEvents()
            r = routes[path]
            o, to = (r["o"], r["dest"]) if r else (self.opts(), dest)
            try:
                _im, pieces, _b = process(path, o)
                names = default_names(path, len(pieces))
                keep = [i for i, p in enumerate(pieces) if not self.win.sigs.find(p)]
                skipped += len(pieces) - len(keep)
                saved = store(path, o, [pieces[i] for i in keep], [names[i] for i in keep], to)
                total += len(saved)
                steps += [("new", p) for p in saved]
                if self.keep.isChecked():
                    steps.append(("move", path, archive(path)))
            except Exception as e:
                bad.append("%s: %s" % (os.path.basename(path), e))
        text = "Сохранено: %d шт. из %d листов" % (total, len(files) - len(bad))
        if skipped:
            text += ", пропущено повторов: %d" % skipped
        self.win.push(text, steps)
        self.finish(text, dest)
        if bad:
            QMessageBox.warning(self, "Не всё получилось", "\n".join(bad))

    def finish(self, text, dest=None):
        self.cfg["archive"] = self.keep.isChecked()
        self.cfg["preset"] = self.preset.currentIndex()
        if dest and not (self.route and not self.manual):
            self.cfg.setdefault("dest", {})[str(self.preset.currentIndex())] = dest
        self.path = None
        self.names.clear()
        self.reload()
        fill_tree(self.tree)
        self.changed.emit()
        self.win.say(text)


def new_folder(parent, tree):
    it = tree.currentItem()
    base = it.data(0, ROLE) if it and it.data(0, ROLE) not in (RECENT, FAV, HEAVY) else LIB
    name, ok = QInputDialog.getText(parent, "Новая папка", "Имя папки внутри «%s»:" % os.path.basename(base))
    name = clean_name(name)
    if ok and name:
        path = os.path.join(base, name)
        os.makedirs(path, exist_ok=True)
        fill_tree(tree)
        select_path(tree, path)


class DestDialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(360, 460)
        self.tree = make_tree()
        fill_tree(self.tree)
        self.tree.itemDoubleClicked.connect(lambda *_: self.accept())
        new = QPushButton(lib_icon("folder"), "Новая папка...")
        new.clicked.connect(lambda: new_folder(self, self.tree))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Перенести")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        for w in (self.tree, new, bb):
            lay.addWidget(w)

    def path(self):
        it = self.tree.currentItem()
        return it.data(0, ROLE) if it else None


# ---------------------------------------------------------------- вкладка "Библиотека"
class DupesDialog(QDialog):
    """Группы одинаковых картинок: отмеченные остаются, остальные уезжают в «_дубли» (Ctrl+Z вернёт)."""

    def __init__(self, win, groups):
        super().__init__(win)
        self.win, self.boxes = win, []
        self.setWindowTitle("Одинаковые картинки: групп %d" % len(groups))
        self.resize(900, 640)
        rows = QWidget()
        rv = QVBoxLayout(rows)
        for g in groups:
            g.sort(key=self.quality, reverse=True)       # первой - самая крупная и тяжёлая: её и оставить
            row = QFrame(objectName="drop")
            h = QHBoxLayout(row)
            for i, p in enumerate(g):
                cell = QVBoxLayout()
                pic = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
                pic.setPixmap(thumb(p, 120, "chk"))
                cell.addWidget(pic)
                info = QLabel("%s\n%s" % (os.path.relpath(p, LIB), self.info(p)), objectName="dim", wordWrap=True)
                info.setFixedWidth(170)
                cell.addWidget(info)
                box = QCheckBox("Оставить")
                box.setChecked(i == 0)
                cell.addWidget(box)
                self.boxes.append((p, box))
                h.addLayout(cell)
            h.addStretch(1)
            rv.addWidget(row)
        rv.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(rows)
        hint = QLabel("Отмеченные остаются. Неотмеченные уедут в «_дубли» с той же структурой папок; "
                      "не дубли - отметьте все в группе.", objectName="dim", wordWrap=True)
        go = QPushButton(lib_icon("trash-bin"), "Убрать неотмеченные в «_дубли»", objectName="primary")
        go.clicked.connect(self.apply)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        bottom.addWidget(close)
        bottom.addWidget(go)
        v = QVBoxLayout(self)
        v.addWidget(area, 1)
        v.addLayout(bottom)

    @staticmethod
    def quality(p):
        try:
            with Image.open(p) as im:
                return im.width * im.height, os.path.getsize(p)
        except Exception:
            return 0, 0

    @staticmethod
    def info(p):
        try:
            with Image.open(p) as im:
                return "%dx%d, %s" % (im.width, im.height, human(os.path.getsize(p)))
        except Exception:
            return human(os.path.getsize(p))

    def apply(self):
        steps = []
        for p, box in self.boxes:
            if not box.isChecked() and os.path.exists(p):
                dst = unique(os.path.join(LIB, "_дубли", os.path.relpath(p, LIB)))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(p, dst)
                steps.append(("move", p, dst))
        text = "В «_дубли» перенесено: %d" % len(steps)
        self.win.push(text, steps)
        self.win.lib.refresh()
        self.win.library_changed()
        self.win.say(text + ("  (Ctrl+Z - вернуть)" if steps else ""))
        self.accept()


class LibList(QListWidget):
    """Плитки библиотеки: Ctrl+колесо меняет размер, перетаскивание отдаёт файлы другим программам."""
    zoom = pyqtSignal(int)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom.emit(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(it.data(ROLE)) for it in items])
        return md

    def startDrag(self, _actions):
        super().startDrag(Qt.DropAction.CopyAction)     # только копия: проводник не должен уносить файл из библиотеки


class Preview(QWidget):
    """Правая панель: крупный просмотр выбранной картинки и действия с ней."""

    def __init__(self, tab):
        super().__init__()
        self.tab, self.src = tab, None
        self.pic = QLabel(objectName="pic", alignment=Qt.AlignmentFlag.AlignCenter)
        self.pic.setMinimumSize(200, 200)
        self.pic.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.name = QLabel(objectName="big", wordWrap=True)
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta = QLabel(objectName="dim", wordWrap=True)
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        g = QGridLayout()
        self.btns = []
        for i, (text, icon, fn, tip) in enumerate((
                ("Открыть", "image-file", tab.open_file, "Двойной щелчок по плитке"),
                ("В проводнике", "folder", tab.reveal, ""),
                ("Копировать картинку", "camera", tab.copy_image, "Ctrl+Shift+C - вставляется в любой редактор"),
                ("Копировать путь", "clipboard", tab.copy_path, "Ctrl+C"),
                ("В избранное", "star", tab.toggle_fav, "Ctrl+D"),
                ("Найти похожие", "magnifying-glass", tab.find_similar, "По рисунку и пропорциям"),
                ("Выгрузить в папку...", "upload-arrow", tab.export, "Ctrl+E - копии нужного формата и размера"),
                ("Просмотр", "eye", tab.look, "Пробел - на всё окно, стрелки листают"))):
            b = QPushButton(lib_icon(icon), text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
            self.btns.append(b)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.pic, 1)
        v.addWidget(self.name)
        v.addWidget(self.meta)
        v.addLayout(g)
        self.show_paths([], "chk")

    def show_paths(self, paths, mode):
        for b in self.btns:
            b.setEnabled(bool(paths))
        self.btns[0].setEnabled(len(paths) == 1)
        self.btns[5].setEnabled(len(paths) == 1)
        fav = self.tab.cfg.get("fav", [])
        self.btns[4].setText("Убрать из избранного" if paths and os.path.relpath(paths[0], LIB) in fav
                             else "В избранное")
        if not paths:
            self.src = None
            self.pic.setPixmap(QPixmap())
            self.pic.setText("Выберите картинку")
            self.name.setText("")
            self.meta.setText("")
            return
        if len(paths) > 1:
            self.src = thumb(paths[0], 512, mode)
            self.name.setText("Выбрано: %d" % len(paths))
            self.meta.setText("Вместе: " + human(sum(os.path.getsize(p) for p in paths if os.path.exists(p))))
            self.fit()
            return
        p = paths[0]
        self.src = thumb(p, 512, mode)
        self.name.setText(os.path.basename(p))
        meta = [os.path.dirname(os.path.relpath(p, LIB)).replace(os.sep, " / ")]
        try:
            st = os.stat(p)
            line = os.path.splitext(p)[1][1:].lower() + "   " + human(st.st_size)
            if not p.lower().endswith(".svg"):
                with Image.open(p) as im:
                    line = "%dx%d   " % im.size + line
            meta += [line, "изменён " + time.strftime("%d.%m.%Y %H:%M", time.localtime(st.st_mtime))]
        except Exception:
            pass
        self.meta.setText("\n".join(meta))
        self.fit()

    def fit(self):
        if self.src and not self.src.isNull():
            s = min(self.pic.width(), self.pic.height()) - 16
            self.pic.setPixmap(self.src.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()


class Look(QDialog):
    """Быстрый просмотр на всё окно: стрелки - соседние картинки, Пробел/Esc - закрыть, B - подложка."""

    def __init__(self, tab, row):
        super().__init__(tab)
        self.tab, self.row, self.src = tab, row, None
        self.mode = tab.cfg.get("bg", "chk")
        self.setWindowTitle("Просмотр")
        self.setStyleSheet("QDialog{background:#0d0d12}")
        self.pic = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.pic.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.pic.setStyleSheet("background:transparent")
        self.cap = QLabel(objectName="dim", alignment=Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Стрелки - листать   B - подложка   Пробел или Esc - закрыть", objectName="dim",
                      alignment=Qt.AlignmentFlag.AlignCenter)
        v = QVBoxLayout(self)
        v.addWidget(self.pic, 1)
        v.addWidget(self.cap)
        v.addWidget(hint)
        self.setGeometry(tab.window().geometry().adjusted(30, 30, -30, -30))
        self.show_row()

    def show_row(self):
        n = self.tab.list.count()
        if not n:
            return
        self.row %= n
        it = self.tab.list.item(self.row)
        self.tab.list.setCurrentItem(it)
        p = it.data(ROLE)
        try:
            if p.lower().endswith(".svg"):
                self.src = QIcon(p).pixmap(1024, 1024)
            else:
                im = K.load(p)
                im.thumbnail((2400, 2400), Image.LANCZOS)
                back = backdrop(im.width, im.height, self.mode)
                back.alpha_composite(im)
                self.src = to_pix(back)
        except Exception:
            self.src = QPixmap()
        self.cap.setText("%s   (%d из %d)" % (os.path.relpath(p, LIB), self.row + 1, n))
        self.fit()

    def fit(self):
        if self.src and not self.src.isNull():
            self.pic.setPixmap(self.src.scaled(self.pic.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            self.row += 1
            self.show_row()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.row -= 1
            self.show_row()
        elif k == Qt.Key.Key_B:
            self.mode = {"chk": "light", "light": "dark"}.get(self.mode, "chk")
            self.show_row()
        elif k in (Qt.Key.Key_Space, Qt.Key.Key_Escape, Qt.Key.Key_Return):
            self.accept()
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, _e):
        self.accept()


class Compare(QWidget):
    """До/после со шторкой, как в Squoosh: тянуть мышью - граница, колесо - масштаб,
    правая кнопка - двигать, двойной щелчок - снова целиком."""

    def __init__(self):
        super().__init__()
        self.a = self.b = None
        self.split, self.zoom, self.off, self.pan = 0.5, 0.0, QPointF(0, 0), None
        self.setMinimumSize(380, 300)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        chk = QPixmap(16, 16)
        chk.fill(QColor("#1f1f29"))
        p = QPainter(chk)
        p.fillRect(0, 0, 8, 8, QColor("#2a2a36"))
        p.fillRect(8, 8, 8, 8, QColor("#2a2a36"))
        p.end()
        self.chk = chk

    def set_images(self, a, b):
        same = self.a is not None and a is not None and self.a.size() == a.size()
        self.a, self.b = a, b
        if not same:
            self.zoom, self.off = 0.0, QPointF(0, 0)
        self.update()

    def scale(self):
        if self.zoom:
            return self.zoom
        if not self.a:
            return 1.0
        return min(self.width() / self.a.width(), self.height() / self.a.height(), 8.0)

    def frame(self):
        k = self.scale()
        w, h = self.a.width() * k, self.a.height() * k
        return QRectF(
            (self.width() - w) / 2 + self.off.x(),
            (self.height() - h) / 2 + self.off.y(),
            w,
            h,
        )

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111117"))
        if not self.a:
            p.setPen(QColor("#9a98a8"))
            p.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Готовлю предпросмотр..."
            )
            return
        r = self.frame()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.scale() < 2)
        p.fillRect(r, QBrush(self.chk))
        x = self.width() * self.split
        if self.b:
            p.drawPixmap(r, self.b, QRectF(self.b.rect()))
        p.save()
        p.setClipRect(QRectF(0, 0, x, self.height()))
        p.drawPixmap(r, self.a, QRectF(self.a.rect()))
        p.restore()
        p.setPen(QPen(QColor("#9d8cff"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        p.setBrush(QColor("#9d8cff"))
        p.drawEllipse(QPointF(x, self.height() / 2), 7, 7)
        for text, left in (("Было", True), ("Стало", False)):
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(text) + 14
            box = QRectF(x - w - 8 if left else x + 8, 8, w, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(21, 21, 28, 210))
            p.drawRoundedRect(box, 5, 5)
            p.setPen(QColor("#e8e6f0"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def mousePressEvent(self, e):
        if (
            e.button() == Qt.MouseButton.RightButton
            or e.button() == Qt.MouseButton.MiddleButton
        ):
            self.pan = (e.position(), QPointF(self.off))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):
        if self.pan:
            self.off = self.pan[1] + (e.position() - self.pan[0])
        elif e.buttons() & Qt.MouseButton.LeftButton:
            self.split = max(0.0, min(1.0, e.position().x() / max(1, self.width())))
        self.update()

    def mouseReleaseEvent(self, _e):
        self.pan = None
        self.setCursor(Qt.CursorShape.SplitHCursor)

    def mouseDoubleClickEvent(self, _e):
        self.zoom, self.off = 0.0, QPointF(0, 0)
        self.update()

    def wheelEvent(self, e):
        if not self.a:
            return
        old = self.scale()
        new = max(0.05, min(16.0, old * (1.25 if e.angleDelta().y() > 0 else 0.8)))
        c = e.position() - QPointF(self.width() / 2, self.height() / 2)
        self.off = c - (c - self.off) * (
            new / old
        )  # точка под курсором остаётся на месте
        self.zoom = new
        self.update()


# формат, подпись
FORMATS = [
    ("", "Как у файла"),
    ("webp", "webp"),
    ("avif", "avif (самый лёгкий)"),
    ("png", "png"),
    ("jpg", "jpg"),
    ("clean", "Только почистить (без потерь)"),
]
CAN = ("webp", "avif", "png", "jpg")  # во что умеем пережимать


def compress_files(paths, o, report):
    """В фоне: сжать файлы по настройкам. Оригиналы уезжают в _исходники/сжатие <дата>, так что
    Ctrl+Z всё возвращает. report((i, n, имя)) - ход работы. Возвращает (шаги для отмены, итоги)."""
    arch = os.path.join(SOURCES, "сжатие " + time.strftime("%Y-%m-%d"))
    steps, done, skipped, before, after = [], 0, {}, 0, 0
    for i, p in enumerate(paths):
        if o.get("stop", [False])[0]:
            break
        report((i, len(paths), os.path.basename(p)))
        src_fmt = K.fmt_of(p)
        fmt = src_fmt if o["fmt"] in ("", "clean") else o["fmt"]
        if src_fmt == "svg" or fmt not in CAN and o["fmt"] != "clean":
            skipped["не поддерживается"] = skipped.get("не поддерживается", 0) + 1
            continue
        try:
            was = os.path.getsize(p)
            if o["fmt"] == "clean":
                data = K.clean(p)
            else:
                data, _q = K.compress(K.load(p), dict(o, fmt=fmt))
            if data is None or (o.get("smaller", True) and len(data) >= was):
                skipped["не стало меньше"] = skipped.get("не стало меньше", 0) + 1
                continue
            new = os.path.splitext(p)[0] + "." + fmt
            keep = unique(os.path.join(arch, os.path.relpath(p, LIB)))
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            shutil.move(p, keep)
            steps.append(("move", p, keep))
            if os.path.exists(new):
                new = unique(new)
            with open(new, "wb") as fh:
                fh.write(data)
            steps.append(("new", new))
            done += 1
            before += was
            after += len(data)
        except Exception as e:
            skipped["ошибка: %s" % e] = skipped.get("ошибка: %s" % e, 0) + 1
    return steps, dict(
        done=done, before=before, after=after, skipped=skipped, total=len(paths)
    )


def report_text(r):
    text = "Сжато: %d из %d" % (r["done"], r["total"])
    if r["done"]:
        text += "\nБыло %s, стало %s (-%d%%)" % (
            human(r["before"]),
            human(r["after"]),
            round(100 * (1 - r["after"] / max(1, r["before"]))),
        )
    for why, n in r["skipped"].items():
        text += "\nПропущено (%s): %d" % (why, n)
    return text


class CompressDialog(QDialog):
    """Сжать и конвертировать: настройки слева, справа шторка до/после и размер было/стало."""

    def __init__(self, tab, paths):
        super().__init__(tab)
        self.tab, self.win, self.paths = (
            tab,
            tab.win,
            [p for p in paths if not p.lower().endswith(".svg")],
        )
        self.o = dict(
            fmt="", q=0, target=0.99, lossless=False, size=0, fit="fit", smaller=True
        )
        self.o.update(tab.cfg.get("comp", {}))
        self.cache, self.gen, self.stop = {}, 0, [False]
        self.setWindowTitle("Сжать и конвертировать: %d шт." % len(self.paths))
        self.resize(1100, 680)

        self.fmt = QComboBox()
        for v, t in FORMATS:
            self.fmt.addItem(t, v)
        self.how = QComboBox()
        for v, t in K.TARGETS:
            self.how.addItem("Подобрать: " + t.lower(), v)
        self.how.addItem("Задать вручную", 0)
        self.q = QSpinBox(minimum=1, maximum=100, value=82, suffix=" %")
        self.q.setToolTip(
            "Качество: меньше - легче файл. Для png - сколько цветов оставить (100 - без потерь)"
        )
        self.lossless = QCheckBox("Без потерь")
        self.lossless.setToolTip(
            "webp и png: картинка не меняется ни на пиксель, файл обычно тяжелее"
        )
        self.size = QSpinBox(
            minimum=0,
            maximum=8192,
            singleStep=64,
            suffix=" px",
            specialValueText="не менять",
        )
        self.fit = QComboBox()
        for v, t in K.FITS:
            self.fit.addItem(t, v)
        self.smaller = QCheckBox("Не трогать файл, если новый не легче")
        self.files = QComboBox()
        for p in self.paths:
            self.files.addItem(os.path.relpath(p, LIB), p)
        self.files.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.files.setMinimumContentsLength(20)
        for c in (self.fmt, self.how, self.fit):
            c.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            c.setMinimumContentsLength(16)

        form = QFormLayout()
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form.addRow("Формат", self.fmt)
        form.addRow("Качество", self.how)
        qrow = QHBoxLayout()
        qrow.addWidget(self.q, 1)
        qrow.addWidget(self.lossless)
        form.addRow("", qrow)
        form.addRow("Размер", self.size)
        form.addRow("Как", self.fit)
        form.addRow("", self.smaller)
        box = QGroupBox("Настройки")
        box.setLayout(form)
        note = QLabel(
            "Подбор качества сам ищет самое низкое качество, при котором на глаз разницы нет.\n\n"
            "Оригиналы уезжают в «_исходники/сжатие <дата>», Ctrl+Z в окне возвращает всё как было.",
            objectName="dim",
            wordWrap=True,
        )
        self.result = QLabel(objectName="big", wordWrap=True)
        self.detail = QLabel(objectName="dim", wordWrap=True)
        self.prog = QLabel(objectName="dim", wordWrap=True)
        self.go = QPushButton(lib_icon("zip-archive"), "", objectName="primary")
        self.go.clicked.connect(self.run)
        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.clicked.connect(lambda: self.stop.__setitem__(0, True))
        self.stop_btn.hide()
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        left = QVBoxLayout()
        left.addWidget(box)
        left.addWidget(note)
        left.addStretch(1)
        left.addWidget(self.result)
        left.addWidget(self.detail)
        left.addWidget(self.prog)
        left.addWidget(self.go)
        row = QHBoxLayout()
        row.addWidget(self.stop_btn)
        row.addStretch(1)
        row.addWidget(close)
        left.addLayout(row)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(360)

        self.cmp = Compare()
        prev, nxt = (
            flat("<", lambda: self.step(-1), "Предыдущий файл"),
            flat(">", lambda: self.step(1), "Следующий файл"),
        )
        top = QHBoxLayout()
        top.addWidget(prev)
        top.addWidget(self.files, 1)
        top.addWidget(nxt)
        hint = QLabel(
            "Тяните мышью - шторка, колесо - увеличить, правая кнопка - двигать, двойной щелчок - целиком",
            objectName="dim",
        )
        right = QVBoxLayout()
        right.addLayout(top)
        right.addWidget(self.cmp, 1)
        right.addWidget(hint)
        lay = QHBoxLayout(self)
        lay.addWidget(lw)
        lay.addLayout(right, 1)

        self.fmt.setCurrentIndex(max(0, self.fmt.findData(self.o["fmt"])))
        q = self.o["q"]
        self.how.setCurrentIndex(
            self.how.findData(0) if q else max(0, self.how.findData(self.o["target"]))
        )
        if q:
            self.q.setValue(q)
        self.lossless.setChecked(self.o["lossless"])
        self.size.setValue(self.o["size"])
        self.fit.setCurrentIndex(max(0, self.fit.findData(self.o["fit"])))
        self.smaller.setChecked(self.o["smaller"])
        self.timer = QTimer(self, singleShot=True, interval=300)
        self.timer.timeout.connect(self.preview)
        for c in (self.fmt, self.how, self.fit, self.files):
            c.currentIndexChanged.connect(self.changed)
        for c in (self.q, self.size):
            c.valueChanged.connect(self.changed)
        for c in (self.lossless, self.smaller):
            c.toggled.connect(self.changed)
        self.changed()

    def step(self, d):
        if self.files.count():
            self.files.setCurrentIndex(
                (self.files.currentIndex() + d) % self.files.count()
            )

    def opts(self):
        target = self.how.currentData()
        return dict(
            fmt=self.fmt.currentData(),
            q=0 if target else self.q.value(),
            target=target or 0.99,
            lossless=self.lossless.isChecked(),
            size=self.size.value(),
            fit=self.fit.currentData(),
            smaller=self.smaller.isChecked(),
        )

    def changed(self, *_):
        o = self.opts()
        clean = o["fmt"] == "clean"
        self.how.setEnabled(not clean and not o["lossless"])
        self.q.setEnabled(not clean and not o["lossless"] and not o["q"] == 0)
        self.lossless.setEnabled(not clean and o["fmt"] in ("", "webp", "png"))
        for w in (self.size, self.fit):
            w.setEnabled(not clean)
        self.go.setText(
            "Сжать %d шт." % len(self.paths) if len(self.paths) > 1 else "Сжать"
        )
        self.go.setEnabled(bool(self.paths))
        self.timer.start()

    def preview(self):
        p = self.files.currentData()
        if not p:
            return
        self.gen += 1
        gen, o = self.gen, self.opts()
        self.result.setText("Считаю...")
        self.detail.setText("")
        cache = self.cache

        def work():
            if p not in cache:
                cache.clear()  # держим в памяти только текущий оригинал
                cache[p] = K.load(p)
            src = cache[p]
            fmt = K.fmt_of(p) if o["fmt"] in ("", "clean") else o["fmt"]
            if o["fmt"] == "clean":
                data, q = K.clean(p), None
                out = src if data else None
            else:
                if fmt not in CAN:
                    return gen, src, None, None, None, fmt
                data, q = K.compress(src, dict(o, fmt=fmt))
                out = Image.open(io.BytesIO(data))
                out.load()
            return gen, src, out, data, q, fmt

        bg(work, self.shown)

    def shown(self, res):
        if isinstance(res, Exception):
            self.result.setText("Не получилось: %s" % res)
            return
        gen, src, out, data, q, fmt = res
        if gen != self.gen:
            return
        p = self.files.currentData()
        was = os.path.getsize(p)
        self.cmp.set_images(to_pix(src), to_pix(out) if out is not None else None)
        if data is None:
            self.result.setText(
                "Этот файл так не сжать"
                if fmt not in CAN
                else "Почистить нечего: файл уже минимальный"
            )
            self.detail.setText("")
            return
        now = len(data)
        sign = (
            "-%d%%" % round(100 * (1 - now / was))
            if now < was
            else "+%d%%" % round(100 * (now / was - 1))
        )
        self.result.setText("%s  ->  %s   (%s)" % (human(was), human(now), sign))
        info = [fmt]
        if q and not self.opts()["lossless"]:
            info.append("качество %d" % q)
        info.append("%dx%d" % out.size)
        if now >= was and self.smaller.isChecked():
            info.append("файл не станет легче - его не тронем")
        self.detail.setText("   ".join(info))

    def run(self):
        o = self.opts()
        self.tab.cfg["comp"] = {k: v for k, v in o.items()}
        o["stop"] = self.stop
        self.stop[0] = False
        self.go.setEnabled(False)
        self.stop_btn.show()

        def progress(v):
            i, n, name = v
            self.prog.setText("%d из %d: %s" % (i + 1, n, name))

        paths = list(self.paths)
        bg(
            lambda: compress_files(paths, o, lambda v: RELAY.done.emit(progress, v)),
            self.finished_batch,
        )

    def finished_batch(self, res):
        self.stop_btn.hide()
        self.go.setEnabled(True)
        self.prog.setText("")
        if isinstance(res, Exception):
            QMessageBox.warning(self, "Не получилось", str(res))
            return
        steps, r = res
        text = report_text(r)
        for st in steps:
            if st[0] == "move":
                src, keep = st[1], st[2]
            else:
                if os.path.splitext(st[1])[0] == os.path.splitext(src)[0]:
                    self.win.moved(src, st[1])  # избранное - за новым файлом
        if steps:
            self.win.push("Сжатие: %d шт." % r["done"], steps)
        self.win.say(text.replace("\n", "   "))
        self.tab.done(text.split("\n")[0])
        QMessageBox.information(
            self,
            "Готово",
            text + ("\n\nВернуть всё как было - Ctrl+Z в окне." if steps else ""),
        )
        self.accept()


# заготовки выгрузки: имя, настройки (fmt "" - как есть, "iconset" - набор значков, q 0 - подобрать на глаз)
EXPORT_PRESETS = [
    ("Своя настройка", None),
    ("Фон для VS Code (webp, 1920)", dict(fmt="webp", q=0, size=1920, fit="fit")),
    ("Для README (webp, 1280)", dict(fmt="webp", q=0, size=1280, fit="fit")),
    ("Для сайта (avif, 1600)", dict(fmt="avif", q=0, size=1600, fit="fit")),
    (
        "Для телеграма (png 512, квадрат)",
        dict(fmt="png", q=100, size=512, fit="square"),
    ),
    (
        "Аватар (png 256, обрезать в квадрат)",
        dict(fmt="png", q=100, size=256, fit="fill"),
    ),
    (
        "Значок программы (ico + png 256 + favicon)",
        dict(fmt="iconset", q=100, size=0, fit="square"),
    ),
]


class ExportDialog(QDialog):
    """Выгрузка выбранных картинок в папку проекта: заготовки, формат, качество, размер."""

    def __init__(self, parent, n, cfg):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Выгрузить в папку: %d шт." % n)
        self.dir = QLineEdit(
            cfg.get("export_dir", ""), placeholderText="папка, куда положить копии"
        )
        pick = QPushButton(lib_icon("folder"), "")
        pick.clicked.connect(self.pick)
        row = QHBoxLayout()
        row.addWidget(self.dir, 1)
        row.addWidget(pick)
        self.preset = QComboBox()
        self.fill_presets()
        self.fmt = QComboBox()
        for t, v in (
            ("Как есть (без пережатия)", ""),
            ("webp", "webp"),
            ("avif", "avif"),
            ("png", "png"),
            ("jpg", "jpg"),
            ("ico", "ico"),
            ("Набор значков (ico + png + favicon)", "iconset"),
        ):
            self.fmt.addItem(t, v)
        self.q = QSpinBox(
            minimum=0, maximum=100, suffix=" %", specialValueText="подобрать на глаз"
        )
        self.q.setToolTip(
            "0 - окно само подберёт качество без видимой разницы; 100 - без потерь"
        )
        self.size = QSpinBox(
            minimum=0,
            maximum=8192,
            singleStep=64,
            suffix=" px",
            specialValueText="не менять",
        )
        self.size.setToolTip(
            "Длинная сторона; меньшие картинки не увеличиваются (кроме квадрата и обрезки)"
        )
        self.fit = QComboBox()
        for v, t in K.FITS:
            self.fit.addItem(t, v)
        self.open_after = QCheckBox("Открыть папку после выгрузки")
        self.open_after.setChecked(cfg.get("export_open", True))
        save_p = flat("Сохранить как заготовку...", self.save_preset)
        form = QFormLayout()
        form.addRow("Заготовка", self.preset)
        form.addRow("Папка", row)
        form.addRow("Формат", self.fmt)
        form.addRow("Качество", self.q)
        form.addRow("Размер", self.size)
        form.addRow("Как", self.fit)
        form.addRow("", self.open_after)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Выгрузить")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(save_p)
        bottom.addStretch(1)
        bottom.addWidget(bb)
        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addLayout(bottom)
        self.resize(520, 0)
        last = cfg.get("export", dict(fmt="", q=0, size=0, fit="fit"))
        self.set_opts(last)
        self.preset.setCurrentIndex(
            max(0, self.preset.findText(cfg.get("export_preset", "")))
        )
        self.preset.currentIndexChanged.connect(self.apply_preset)

    def presets(self):
        return EXPORT_PRESETS + [
            (k, v) for k, v in self.cfg.get("export_presets", {}).items()
        ]

    def fill_presets(self):
        self.preset.clear()
        for name, _o in self.presets():
            self.preset.addItem(name)

    def set_opts(self, o):
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(o.get("fmt", ""))))
        self.q.setValue(o.get("q", 0))
        self.size.setValue(o.get("size", 0))
        self.fit.setCurrentIndex(max(0, self.fit.findData(o.get("fit", "fit"))))

    def opts(self):
        return dict(
            fmt=self.fmt.currentData(),
            q=self.q.value(),
            size=self.size.value(),
            fit=self.fit.currentData(),
        )

    def apply_preset(self):
        o = dict(self.presets())[self.preset.currentText()]
        if o:
            self.set_opts(o)

    def save_preset(self):
        name, ok = QInputDialog.getText(
            self, "Заготовка выгрузки", "Название, например «Для игры (png 128)»:"
        )
        name = name.strip()
        if ok and name:
            self.cfg.setdefault("export_presets", {})[name] = self.opts()
            self.fill_presets()
            self.preset.setCurrentText(name)

    def pick(self):
        d = QFileDialog.getExistingDirectory(self, "Куда выгрузить", self.dir.text())
        if d:
            self.dir.setText(os.path.normpath(d))

    def accept(self):
        if not self.dir.text().strip():
            self.pick()
            if not self.dir.text().strip():
                return
        self.cfg.update(
            export_dir=self.dir.text().strip(),
            export=self.opts(),
            export_preset=self.preset.currentText(),
            export_open=self.open_after.isChecked(),
        )
        super().accept()


def export(paths, folder, o, report=None):
    """Копии картинок в folder по настройкам o (fmt, q, size, fit). Как есть и без размера - простое копирование."""
    os.makedirs(folder, exist_ok=True)
    n = 0
    for i, p in enumerate(paths):
        if report:
            report((i, len(paths), os.path.basename(p)))
        stem, ext = os.path.splitext(os.path.basename(p))
        fmt = o.get("fmt", "")
        if p.lower().endswith(".svg") or (
            not fmt and not o.get("size") and o.get("fit", "fit") == "fit"
        ):
            shutil.copy2(p, unique(os.path.join(folder, stem + ext)))
        elif fmt == "iconset":
            K.icon_set(K.load(p), folder, stem)
        else:
            f = fmt or K.fmt_of(p)
            if f not in CAN + ("ico",):
                f = "png"
            q = o.get("q", 0)
            data, _q = K.compress(
                K.load(p),
                dict(
                    fmt=f,
                    q=q,
                    lossless=q >= 100,
                    size=o.get("size", 0),
                    fit=o.get("fit", "fit"),
                ),
            )
            with open(unique(os.path.join(folder, stem + "." + f)), "wb") as fh:
                fh.write(data)
        n += 1
    return n


class LibTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.side = max(64, min(THUMB, self.cfg.get("thumb", 128)))
        self.like = None                    # "Похожие на ...": путь картинки-образца
        self.tree = make_tree()
        self.tree.currentItemChanged.connect(lambda *_: self.leave_similar())
        self.q = QLineEdit(placeholderText="Поиск по всей библиотеке (Ctrl+F)...")
        self.q.setClearButtonEnabled(True)
        self.q.addAction(lib_icon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self.qt = QTimer(self, singleShot=True, interval=180)        # не перерисовывать на каждую букву
        self.qt.timeout.connect(self.show_files)
        self.q.textChanged.connect(lambda *_: self.qt.start())
        self.color = QComboBox()
        self.color.addItem(lib_icon("color-palette"), "Любой цвет", "")
        for code, name, hexv in K.COLORS:
            self.color.addItem(swatch(hexv), name, code)
        self.color.setToolTip("Показать только картинки, где заметен этот цвет")
        self.color.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.color.currentIndexChanged.connect(self.show_files)
        self.sort = QComboBox()
        for t, v in (("По имени", "name"), ("Сначала новые", "new"), ("Сначала тяжёлые", "size")):
            self.sort.addItem(t, v)
        self.sort.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.sort.setCurrentIndex(max(0, self.sort.findData(self.cfg.get("sort", "name"))))
        self.sort.currentIndexChanged.connect(self.show_files)
        self.slider = QSlider(Qt.Orientation.Horizontal, minimum=64, maximum=THUMB, singleStep=16, pageStep=32)
        self.slider.setFixedWidth(80)
        self.slider.setValue(self.side)
        self.slider.setToolTip("Размер плиток (Ctrl+колесо)")
        self.slider.valueChanged.connect(self.resize_tiles)
        self.list = icon_list(self.side, LibList)
        self.list.zoom.connect(lambda d: self.slider.setValue(self.side + 16 * d))
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.menu)
        self.list.itemDoubleClicked.connect(lambda it: os.startfile(it.data(ROLE)))
        self.list.itemSelectionChanged.connect(self.describe)
        self.info = QLabel("", objectName="dim")
        bar = QHBoxLayout()
        self.q.setMinimumWidth(170)
        bar.addWidget(self.q, 1)
        bar.addWidget(self.color)
        bar.addWidget(self.sort)
        bar.addWidget(self.slider)
        for text, icon, fn, tip in (("Сжать и конвертировать", "zip-archive", self.compress, "Ctrl+K"),
                                    ("Переименовать", "quill-pen", self.rename, "F2"),
                                    ("Перенести...", "folder", self.move, "В другой раздел"),
                                    ("В корзину", "trash-bin", self.trash, "Del")):
            b = QPushButton(lib_icon(icon), "")
            b.setToolTip("%s (%s)" % (text, tip))
            b.clicked.connect(fn)
            bar.addWidget(b)
        mid = QWidget()
        rv = QVBoxLayout(mid)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(bar)
        rv.addWidget(self.list, 1)
        rv.addWidget(self.info)
        self.preview = Preview(self)
        self.split = QSplitter()
        for w in (self.tree, mid, self.preview):
            self.split.addWidget(w)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes(self.cfg.get("split_lib", [250, 720, 300]))
        lay = QVBoxLayout(self)
        lay.addWidget(self.split)
        key("F2", self.list, self.rename)
        key("Delete", self.list, self.trash)
        key("Ctrl+C", self.list, self.copy_path)
        key("Ctrl+Shift+C", self.list, self.copy_image)
        key("Return", self.list, self.open_file)
        key("Ctrl+F", self, lambda: (self.q.setFocus(), self.q.selectAll()))
        key("Space", self.list, self.look)
        key("Ctrl+D", self.list, self.toggle_fav)
        key("Ctrl+E", self.list, self.export)
        key("Ctrl+K", self.list, self.compress)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.refresh()

    def refresh(self):
        fill_tree(self.tree, planned=False, recent=True)
        if not self.tree.currentItem() and self.tree.topLevelItemCount() > 3:
            self.tree.setCurrentItem(self.tree.topLevelItem(3))

    def show_section(self, role):
        self.q.clear()
        self.color.setCurrentIndex(0)
        select_path(self.tree, role)

    def all_shown(self):
        return [self.list.item(i).data(ROLE) for i in range(self.list.count())]

    def tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it:
            return
        self.tree.setCurrentItem(it)
        files = self.all_shown()
        if not files:
            return
        m = QMenu(self)
        m.addAction("Сжать весь раздел (%d)..." % len(files), lambda: self.compress(files))
        m.addAction("Выгрузить раздел в папку...", lambda: self.export(files))
        m.addAction("Лист превью раздела...", lambda: self.preview_sheet(files))
        m.exec(self.tree.mapToGlobal(pos))
        self.show_files()

    def resize_tiles(self, v):
        self.side = v
        self.cfg["thumb"] = v
        set_side(self.list, v)

    def show_files(self):
        words = self.q.text().strip().lower().replace("ё", "е").split()
        it = self.tree.currentItem()
        root = LIB if words else (it.data(0, ROLE) if it else None)
        keep = set(self.paths())
        self.list.clear()
        fav = set(self.cfg.get("fav", []))
        if self.like:
            root = RECENT                   # порядок задаёт похожесть, сортировку не применяем
            files = self.win.sigs.similar(self.like)
        elif root == RECENT:
            files = sorted(K.images_in(LIB), key=os.path.getmtime, reverse=True)[:120]
        elif root == HEAVY:
            files = sorted((f for f in K.images_in(LIB) if os.path.getsize(f) > HEAVY_KB * 1024),
                           key=os.path.getsize, reverse=True)
        elif root == FAV:
            files = [os.path.join(LIB, r) for r in sorted(fav) if os.path.exists(os.path.join(LIB, r))]
        elif root and os.path.isdir(root):
            files = K.images_in(root)
        else:
            files = []
        if words:
            files = [p for p in files
                     if all(w in os.path.relpath(p, LIB).lower().replace("ё", "е") for w in words)]
        code = self.color.currentData()
        if code:
            files = [p for p in files if self.win.sigs.has_color(p, code)]
        how = self.sort.currentData()
        self.cfg["sort"] = how
        if how == "new" and root not in (RECENT, HEAVY):
            files.sort(key=os.path.getmtime, reverse=True)
        elif how == "size":
            files.sort(key=os.path.getsize, reverse=True)
        mode = self.cfg.get("bg", "chk")
        todo = []
        self.list.setUpdatesEnabled(False)
        for i, p in enumerate(files):
            rel = os.path.relpath(p, LIB)
            key = thumb_key(p, THUMB, mode)
            if key in _thumbs or p.lower().endswith(".svg"):
                pm = thumb(p, THUMB, mode)
                icon = QIcon(with_star(pm) if rel in fav else pm)
            else:
                icon = QIcon()
                todo.append((i, p, rel in fav))
            item = QListWidgetItem(icon, os.path.basename(p))
            item.setData(ROLE, p)
            item.setToolTip(rel)
            self.list.addItem(item)
            if p in keep:
                item.setSelected(True)
        self.list.setUpdatesEnabled(True)
        self.load_tiles(todo, mode)
        self.describe()

    def load_tiles(self, todo, mode):
        """Плитки, которых нет в памяти, дорисовываются в фоне порциями - окно не замирает."""
        self.tgen = getattr(self, "tgen", 0) + 1
        gen = self.tgen

        def step():
            if gen != self.tgen or not todo:
                return
            chunk = todo[:48]
            del todo[:48]

            def work():
                out = []
                for i, p, star in chunk:
                    try:
                        out.append((i, p, star, tile_image(p, THUMB, mode)))
                    except Exception:
                        out.append((i, p, star, None))
                return out

            def done(res):
                if gen != self.tgen or isinstance(res, Exception):
                    return
                for i, p, star, img in res:
                    it = self.list.item(i)
                    if img is None or not it or it.data(ROLE) != p:
                        continue
                    key = thumb_key(p, THUMB, mode)
                    pm = remember(key, QPixmap.fromImage(img)) if key else QPixmap.fromImage(img)
                    it.setIcon(QIcon(with_star(pm) if star else pm))
                step()

            bg(work, done)

        step()

    def paths(self):
        return [i.data(ROLE) for i in self.list.selectedItems()]

    def describe(self):
        sel = self.paths()
        self.preview.show_paths(sel, self.cfg.get("bg", "chk"))
        if self.like and not sel:
            self.info.setText("Похожие на «%s» - щёлкните раздел слева, чтобы вернуться" % os.path.basename(self.like))
        elif sel:
            self.info.setText("Выбрано: %d из %d" % (len(sel), self.list.count()))
        else:
            self.info.setText("Картинок: %d   Перетащите плитку в другую программу, чтобы вставить туда файл"
                              % self.list.count())

    def menu(self, pos):
        if not self.paths():
            return
        m = QMenu(self)
        m.addAction("Открыть\tEnter", self.open_file)
        m.addAction("Быстрый просмотр\tПробел", self.look)
        m.addAction("Показать в проводнике", self.reveal)
        m.addSeparator()
        fav = os.path.relpath(self.paths()[0], LIB) in self.cfg.get("fav", [])
        m.addAction("Убрать из избранного\tCtrl+D" if fav else "В избранное\tCtrl+D", self.toggle_fav)
        m.addAction("Найти похожие", self.find_similar)
        m.addAction("Выгрузить в папку...\tCtrl+E", self.export)
        m.addSeparator()
        m.addAction("Переименовать\tF2", self.rename)
        m.addAction("Перенести в раздел...", self.move)
        m.addAction("Копировать путь\tCtrl+C", self.copy_path)
        m.addAction("Копировать картинку\tCtrl+Shift+C", self.copy_image)
        m.addAction("Сжать и конвертировать...\tCtrl+K", self.compress)
        m.addAction("Лист превью...", self.preview_sheet)
        conv = m.addMenu("Сделать копию в формате")
        for fmt in ("webp", "avif", "png", "jpg", "ico"):
            conv.addAction(fmt, lambda f=fmt: self.convert(f))
        m.addSeparator()
        m.addAction("В корзину\tDel", self.trash)
        m.exec(self.list.mapToGlobal(pos))

    def done(self, text):
        self.refresh()
        self.changed.emit()
        self.win.say(text)

    def leave_similar(self):
        self.like = None
        self.show_files()

    def find_similar(self):
        sel = self.paths()
        if not sel:
            return
        if os.path.relpath(sel[0], LIB) not in self.win.sigs.data:
            self.win.say("Отпечаток этой картинки ещё считается - попробуйте через пару секунд")
            return
        self.like = sel[0]
        self.q.blockSignals(True)
        self.q.clear()
        self.q.blockSignals(False)
        self.show_files()
        self.list.scrollToTop()

    def toggle_fav(self):
        sel = [os.path.relpath(p, LIB) for p in self.paths()]
        if not sel:
            return
        fav = self.cfg.setdefault("fav", [])
        add = any(r not in fav for r in sel)
        for r in sel:
            if add and r not in fav:
                fav.append(r)
            elif not add and r in fav:
                fav.remove(r)
        self.show_files()
        self.win.say(("В избранном: +%d" if add else "Убрано из избранного: %d") % len(sel))

    def look(self):
        if self.list.count():
            Look(self, max(0, self.list.currentRow())).exec()

    def export(self, files=None):
        sel = files or self.paths()
        if not sel:
            return
        d = ExportDialog(self, len(sel), self.cfg)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        folder, o = self.cfg["export_dir"], dict(self.cfg["export"])

        def progress(v):
            self.win.say("Выгружаю %d из %d: %s" % (v[0] + 1, v[1], v[2]))

        def finished(res):
            if isinstance(res, Exception):
                QMessageBox.warning(self, "Не выгрузилось", str(res))
                return
            self.win.say("Выгружено: %d шт. в %s" % (res, folder))
            if self.cfg.get("export_open"):
                os.startfile(folder)

        bg(lambda: export(sel, folder, o, lambda v: RELAY.done.emit(progress, v)), finished)

    def compress(self, files=None):
        sel = files or self.paths()
        if not sel:
            self.win.say("Выберите картинки или щёлкните раздел слева правой кнопкой - «Сжать весь раздел»")
            return
        CompressDialog(self, sel).exec()

    def preview_sheet(self, files=None):
        sel = files or self.paths()
        if not sel:
            return
        start = os.path.join(self.cfg.get("export_dir", "") or os.path.expanduser("~"), "Превью.png")
        p, _ = QFileDialog.getSaveFileName(self, "Лист превью: %d шт." % len(sel), start, "PNG (*.png)")
        if not p:
            return
        try:
            K.contact_sheet(sel[:200]).save(p, "PNG", optimize=True)
        except Exception as e:
            QMessageBox.warning(self, "Не получилось", str(e))
            return
        self.win.say("Лист превью сохранён: " + p)
        os.startfile(p)

    def open_file(self):
        sel = self.paths()
        if sel:
            os.startfile(sel[0])

    def reveal(self):
        sel = self.paths()
        if sel:
            reveal(sel[0])

    def rename(self):
        sel = self.paths()
        if len(sel) != 1:
            return
        stem, ext = os.path.splitext(os.path.basename(sel[0]))
        name, ok = QInputDialog.getText(self, "Переименовать", "Новое имя:", text=stem)
        name = clean_name(name)
        if not ok or not name or name == stem:
            return
        dst = os.path.join(os.path.dirname(sel[0]), name + ext)
        if os.path.exists(dst) and dst.lower() != sel[0].lower():
            QMessageBox.warning(self, "Переименовать", "Такое имя в этой папке уже есть.")
            return
        os.rename(sel[0], dst)
        self.win.moved(sel[0], dst)
        self.win.push("Переименовано: " + name + ext, [("move", sel[0], dst)])
        self.done("Переименовано: " + name + ext)

    def move(self):
        sel = self.paths()
        if not sel:
            return
        d = DestDialog(self, "Перенести: %d шт." % len(sel))
        if d.exec() != QDialog.DialogCode.Accepted or not d.path():
            return
        os.makedirs(d.path(), exist_ok=True)
        steps = []
        for p in sel:
            if os.path.dirname(p) != d.path():
                dst = unique(os.path.join(d.path(), os.path.basename(p)))
                shutil.move(p, dst)
                self.win.moved(p, dst)
                steps.append(("move", p, dst))
        text = "Перенесено: %d шт. в «%s»" % (len(steps), os.path.relpath(d.path(), LIB))
        self.win.push(text, steps)
        self.done(text)

    def copy_path(self):
        sel = self.paths()
        if sel:
            QApplication.clipboard().setText("\n".join(sel))
            self.win.say("Путь скопирован" if len(sel) == 1 else "Скопировано путей: %d" % len(sel))

    def copy_image(self):
        sel = self.paths()
        if not sel:
            return
        try:
            img = QIcon(sel[0]).pixmap(512, 512).toImage() if sel[0].lower().endswith(".svg") \
                else to_qimage(K.load(sel[0]))
        except Exception as e:
            self.win.say("Не скопировалось: %s" % e)
            return
        md = QMimeData()
        md.setImageData(img)
        md.setUrls([QUrl.fromLocalFile(sel[0])])      # проводник и мессенджеры вставят файл, редакторы - картинку
        QApplication.clipboard().setMimeData(md)
        self.win.say("Картинка скопирована: " + os.path.basename(sel[0]))

    def convert(self, fmt):
        n = 0
        for p in self.paths():
            if p.lower().endswith((".svg", "." + fmt)):
                continue
            K.save(K.load(p), unique(os.path.splitext(p)[0] + "." + fmt), fmt)
            n += 1
        self.done("Сделано копий в %s: %d" % (fmt, n))

    def trash(self):
        sel = self.paths()
        if not sel:
            return
        what = os.path.basename(sel[0]) if len(sel) == 1 else "%d шт." % len(sel)
        if QMessageBox.question(self, "В корзину", "Отправить в корзину: %s?\n(вернуть можно из корзины Windows)"
                                % what) != QMessageBox.StandardButton.Yes:
            return
        n = sum(1 for p in sel if QFile.moveToTrash(p))
        self.done("В корзине: %d шт." % n)


# ---------------------------------------------------------------- окно
class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        self.history = []                   # для Ctrl+Z: [(подпись, [("new", путь) | ("move", было, стало)])]
        self.sigs = SigIndex()
        self.setWindowTitle("Библиотека картинок")
        self.setWindowIcon(lib_icon("Звезда"))
        self.resize(*self.cfg.get("size", [1280, 800]))
        self.setAcceptDrops(True)
        os.makedirs(INBOX, exist_ok=True)

        self.tabs = QTabWidget()
        self.tabs.setIconSize(QSize(20, 20))
        self.inbox = InboxTab(self)
        self.lib = LibTab(self)
        self.tabs.addTab(self.inbox, lib_icon("Задачи"), "Входящие")
        self.tabs.addTab(self.lib, lib_icon("Книга"), "Библиотека")
        self.inbox.reload()
        self.setCentralWidget(self.tabs)

        corner = QWidget()
        ch = QHBoxLayout(corner)
        ch.setContentsMargins(0, 0, 8, 4)
        for text, icon, fn, tip in (("Галерея", "Компас", self.open_gallery, "Вся библиотека в браузере"),
                                    ("Промпты", "Заметка", self.open_prompts, ""),
                                    ("Найти дубли", "Лупа", self.dupes, "Одинаковые картинки уедут в «_дубли»")):
            b = QPushButton(lib_icon(icon), text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            ch.addWidget(b)
        self.gen_btn = QPushButton(lib_icon("eye"), "")
        self.gen_btn.clicked.connect(self.pick_gen)
        ch.addWidget(self.gen_btn)
        helpb = QPushButton(lib_icon("question-mark-bubble"), "")
        helpb.setToolTip("Горячие клавиши (F1)")
        helpb.clicked.connect(self.show_help)
        ch.addWidget(helpb)
        self.tabs.setCornerWidget(corner)

        self.undo_btn = QPushButton("Отменить", objectName="undo")
        self.undo_btn.clicked.connect(self.undo)
        self.undo_btn.hide()
        self.stats = QLabel()
        self.heavy_btn = QPushButton(objectName="flat")
        self.heavy_btn.setToolTip("Показать файлы тяжелее %d КБ - их можно сжать (Ctrl+K)" % HEAVY_KB)
        self.heavy_btn.clicked.connect(lambda: (self.tabs.setCurrentIndex(1), self.lib.show_section(HEAVY)))
        self.statusBar().addPermanentWidget(self.heavy_btn)
        self.statusBar().addPermanentWidget(self.undo_btn)
        self.statusBar().addPermanentWidget(self.stats)

        self.overlay = QLabel("Отпустите - картинки попадут во входящие", self, objectName="overlay",
                              alignment=Qt.AlignmentFlag.AlignCenter)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.hide()

        self.inbox.changed.connect(self.library_changed)
        self.lib.changed.connect(self.library_changed)
        self.tabs.currentChanged.connect(self.tab_changed)

        self.watch = QFileSystemWatcher([INBOX], self)
        self.watch.directoryChanged.connect(lambda _p: self.inbox.reload())
        self.gal = QTimer(self, singleShot=True, interval=1500)     # галерею и отпечатки пересобираем один раз на пачку правок
        self.gal.timeout.connect(self.rebuild)
        self.sizes = {}                                             # размеры файлов генератора на прошлом опросе
        self.poll = QTimer(self, interval=2000)
        self.poll.timeout.connect(self.check_gen)
        self.poll.start()

        for keys, fn in (("Ctrl+Z", self.undo), ("Ctrl+V", self.paste), ("F1", self.show_help),
                         ("Ctrl+1", lambda: self.tabs.setCurrentIndex(0)),
                         ("Ctrl+2", lambda: self.tabs.setCurrentIndex(1))):
            key(keys, self, fn, local=False)

        self.show_gen()
        self.update_stats()
        self.sigs.refresh()
        self.tabs.setCurrentIndex(self.cfg.get("tab", 0) if inbox_files() == [] else 0)
        if self.cfg.get("max"):
            self.setWindowState(Qt.WindowState.WindowMaximized)

    def say(self, text):
        self.statusBar().showMessage(text, 8000)

    def tab_changed(self, i):
        if i == 1:
            self.lib.refresh()
        else:
            self.inbox.reload()

    def library_changed(self):
        fill_tree(self.inbox.tree)
        self.inbox.update_save()
        self.update_stats()
        self.gal.start()

    def rebuild(self):
        K.cmd_gallery()
        self.sigs.refresh()

    def update_stats(self):
        files = K.images_in(LIB)
        size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
        self.stats.setText("В библиотеке: %d картинок, %s" % (len(files), human(size)))
        heavy = [f for f in files if os.path.exists(f) and os.path.getsize(f) > HEAVY_KB * 1024]
        self.heavy_btn.setText("Тяжёлых: %d (%s) - сжать?" % (len(heavy), human(sum(map(os.path.getsize, heavy)))))
        self.heavy_btn.setVisible(bool(heavy))

    # --- отмена
    def push(self, text, steps):
        if not steps:
            return
        self.history = (self.history + [(text, steps)])[-20:]
        self.undo_btn.setToolTip("Ctrl+Z: " + text)
        self.undo_btn.show()

    def undo(self):
        if not self.history:
            self.say("Отменять нечего")
            return
        text, steps = self.history.pop()
        bad = 0
        for step in reversed(steps):
            try:
                if step[0] == "new":
                    if os.path.exists(step[1]) and not QFile.moveToTrash(step[1]):
                        bad += 1
                elif os.path.exists(step[2]):
                    back = step[1] if not os.path.exists(step[1]) else unique(step[1])
                    os.makedirs(os.path.dirname(back), exist_ok=True)
                    shutil.move(step[2], back)
                    self.moved(step[2], back)
                    if os.path.dirname(back) == INBOX:
                        self.inbox.no_auto.add(back)
            except Exception:
                bad += 1
        if self.history:
            self.undo_btn.setToolTip("Ctrl+Z: " + self.history[-1][0])
        else:
            self.undo_btn.hide()
        self.inbox.reload()
        if self.tabs.currentIndex() == 1:
            self.lib.refresh()
        self.library_changed()
        self.say("Отменено: " + text + ("  (не получилось: %d)" % bad if bad else ""))

    def moved(self, src, dst):
        """Избранное едет вместе с файлом."""
        fav = self.cfg.get("fav", [])
        a, b = os.path.relpath(src, LIB), os.path.relpath(dst, LIB)
        if a in fav:
            fav[fav.index(a)] = b

    # --- приём файлов
    def take(self, files):
        n = 0
        for f in files:
            if os.path.isfile(f) and is_image(os.path.basename(f)) and os.path.dirname(os.path.abspath(f)) != INBOX:
                shutil.copy2(f, unique(os.path.join(INBOX, os.path.basename(f))))
                n += 1
        if n:
            self.tabs.setCurrentIndex(0)
            self.inbox.reload()
            self.say("Во входящие добавлено: %d" % n)
        return n

    def paste(self):
        cb = QApplication.clipboard()
        md = cb.mimeData()
        if md.hasUrls() and self.take([u.toLocalFile() for u in md.urls() if u.isLocalFile()]):
            return
        if md.hasImage():
            img = cb.image()
            if not img.isNull():
                p = unique(os.path.join(INBOX, "Вставка %s.png" % time.strftime("%Y-%m-%d %H-%M-%S")))
                img.save(p, "PNG")
                self.tabs.setCurrentIndex(0)
                self.inbox.reload()
                self.say("Картинка из буфера во входящих: " + os.path.basename(p))
                return
        self.say("В буфере нет картинки")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is None:      # свои плитки обратно во входящие не принимаем
            e.acceptProposedAction()
            self.overlay.setGeometry(self.rect().adjusted(24, 24, -24, -24))
            self.overlay.raise_()
            self.overlay.show()

    def dragLeaveEvent(self, _e):
        self.overlay.hide()

    def dropEvent(self, e):
        self.overlay.hide()
        self.take([u.toLocalFile() for u in e.mimeData().urls()])

    # --- папка генератора: новые картинки сами копируются во входящие
    def show_gen(self):
        d = self.cfg.get("gen_dir")
        self.gen_btn.setText("Генератор: слежу" if d else "Папка генератора...")
        self.gen_btn.setToolTip(("Слежу за папкой: %s\nНовые картинки сами попадают во входящие.\n"
                                 "Щелчок - выбрать другую или отключить" % d) if d else
                                "Выберите папку, куда генератор сохраняет картинки - новые будут сами попадать во входящие")
        self.inbox.gen_hint.setText(("Слежу за папкой генератора: %s" % d) if d else
                                    "Можно указать папку генератора (кнопка вверху) - новые картинки будут приходить сами")
        self.say("Слежу за папкой генератора: " + d if d else "Папка генератора не задана")

    def pick_gen(self):
        d = QFileDialog.getExistingDirectory(self, "Папка, куда генератор сохраняет картинки (Отмена - не следить)",
                                             self.cfg.get("gen_dir", ""))
        self.cfg["gen_dir"] = os.path.normpath(d) if d else ""
        self.cfg["gen_since"] = time.time()         # берём только то, что появится после выбора
        self.sizes = {}
        self.show_gen()

    def check_gen(self):
        d = self.cfg.get("gen_dir")
        if not d or not os.path.isdir(d):
            return
        since, newest, ready = self.cfg.get("gen_since", time.time()), 0, []
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if not is_image(f) or not os.path.isfile(p):
                continue
            st = os.stat(p)
            if st.st_mtime <= since:
                continue
            if self.sizes.get(p) == st.st_size and st.st_size:      # размер не растёт - файл дописан
                ready.append(p)
                newest = max(newest, st.st_mtime)
            self.sizes[p] = st.st_size
        if ready:
            self.cfg["gen_since"] = newest
            if self.take(ready):
                QApplication.alert(self)            # мигнуть на панели задач, если окно в фоне

    # --- прочее
    def show_help(self):
        QMessageBox.information(self, "Горячие клавиши", HELP)

    def open_gallery(self):
        self.gal.stop()
        K.cmd_gallery()
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(LIB, "Галерея.html")))

    def open_prompts(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(LIB, "Промпты.html")))

    def dupes(self):
        if self.sigs.busy:
            self.say("Отпечатки библиотеки ещё считаются - попробуйте через пару секунд")
            return
        groups = self.sigs.groups()
        if not groups:
            QMessageBox.information(self, "Дубли", "Одинаковых картинок нет.")
            return
        DupesDialog(self, groups).exec()

    def closeEvent(self, e):
        self.cfg["max"] = self.isMaximized()
        if not self.isMaximized():
            self.cfg["size"] = [self.width(), self.height()]
        self.cfg["tab"] = self.tabs.currentIndex()
        self.cfg["split_in"] = self.inbox.split.sizes()
        self.cfg["split_mid"] = self.inbox.mid.sizes()
        self.cfg["split_lib"] = self.lib.split.sizes()
        self.cfg["archive"] = self.inbox.keep.isChecked()
        save_cfg(self.cfg)
        if self.gal.isActive():
            K.cmd_gallery()
        e.accept()


def main():
    global RELAY
    app = QApplication(sys.argv)
    RELAY = Relay()
    RELAY.done.connect(lambda cb, res: cb(res))
    app.setStyleSheet(QSS.replace("@UI", ui_files()))
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
