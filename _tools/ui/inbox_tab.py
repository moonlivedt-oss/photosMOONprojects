"""Вкладка «Входящие»: лист с рамками, нарезка в фоне, выбор раздела, сохранение."""

import os

from PIL import Image
from PyQt6.QtCore import (
    QFile,
    QObject,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import imaging as K
from library import db
from library.sorting import PRESETS, default_names, process, route, sort_files, store
from library.tagging import tag_saved
from ui.animations import Floaty
from ui.common import (
    CLOSING,
    DUPE,
    EXT,
    INBOX,
    LIB,
    PIX,
    ROLE,
    SUB,
    archive,
    bg,
    in_main,
    inbox_files,
    log_error,
    reveal,
    short,
)
from ui.editor import EditDialog, recipe_by_name, recipes
from ui.theme import C
from ui.thumbnails import PieceDelegate, _thumbs, backdrop, lib_icon, thumb, thumb_key, tile, to_pix
from ui.widgets import (
    LibList,
    TagHints,
    fill_tree,
    flat,
    icon_list,
    key,
    make_tree,
    new_folder,
    select_path,
)


# ---------------------------------------------------------------- предпросмотр листа
class Sheet(QWidget):
    """Исходный лист с рамками найденных рисунков и их номерами. Щелчок по рамке - отметить/снять кусок."""

    toggled = pyqtSignal(int)
    edited = pyqtSignal(int, tuple)  # рамку куска подвинули руками: номер, новая рамка (в пикселях листа)
    added = pyqtSignal(tuple)  # Shift + протяжка по пустому месту - новая рамка
    EDGE = 7

    def __init__(self):
        super().__init__()
        self.pm, self.boxes, self.full, self.on, self.hover = None, [], (1, 1), [], -1
        self.drag, self.editable = None, False
        self.setMinimumHeight(160)
        self.setMouseTracking(True)

    def show_sheet(self, im, boxes, mode):
        self.full, self.boxes = im.size, [tuple(b) for b in boxes]  # своя копия: её тянут мышью
        small = im.copy()
        small.thumbnail((1400, 1400), Image.LANCZOS)
        back = backdrop(small.width, small.height, mode)
        back.alpha_composite(small.convert("RGBA"))
        self.pm = to_pix(back)
        self.update()

    def clear(self):
        self.pm, self.boxes, self.on, self.hover = None, [], [], -1
        self.update()

    M = 16  # поля вокруг листа внутри панели

    def frame(self):
        aw, ah = self.width() - 2 * self.M, self.height() - 2 * self.M
        k = min(aw / self.pm.width(), ah / self.pm.height())
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

    # --- правка рамок руками
    def to_sheet(self, pos):
        x0, y0, w, h = self.frame()
        return (
            min(self.full[0], max(0, (pos.x() - x0) * self.full[0] / w)),
            min(self.full[1], max(0, (pos.y() - y0) * self.full[1] / h)),
        )

    def edge_at(self, pos):
        """(номер рамки, какие края тянуть: строка из l t r b) или None."""
        if not self.pm or not self.editable:
            return None
        for i, r in enumerate(self.rects()):
            if not r.adjusted(-self.EDGE, -self.EDGE, self.EDGE, self.EDGE).contains(pos):
                continue
            s = ""
            if abs(pos.x() - r.left()) <= self.EDGE:
                s += "l"
            elif abs(pos.x() - r.right()) <= self.EDGE:
                s += "r"
            if abs(pos.y() - r.top()) <= self.EDGE:
                s += "t"
            elif abs(pos.y() - r.bottom()) <= self.EDGE:
                s += "b"
            if s:
                return i, s
        return None

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.drag:
            x, y = self.to_sheet(pos)
            if self.drag[0] == "edge":
                _k, i, s, (a, b, c, d) = self.drag
                a, c = (min(x, c - 4), c) if "l" in s else (a, max(x, a + 4)) if "r" in s else (a, c)
                b, d = (min(y, d - 4), d) if "t" in s else (b, max(y, b + 4)) if "b" in s else (b, d)
                self.boxes[i] = (int(a), int(b), int(c), int(d))
            else:
                sx, sy = self.drag[1]
                self.drag = ("new", (sx, sy), (min(sx, x), min(sy, y), max(sx, x), max(sy, y)))
            self.update()
            return
        hit = self.edge_at(pos)
        if hit:
            s = hit[1]
            self.setCursor(
                Qt.CursorShape.SizeHorCursor
                if s in ("l", "r")
                else Qt.CursorShape.SizeVerCursor
                if s in ("t", "b")
                else Qt.CursorShape.SizeFDiagCursor
                if s in ("lt", "rb")
                else Qt.CursorShape.SizeBDiagCursor
            )
            if self.hover != -1:
                self.hover = -1
                self.update()
            return
        i = self.box_at(pos)
        shift = e.modifiers() & Qt.KeyboardModifier.ShiftModifier and self.editable
        self.setCursor(
            Qt.CursorShape.CrossCursor
            if shift and i < 0
            else Qt.CursorShape.PointingHandCursor
            if i >= 0
            else Qt.CursorShape.ArrowCursor
        )
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, _e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self.pm:
            return
        pos = e.position()
        hit = self.edge_at(pos)
        if hit:
            i, s = hit
            self.drag = ("edge", i, s, tuple(self.boxes[i]))
            return
        i = self.box_at(pos)
        if i >= 0:
            self.toggled.emit(i)
        elif self.editable and e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            x, y = self.to_sheet(pos)
            self.drag = ("new", (x, y), (x, y, x, y))

    def mouseReleaseEvent(self, _e):
        d, self.drag = self.drag, None
        if not d:
            return
        if d[0] == "edge":
            if tuple(self.boxes[d[1]]) != d[3]:
                self.edited.emit(d[1], tuple(self.boxes[d[1]]))
        else:
            a, b, c, dd = d[2]
            if c - a > 8 and dd - b > 8:
                self.added.emit((int(a), int(b), int(c), int(dd)))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(C["line"]), 1))
        p.setBrush(QColor(C["bg1"]))
        p.drawRoundedRect(panel, 14, 14)
        if not self.pm:
            p.end()
            return
        x0, y0, w, h = self.frame()
        img = QRectF(x0, y0, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(1, 6):  # тень под листом
            p.setBrush(QColor(0, 0, 0, 26 - 4 * i))
            p.drawRoundedRect(img.adjusted(-i, -i + 3, i, i + 3), 10 + i, 10 + i)
        clip = QPainterPath()
        clip.addRoundedRect(img, 10, 10)
        p.setClipPath(clip)
        p.drawPixmap(img, self.pm, QRectF(self.pm.rect()))
        p.setClipping(False)
        grad = QLinearGradient(img.topLeft(), img.bottomRight())
        grad.setColorAt(0, QColor(C["acc"]))
        grad.setColorAt(1, QColor(C["acc2"]))
        f = p.font()
        f.setPointSizeF(8)
        f.setBold(True)
        p.setFont(f)
        for i, r in enumerate(self.rects()):
            on = self.on[i] if i < len(self.on) else True
            hot = i == self.hover
            if not on:  # снятый кусок притушен и обведён пунктиром
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(9, 9, 13, 170))
                p.drawRoundedRect(r, 6, 6)
                pen = QPen(QColor(C["dim"]), 1.5, Qt.PenStyle.DashLine)
            else:
                if hot:
                    fill = QColor(C["acc"])
                    fill.setAlpha(45)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(fill)
                    p.drawRoundedRect(r, 6, 6)
                pen = QPen(QBrush(grad), 3 if hot else 2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 6, 6)
            d = 20
            dot = QRectF(r.x() + 4, r.y() + 4, d, d)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad) if on else QColor(C["line2"]))
            p.drawEllipse(dot)
            p.setPen(QColor(C["ink"] if on else C["dim"]))
            p.drawText(dot, Qt.AlignmentFlag.AlignCenter, str(i + 1))
        if self.drag and self.drag[0] == "new":  # новая рамка, пока её тянут
            a, b, c, d = self.drag[2]
            kx, ky = w / self.full[0], h / self.full[1]
            pen = QPen(QColor(C["teal"]), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(x0 + a * kx, y0 + b * ky, (c - a) * kx, (d - b) * ky))
        p.end()


