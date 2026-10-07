#!/usr/bin/env python3
# ============================================================
#  Окно библиотеки картинок (PyQt6). Запуск: Библиотека.cmd в корне библиотеки.
#
#  Вкладка "Входящие": всё, что лежит в "00 Входящие" (или перетащено в окно),
#  режется с предпросмотром и раскладывается по разделам. Исходный лист уезжает
#  в "_исходники/<год-месяц>", чтобы его можно было перерезать.
#  Вкладка "Библиотека": просмотр разделов, поиск, переименование, перенос,
#  корзина, копирование пути, конвертация.
#
#  Вся работа с картинками - в картинки.py, здесь только интерфейс.
#  Значки кнопок берутся из "04 Иконки" самой библиотеки (нет файла - кнопка без значка).
# ============================================================
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image
from PyQt6.QtCore import QFile, QFileSystemWatcher, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMainWindow, QMenu, QMessageBox, QPushButton, QSpinBox, QSplitter, QTabWidget,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import картинки as K  # noqa: E402

LIB = K.LIB
INBOX = os.path.join(LIB, K.INBOX)
SOURCES = os.path.join(LIB, "_исходники")
CFG = os.path.join(HERE, "настройки.json")
ROLE = Qt.ItemDataRole.UserRole

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

QSS = """
QWidget{background:#15151c;color:#e8e6f0;font:10pt "Segoe UI"}
QListWidget,QTreeWidget,QLineEdit,QSpinBox,QComboBox{background:#1f1f29;border:1px solid #2a2a36;border-radius:6px;padding:3px}
QComboBox QAbstractItemView{background:#1f1f29;selection-background-color:#3a3560}
QPushButton{background:#1f1f29;border:1px solid #2a2a36;border-radius:6px;padding:6px 12px}
QPushButton:hover{border-color:#9d8cff}
QPushButton:disabled{color:#6b6978}
QPushButton#primary{background:#9d8cff;color:#15151c;font-weight:600;border-color:#9d8cff}
QGroupBox{border:1px solid #2a2a36;border-radius:8px;margin-top:10px;padding-top:10px}
QGroupBox::title{subcontrol-origin:margin;left:10px;color:#9a98a8}
QTabWidget::pane{border:0}
QTabBar::tab{padding:7px 16px;background:transparent;border-bottom:2px solid transparent}
QTabBar::tab:selected{border-bottom-color:#9d8cff}
QListWidget::item:selected,QTreeWidget::item:selected{background:#3a3560;color:#fff}
QSplitter::handle{background:#2a2a36}
QLabel#dim{color:#9a98a8}
QMenu{border:1px solid #2a2a36}QMenu::item:selected{background:#3a3560}
"""


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


