"""Мелкие общие виджеты: дерево разделов, списки плиток, горячие клавиши, выбор папки."""
import os
import time

import картинки as K
from PyQt6.QtCore import (
    QEasingCurve,
    QMimeData,
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

from окно.миниатюры import TileDelegate, lib_icon, lib_pix, remember, thumb_key, tile_image
from окно.общее import CLOSING, FAV, HEAVY, LIB, PIX, RECENT, ROLE, bg, clean_name
from окно.оформление import C
from окно.раскладка import PLANNED


# ---------------------------------------------------------------- дерево разделов
_counts = [0.0, {}]


def forget_counts():
    """Файлы поменялись - следующее дерево пересчитает числа."""
    _counts[0] = 0.0


def folder_counts():
    """Сколько картинок в каждой папке библиотеки вместе с подпапками - за один обход диска
    (раньше каждая папка пересчитывалась отдельно, и большие разделы обходились по 3-4 раза).
    После сохранения дерево пересобирается в двух вкладках подряд - обход один на обе."""
    if time.monotonic() - _counts[0] < 1.5:
        return _counts[1]
    counts = {}
    for d, dirs, files in os.walk(LIB):
        dirs[:] = [x for x in dirs if not x.startswith("_") and x != K.INBOX]
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


def fill_tree(tree, planned=True, recent=False):
    keep = tree.currentItem().data(0, ROLE) if tree.currentItem() else None
    tree.clear()
    folder, star, plus = lib_icon("folder"), lib_icon("folder-star"), lib_icon("plus-circle")

    if recent:
        header(tree, "БЫСТРЫЙ ДОСТУП")
        for text, role, icon in (("Недавние", RECENT, "hourglass"), ("Избранное", FAV, "star"),
                                 ("Тяжёлые", HEAVY, "zip-archive")):
            tree_item(tree, text, role, lib_icon(icon))
    counts = folder_counts()
    if recent:
        header(tree, "РАЗДЕЛЫ")

    def add(parent, path, depth):
        it = tree_item(parent, os.path.basename(path), path, star if depth == 1 else folder, counts.get(path, 0))
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
    t.setColumnCount(2)                     # имя и число картинок справа: длинное имя не съедает число
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


class PicView(QWidget):
    """Картинка на тёмной карточке с мягким свечением её главного цвета за ней (set_glow).
    Пустая - значок и подсказка."""

    def __init__(self, hint="Выберите картинку", frame=True):
        super().__init__()
        self.pm, self.glow, self.hint, self.frame = None, None, hint, frame
        self.old, self.old_glow, self.t = None, None, 1.0      # прошлая картинка тает, новая проявляется
        self.fade = QVariantAnimation(self, duration=360, startValue=0.0, endValue=1.0,
                                      easingCurve=QEasingCurve.Type.OutCubic)
        self.fade.valueChanged.connect(self.step)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_pixmap(self, pm):
        pm = pm if pm and not pm.isNull() else None
        if pm is self.pm:
            return
        self.old, self.old_glow, self.pm = self.pm, self.glow, pm
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

    def draw_pic(self, p, r, pm, k, zoom):
        box = r.adjusted(18, 18, -18, -18)
        s = min(box.width() / pm.width(), box.height() / pm.height()) * zoom
        w, h = pm.width() * s, pm.height() * s
        img = QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)
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
            self.draw_pic(p, r, self.pm, t, 0.96 + 0.04 * t)
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
        p.end()


class LibList(QListWidget):
    """Плитки библиотеки: Ctrl+колесо меняет размер, перетаскивание отдаёт файлы другим программам.
    Здесь же живут анимации плиток: наведение (hover_amount) и проявление после загрузки (fade_amount)."""
    zoom = pyqtSignal(int)
    FADE = 0.28                             # секунд на проявление загруженной плитки

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
        self.shimmer = False                    # на экране есть ещё не загруженные плитки - перелив
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
            v += (want - v) * 0.28              # плавно догоняет цель
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
        self.shimmer = False                    # рисовальщик снова поднимет, если заглушки ещё видны
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
        if not self.count() and self.empty:      # пустая заглушка: значок и пояснение
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            vr = self.viewport().rect()
            ic = lib_pix(self.empty_icon, 96)
            y = vr.center().y() - 70
            if not ic.isNull():
                p.setOpacity(0.55)
                p.drawPixmap(QRectF(vr.center().x() - 40, y, 80, 80), ic, QRectF(ic.rect()))
                p.setOpacity(1)
            p.setPen(QColor(C["dim"]))
            p.drawText(QRectF(vr.x() + 30, y + 96, vr.width() - 60, 80),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self.empty)
            p.end()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom.emit(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        dy = e.angleDelta().y()
        if not dy or e.pixelDelta().y():        # тачпад крутит сам и плавно
            super().wheelEvent(e)
            return
        bar = self.verticalScrollBar()          # колесо - плавный разгон к цели, а не скачок
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
            drag.setPixmap(pm.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.CopyAction)     # только копия: проводник не должен уносить файл из библиотеки
