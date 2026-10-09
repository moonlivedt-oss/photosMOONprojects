"""Мелкие общие виджеты: дерево разделов, списки плиток, горячие клавиши, выбор папки."""

import os
import time

from PyQt6.QtCore import (
    QEasingCurve,
    QMimeData,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDrag,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QInputDialog,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import imaging as K
from library import db
from library.sorting import PLANNED
from ui.common import CLOSING, FAV, HEAVY, LIB, PIX, RECENT, ROLE, SETS, SMART, TAG, bg, clean_name
from ui.theme import C, readable
from ui.thumbnails import TileDelegate, lib_icon, lib_pix, remember, thumb_key, tile_image

# ---------------------------------------------------------------- дерево разделов
_counts = [0.0, {}]


def forget_counts():
    """Файлы поменялись - следующее дерево пересчитает числа."""
    _counts[0] = 0.0


def folder_counts():
    """Сколько картинок в каждой папке вместе с подпапками - за один обход диска.
    Кэш на 1.5 с: после сохранения дерево пересобирают обе вкладки подряд."""
    if time.monotonic() - _counts[0] < 1.5:
        return _counts[1]
    counts = {}
    for d, dirs, files in os.walk(LIB):
        dirs[:] = [x for x in dirs if not x.startswith(("_", ".")) and x != K.INBOX]
        n = sum(1 for f in files if f.lower().endswith(K.EXT) and not f.startswith("_"))
        while n and len(d) >= len(LIB):
            counts[d] = counts.get(d, 0) + n
            d = os.path.dirname(d)
    _counts[:] = [time.monotonic(), counts]
    return counts


def tree_item(parent, text, role, icon, count=None):
    it = QTreeWidgetItem(parent, [text, "" if count is None else str(count)])
    it.setData(0, ROLE, role)
    it.setIcon(0, icon)
    it.setForeground(1, QColor("#7d7a8c"))
    it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return it


def header(tree, text):
    """Подпись группы в дереве: мелкие прописные, не выбирается."""
    it = QTreeWidgetItem(tree, [text, ""])
    it.setFlags(Qt.ItemFlag.NoItemFlags)
    f = QFont("Segoe UI", 7)
    f.setBold(True)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
    it.setFont(0, f)
    it.setForeground(0, QColor(C["faint"]))
    it.setSizeHint(0, QSize(10, 30))
    return it


# цвет раздела библиотеки - как цвет вида у ассетов Unreal: черта на плитках, числа в дереве
SECTION_COLORS = {
    "01": "#6cb8ff",
    "02": "#ff8ac9",
    "03": "#f0a35e",
    "04": "#a897ff",
    "05": "#ffd166",
    "06": "#5ee0d0",
    "07": "#7ee0a0",
    "08": "#c9a0ff",
    "09": "#ffb86c",
    "10": "#ff7b7b",
    "11": "#8fd3ff",
}


def section_color(path):
    try:
        top = os.path.relpath(path, LIB).split(os.sep)[0]
    except ValueError:
        return C["acc"]
    return readable(SECTION_COLORS.get(top[:2], C["acc"]))


def fill_tree(tree, planned=True, recent=False):
    keep = tree.currentItem().data(0, ROLE) if tree.currentItem() else None
    tree.clear()
    folder, star, plus = lib_icon("folder"), lib_icon("folder-star"), lib_icon("plus-circle")

    if recent:
        # быстрый доступ - карточками над деревом (QuickCards); строки остаются скрытыми: выбор раздела
        # по-прежнему идёт через дерево (show_section, «назад», запоминание раздела)
        for text, role, icon in (
            ("Недавние", RECENT, "hourglass"),
            ("Избранное", FAV, "star"),
            ("Наборы", SETS, "color-palette"),
            ("Тяжёлые", HEAVY, "zip-archive"),
        ):
            tree_item(tree, text, role, lib_icon(icon)).setHidden(True)
        try:
            tags = db.all_tags().most_common(40)
        except Exception:
            tags = []
        try:
            smart = db.smart_folders()
        except Exception:
            smart = []
        if smart:
            header(tree, "УМНЫЕ ПАПКИ")
            smart_icon = lib_icon("magnifier-text-lines")
            for name, query, _col, sem in smart:
                it = tree_item(tree, name, SMART + name, smart_icon)
                it.setToolTip(0, ("По смыслу: " if sem else "Поиск: ") + (query or "только цвет"))
        if tags:
            header(tree, "МЕТКИ")
            tag_icon = lib_icon("bookmark")
            for t, n in sorted(tags):
                tree_item(tree, t, TAG + t, tag_icon, n)
    counts = folder_counts()
    if recent:
        header(tree, "РАЗДЕЛЫ")

    def add(parent, path, depth):
        it = tree_item(parent, os.path.basename(path), path, star if depth == 1 else folder, counts.get(path, 0))
        it.setToolTip(0, os.path.relpath(path, LIB))
        it.setForeground(1, QColor(section_color(path)))
        if depth < 3:
            for d in sorted(os.listdir(path)):
                sub = os.path.join(path, d)
                if os.path.isdir(sub) and not d.startswith(("_", ".")):  # служебные и скрытые (.ruff_cache)
                    add(it, sub, depth + 1)
        return it

    names = [
        d
        for d in os.listdir(LIB)
        if os.path.isdir(os.path.join(LIB, d)) and not d.startswith(("_", ".")) and d != K.INBOX
    ]
    for d in sorted(set(names) | (set(PLANNED) if planned else set())):
        path = os.path.join(LIB, d)
        if os.path.isdir(path):
            add(tree.invisibleRootItem(), path, 1)
        else:
            it = tree_item(tree, d, path, plus)
            it.setText(1, "новый")
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
    t.setColumnCount(2)  # имя и число картинок справа: длинное имя не съедает число
    t.header().setStretchLastSection(False)
    t.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    t.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
    t.header().resizeSection(1, t.fontMetrics().horizontalAdvance("00000") + 18)
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


def new_folder(parent, tree):
    it = tree.currentItem()
    role = it.data(0, ROLE) if it else None
    base = role if role and os.path.isdir(role) else LIB
    name, ok = QInputDialog.getText(parent, "Новая папка", f"Имя папки внутри «{os.path.basename(base)}»:")
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


class PicView(QWidget):
    """Картинка на тёмной карточке с мягким свечением её главного цвета за ней (set_glow).
    Пустая - значок и подсказка."""

    def __init__(self, hint="Выберите картинку", frame=True):
        super().__init__()
        self.pm, self.glow, self.hint, self.frame = None, None, hint, frame
        self.old, self.old_glow, self.t = None, None, 1.0  # прошлая картинка тает, новая проявляется
        self.fade = QVariantAnimation(
            self, duration=360, startValue=0.0, endValue=1.0, easingCurve=QEasingCurve.Type.OutCubic
        )
        self.fade.valueChanged.connect(self.step)
        self.zoomable, self.zoom, self.off, self.pan = False, 1.0, QPointF(0, 0), None  # увеличение (просмотр)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.fit_aspect = False  # высота по пропорциям картинки: квадрат не стоит в высокой пустой рамке

    def fit_height(self):
        if not self.fit_aspect:
            return
        if self.pm is None or self.pm.width() <= 0:
            self.setMaximumHeight(320)
            return
        k = self.pm.height() / self.pm.width()
        self.setMaximumHeight(max(200, int((self.width() - 24) * min(k, 1.6)) + 24))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit_height()

    def set_pixmap(self, pm):
        pm = pm if pm and not pm.isNull() else None
        if pm is self.pm:
            return
        self.old, self.old_glow, self.pm = self.pm, self.glow, pm
        self.fit_height()
        self.zoom, self.off = 1.0, QPointF(0, 0)
        self.fade.stop()
        self.t = 0.0
        self.fade.start()

    def step(self, v):
        self.t = v
        if v >= 1:
            self.old = self.old_glow = None
        self.update()

    def set_glow(self, color):
        self.glow = QColor(color) if color else None
        self.update()

    def draw_glow(self, p, r, color, k):
        g = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.62)
        c = QColor(color)
        c.setAlpha(int(150 * k))
        g.setColorAt(0, c)
        c.setAlpha(int(50 * k))
        g.setColorAt(0.55, c)
        c.setAlpha(0)
        g.setColorAt(1, c)
        p.fillRect(r, QBrush(g))

    def fit(self, pm=None):
        pm = pm or self.pm
        box = QRectF(self.rect()).adjusted(18, 18, -18, -18)
        return min(box.width() / pm.width(), box.height() / pm.height()) if pm else 1.0

    def draw_pic(self, p, r, pm, k, zoom, user=False):
        box = r.adjusted(18, 18, -18, -18)
        s = min(box.width() / pm.width(), box.height() / pm.height()) * zoom
        off = QPointF(0, 0)
        if user:  # увеличение и сдвиг - только у текущей картинки
            s *= self.zoom
            off = self.off
        w, h = pm.width() * s, pm.height() * s
        img = QRectF(box.center().x() - w / 2 + off.x(), box.center().y() - h / 2 + off.y(), w, h)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 2.5)  # крупно - пиксели чёткие
        path = QPainterPath()
        path.addRoundedRect(img, 8, 8)
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        p.setOpacity(k)
        p.drawPixmap(img, pm, QRectF(pm.rect()))
        p.restore()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, 14, 14)
        if self.frame:
            p.fillPath(clip, QColor(C["bg2"]))
        p.setClipPath(clip)
        t = self.t
        if self.old_glow is not None and self.old and t < 1:
            self.draw_glow(p, r, self.old_glow, 1 - t)
        if self.glow is not None and self.pm:
            self.draw_glow(p, r, self.glow, t)
        if self.old and t < 1:
            self.draw_pic(p, r, self.old, 1 - t, 1 + 0.03 * t)
        if self.pm:
            self.draw_pic(p, r, self.pm, t, 0.96 + 0.04 * t, user=True)
        else:
            ic = lib_pix("image-file", 96)
            if not ic.isNull():
                p.setOpacity(0.35)
                p.drawPixmap(QRectF(r.center().x() - 32, r.center().y() - 50, 64, 64), ic, QRectF(ic.rect()))
                p.setOpacity(1)
            p.setPen(QColor(C["dim"]))
            p.drawText(QRectF(r.x(), r.center().y() + 22, r.width(), 24), Qt.AlignmentFlag.AlignCenter, self.hint)
        p.setClipping(False)
        if self.frame:
            p.setPen(QPen(QColor(C["line"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 14, 14)
        if self.zoomable and self.pm and self.zoom != 1.0:
            p.setPen(QColor(C["dim"]))
            p.drawText(
                QRectF(r.right() - 140, r.top() + 10, 130, 20),
                Qt.AlignmentFlag.AlignRight,
                "%d%%" % round(self.fit() * self.zoom * 100),
            )
        p.end()

    # --- увеличение (только если zoomable)
    def set_zoom(self, z, at=None):
        if not self.pm:
            return
        z = max(1.0, min(32.0, z))
        c = (at or QPointF(self.width() / 2, self.height() / 2)) - QPointF(self.width() / 2, self.height() / 2)
        self.off = c - (c - self.off) * (z / self.zoom)
        if z == 1.0:
            self.off = QPointF(0, 0)
        self.zoom = z
        self.update()

    def actual_size(self):
        """1:1 - пиксель картинки на пиксель экрана; повторно - снова целиком."""
        if self.pm:
            one = 1 / self.fit()
            self.set_zoom(1.0 if abs(self.zoom - one) < 0.01 or one <= 1 else one)

    def wheelEvent(self, e):
        if not self.zoomable:
            return super().wheelEvent(e)
        self.set_zoom(self.zoom * (1.25 if e.angleDelta().y() > 0 else 0.8), e.position())

    def mousePressEvent(self, e):
        if self.zoomable and self.zoom > 1:
            self.pan = (e.position(), QPointF(self.off))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.pan:
            self.off = self.pan[1] + (e.position() - self.pan[0])
            self.update()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.pan:
            self.pan = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            super().mouseReleaseEvent(e)


class LibList(QListWidget):
    """Плитки библиотеки: Ctrl+колесо меняет размер, перетаскивание отдаёт файлы другим программам.
    Здесь же живут анимации плиток: наведение (hover_amount) и проявление после загрузки (fade_amount)."""

    zoom = pyqtSignal(int)
    FADE = 0.28  # секунд на проявление загруженной плитки

    def __init__(self, side):
        super().__init__()
        self.base, self.empty, self.empty_icon = side, "", "folder"
        self.hover_row, self.hover, self.born = -1, {}, {}
        self.anim = QTimer(self, interval=16)
        self.anim.timeout.connect(self.tick)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setItemDelegate(TileDelegate(self))
        self.shimmer = False  # на экране есть ещё не загруженные плитки - перелив
        self.scroll_to = None
        self.glide = QVariantAnimation(self, duration=260, easingCurve=QEasingCurve.Type.OutCubic)
        self.glide.valueChanged.connect(lambda v: self.verticalScrollBar().setValue(int(v)))
        self.relayout()

    # --- раскладка
    def relayout(self):
        """Столбцов столько, сколько влезает плиток желаемого размера; лишняя ширина делится между ними,
        чтобы справа не оставалась пустая полоса."""
        w = max(1, self.viewport().width() - 2)
        cols = max(1, w // (self.base + 28))
        cell = w // cols
        self.setGridSize(QSize(cell, cell + 38))

    def set_base(self, side):
        self.base = side
        self.relayout()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    # --- ленивая загрузка
    def load_tiles(self, todo, side, mode):
        """Плитки, которых нет в памяти, дорисовываются в фоне порциями - окно не замирает.
        todo = [(строка, путь)]; новый вызов отменяет недогруженное прошлым."""
        self.tgen = getattr(self, "tgen", 0) + 1
        gen = self.tgen

        def step():
            if gen != self.tgen or not todo:
                return
            chunk = todo[:48]
            del todo[:48]

            def work():
                out = []
                for i, p in chunk:
                    if CLOSING.is_set():
                        break
                    try:
                        out.append((i, p, tile_image(p, side, mode)))
                    except Exception:
                        out.append((i, p, None))
                return out

            def done(res):
                if gen != self.tgen or isinstance(res, Exception):
                    return
                for i, p, img in res:
                    it = self.item(i)
                    if img is None or not it or it.data(ROLE) != p:
                        continue
                    key = thumb_key(p, side, mode)
                    pm = remember(key, QPixmap.fromImage(img)) if key else QPixmap.fromImage(img)
                    it.setData(PIX, pm)
                    self.loaded(i)
                step()

            bg(work, done)

        step()

    # --- анимации
    def reset_anim(self):
        self.hover_row, self.hover, self.born = -1, {}, {}

    def loaded(self, row):
        self.born[row] = time.monotonic()
        self.anim.start()

    def hover_amount(self, row):
        return self.hover.get(row, 0.0)

    def fade_amount(self, row):
        t = self.born.get(row)
        return 1.0 if t is None else min(1.0, (time.monotonic() - t) / self.FADE)

    def tick(self):
        busy = False
        for row in set(self.hover) | {self.hover_row}:
            if row < 0:
                continue
            want = 1.0 if row == self.hover_row else 0.0
            v = self.hover.get(row, 0.0)
            v += (want - v) * 0.28  # плавно догоняет цель
            if abs(want - v) < 0.02:
                v = want
            else:
                busy = True
            if v:
                self.hover[row] = v
            else:
                self.hover.pop(row, None)
        now = time.monotonic()
        for row, t in list(self.born.items()):
            if now - t >= self.FADE:
                del self.born[row]
            else:
                busy = True
        busy = busy or self.shimmer
        self.shimmer = False  # рисовальщик снова поднимет, если заглушки ещё видны
        self.viewport().update()
        if not busy:
            self.anim.stop()

    def set_hover(self, row):
        if row != self.hover_row:
            self.hover_row = row
            self.anim.start()

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        idx = self.indexAt(e.position().toPoint())
        self.set_hover(idx.row() if idx.isValid() else -1)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.set_hover(-1)

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.count() and self.empty:  # пустая заглушка: значок и пояснение
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            vr = self.viewport().rect()
            mascot = self.empty_icon.startswith("mascot:")  # маскот - крупнее и не бледный
            ic = lib_pix(self.empty_icon, 256 if mascot else 96)
            side = 150 if mascot else 80
            y = vr.center().y() - side // 2 - 50
            if not ic.isNull():
                p.setOpacity(1 if mascot else 0.55)
                p.drawPixmap(QRectF(vr.center().x() - side / 2, y, side, side), ic, QRectF(ic.rect()))
                p.setOpacity(1)
            p.setPen(QColor(C["dim"]))
            p.drawText(
                QRectF(vr.x() + 30, y + side + 16, vr.width() - 60, 80),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                self.empty,
            )
            p.end()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom.emit(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        dy = e.angleDelta().y()
        if not dy or e.pixelDelta().y():  # тачпад крутит сам и плавно
            super().wheelEvent(e)
            return
        bar = self.verticalScrollBar()  # колесо - плавный разгон к цели, а не скачок
        if self.glide.state() != QVariantAnimation.State.Running:
            self.scroll_to = bar.value()
        self.scroll_to = max(bar.minimum(), min(bar.maximum(), self.scroll_to - dy * 1.1))
        self.glide.stop()
        self.glide.setStartValue(float(bar.value()))
        self.glide.setEndValue(float(self.scroll_to))
        self.glide.start()
        e.accept()

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(it.data(ROLE)) for it in items])
        return md

    def startDrag(self, _actions):
        items = self.selectedItems()
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        pm = items[0].data(PIX)
        if isinstance(pm, QPixmap) and not pm.isNull():
            drag.setPixmap(
                pm.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        drag.exec(Qt.DropAction.CopyAction)  # только копия: проводник не должен уносить файл из библиотеки


class TagHints(QWidget):
    """Подсказанные метки кнопками по три в ряд; щелчок - picked(метка), «все» - picked по каждой."""

    picked = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(4)
        self.tags = []
        self.hide()

    def set_tags(self, tags, have=()):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.tags = [t for t in tags if t not in have] if isinstance(tags, list) else []
        for i, t in enumerate(self.tags):
            b = QPushButton("+ " + t, objectName="chip")
            b.setToolTip("Добавить метку «%s»" % t)
            b.clicked.connect(lambda _c, t=t, b=b: (b.setEnabled(False), self.picked.emit(t)))
            self.grid.addWidget(b, i // 3, i % 3)
        if len(self.tags) > 1:
            b = QPushButton("все", objectName="chip")
            b.setToolTip("Добавить все подсказки")
            b.clicked.connect(self.pick_all)
            self.grid.addWidget(b, len(self.tags) // 3, len(self.tags) % 3)
        self.setVisible(bool(self.tags))

    def pick_all(self):
        for t in list(self.tags):
            self.picked.emit(t)
        self.set_tags([])