class Sig(QObject):
    done = pyqtSignal(int, object, object, object, str)


class Job(QRunnable):
    """Нарезка в фоновом потоке: большой лист не должен подвешивать окно."""

    def __init__(self, gen, path, opts, sig):
        super().__init__()
        self.gen, self.path, self.opts, self.sig = gen, path, opts, sig

    def run(self):
        if CLOSING.is_set():
            return
        try:
            im, pieces, boxes = process(self.path, self.opts)
            self.sig.done.emit(self.gen, im, pieces, boxes, "")
        except Exception as e:
            self.sig.done.emit(self.gen, None, [], [], str(e))


# ---------------------------------------------------------------- вкладка "Входящие"
class InboxTab(QWidget):
    changed = pyqtSignal()  # в библиотеку что-то записано

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.gen, self.path, self.pieces, self.loading, self.dupe = 0, None, [], False, {}
        self.pool = QThreadPool.globalInstance()
        self.sig = Sig()
        self.sig.done.connect(self.on_done)
        self.timer = QTimer(self, singleShot=True, interval=250)  # ждём, пока докрутят настройку
        self.timer.timeout.connect(self.run)

        # слева - входящие
        self.files = LibList(140)
        self.files.empty = "Пусто"
        self.files.currentItemChanged.connect(self.pick)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self.files_menu)
        self.files.itemDoubleClicked.connect(lambda it: os.startfile(it.data(ROLE)))
        add = QPushButton(lib_icon("plus-circle"), "Добавить файлы...")
        add.clicked.connect(self.add_files)
        left = self.left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.count = QLabel("ЛИСТЫ", objectName="faint")
        for w in (self.count, self.files, add):
            lv.addWidget(w)

        # центр - лист и результат (или пустая заглушка)
        self.sheet = Sheet()
        self.sheet.toggled.connect(self.toggle_piece)
        self.sheet.edited.connect(self.box_edited)
        self.sheet.added.connect(self.box_added)
        self.sheet.setToolTip(
            "Щелчок по рамке - отметить или снять кусок.\n"
            "Тяните край рамки - поправить, Shift + протяжка по пустому месту - новая рамка."
        )
        self.manual_boxes = None
        self.out = icon_list(112)
        self.out.setSpacing(0)
        self.out.setGridSize(QSize(150, 182))
        self.out.setMouseTracking(True)
        self.out.setItemDelegate(PieceDelegate(self.out))
        self.out.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.out.setEditTriggers(QListWidget.EditTrigger.DoubleClicked | QListWidget.EditTrigger.EditKeyPressed)
        self.out.itemChanged.connect(self.checks_changed)
        self.title = QLabel(objectName="head")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.info = QLabel("Выберите лист слева", objectName="dim")
        self.info.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )  # длинное имя листа не раздвигает окно
        self.bg = QComboBox()
        for t, v in (("Фон: шахматка", "chk"), ("Фон: светлый", "light"), ("Фон: тёмный", "dark")):
            self.bg.addItem(t, v)
        self.bg.setCurrentIndex(max(0, self.bg.findData(self.cfg.get("bg", "chk"))))
        self.bg.currentIndexChanged.connect(self.repaint_preview)
        top = QHBoxLayout()
        heads = QVBoxLayout()
        heads.setSpacing(0)
        heads.addWidget(self.title)
        heads.addWidget(self.info)
        top.addLayout(heads, 1)
        self.merge_b = flat("Склеить", self.merge_boxes, "Выделенные куски (Ctrl+щелчок) - в один")
        self.split_b = flat("Разрезать", self.split_box, "Выделенный кусок - на два по длинной стороне")
        self.boxes_lbl = flat("Рамки поправлены - сбросить", self.reset_boxes, "Вернуть рамки, найденные само")
        self.boxes_lbl.hide()
        for w in (self.boxes_lbl, self.merge_b, self.split_b):
            top.addWidget(w)
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
        self.kind_lbl = QLabel(objectName="dim", wordWrap=True)  # «цельная картинка - сохраню целиком»
        self.kind_lbl.hide()
        for name, _o, _s in PRESETS:
            self.preset.addItem(name)
        self.mode = QComboBox()
        for t, v in (
            ("Найти рисунки автоматически", "auto"),
            ("Резать по сетке", "grid"),
            ("Не резать (целиком)", "whole"),
            ("Цельные картинки сеткой (фоны листом)", "cells"),
        ):
            self.mode.addItem(t, v)
        self.cols = QSpinBox(minimum=1, maximum=20, value=4)
        self.rows = QSpinBox(minimum=1, maximum=20, value=3)
        grid = QHBoxLayout()
        grid.addWidget(self.cols, 1)
        grid.addWidget(QLabel("x", objectName="dim"))
        grid.addWidget(self.rows, 1)
        self.bg_mode = QComboBox()
        for t, v in (
            ("Убрать, если однотонный", "auto"),
            ("Убрать всегда", "remove"),
            ("Убрать нейросетью (любой фон)", "ai"),
            ("Оставить", "keep"),
        ):
            self.bg_mode.addItem(t, v)
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
        self.names.setToolTip(
            "Пусто - имена из названия листа. Одно слово - префикс с номерами. Через запятую - по порядку."
        )
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setVerticalSpacing(5)
        form.addRow("Заготовка", self.preset)
        form.addRow("", self.kind_lbl)
        form.addRow("Нарезка", self.mode)
        form.addRow("Сетка", grid)
        form.addRow("Фон листа", self.bg_mode)
        form.addRow("Обводка", self.obv)
        form.addRow("Поля", self.pad)
        form.addRow(self.size_label, self.size)
        form.addRow("Формат", self.fmt)
        form.addRow("Имена", self.names)
        self.tags = QLineEdit(placeholderText="через запятую: космос, для сайта")
        self.tags.setClearButtonEnabled(True)
        self.tags.setToolTip("Метки ставятся всем сохранённым кускам. Подсказки ниже - щелчок добавляет.")
        self.tag_box = TagHints()
        self.tag_box.picked.connect(self.add_tag)
        self.tag_gen = 0
        form.addRow("Метки", self.tags)
        form.addRow("", self.tag_box)
        self.recipe = QComboBox()
        self.recipe.setToolTip(
            "Рецепт из редактора применяется к каждому куску: убрать фон, кайма, обводка, квадрат...\n"
            "Свои рецепты сохраняются в редакторе (Ctrl+R), вкладка «Рецепты»."
        )
        self.recipe.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.recipe.setMinimumContentsLength(14)
        self.fill_recipes()
        self.recipe.currentIndexChanged.connect(self.recipe_changed)
        form.addRow("Правка кусков", self.recipe)
        for c in (self.preset, self.mode, self.bg_mode):  # длинные пункты не раздвигают правую панель
            c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(14)
        box1 = QGroupBox("НАРЕЗКА")
        box1.setLayout(form)

        self.tree = make_tree()
        self.tree.setMinimumHeight(130)
        self.tree.currentItemChanged.connect(lambda *_: self.update_save())
        self.tree.itemClicked.connect(self.tree_clicked)
        self.route, self.manual, self.auto_busy = None, False, False
        self.no_auto = set()  # вернулись во входящие по Ctrl+Z - сами не раскладывать
        self.route_lbl = QLabel(objectName="dim", wordWrap=True)
        self.route_lbl.hide()
        self.where_btn = QPushButton(lib_icon("sparkles"), "", objectName="chip")  # «похоже на» - куда положить
        self.where_btn.clicked.connect(self.take_where)
        self.where_btn.hide()
        self.where = None
        newdir = QPushButton(lib_icon("folder"), "Новая папка...")
        newdir.clicked.connect(lambda: new_folder(self, self.tree))
        self.auto = QCheckBox("Помеченные раскладывать сразу")
        self.auto.setToolTip(
            "Картинки с меткой в имени (кнопка «Имена» в промптах, например «Космос [ic tokyo]»)\n"
            "нарезаются и раскладываются сами, как только попадают во входящие. Ctrl+Z отменяет."
        )
        self.auto.setChecked(self.cfg.get("auto_route", False))
        self.auto.toggled.connect(self.auto_toggled)
        self.auto_timer = QTimer(self, singleShot=True, interval=900)
        self.auto_timer.timeout.connect(self.auto_sort)
        self.keep = QCheckBox("Исходник убрать в _sources")
        self.keep.setChecked(self.cfg.get("archive", True))
        self.squeeze = QCheckBox("Сжимать при сохранении")
        self.squeeze.setToolTip(
            "Куски сразу сохраняются с подобранным на глаз качеством -\n"
            "раздел «Тяжёлые» не копится. Работает по всем ядрам."
        )
        self.squeeze.setChecked(self.cfg.get("squeeze", True))
        self.squeeze.toggled.connect(lambda on: self.cfg.__setitem__("squeeze", on))
        self.auto_tags = QCheckBox("Ставить подсказанные метки")
        self.auto_tags.setToolTip(
            "Для «Разобрать все» и автораскладки: каждый лист получает метки,\n"
            "которые окно подсказывает по смыслу его кусков"
        )
        self.auto_tags.setChecked(self.cfg.get("auto_tags", True) and win.sem.ok)
        self.auto_tags.setVisible(win.sem.ok)
        self.auto_tags.toggled.connect(lambda on: self.cfg.__setitem__("auto_tags", on))
        self.save_btn = QPushButton("Сохранить в раздел", objectName="primary")
        self.save_btn.setToolTip("Ctrl+S")
        self.save_btn.clicked.connect(self.save_current)
        self.all_btn = QPushButton("Разобрать все входящие")
        self.all_btn.setToolTip("Помеченные - по своим папкам, остальные - с текущими настройками в выбранный раздел")
        self.all_btn.clicked.connect(self.save_all)
        b2 = QVBoxLayout()
        for w in (
            self.route_lbl,
            self.where_btn,
            self.tree,
            newdir,
            self.auto,
            self.keep,
            self.squeeze,
            self.auto_tags,
            self.save_btn,
            self.all_btn,
        ):
            b2.addWidget(w)
        box2 = QGroupBox("КУДА")
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
        for c in (self.mode, self.bg_mode, self.fmt):
            c.currentIndexChanged.connect(self.touched)
        for s in (self.cols, self.rows, self.obv, self.pad, self.size):
            s.valueChanged.connect(self.touched)
        self.names.textChanged.connect(self.rename_pieces)
        key("Ctrl+S", self, self.save_current)
        key("Space", self.out, self.toggle_selected)
        key("Delete", self.files, self.trash_file)

        fill_tree(self.tree)
        self.preset.setCurrentIndex(min(self.cfg.get("preset", 0), len(PRESETS) - 1))
        self.user_preset = self.preset.currentIndex()  # выбранная руками; цельные картинки её не сбивают
        self.apply_preset()
        self.reload()

    def empty_page(self):
        f = QFrame(objectName="drop")
        v = QVBoxLayout(f)
        v.addStretch(1)
        ic = Floaty("download-arrow")
        t = QLabel("Входящих нет", objectName="title", alignment=Qt.AlignmentFlag.AlignCenter)
        s = QLabel(
            f"Перетащите листы в окно, вставьте картинку из буфера (Ctrl+V)\nили положите файлы в папку «{K.INBOX}»",
            objectName="dim",
            alignment=Qt.AlignmentFlag.AlignCenter,
            wordWrap=True,
        )
        self.gen_hint = QLabel(objectName="dim", alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
        row = QHBoxLayout()
        row.addStretch(1)
        for text, icon, fn in (
            ("Добавить файлы...", "plus-circle", self.add_files),
            ("Вставить из буфера", "clipboard", self.win.paste),
            ("Открыть папку", "folder", lambda: os.startfile(INBOX)),
        ):
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
    def opts(self, boxes=False):
        """Настройки нарезки. boxes - с рамками, поправленными руками (только для текущего листа)."""
        o = dict(
            mode=self.mode.currentData(),
            cols=self.cols.value(),
            rows=self.rows.value(),
            bg_mode=self.bg_mode.currentData(),
            obv=self.obv.value(),
            pad=self.pad.value(),
            size=self.size.value(),
            fmt=self.fmt.currentText(),
            recipe=recipe_by_name(self.cfg, self.recipe.currentData()) if self.recipe.currentData() else None,
        )
        if boxes and self.manual_boxes and o["mode"] != "whole":
            o["boxes"] = list(self.manual_boxes)
        return o

    def fill_recipes(self):
        cur = self.recipe.currentData() if self.recipe.count() else self.cfg.get("piece_recipe")
        self.recipe.blockSignals(True)
        self.recipe.clear()
        self.recipe.addItem("Без правки", None)
        for name, _r, _own in recipes(self.cfg):
            self.recipe.addItem(name, name)
        self.recipe.setCurrentIndex(max(0, self.recipe.findData(cur)))
        self.recipe.blockSignals(False)

    def recipe_changed(self):
        self.cfg["piece_recipe"] = self.recipe.currentData()
        self.touched()

    # --- рамки, поправленные руками
    def box_edited(self, i, box):
        boxes = list(self.manual_boxes or self.boxes)
        if i < len(boxes):
            boxes[i] = box
            self.set_boxes(boxes)

    def box_added(self, box):
        self.set_boxes(list(self.manual_boxes or self.boxes) + [box])

    def set_boxes(self, boxes):
        self.manual_boxes = [tuple(int(v) for v in b) for b in boxes]
        self.boxes_lbl.setVisible(True)
        self.run()

    def merge_boxes(self):
        sel = sorted(self.out.row(it) for it in self.out.selectedItems())
        if len(sel) < 2:
            self.win.say("Выделите два куска или больше (Ctrl+щелчок), чтобы склеить их в один")
            return
        boxes = list(self.manual_boxes or self.boxes)
        u = [boxes[i] for i in sel]
        merged = (min(b[0] for b in u), min(b[1] for b in u), max(b[2] for b in u), max(b[3] for b in u))
        boxes = [b for i, b in enumerate(boxes) if i not in sel[1:]]
        boxes[sel[0]] = merged
        self.set_boxes(boxes)

    def split_box(self):
        sel = [self.out.row(it) for it in self.out.selectedItems()]
        if len(sel) != 1:
            self.win.say("Выделите один кусок - он разрежется пополам по длинной стороне")
            return
        boxes = list(self.manual_boxes or self.boxes)
        a, b, c, d = boxes[sel[0]]
        if c - a >= d - b:
            m = (a + c) // 2
            two = [(a, b, m, d), (m, b, c, d)]
        else:
            m = (b + d) // 2
            two = [(a, b, c, m), (a, m, c, d)]
        self.set_boxes(boxes[: sel[0]] + two + boxes[sel[0] + 1 :])

    def reset_boxes(self):
        self.manual_boxes = None
        self.boxes_lbl.setVisible(False)
        self.run()

    def apply_preset(self):
        if not getattr(self, "guessing", False):
            self.user_preset = self.preset.currentIndex()
            self.kind_lbl.hide()
        _name, o, section = PRESETS[self.preset.currentIndex()]
        self.loading = True
        self.mode.setCurrentIndex(self.mode.findData(o["mode"]))
        self.bg_mode.setCurrentIndex(self.bg_mode.findData(o["bg_mode"]))
        self.obv.setValue(o["obv"])
        self.pad.setValue(o["pad"])
        self.size.setValue(o["size"])
        self.fmt.setCurrentText(o["fmt"])
        self.loading = False
        last = self.cfg.get("dest", {}).get(str(self.preset.currentIndex()))  # куда сохраняли с этой заготовкой
        if not (last and os.path.isdir(last) and select_path(self.tree, last)):
            select_path(self.tree, os.path.join(LIB, section))
        self.touched()

    def touched(self):
        if self.loading:
            return
        if self.sender() in (self.mode, self.cols, self.rows) and self.manual_boxes:
            self.manual_boxes = None  # другая сетка - рамки руками больше не к месту
            self.boxes_lbl.setVisible(False)
        mode = self.mode.currentData()
        for w in (self.merge_b, self.split_b):
            w.setVisible(mode != "whole")
        self.sheet.editable = mode != "whole"
        for w in (self.cols, self.rows):
            w.setEnabled(mode in ("grid", "cells"))
        for w in (self.obv, self.pad):
            w.setEnabled(mode not in ("whole", "cells"))
        self.size_label.setText("Длинная сторона" if mode in ("whole", "cells") else "Сторона")
        self.timer.start()

    # --- список входящих
    def reload(self):
        keep = self.path
        self.files.blockSignals(True)
        self.files.clear()
        self.files.reset_anim()
        todo = []
        for row, p in enumerate(inbox_files()):
            stem, ext = os.path.splitext(os.path.basename(p))
            r = route(p)
            it = QListWidgetItem(stem)
            it.setData(ROLE, p)
            if thumb_key(p, 256, "chk") in _thumbs:  # остальные дорисуются в фоне
                it.setData(PIX, thumb(p, 256, "chk"))
            else:
                todo.append((row, p))
            it.setData(EXT, ext[1:].upper())
            try:
                size = "%d × %d" % K.size_of(p)
            except Exception:
                size = ""
            it.setData(SUB, ("в " + short(r["dest"])) if r else size)
            it.setToolTip(p + ("\nМетка в имени: уйдёт в " + short(r["dest"]) if r else ""))
            self.files.addItem(it)
        self.files.blockSignals(False)
        self.files.load_tiles(todo, 256, "chk")
        rows = [i for i in range(self.files.count()) if self.files.item(i).data(ROLE) == keep]
        n = self.files.count()
        if n:
            self.files.setCurrentRow(rows[0] if rows else 0)
        else:
            self.pick(None)
        self.stack.setCurrentIndex(1 if n else 0)
        self.count.setText("ЛИСТЫ: %d" % n if n else "ЛИСТОВ НЕТ")
        self.all_btn.setEnabled(n > 1 and not self.auto_busy)
        self.win.tabs.setTabText(0, "Входящие  %d" % n if n else "Входящие")
        self.left.setVisible(bool(n))  # пустая колонка листов не занимает место
        if self.auto.isChecked() and n:
            self.auto_timer.start()

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Добавить во входящие",
            self.cfg.get("add_dir", ""),
            "Картинки (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.avif)",
        )
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
        m.addAction("Редактировать...", lambda: self.edit(p))
        m.addSeparator()
        m.addAction("В корзину\tDel", self.trash_file)
        m.exec(self.files.mapToGlobal(pos))

    def edit(self, p):
        """Поправить лист до нарезки: повернуть, обрезать лишнее, убрать фон."""

        def saved(text):
            self.path = None  # тот же путь - лист всё равно надо перерезать
            self.reload()
            self.win.say(text)

        EditDialog(self, self.win, [p], on_saved=saved).exec()

    def trash_file(self):
        it = self.files.currentItem()
        if not it:
            return
        p = it.data(ROLE)
        if (
            QMessageBox.question(self, "В корзину", f"Убрать лист в корзину: {os.path.basename(p)}?")
            == QMessageBox.StandardButton.Yes
            and QFile.moveToTrash(p)[0]
        ):
            self.path = None
            self.reload()
            self.win.say("Лист в корзине: " + os.path.basename(p))

    def pick(self, item, _prev=None):
        path = item.data(ROLE) if item else None
        if path == self.path and path:
            return
        self.path = path
        self.route, self.manual = (route(path) if path else None), False
        self.manual_boxes = None  # рамки руками - только у того листа, где их правили
        self.boxes_lbl.setVisible(False)
        self.show_route()
        if not path:
            self.gen += 1
            self.pieces, self.dupe = [], {}
            self.sheet.clear()
            self.out.clear()
            self.info.setText("Входящих нет")
            self.update_save()
            return
        self.kind_lbl.hide()
        if self.route:  # метка в имени: нарезка и папка - по ней
            o = self.route["o"]
            self.loading = True
            self.mode.setCurrentIndex(self.mode.findData(o["mode"]))
            self.cols.setValue(o["cols"])
            self.rows.setValue(o["rows"])
            self.bg_mode.setCurrentIndex(self.bg_mode.findData(o["bg_mode"]))
            self.obv.setValue(o["obv"])
            self.pad.setValue(o["pad"])
            self.size.setValue(o["size"])
            self.fmt.setCurrentText(o["fmt"])
            self.loading = False
            self.touched()
            self.timer.stop()
            select_path(self.tree, self.route["dest"])
        else:
            self.guess_kind(path)
        self.run()

    def guess_kind(self, path):
        """Без метки в имени: фон или иллюстрация - целиком, один рисунок - вырезать его, лист - как в
        заготовке. Решение видно под заготовкой; выбор заготовки руками его отменяет."""
        try:
            with Image.open(path) as im:
                im.draft("RGB", (768, 768))
                kind = K.sheet_kind(K.upright(im))
        except Exception:
            return
        named = os.path.splitext(os.path.basename(path))[0].count(",") >= 2  # имена кусков через запятую - лист
        whole = next(i for i, (_n, o, _s) in enumerate(PRESETS) if o["mode"] == "whole" and o["fmt"] != "ico")
        want = whole if (kind == "whole" and not named) or kind == "cells" else self.user_preset
        self.guessing = True
        try:
            if self.preset.currentIndex() != want:
                self.preset.setCurrentIndex(want)
            mode = PRESETS[want][1]["mode"]  # прошлый лист мог переключить режим на «один рисунок»
            if kind == "single" and not named and mode == "grid":
                mode = "auto"
            if kind == "cells":  # фоны листом 2x2 - резать по пурпурным полосам
                mode = "cells"
                self.loading = True
                self.cols.setValue(2)
                self.rows.setValue(2)
                self.loading = False
            if self.mode.currentData() != mode:
                self.loading = True
                self.mode.setCurrentIndex(self.mode.findData(mode))
                self.loading = False
        finally:
            self.guessing = False
        text = {
            "whole": "Похоже на цельную картинку (фон, иллюстрация) - сохраню целиком.",
            "single": "Похоже на один рисунок - вырежу его.",
            "cells": "Похоже на несколько фонов в пурпурной рамке - разрежу по полосам и увеличу каждый x2.",
        }.get(kind if not named or kind == "cells" else "")
        if text:
            self.kind_lbl.setText(text + " Другая заготовка выше - решить иначе.")
        self.kind_lbl.setVisible(bool(text))
        self.timer.stop()

    def show_route(self):
        r = self.route
        if r and not self.manual:
            new = "" if os.path.isdir(r["dest"]) else "  (папка появится при сохранении)"
            self.route_lbl.setText(
                "По имени файла: {}{}\nЩёлкните раздел ниже, чтобы выбрать другой.".format(short(r["dest"]), new)
            )
        self.route_lbl.setVisible(bool(r and not self.manual))
        self.update_save()

    def tree_clicked(self, *_):
        if self.route:
            self.manual = True  # раздел выбран руками - метка больше не решает
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
        self.all_btn.setEnabled(False)
        items = [(f, r["o"], r["dest"]) for f, r in files]
        self.auto_items = [f for f, _r in files]
        keep_src, sigs, squeeze = self.keep.isChecked(), self.win.sigs, self.squeeze.isChecked()
        tagger = self.win.tagger if self.auto_tags.isChecked() else None
        bg(lambda: sort_files(items, sigs, keep_src, squeeze, tagger=tagger), self.auto_done)

    def auto_done(self, res):
        self.auto_busy = False
        # что осталось во входящих (ошибка или исходник не убирается) - само больше не берём,
        # иначе после каждого перечитывания папки оно резалось бы заново, раз в секунду
        self.no_auto.update(f for f in self.auto_items if os.path.exists(f))
        if isinstance(res, Exception):
            self.win.say(f"Автораскладка не удалась: {res}")
            self.reload()
            return
        steps, total, skipped, bad, where = res
        text = "Разложено само: %d шт. в %s" % (total, ", ".join(sorted(where))) if total else "Новых кусков нет"
        if skipped:
            text += ", повторов пропущено: %d" % skipped
        if bad:
            text += ", не получилось: " + "; ".join(f"{os.path.basename(f)}: {e}" for f, e in bad)
        self.win.push(text, steps)
        self.path = None
        self.reload()
        fill_tree(self.tree)
        self.changed.emit()
        self.win.say(text, undo=bool(steps))
        QApplication.alert(self.win)

    # --- нарезка
    def run(self):
        if not self.path:
            return
        self.gen += 1
        self.info.setText("Режу...")
        self.save_btn.setEnabled(False)
        self.pool.start(Job(self.gen, self.path, self.opts(boxes=True), self.sig))

    def on_done(self, gen, im, pieces, boxes, err):
        if gen != self.gen:  # пока резали, настройки уже поменяли
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
        self.out.clear()  # новый результат: отметки и имена прошлой нарезки не переносим
        for i, piece in enumerate(pieces):
            hit = self.win.sigs.find(piece)
            if hit:
                self.dupe[i] = hit
        self.repaint_preview()
        self.suggest_tags()

    # --- подсказка меток
    def suggest_tags(self):
        """Метки по смыслу кусков (CLIP) - в фоне, щелчок по подсказке добавляет её в поле."""
        self.tag_gen += 1
        gen, pieces = self.tag_gen, list(self.pieces)
        self.show_tag_hints(([], None))
        if not self.win.sem.ok or not pieces:
            return
        bg(lambda: self.win.tagger.suggest_all(pieces), lambda res: gen == self.tag_gen and self.show_tag_hints(res))

    def show_tag_hints(self, res):
        if isinstance(res, Exception):
            log_error(f"подсказка меток: {res}")
            res = ([], None)
        tags, where = res
        self.tag_box.set_tags(tags, set(self.tag_list()))
        self.where = os.path.join(LIB, where[0]) if where and not self.route else None
        self.show_where()

    def show_where(self):
        """Кнопка «Похоже на: раздел» - где в библиотеке лежат самые похожие картинки. Щелчок выбирает раздел."""
        w = self.where
        here = self.dest_path()
        show = bool(w and os.path.isdir(w) and os.path.normcase(w) != os.path.normcase(here or ""))
        if show:
            self.where_btn.setText("Похоже на: " + os.path.relpath(w, LIB).replace(os.sep, " / "))
            self.where_btn.setToolTip("Там лежат самые похожие по смыслу картинки. Щелчок - выбрать этот раздел")
        self.where_btn.setVisible(show)

    def take_where(self):
        if self.where and select_path(self.tree, self.where):
            self.where_btn.hide()

    def tag_list(self):
        return [t for t in (db.clean_tag(x) for x in self.tags.text().split(",")) if t]

    def add_tag(self, tag):
        tags = self.tag_list()
        if tag not in tags:
            self.tags.setText(", ".join(tags + [tag]))

    def repaint_preview(self):
        mode = self.bg.currentData()
        self.cfg["bg"] = mode
        if not self.pieces or not self.path:
            return
        self.sheet.show_sheet(self.im, self.boxes, mode)
        old = {self.out.item(i).data(ROLE): self.out.item(i) for i in range(self.out.count())}
        same = len(old) == len(self.pieces)  # сменили только подложку - отметки и имена не трогаем
        states = {i: (it.checkState(), it.text()) for i, it in old.items()} if same else {}
        self.out.blockSignals(True)
        self.out.clear()
        names = default_names(self.path, len(self.pieces), self.names.text())
        for i, (im, name) in enumerate(zip(self.pieces, names)):
            it = QListWidgetItem(name)
            it.setData(PIX, tile(im.copy(), 160, mode))
            it.setData(DUPE, self.dupe.get(i))
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
        return [
            self.out.item(i) for i in range(self.out.count()) if self.out.item(i).checkState() == Qt.CheckState.Checked
        ]

    def checks_changed(self, *_):
        self.sheet.on = [self.out.item(i).checkState() == Qt.CheckState.Checked for i in range(self.out.count())]
        self.sheet.update()
        if self.path and self.pieces:
            name = os.path.splitext(os.path.basename(self.path))[0]
            self.title.setToolTip(name)
            self.title.setText(name if len(name) <= 60 else name[:57] + "...")
            text = "Отмечено %d из %d" % (
                len(self.checked()),
                len(self.pieces),
            )  # главное - в начале, хвост может не влезть
            if self.dupe:
                text += ", уже есть: %d" % len(self.dupe)
            self.info.setText(text + ", лист %d × %d" % (self.im.width, self.im.height))
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
        self.save_btn.setEnabled(bool(self.path and n and d) and not self.auto_busy)
        if hasattr(self, "where_btn"):
            self.show_where()

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
        if self.auto_busy:  # Ctrl+S, пока в фоне режется пачка, - тот же лист дважды
            self.win.say("Сейчас разбирается пачка - подождите, пока закончится")
            return
        dest = self.dest()
        picked = self.checked()
        if not dest or not picked:
            return
        steps = []
        try:
            saved = store(
                self.path,
                self.opts(),
                [self.pieces[it.data(ROLE)] for it in picked],
                [it.text() for it in picked],
                dest,
                self.squeeze.isChecked(),
            )
            steps = [("new", p) for p in saved]
            tag_saved(saved, self.tag_list())
            if self.keep.isChecked():
                steps.append(("move", self.path, archive(self.path)))
        except Exception as e:
            # то, что успело записаться, тоже уходит в историю для Ctrl+Z
            steps = steps or [("new", p) for p in getattr(e, "saved", [])]
            self.win.push("Сохранено частично: %d шт." % len(steps), steps)
            if steps:
                self.changed.emit()
            QMessageBox.warning(
                self, "Не сохранилось", str(e) + ("\n\nУже записанное убирает Ctrl+Z." if steps else "")
            )
            return
        text = "Сохранено: %d шт. в «%s»" % (len(saved), os.path.relpath(dest, LIB))
        if self.tag_list():
            text += ", метки: " + ", ".join(self.tag_list())
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
        ask = QMessageBox.question(
            self,
            "Разобрать все входящие",
            text + "\nКуски, которые уже есть в библиотеке или повторяются в этой пачке, будут пропущены. Продолжить?",
        )
        if ask != QMessageBox.StandardButton.Yes or self.auto_busy:
            return
        opts = self.opts()
        items = [(f, routes[f]["o"], routes[f]["dest"]) if routes[f] else (f, opts, dest) for f in files]
        keep_src, sigs, squeeze = self.keep.isChecked(), self.win.sigs, self.squeeze.isChecked()
        self.auto_busy = True  # пока режется пачка - ни автораскладки, ни второго запуска
        self.all_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        say = lambda t: in_main(self.win.say, t)  # noqa: E731

        def done(res):
            self.auto_busy = False
            if isinstance(res, Exception):
                QMessageBox.warning(self, "Не получилось", str(res))
                self.reload()
                return
            steps, total, skipped, bad, _where = res
            text = "Сохранено: %d шт. из %d листов" % (total, len(files) - len(bad))
            if skipped:
                text += ", пропущено повторов: %d" % skipped
            self.win.push(text, steps)
            self.finish(text, dest)
            if bad:
                QMessageBox.warning(self, "Не всё получилось", "\n".join(f"{os.path.basename(f)}: {e}" for f, e in bad))

        tagger = self.win.tagger if self.auto_tags.isChecked() else None
        bg(lambda: sort_files(items, sigs, keep_src, squeeze, say, tagger), done)

    def finish(self, text, dest=None):
        self.cfg["archive"] = self.keep.isChecked()
        self.cfg["preset"] = self.user_preset  # не «целиком», если окно само так решило
        if dest and not (self.route and not self.manual):
            self.cfg.setdefault("dest", {})[str(self.preset.currentIndex())] = dest
        self.path = None
        self.names.clear()
        self.tags.clear()
        self.reload()
        fill_tree(self.tree)
        self.changed.emit()
        self.win.say(text, undo=True)