def to_pix(im):
    im = im.convert("RGBA")
    q = QImage(im.tobytes("raw", "RGBA"), im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(q.copy())      # copy: буфер PIL не переживёт выход из функции


def tile(im, side, mode=None):
    """Квадратная плитка side x side: картинка по центру, под ней подложка (mode=None - прозрачно)."""
    im = im.convert("RGBA")
    im.thumbnail((side, side), Image.LANCZOS)
    bg = backdrop(side, side, mode) if mode else Image.new("RGBA", (side, side), (0, 0, 0, 0))
    bg.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return to_pix(bg)


_thumbs = {}


def thumb(path, side, mode=None):
    try:
        key = (path, os.path.getmtime(path), side, mode)
    except OSError:
        return QPixmap()
    if key not in _thumbs:
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
                with Image.open(path) as im:
                    im.draft("RGB", (side * 2, side * 2))      # jpg открывается сразу уменьшенным
                    pm = tile(im, side, mode)
        except Exception:
            pm = QPixmap()
        _thumbs[key] = pm
    return _thumbs[key]


def lib_icon(name):
    """Значок из "04 Иконки" библиотеки по имени файла без расширения."""
    for p in K.images_in(os.path.join(LIB, "04 Иконки")):      # иконки лежат по подпапкам
        if os.path.splitext(os.path.basename(p))[0] == name:
            return QIcon(thumb(p, 48))
    return QIcon()


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


def default_names(path, n, text=""):
    """Имена по порядку: список через запятую, общий префикс или имя листа."""
    stem = os.path.splitext(os.path.basename(path))[0]
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
    """Убирает разобранный исходник из входящих в _исходники/<год-месяц>."""
    d = os.path.join(SOURCES, time.strftime("%Y-%m"))
    os.makedirs(d, exist_ok=True)
    shutil.move(path, unique(os.path.join(d, os.path.basename(path))))


# ---------------------------------------------------------------- дерево разделов
def fill_tree(tree, planned=True):
    keep = tree.currentItem().data(0, ROLE) if tree.currentItem() else None
    tree.clear()

    def add(parent, path, depth):
        n = len(K.images_in(path))
        it = QTreeWidgetItem(parent, ["%s  (%d)" % (os.path.basename(path), n)])
        it.setData(0, ROLE, path)
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
            it.setForeground(0, QColor("#9a98a8"))
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
    t.setIndentation(14)
    return t


def icon_list(side):
    w = QListWidget()
    w.setViewMode(QListWidget.ViewMode.IconMode)
    w.setResizeMode(QListWidget.ResizeMode.Adjust)
    w.setMovement(QListWidget.Movement.Static)
    w.setIconSize(QSize(side, side))
    w.setGridSize(QSize(side + 22, side + 40))
    w.setWordWrap(True)
    w.setUniformItemSizes(True)
    return w


# ---------------------------------------------------------------- предпросмотр листа
class Sheet(QWidget):
    """Исходный лист с рамками найденных рисунков и их номерами."""

    def __init__(self):
        super().__init__()
        self.pm, self.boxes, self.full = None, [], (1, 1)
        self.setMinimumHeight(160)

    def show_sheet(self, im, boxes, mode):
        self.full, self.boxes = im.size, boxes
        small = im.copy()
        small.thumbnail((1400, 1400), Image.LANCZOS)
        bg = backdrop(small.width, small.height, mode)
        bg.alpha_composite(small.convert("RGBA"))
        self.pm = to_pix(bg)
        self.update()

    def clear(self):
        self.pm, self.boxes = None, []
        self.update()

    def paintEvent(self, _e):
        if not self.pm:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        k = min(self.width() / self.pm.width(), self.height() / self.pm.height())
        w, h = self.pm.width() * k, self.pm.height() * k
        x0, y0 = (self.width() - w) / 2, (self.height() - h) / 2
        p.drawPixmap(int(x0), int(y0), int(w), int(h), self.pm)
        kx, ky = w / self.full[0], h / self.full[1]
        for i, (a, b, c, d) in enumerate(self.boxes):
            x, y = int(x0 + a * kx), int(y0 + b * ky)
            p.setPen(QPen(QColor("#9d8cff"), 2))
            p.drawRect(x, y, int((c - a) * kx), int((d - b) * ky))
            p.fillRect(x, y, 22, 18, QColor("#9d8cff"))
            p.setPen(QColor("#15151c"))
            p.drawText(x, y, 22, 18, Qt.AlignmentFlag.AlignCenter, str(i + 1))
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
        self.gen, self.path, self.pieces, self.loading = 0, None, [], False
        self.pool = QThreadPool.globalInstance()
        self.sig = Sig()
        self.sig.done.connect(self.on_done)
        self.timer = QTimer(self, singleShot=True, interval=250)     # ждём, пока докрутят настройку
        self.timer.timeout.connect(self.run)

        # слева - входящие
        self.files = icon_list(96)
        self.files.currentItemChanged.connect(self.pick)
        add = QPushButton("Добавить файлы...")
        add.clicked.connect(self.add_files)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("Перетащите листы в окно или положите в папку «%s»" % K.INBOX, objectName="dim", wordWrap=True)
        for w in (hint, self.files, add):
            lv.addWidget(w)

        # центр - лист и результат
        self.sheet = Sheet()
        self.out = icon_list(112)
        self.out.setEditTriggers(QListWidget.EditTrigger.DoubleClicked | QListWidget.EditTrigger.EditKeyPressed)
        self.info = QLabel("Выберите лист слева", objectName="dim")
        self.bg = QComboBox()
        for t, v in (("Фон: шахматка", "chk"), ("Фон: светлый", "light"), ("Фон: тёмный", "dark")):
            self.bg.addItem(t, v)
        self.bg.setCurrentIndex(max(0, self.bg.findData(self.cfg.get("bg", "chk"))))
        self.bg.currentIndexChanged.connect(self.repaint_preview)
        top = QHBoxLayout()
        top.addWidget(self.info, 1)
        top.addWidget(self.bg)
        mid = QSplitter(Qt.Orientation.Vertical)
        mid.addWidget(self.sheet)
        mid.addWidget(self.out)
        mid.setSizes([300, 360])
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addLayout(top)
        cv.addWidget(mid, 1)

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
        grid.addWidget(self.cols)
        grid.addWidget(QLabel("x"))
        grid.addWidget(self.rows)
        grid.addStretch(1)
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
        form = QFormLayout()
        form.addRow("Заготовка", self.preset)
        form.addRow("Нарезка", self.mode)
        form.addRow("Сетка", grid)
        form.addRow("Фон листа", self.fon)
        form.addRow("Обводка", self.obv)
        form.addRow("Поля", self.pad)
        form.addRow(self.size_label, self.size)
        form.addRow("Формат", self.fmt)
        form.addRow("Имена", self.names)
        box1 = QGroupBox("Нарезка")
        box1.setLayout(form)

        self.tree = make_tree()
        newdir = QPushButton("Новая папка...")
        newdir.clicked.connect(lambda: new_folder(self, self.tree))
        self.keep = QCheckBox("Исходник убрать в _исходники")
        self.keep.setChecked(self.cfg.get("archive", True))
        self.save_btn = QPushButton("Сохранить в раздел", objectName="primary")
        self.save_btn.clicked.connect(self.save_current)
        self.all_btn = QPushButton("Разобрать все входящие так же")
        self.all_btn.clicked.connect(self.save_all)
        b2 = QVBoxLayout()
        for w in (self.tree, newdir, self.keep, self.save_btn, self.all_btn):
            b2.addWidget(w)
        box2 = QGroupBox("Куда")
        box2.setLayout(b2)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(box1)
        rv.addWidget(box2, 1)

        sp = QSplitter()
        for w in (left, center, right):
            sp.addWidget(w)
        sp.setSizes([230, 640, 330])
        lay = QVBoxLayout(self)
        lay.addWidget(sp)

        self.preset.currentIndexChanged.connect(self.apply_preset)
        for c in (self.mode, self.fon, self.fmt):
            c.currentIndexChanged.connect(self.touched)
        for s in (self.cols, self.rows, self.obv, self.pad, self.size):
            s.valueChanged.connect(self.touched)
        self.names.textEdited.connect(self.rename_pieces)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_current)

        fill_tree(self.tree)
        self.preset.setCurrentIndex(min(self.cfg.get("preset", 0), len(PRESETS) - 1))
        self.apply_preset()
        self.reload()

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
        if self.files.count():
            self.files.setCurrentRow(rows[0] if rows else 0)
        else:
            self.pick(None)
        self.win.tabs.setTabText(0, "Входящие (%d)" % self.files.count())

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Добавить во входящие", "",
                                                "Картинки (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.avif)")
        self.win.take(files)

    def pick(self, item, _prev=None):
        path = item.data(ROLE) if item else None
        if path == self.path and path:
            return
        self.path = path
        if not path:
            self.gen += 1
            self.pieces = []
            self.sheet.clear()
            self.out.clear()
            self.info.setText("Входящих нет")
            self.save_btn.setEnabled(False)
            return
        self.run()

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
            self.pieces = []
            self.sheet.clear()
            self.out.clear()
            self.info.setText("Не получилось: " + err)
            return
        self.im, self.pieces, self.boxes = im, pieces, boxes
        self.repaint_preview()
        self.info.setText("%s: %dx%d, картинок: %d" % (os.path.basename(self.path), im.width, im.height, len(pieces)))
        self.save_btn.setEnabled(bool(pieces))

    def repaint_preview(self):
        mode = self.bg.currentData()
        self.cfg["bg"] = mode
        if not self.pieces or not self.path:
            return
        self.sheet.show_sheet(self.im, self.boxes, mode)
        self.out.clear()
        names = default_names(self.path, len(self.pieces), self.names.text())
        for i, (im, name) in enumerate(zip(self.pieces, names)):
            it = QListWidgetItem(QIcon(tile(im.copy(), 112, mode)), name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            it.setData(ROLE, i)
            self.out.addItem(it)

    def rename_pieces(self):
        if not self.path:
            return
        names = default_names(self.path, self.out.count(), self.names.text())
        for i, name in enumerate(names):
            self.out.item(i).setText(name)

    # --- сохранение
    def dest(self):
        it = self.tree.currentItem()
        if not it:
            QMessageBox.information(self, "Куда сохранить", "Выберите раздел справа.")
            return None
        return it.data(0, ROLE)

    def save_current(self):
        if not self.path or not self.pieces:
            return
        dest = self.dest()
        if not dest:
            return
        picked = [self.out.item(i) for i in range(self.out.count())
                  if self.out.item(i).checkState() == Qt.CheckState.Checked]
        if not picked:
            return
        try:
            saved = store(self.path, self.opts(), [self.pieces[it.data(ROLE)] for it in picked],
                          [it.text() for it in picked], dest)
            if self.keep.isChecked():
                archive(self.path)
        except Exception as e:
            QMessageBox.warning(self, "Не сохранилось", str(e))
            return
        self.finish("Сохранено: %d шт. в «%s»" % (len(saved), os.path.relpath(dest, LIB)))

    def save_all(self):
        files = inbox_files()
        dest = self.dest()
        if not files or not dest:
            return
        ask = QMessageBox.question(self, "Разобрать все входящие",
                                   "Листов: %d. Все будут нарезаны с текущими настройками и сохранены в «%s». Продолжить?"
                                   % (len(files), os.path.relpath(dest, LIB)))
        if ask != QMessageBox.StandardButton.Yes:
            return
        o, total, bad = self.opts(), 0, []
        for n, path in enumerate(files):
            self.win.say("Режу %d из %d: %s" % (n + 1, len(files), os.path.basename(path)))
            QApplication.processEvents()
            try:
                _im, pieces, _b = process(path, o)
                total += len(store(path, o, pieces, default_names(path, len(pieces)), dest))
                if self.keep.isChecked():
                    archive(path)
            except Exception as e:
                bad.append("%s: %s" % (os.path.basename(path), e))
        self.finish("Сохранено: %d шт. из %d листов" % (total, len(files) - len(bad)))
        if bad:
            QMessageBox.warning(self, "Не всё получилось", "\n".join(bad))

    def finish(self, text):
        self.cfg["archive"] = self.keep.isChecked()
        self.cfg["preset"] = self.preset.currentIndex()
        self.path = None
        self.names.clear()
        self.reload()
        fill_tree(self.tree)
        self.changed.emit()
        self.win.say(text)


def new_folder(parent, tree):
    it = tree.currentItem()
    base = it.data(0, ROLE) if it else LIB
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
        new = QPushButton("Новая папка...")
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
class LibTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.tree = make_tree()
        self.tree.currentItemChanged.connect(lambda *_: self.show_files())
        self.q = QLineEdit(placeholderText="Поиск по всей библиотеке...")
        self.q.setClearButtonEnabled(True)
        self.q.addAction(lib_icon("Лупа"), QLineEdit.ActionPosition.LeadingPosition)
        self.q.textChanged.connect(lambda *_: self.show_files())
        self.list = icon_list(128)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.menu)
        self.list.itemDoubleClicked.connect(lambda it: os.startfile(it.data(ROLE)))
        self.list.itemSelectionChanged.connect(self.describe)
        self.info = QLabel("", objectName="dim")
        bar = QHBoxLayout()
        bar.addWidget(self.q, 1)
        for text, fn in (("Переименовать", self.rename), ("Перенести...", self.move), ("Копировать путь", self.copy_path),
                         ("В корзину", self.trash)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(bar)
        rv.addWidget(self.list, 1)
        rv.addWidget(self.info)
        sp = QSplitter()
        sp.addWidget(self.tree)
        sp.addWidget(right)
        sp.setSizes([260, 940])
        lay = QVBoxLayout(self)
        lay.addWidget(sp)
        QShortcut(QKeySequence("F2"), self.list, self.rename)
        QShortcut(QKeySequence("Delete"), self.list, self.trash)
        QShortcut(QKeySequence("Ctrl+C"), self.list, self.copy_path)
        self.refresh()

    def refresh(self):
        fill_tree(self.tree, planned=False)
        if not self.tree.currentItem() and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.show_files()

    def show_files(self):
        q = self.q.text().strip().lower()
        it = self.tree.currentItem()
        root = LIB if q else (it.data(0, ROLE) if it else None)
        self.list.clear()
        if not root or not os.path.isdir(root):
            return
        mode = self.cfg.get("bg", "chk")
        for p in K.images_in(root):
            rel = os.path.relpath(p, LIB)
            if q and q not in rel.lower():
                continue
            item = QListWidgetItem(QIcon(thumb(p, 128, mode)), os.path.basename(p))
            item.setData(ROLE, p)
            item.setToolTip(rel)
            self.list.addItem(item)
        self.describe()

    def paths(self):
        return [i.data(ROLE) for i in self.list.selectedItems()]

    def describe(self):
        sel = self.paths()
        if len(sel) == 1:
            p, text = sel[0], os.path.relpath(sel[0], LIB)
            try:
                with Image.open(p) as im:
                    text += "   %dx%d" % im.size
            except Exception:
                pass
            self.info.setText("%s   %d КБ" % (text, max(1, os.path.getsize(p) // 1024)))
        else:
            self.info.setText("Выбрано: %d из %d" % (len(sel), self.list.count()))

    def menu(self, pos):
        if not self.paths():
            return
        m = QMenu(self)
        m.addAction("Переименовать\tF2", self.rename)
        m.addAction("Перенести в раздел...", self.move)
        m.addAction("Копировать путь\tCtrl+C", self.copy_path)
        m.addAction("Показать в проводнике", self.reveal)
        conv = m.addMenu("Сделать копию в формате")
        for fmt in ("webp", "png", "jpg", "ico"):
            conv.addAction(fmt, lambda f=fmt: self.convert(f))
        m.addSeparator()
        m.addAction("В корзину\tDel", self.trash)
        m.exec(self.list.mapToGlobal(pos))

    def done(self, text):
        self.refresh()
        self.changed.emit()
        self.win.say(text)

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
        self.done("Переименовано: " + name + ext)

    def move(self):
        sel = self.paths()
        if not sel:
            return
        d = DestDialog(self, "Перенести: %d шт." % len(sel))
        if d.exec() != QDialog.DialogCode.Accepted or not d.path():
            return
        os.makedirs(d.path(), exist_ok=True)
        n = 0
        for p in sel:
            if os.path.dirname(p) != d.path():
                shutil.move(p, unique(os.path.join(d.path(), os.path.basename(p))))
                n += 1
        self.done("Перенесено: %d шт. в «%s»" % (n, os.path.relpath(d.path(), LIB)))

    def copy_path(self):
        sel = self.paths()
        if sel:
            QApplication.clipboard().setText("\n".join(sel))
            self.win.say("Путь скопирован" if len(sel) == 1 else "Скопировано путей: %d" % len(sel))

    def reveal(self):
        sel = self.paths()
        if sel:
            subprocess.Popen('explorer /select,"%s"' % sel[0])

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
        if QMessageBox.question(self, "В корзину", "Отправить в корзину: %s?" % what) != QMessageBox.StandardButton.Yes:
            return
        n = sum(1 for p in sel if QFile.moveToTrash(p))
        self.done("В корзине: %d шт." % n)


# ---------------------------------------------------------------- окно
class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
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
        for text, icon, fn in (("Галерея", "Компас", self.open_gallery), ("Промпты", "Заметка", self.open_prompts),
                               ("Найти дубли", "Лупа", self.dupes), ("Папка генератора...", "", self.pick_gen)):
            b = QPushButton(lib_icon(icon), text) if icon else QPushButton(text)
            b.clicked.connect(fn)
            ch.addWidget(b)
        self.tabs.setCornerWidget(corner)

        self.inbox.changed.connect(self.library_changed)
        self.lib.changed.connect(self.library_changed)
        self.tabs.currentChanged.connect(lambda i: self.lib.refresh() if i == 1 else self.inbox.reload())

        self.watch = QFileSystemWatcher([INBOX], self)
        self.watch.directoryChanged.connect(lambda _p: self.inbox.reload())
        self.gal = QTimer(self, singleShot=True, interval=1500)     # галерею пересобираем один раз на пачку правок
        self.gal.timeout.connect(K.cmd_gallery)
        self.sizes = {}                                             # размеры файлов генератора на прошлом опросе
        self.poll = QTimer(self, interval=2000)
        self.poll.timeout.connect(self.check_gen)
        self.poll.start()
        self.say(self.gen_text())

    def say(self, text):
        self.statusBar().showMessage(text, 8000)

    def library_changed(self):
        fill_tree(self.inbox.tree)
        self.gal.start()

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

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.take([u.toLocalFile() for u in e.mimeData().urls()])

    # --- папка генератора: новые картинки сами копируются во входящие
    def gen_text(self):
        d = self.cfg.get("gen_dir")
        return "Слежу за папкой генератора: " + d if d else "Папка генератора не задана - листы добавляются перетаскиванием"

    def pick_gen(self):
        d = QFileDialog.getExistingDirectory(self, "Папка, куда генератор сохраняет картинки (Отмена - не следить)",
                                             self.cfg.get("gen_dir", ""))
        self.cfg["gen_dir"] = os.path.normpath(d) if d else ""
        self.cfg["gen_since"] = time.time()         # берём только то, что появится после выбора
        self.sizes = {}
        self.say(self.gen_text())

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
            self.take(ready)

    # --- прочее
    def open_gallery(self):
        self.gal.stop()
        K.cmd_gallery()
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(LIB, "Галерея.html")))

    def open_prompts(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(LIB, "Промпты.html")))

    def dupes(self):
        before = len(K.images_in(LIB))
        K.cmd_dupes(type("A", (), {"papka": None}))
        moved = before - len(K.images_in(LIB))
        self.lib.refresh()
        self.library_changed()
        QMessageBox.information(self, "Дубли", "Перенесено в папку «_дубли»: %d" % moved if moved else "Дублей нет.")

    def closeEvent(self, e):
        self.cfg["size"] = [self.width(), self.height()]
        save_cfg(self.cfg)
        if self.gal.isActive():
            K.cmd_gallery()
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
