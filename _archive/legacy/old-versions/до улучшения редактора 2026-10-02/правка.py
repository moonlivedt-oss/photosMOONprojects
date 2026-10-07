"""Редактор картинки. Правка - рецепт (цвет + шаги): он показывается на уменьшенной копии сразу,
а при сохранении применяется к полному размеру в фоне, по ядрам.
«Сохранить» уносит оригинал в «_исходники/правка <дата>» (Ctrl+Z в окне возвращает), «Сохранить копию»
кладёт новый файл рядом, а после перекраски можно сохранить в папку новой палитры рядом с исходной
(так набор, сделанный в одной палитре, появляется в другой без генерации).
Несколько выбранных картинок - один рецепт на все. Рецепты можно сохранять и применять одной кнопкой
(в том числе к кускам листа во входящих).
Вкладки: Основное (поворот, обрезка, размер), Цвет (коррекция, перекраска в палитру), Фон (убрать фон,
кайма, кисть, обводка, квадрат), Эффекты (тень, свечение, скругление), Рецепты.
Холст: колесо - увеличение под курсором, правая или средняя кнопка - двигать, двойной щелчок - целиком."""
import os
import shutil
import time

import картинки as K
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from окно import промпты
from окно.виджеты import flat, key
from окно.миниатюры import lib_icon, to_qimage
from окно.общее import LIB, SOURCES, bg, human, in_main, parallel, unique
from окно.оформление import C

PROXY = 1200                                # сторона копии для живого предпросмотра
RATIOS = [("Свободно", None), ("1:1", 1.0), ("4:3", 4 / 3), ("3:2", 1.5), ("16:9", 16 / 9),
          ("3:4", 3 / 4), ("9:16", 9 / 16)]
NAMES = {"rotate": "поворот", "flip": "отражение", "crop": "обрезка", "trim": "поля срезаны",
         "nobg": "фон убран", "outline": "обводка", "square": "квадрат", "resize": "размер",
         "recolor": "перекраска", "defringe": "кайма убрана", "brush": "кисть", "shadow": "тень",
         "glow": "свечение", "round": "скругление", "center": "квадрат по центру"}

# Рецепты из коробки: имя, шаги. Размеры в пикселях - для кусков 256 px (так режутся листы).
RECIPES = [
    ("Наклейка: убрать фон, кайма, обводка, квадрат",
     [dict(op="nobg", tol=38), dict(op="defringe", px=1), dict(op="outline", px=8), dict(op="square", pad=0.06)]),
    ("Иконка: срезать поля и в квадрат", [dict(op="trim"), dict(op="square", pad=0.06)]),
    ("Чистый край: убрать кайму", [dict(op="defringe", px=1)]),
    ("Карточка: скругление и тень", [dict(op="round", rad=0.08), dict(op="shadow", dx=4, dy=6, blur=8, a=0.45)]),
    ("Аватар: круг", [dict(op="center"), dict(op="round", rad=0.5)]),
]


def recipes(cfg):
    """[(имя, {ops, adj}, своё ли)] - из коробки и сохранённые."""
    out = [(n, dict(ops=o, adj={}), False) for n, o in RECIPES]
    out += [(n, r, True) for n, r in sorted(cfg.get("recipes", {}).items())]
    return out


def recipe_by_name(cfg, name):
    for n, r, _own in recipes(cfg):
        if n == name:
            return r
    return None


def swatch_icon(colors, w=40, h=14):
    pm = QPixmap(w, h)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)
    p.setClipPath(path)
    n = max(1, len(colors))
    for i, c in enumerate(colors):
        p.fillRect(QRectF(i * w / n, 0, w / n + 1, h), QColor(c))
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- холст
class Canvas(QWidget):
    """Картинка на шахматке. Колесо - увеличение под курсором, правая/средняя кнопка - двигать,
    двойной щелчок - снова целиком. Режимы: кадрирование (рамка: новая, двигать, уголки) и кисть."""
    HANDLE = 9

    def __init__(self, dlg):
        super().__init__()
        self.dlg, self.pm, self.orig, self.compare = dlg, None, None, False
        self.cropping, self.crop, self.ratio, self.drag = False, None, None, None
        self.brushing, self.stroke, self.radius, self.cursor_at = None, [], 24, None
        self.zoom, self.off, self.pan = 1.0, QPointF(0, 0), None
        self.busy = False
        self.setMinimumSize(420, 360)
        self.setMouseTracking(True)
        chk = QPixmap(16, 16)
        chk.fill(QColor("#1f1f29"))
        p = QPainter(chk)
        p.fillRect(0, 0, 8, 8, QColor("#2a2a36"))
        p.fillRect(8, 8, 8, 8, QColor("#2a2a36"))
        p.end()
        self.chk = chk

    def image_rect(self, pm=None):
        pm = pm or self.pm
        if not pm or pm.isNull():
            return QRectF()
        box = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        k = min(box.width() / pm.width(), box.height() / pm.height()) * self.zoom
        w, h = pm.width() * k, pm.height() * k
        return QRectF(box.center().x() - w / 2 + self.off.x(), box.center().y() - h / 2 + self.off.y(), w, h)

    def reset_view(self):
        self.zoom, self.off = 1.0, QPointF(0, 0)
        self.update()

    def wheelEvent(self, e):
        if not self.pm:
            return
        new = max(1.0, min(16.0, self.zoom * (1.25 if e.angleDelta().y() > 0 else 0.8)))
        c = e.position() - QPointF(self.width() / 2, self.height() / 2)
        self.off = c - (c - self.off) * (new / self.zoom)       # точка под курсором остаётся на месте
        if new == 1.0:
            self.off = QPointF(0, 0)
        self.zoom = new
        self.dlg.zoom_changed(new)
        self.update()

    # --- кадрирование
    def crop_rect(self):
        r, c = self.image_rect(), self.crop
        return QRectF(r.x() + c[0] * r.width(), r.y() + c[1] * r.height(),
                      (c[2] - c[0]) * r.width(), (c[3] - c[1]) * r.height())

    def to_norm(self, pos, clamp=True):
        r = self.image_rect()
        x, y = (pos.x() - r.x()) / r.width(), (pos.y() - r.y()) / r.height()
        return (min(1.0, max(0.0, x)), min(1.0, max(0.0, y))) if clamp else (x, y)

    def corner_at(self, pos):
        if not self.crop:
            return None
        cr = self.crop_rect()
        for name, pt in (("tl", cr.topLeft()), ("tr", cr.topRight()), ("bl", cr.bottomLeft()), ("br", cr.bottomRight())):
            if abs(pos.x() - pt.x()) <= self.HANDLE + 3 and abs(pos.y() - pt.y()) <= self.HANDLE + 3:
                return name
        return None

    def fix_ratio(self, ax, ay, x1, y1):
        """Подогнать рамку под пропорцию: ширина главная, высота следует (в пикселях картинки)."""
        if not self.ratio or not self.pm:
            return x1, y1
        W, H = self.pm.width(), self.pm.height()
        sx = 1 if x1 >= ax else -1
        sy = 1 if y1 >= ay else -1
        w = abs(x1 - ax)
        h = w * W / (H * self.ratio)
        lim_y = (1 - ay) if sy > 0 else ay
        lim_x = (1 - ax) if sx > 0 else ax
        if h > lim_y:                           # упёрлись в край - от высоты
            h = lim_y
            w = h * H * self.ratio / W
        if w > lim_x:
            w = lim_x
            h = w * W / (H * self.ratio)
        return ax + sx * w, ay + sy * h

    def set_ratio(self, ratio):
        self.ratio = ratio
        if self.cropping and self.pm:
            self.reset_crop()

    def reset_crop(self):
        """Рамка по умолчанию: вся картинка или самая большая по центру с нужной пропорцией."""
        if not self.ratio:
            self.crop = (0.0, 0.0, 1.0, 1.0)
        else:
            W, H = self.pm.width(), self.pm.height()
            w, h = 1.0, W / (H * self.ratio)
            if h > 1:
                w, h = H * self.ratio / W, 1.0
            self.crop = ((1 - w) / 2, (1 - h) / 2, (1 + w) / 2, (1 + h) / 2)
        self.update()
        self.dlg.crop_changed()

    # --- мышь
    def mousePressEvent(self, e):
        if not self.pm:
            return
        pos = e.position()
        if e.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self.pan = (pos, QPointF(self.off))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.brushing:
            self.stroke = [self.to_norm(pos, clamp=False)]
            self.update()
            return
        if not self.cropping:
            return
        corner = self.corner_at(pos)
        if corner:
            x0, y0, x1, y1 = self.crop
            self.drag = ("corner", x1 if "l" in corner else x0, y1 if "t" in corner else y0)
        elif self.crop and self.crop_rect().contains(pos):
            self.drag = ("move", self.to_norm(pos), self.crop)
        else:
            nx, ny = self.to_norm(pos)
            self.drag = ("corner", nx, ny)
            self.crop = (nx, ny, nx, ny)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.pan:
            self.off = self.pan[1] + (pos - self.pan[0])
            self.update()
            return
        if self.brushing:
            self.cursor_at = pos
            if self.stroke and e.buttons() & Qt.MouseButton.LeftButton:
                self.stroke.append(self.to_norm(pos, clamp=False))
            self.update()
            return
        if not self.cropping:
            return
        if not self.drag:
            c = self.corner_at(pos)
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if c in ("tl", "br") else
                           Qt.CursorShape.SizeBDiagCursor if c in ("tr", "bl") else
                           Qt.CursorShape.SizeAllCursor if self.crop and self.crop_rect().contains(pos) else
                           Qt.CursorShape.CrossCursor)
            return
        if self.drag[0] == "move":
            (sx, sy), (x0, y0, x1, y1) = self.drag[1], self.drag[2]
            nx, ny = self.to_norm(pos)
            dx = min(1 - x1, max(-x0, nx - sx))
            dy = min(1 - y1, max(-y0, ny - sy))
            self.crop = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        else:
            ax, ay = self.drag[1], self.drag[2]
            nx, ny = self.fix_ratio(ax, ay, *self.to_norm(pos))
            self.crop = (min(ax, nx), min(ay, ny), max(ax, nx), max(ay, ny))
        self.update()
        self.dlg.crop_changed()

    def mouseReleaseEvent(self, e):
        if self.pan and e.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self.pan = None
            self.setCursor(Qt.CursorShape.CrossCursor if self.brushing or self.cropping else Qt.CursorShape.ArrowCursor)
            return
        if self.brushing and self.stroke:
            r = self.image_rect()
            self.dlg.add_stroke(self.stroke, self.radius / max(r.width(), r.height()))
            self.stroke = []
            return
        if self.drag and self.crop and (self.crop[2] - self.crop[0] < 0.01 or self.crop[3] - self.crop[1] < 0.01):
            self.reset_crop()                   # щелчок без протяжки - рамка на всю картинку
        self.drag = None

    def leaveEvent(self, _e):
        self.cursor_at = None
        self.update()

    def mouseDoubleClickEvent(self, _e):
        if self.cropping:
            self.dlg.apply_crop()
        elif not self.brushing:
            self.reset_view()
            self.dlg.zoom_changed(1.0)

    # --- рисование
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 3)   # крупно - пиксели чёткие
        p.fillRect(self.rect(), QColor("#111117"))
        pm = self.orig if self.compare and self.orig else self.pm
        if not pm or pm.isNull():
            p.setPen(QColor(C["dim"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Открываю картинку...")
            p.end()
            return
        r = self.image_rect(pm)
        p.fillRect(r, QBrush(self.chk))
        p.drawPixmap(r, pm, QRectF(pm.rect()))
        if self.compare:
            self.tag(p, "Было")
        elif self.busy:
            self.tag(p, "Считаю...")
        if self.cropping and self.crop and not self.compare:
            self.paint_crop(p, r)
        if self.brushing and not self.compare:
            col = QColor(C["acc2"] if self.brushing == "erase" else C["teal"])
            if len(self.stroke) > 1:
                pen = QPen(QColor(col.red(), col.green(), col.blue(), 110), self.radius * 2)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                path = QPainterPath(QPointF(r.x() + self.stroke[0][0] * r.width(), r.y() + self.stroke[0][1] * r.height()))
                for x, y in self.stroke[1:]:
                    path.lineTo(r.x() + x * r.width(), r.y() + y * r.height())
                p.drawPath(path)
            if self.cursor_at:
                p.setPen(QPen(col, 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(self.cursor_at, self.radius, self.radius)
        p.end()

    def paint_crop(self, p, r):
        cr = self.crop_rect()
        shade = QColor(0, 0, 0, 150)
        for part in (QRectF(r.left(), r.top(), r.width(), cr.top() - r.top()),
                     QRectF(r.left(), cr.bottom(), r.width(), r.bottom() - cr.bottom()),
                     QRectF(r.left(), cr.top(), cr.left() - r.left(), cr.height()),
                     QRectF(cr.right(), cr.top(), r.right() - cr.right(), cr.height())):
            p.fillRect(part, shade)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))       # третьи - для композиции
        for i in (1, 2):
            x = cr.left() + cr.width() * i / 3
            y = cr.top() + cr.height() * i / 3
            p.drawLine(QPointF(x, cr.top()), QPointF(x, cr.bottom()))
            p.drawLine(QPointF(cr.left(), y), QPointF(cr.right(), y))
        p.setPen(QPen(QColor(C["acc"]), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(cr)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        for pt in (cr.topLeft(), cr.topRight(), cr.bottomLeft(), cr.bottomRight()):
            p.drawRoundedRect(QRectF(pt.x() - 5, pt.y() - 5, 10, 10), 3, 3)

    def tag(self, p, text):
        fm = p.fontMetrics()
        box = QRectF(12, 12, fm.horizontalAdvance(text) + 18, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(21, 21, 28, 220))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor(C["text"]))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


# ---------------------------------------------------------------- сохранение
def save_edits(paths, ops, adj, copy, report, target=None):
    """В фоне, по ядрам: рецепт ко всем файлам. target - папка, куда положить новые файлы с теми же
    именами (перекраска в другую палитру); copy - новый файл рядом; иначе оригинал уезжает
    в _исходники/правка <дата>. Возвращает (шаги для Ctrl+Z, [(было, стало)], [ошибки])."""
    arch = os.path.join(SOURCES, "правка " + time.strftime("%Y-%m-%d"))
    steps, done, bad = [], [], []
    items = [(p, dict(ops=ops, adj=adj)) for p in paths]
    if target:
        os.makedirs(target, exist_ok=True)
    for i, (p, res) in enumerate(parallel(K.job_edit, items)):
        report((i, len(items), os.path.basename(p)))
        try:
            if isinstance(res, Exception):
                raise res
            data, fmt, _size = res
            stem = os.path.splitext(p)[0]
            if target:
                new = unique(os.path.join(target, os.path.basename(stem) + "." + fmt))
            elif copy:
                new = unique(stem + " правка." + fmt)
            else:
                keep = unique(os.path.join(arch, os.path.relpath(p, LIB)))
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.move(p, keep)
                steps.append(("move", p, keep))
                new = stem + "." + fmt
                if os.path.exists(new):
                    new = unique(new)
            with open(new, "wb") as fh:
                fh.write(data)
            steps.append(("new", new))
            done.append((p, new))
        except Exception as e:
            bad.append("%s: %s" % (os.path.basename(p), e))
    return steps, done, bad


# ---------------------------------------------------------------- окно
class EditDialog(QDialog):
    def __init__(self, parent, win, paths, on_saved=None, ops=None, target=None):
        super().__init__(parent)
        self.win, self.cfg, self.on_saved, self.target = win, win.cfg, on_saved, target
        self.paths = [p for p in paths if K.fmt_of(p) in K.EDITABLE and not K.is_animated(p)]
        self.skipped = len(paths) - len(self.paths)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Правка" + (": %d шт." % len(self.paths) if len(self.paths) > 1 else ""))
        self.resize(1240, 800)
        self.ops, self.adj = [dict(o) for o in (ops or [])], {k: 0 for k, _t in K.ADJ}
        self.undo_stack, self.redo_stack = [], []
        self.base = None                    # уменьшенная копия текущего файла (PIL)
        self.scale, self.full, self.cur = 1.0, (1, 1), (1, 1)
        self.gen, self.saving, self.idx = 0, False, 0
        self.glow_color = "#ffffff"

        self.canvas = Canvas(self)
        self.file_lbl = QLabel(objectName="dim")
        prev, nxt = flat("<", lambda: self.step_file(-1), "Предыдущий файл"), flat(">", lambda: self.step_file(1), "Следующий")
        self.zoom_lbl = flat("100%", self.canvas_fit, "Двойной щелчок по картинке - целиком")
        top = QHBoxLayout()
        top.addWidget(prev)
        top.addWidget(self.file_lbl, 1)
        top.addWidget(nxt)
        top.addWidget(self.zoom_lbl)
        for w in (prev, nxt):
            w.setVisible(len(self.paths) > 1)
        self.size_lbl = QLabel(objectName="dim")
        hint = QLabel("Колесо - увеличить, правая кнопка - двигать.  Удерживайте «Сравнить» или \\ - как было.  "
                      "Ctrl+Z / Ctrl+Y - шаг", objectName="dim")
        left = QVBoxLayout()
        left.addLayout(top)
        left.addWidget(self.canvas, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        bottom.addWidget(self.size_lbl)
        left.addLayout(bottom)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setUsesScrollButtons(False)       # все пять вкладок видны сразу
        self.tabs.tabBar().setExpanding(True)
        self.tabs.setStyleSheet("QTabBar::tab{padding:6px 7px;margin:6px 1px 4px 1px}")
        self.tabs.addTab(self.page_main(), "Основное")
        self.tabs.addTab(self.page_color(), "Цвет")
        self.tabs.addTab(self.page_bg(), "Фон")
        self.tabs.addTab(self.page_fx(), "Эффекты")
        self.tabs.addTab(self.page_recipes(), "Рецепты")
        self.tabs.currentChanged.connect(lambda _i: self.set_brush(None))

        # --- шаги и сохранение
        self.steps_lbl = QLabel(objectName="dim", wordWrap=True)
        self.undo_b = flat("Шаг назад", self.undo, "Ctrl+Z")
        self.redo_b = flat("Шаг вперёд", self.redo, "Ctrl+Y")
        self.reset_b = flat("Всё сначала", self.reset_all)
        hist = QHBoxLayout()
        for w in (self.undo_b, self.redo_b, self.reset_b):
            hist.addWidget(w)
        hist.addStretch(1)
        self.cmp_b = QPushButton("Сравнить")
        self.cmp_b.setToolTip("Пока нажата - видно, как было (клавиша \\)")
        self.cmp_b.pressed.connect(lambda: self.show_orig(True))
        self.cmp_b.released.connect(lambda: self.show_orig(False))
        self.save_b = QPushButton(lib_icon("paint-brush"), "", objectName="primary")
        self.save_b.clicked.connect(lambda: self.save("replace"))
        self.pal_b = QPushButton(objectName="primary")
        self.pal_b.setToolTip("Новые файлы с теми же именами - в папку этой палитры рядом с исходной")
        self.pal_b.clicked.connect(lambda: self.save("palette"))
        self.copy_b = QPushButton("Сохранить копию")
        self.copy_b.setToolTip("Новый файл рядом: «<имя> правка»")
        self.copy_b.clicked.connect(lambda: self.save("copy"))
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        sv = QHBoxLayout()
        sv.addWidget(self.cmp_b)
        sv.addWidget(self.copy_b)
        sv.addWidget(close)

        right = QVBoxLayout()
        right.addWidget(self.tabs, 1)
        right.addWidget(self.steps_lbl)
        right.addLayout(hist)
        right.addWidget(self.pal_b)
        right.addWidget(self.save_b)
        right.addLayout(sv)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(380)
        lay = QHBoxLayout(self)
        lay.addLayout(left, 1)
        lay.addWidget(rw)

        self.timer = QTimer(self, singleShot=True, interval=40)     # слайдер крутят - считаем по паузе
        self.timer.timeout.connect(self.render)
        key("Ctrl+Z", self, self.undo)
        key("Ctrl+Y", self, self.redo)
        key("Ctrl+Shift+Z", self, self.redo)
        key("Ctrl+S", self, lambda: self.save("replace"))
        key("[", self, lambda: self.brush_size(-4))
        key("]", self, lambda: self.brush_size(4))
        self.update_ui()
        self.open_file()

    # ---------------------------------------------------------------- вкладки
    @staticmethod
    def box(title, lay):
        b = QGroupBox(title)
        b.setLayout(lay)
        return b

    @staticmethod
    def page(*widgets):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 8, 4, 4)
        for x in widgets:
            v.addWidget(x)
        v.addStretch(1)
        return w

    def button(self, text, fn, tip=""):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.clicked.connect(fn)
        return b

    def page_main(self):
        g1 = QGridLayout()
        for i, (text, fn) in enumerate((("Влево", lambda: self.add(op="rotate", deg=270)),
                                        ("Вправо", lambda: self.add(op="rotate", deg=90)),
                                        ("Отразить", lambda: self.add(op="flip", dir="h")),
                                        ("Вверх ногами", lambda: self.add(op="flip", dir="v")))):
            g1.addWidget(self.button(text, fn), i // 2, i % 2)
        self.ratio = QComboBox()
        for t, v in RATIOS:
            self.ratio.addItem(t, v)
        self.ratio.currentIndexChanged.connect(lambda _i: self.canvas.set_ratio(self.ratio.currentData()))
        self.crop_btn = self.button("Кадрировать", self.toggle_crop,
                                    "Рамка на картинке: тянуть, двигать, уголки. Enter или двойной щелчок - обрезать")
        self.crop_ok = QPushButton("Обрезать", objectName="primary")
        self.crop_ok.clicked.connect(self.apply_crop)
        self.crop_ok.hide()
        v2 = QVBoxLayout()
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Пропорции"))
        r2.addWidget(self.ratio, 1)
        v2.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(self.crop_btn)
        r3.addWidget(self.crop_ok)
        v2.addLayout(r3)
        v2.addWidget(self.button("Срезать пустые поля", lambda: self.add(op="trim"),
                                 "Убрать прозрачную рамку вокруг рисунка"))
        self.side = QSpinBox(minimum=16, maximum=8192, singleStep=64, suffix=" px")
        self.side.setToolTip("Длинная сторона картинки после правки")
        r5 = QHBoxLayout()
        r5.addWidget(self.side, 1)
        r5.addWidget(self.button("Изменить размер", lambda: self.add(op="resize", size=self.side.value())))
        return self.page(self.box("Поворот и отражение", g1), self.box("Обрезка", v2), self.box("Размер", r5))

    def page_color(self):
        g3 = QGridLayout()
        self.sliders = {}
        for i, (k, text) in enumerate(K.ADJ):
            s = QSlider(Qt.Orientation.Horizontal, minimum=-180 if k == "hue" else -100,
                        maximum=180 if k == "hue" else 100)
            val = QLabel("0", objectName="dim")
            val.setFixedWidth(34)
            lbl = QPushButton(text, objectName="flat")
            lbl.setToolTip("Щелчок - сбросить")
            lbl.clicked.connect(lambda _c=False, sl=s: sl.setValue(0))
            s.sliderPressed.connect(self.remember)
            s.valueChanged.connect(lambda v, kk=k, vl=val: self.adj_changed(kk, v, vl))
            g3.addWidget(lbl, i, 0)
            g3.addWidget(s, i, 1)
            g3.addWidget(val, i, 2)
            self.sliders[k] = (s, val)
        g3.addWidget(flat("Сбросить цвет", self.reset_color), len(K.ADJ), 1)

        self.pal = QComboBox()
        for pid, name, folder, cols in промпты.palettes():
            self.pal.addItem(swatch_icon(cols), name, (pid, folder, cols))
        self.pal.setIconSize(QSize(40, 14))
        self.strength = QSpinBox(minimum=10, maximum=100, value=100, suffix=" %")
        self.strength.setToolTip("Сила перекраски: меньше - сквозь палитру видны прежние цвета")
        v = QVBoxLayout()
        v.addWidget(self.pal)
        r = QHBoxLayout()
        r.addWidget(QLabel("Сила"))
        r.addWidget(self.strength)
        r.addWidget(self.button("Перекрасить", self.add_recolor,
                                "Тёмное - в тёмный цвет палитры, светлое - в светлый (градиентная карта)"), 1)
        v.addLayout(r)
        note = QLabel("Если картинка лежит в папке палитры (например «04 Иконки/Космос/Tokyo Night»), "
                      "после перекраски можно сохранить её в папку новой палитры рядом.", objectName="dim", wordWrap=True)
        v.addWidget(note)
        if not self.pal.count():
            v.addWidget(QLabel("Палитры берутся из Промпты.html - страница не найдена", objectName="dim"))
        return self.page(self.box("Цвет", g3), self.box("Перекрасить в палитру", v))

    def page_bg(self):
        self.tol = QSpinBox(minimum=5, maximum=120, value=38)
        self.tol.setToolTip("Насколько цвет может отличаться от фона по краям, чтобы считаться фоном")
        self.fringe = QSpinBox(minimum=0, maximum=4, value=1, suffix=" px")
        self.fringe.setToolTip("На сколько пикселей поджать край; цвет края берётся у рисунка, а не у старого фона")
        self.px = QSpinBox(minimum=1, maximum=60, value=8, suffix=" px")
        self.pad = QSpinBox(minimum=0, maximum=40, value=6, suffix=" %")
        g4 = QGridLayout()
        rows = ((self.button("Убрать фон", lambda: self.add(op="nobg", tol=self.tol.value()),
                             "Однотонный фон, связанный с краями; белые детали внутри рисунка остаются"), self.tol),
                (self.button("Убрать кайму", lambda: self.add(op="defringe", px=self.fringe.value()),
                             "Светлый ореол от старого фона вокруг рисунка"), self.fringe),
                (self.button("Обводка", lambda: self.add(op="outline", px=self.px.value()),
                             "Белая обводка вокруг рисунка, как у наклеек (нужна прозрачность)"), self.px),
                (self.button("Квадрат с полями", lambda: self.add(op="square", pad=self.pad.value() / 100),
                             "Рисунок по центру квадрата, вокруг - прозрачные поля"), self.pad))
        for i, (b, spin) in enumerate(rows):
            g4.addWidget(b, i, 0)
            g4.addWidget(spin, i, 1)
        self.erase_b = self.button("Стереть", lambda: self.set_brush("erase"), "Кисть: стереть до прозрачного")
        self.restore_b = self.button("Вернуть", lambda: self.set_brush("restore"),
                                     "Кисть: вернуть стёртое (например, лишнее, что съело «Убрать фон»)")
        for b in (self.erase_b, self.restore_b):
            b.setCheckable(True)
        self.bsize = QSlider(Qt.Orientation.Horizontal, minimum=3, maximum=120, value=24)
        self.bsize.setToolTip("Размер кисти на экране ( [ и ] )")
        self.bsize.valueChanged.connect(self.brush_size_set)
        g5 = QGridLayout()
        g5.addWidget(self.erase_b, 0, 0)
        g5.addWidget(self.restore_b, 0, 1)
        g5.addWidget(QLabel("Размер"), 1, 0)
        g5.addWidget(self.bsize, 1, 1)
        g5.addWidget(QLabel("Кисть рисует по экрану: увеличьте колесом, чтобы поправить мелочь.",
                            objectName="dim", wordWrap=True), 2, 0, 1, 2)
        return self.page(self.box("Фон и наклейка", g4), self.box("Кисть", g5))

    def page_fx(self):
        self.sh_size = QSpinBox(minimum=1, maximum=20, value=3, suffix=" %")
        self.sh_size.setToolTip("Размытие и сдвиг тени - доля длинной стороны")
        self.sh_a = QSpinBox(minimum=10, maximum=100, value=45, suffix=" %")
        self.glow_r = QSpinBox(minimum=1, maximum=20, value=3, suffix=" %")
        self.glow_btn = self.button("", self.pick_glow, "Цвет свечения")
        self.glow_btn.setFixedWidth(44)
        self.paint_glow_btn()
        self.rad = QSpinBox(minimum=1, maximum=50, value=10, suffix=" %")
        self.rad.setToolTip("Радиус - доля короткой стороны; 50% - круг или «таблетка»")
        g = QGridLayout()
        g.addWidget(self.button("Тень", self.add_shadow, "Мягкая тень вниз-вправо по форме рисунка"), 0, 0)
        g.addWidget(self.sh_size, 0, 1)
        g.addWidget(self.sh_a, 0, 2)
        g.addWidget(self.button("Свечение", self.add_glow, "Ореол вокруг рисунка"), 1, 0)
        g.addWidget(self.glow_r, 1, 1)
        g.addWidget(self.glow_btn, 1, 2)
        g.addWidget(self.button("Скруглить углы", lambda: self.add(op="round", rad=self.rad.value() / 100)), 2, 0)
        g.addWidget(self.rad, 2, 1)
        return self.page(self.box("Тень, свечение, углы", g),
                         QLabel("Тень и свечение расширяют холст, чтобы им хватило места.", objectName="dim", wordWrap=True))

    def page_recipes(self):
        self.rec = QComboBox()
        self.fill_recipes()
        v = QVBoxLayout()
        v.addWidget(self.rec)
        r = QHBoxLayout()
        r.addWidget(self.button("Применить", self.apply_recipe, "Шаги рецепта - вместо текущих (Ctrl+Z вернёт)"), 1)
        r.addWidget(self.button("Добавить в конец", lambda: self.apply_recipe(append=True)), 1)
        v.addLayout(r)
        r2 = QHBoxLayout()
        r2.addWidget(self.button("Сохранить текущие шаги...", self.save_recipe,
                                 "Мазки кисти в рецепт не попадают - они у каждой картинки свои"), 1)
        self.del_b = self.button("Удалить", self.delete_recipe)
        r2.addWidget(self.del_b)
        v.addLayout(r2)
        self.rec_lbl = QLabel(objectName="dim", wordWrap=True)
        v.addWidget(self.rec_lbl)
        self.rec.currentIndexChanged.connect(self.show_recipe)
        self.show_recipe()
        return self.page(self.box("Рецепты", v),
                         QLabel("Рецепт можно выбрать и во входящих («Правка кусков») - тогда каждый кусок листа "
                                "выходит уже готовым.", objectName="dim", wordWrap=True))

    # ---------------------------------------------------------------- файл
    def step_file(self, d):
        if len(self.paths) > 1:
            self.idx = (self.idx + d) % len(self.paths)
            self.open_file()

    def open_file(self):
        if not self.paths:
            self.file_lbl.setText("Эти файлы не правятся (svg, анимация или ico)")
            for b in (self.save_b, self.copy_b, self.pal_b):
                b.setEnabled(False)
            return
        p = self.paths[self.idx]
        self.file_lbl.setText(os.path.relpath(p, LIB) + ("   (%d из %d)" % (self.idx + 1, len(self.paths))
                                                        if len(self.paths) > 1 else ""))
        self.base = None
        self.canvas.pm = self.canvas.orig = None
        self.canvas.reset_view()
        self.gen += 1
        gen = self.gen

        def work():
            im = K.load(p)
            full = im.size
            if max(im.size) > PROXY:
                im.thumbnail((PROXY, PROXY), Image.LANCZOS)
            return im, full

        def done(res):
            if sip.isdeleted(self) or gen != self.gen:
                return
            if isinstance(res, Exception):
                self.file_lbl.setText("Не открылось: %s" % res)
                return
            self.base, self.full = res
            self.scale = self.base.width / self.full[0]
            self.canvas.orig = QPixmap.fromImage(to_qimage(self.base))
            if self.side.value() == self.side.minimum():
                self.side.setValue(max(self.full))
            self.render()
            self.update_ui()

        bg(work, done)

    # ---------------------------------------------------------------- рецепт правки
    def snapshot(self):
        return [dict(o) for o in self.ops], dict(self.adj)

    def remember(self):
        self.undo_stack = (self.undo_stack + [self.snapshot()])[-60:]
        self.redo_stack = []

    def add(self, **op):
        if self.canvas.cropping:
            self.toggle_crop()
        self.remember()
        if op["op"] == "rotate" and self.ops and self.ops[-1]["op"] == "rotate":
            deg = (self.ops[-1]["deg"] + op["deg"]) % 360       # подряд идущие повороты - один шаг
            self.ops.pop()
            if deg:
                self.ops.append(dict(op="rotate", deg=deg))
        else:
            self.ops.append(op)
        self.changed()

    def long_side(self):
        """Длинная сторона текущей картинки в полном размере (после уже сделанных шагов)."""
        return max(self.cur) if self.cur else max(self.full)

    def add_recolor(self):
        d = self.pal.currentData()
        if d:
            pid, folder, cols = d
            self.add(op="recolor", colors=cols, k=self.strength.value() / 100, pal=pid, folder=folder)

    def add_shadow(self):
        s = self.long_side() * self.sh_size.value() / 100
        self.add(op="shadow", dx=round(s * 0.5), dy=round(s * 0.8), blur=round(s, 1), a=self.sh_a.value() / 100)

    def add_glow(self):
        self.add(op="glow", r=round(self.long_side() * self.glow_r.value() / 100, 1), color=self.glow_color, a=0.85)

    def pick_glow(self):
        c = QColorDialog.getColor(QColor(self.glow_color), self, "Цвет свечения")
        if c.isValid():
            self.glow_color = c.name()
            self.paint_glow_btn()

    def paint_glow_btn(self):
        self.glow_btn.setStyleSheet("background:%s;border:1px solid %s" % (self.glow_color, C["line2"]))

    def add_stroke(self, pts, r):
        mode = self.canvas.brushing
        self.add(op="brush", mode=mode, r=round(r, 5), pts=[(round(x, 5), round(y, 5)) for x, y in pts])
        self.canvas.brushing = mode             # add() не выходит из режима кисти

    def adj_changed(self, k, v, lbl):
        lbl.setText(str(v))
        if self.adj[k] != v:
            if not any(s.isSliderDown() for s, _l in self.sliders.values()):
                self.remember()             # колесо или клавиши - каждое изменение отдельным шагом
            self.adj[k] = v
            self.changed()

    def reset_color(self):
        if any(self.adj.values()):
            self.remember()
            self.set_adj({k: 0 for k in self.adj})
            self.changed()

    def set_adj(self, adj):
        self.adj = {k: adj.get(k, 0) for k, _t in K.ADJ}
        for k, (s, lbl) in self.sliders.items():
            s.blockSignals(True)
            s.setValue(self.adj[k])
            s.blockSignals(False)
            lbl.setText(str(self.adj[k]))

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.snapshot())
            ops, adj = self.undo_stack.pop()
            self.ops = ops
            self.set_adj(adj)
            self.changed()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.snapshot())
            ops, adj = self.redo_stack.pop()
            self.ops = ops
            self.set_adj(adj)
            self.changed()

    def reset_all(self):
        if self.dirty():
            self.remember()
            self.ops = []
            self.set_adj({})
            self.changed()

    def dirty(self):
        return bool(self.ops or any(self.adj.values()))

    def changed(self):
        self.update_ui()
        self.timer.start()

    def palette_target(self):
        """Папка новой палитры рядом с исходной, если после перекраски это имеет смысл."""
        if self.target:
            return self.target
        rec = [o for o in self.ops if o["op"] == "recolor" and o.get("folder")]
        if not rec or not self.paths:
            return None
        parent = os.path.dirname(self.paths[0])
        if os.path.basename(parent) not in промпты.pal_by_folder() or os.path.basename(parent) == rec[-1]["folder"]:
            return None
        if any(os.path.dirname(p) != parent for p in self.paths):
            return None
        return os.path.join(os.path.dirname(parent), rec[-1]["folder"])

    def update_ui(self):
        parts = [NAMES.get(o["op"], o["op"]) for o in self.ops]
        if any(self.adj.values()):
            parts.insert(0, "цвет")
        self.steps_lbl.setText("Сделано: " + ", ".join(parts) if parts else "Правок пока нет")
        self.undo_b.setEnabled(bool(self.undo_stack))
        self.redo_b.setEnabled(bool(self.redo_stack))
        self.reset_b.setEnabled(self.dirty())
        n = len(self.paths)
        self.save_b.setText("Сохранить" if n <= 1 else "Применить ко всем (%d)" % n)
        self.copy_b.setText("Сохранить копию" if n <= 1 else "Копии для всех")
        ok = self.dirty() and bool(self.paths) and not self.saving
        for b in (self.save_b, self.copy_b, self.pal_b):
            b.setEnabled(ok)
        t = self.palette_target()
        self.pal_b.setVisible(bool(t))
        if t:
            self.pal_b.setText("Сохранить в «%s»" % os.path.relpath(t, LIB).replace(os.sep, " / "))
            self.save_b.setObjectName("")       # главная кнопка - сохранить в палитру
        else:
            self.save_b.setObjectName("primary")
        self.save_b.style().unpolish(self.save_b)
        self.save_b.style().polish(self.save_b)

    # ---------------------------------------------------------------- рецепты
    def fill_recipes(self, select=None):
        self.rec.blockSignals(True)
        self.rec.clear()
        for name, r, own in recipes(self.cfg):
            self.rec.addItem(name, (r, own))
        if select:
            self.rec.setCurrentText(select)
        self.rec.blockSignals(False)

    def show_recipe(self, *_):
        d = self.rec.currentData()
        if not d:
            self.rec_lbl.setText("")
            return
        r, own = d
        parts = [NAMES.get(o["op"], o["op"]) for o in r.get("ops", [])]
        if any((r.get("adj") or {}).values()):
            parts.insert(0, "цвет")
        self.rec_lbl.setText("Шаги: " + ", ".join(parts) if parts else "Пустой рецепт")
        self.del_b.setEnabled(own)

    def apply_recipe(self, append=False):
        d = self.rec.currentData()
        if not d:
            return
        r, _own = d
        self.remember()
        ops = [dict(o) for o in r.get("ops", [])]
        self.ops = self.ops + ops if append else ops
        if not append:
            self.set_adj(r.get("adj") or {})
        self.changed()

    def save_recipe(self):
        ops = [dict(o) for o in self.ops if o["op"] != "brush"]
        if not ops and not any(self.adj.values()):
            self.win.say("Шагов пока нет - сохранять нечего")
            return
        name, ok = QInputDialog.getText(self, "Рецепт", "Название, например «Наклейка для набора»:")
        name = name.strip()
        if ok and name:
            self.cfg.setdefault("recipes", {})[name] = dict(ops=ops, adj={k: v for k, v in self.adj.items() if v})
            self.fill_recipes(name)
            self.show_recipe()
            self.win.say("Рецепт сохранён: " + name)

    def delete_recipe(self):
        d = self.rec.currentData()
        if d and d[1]:
            self.cfg.get("recipes", {}).pop(self.rec.currentText(), None)
            self.fill_recipes()
            self.show_recipe()

    # ---------------------------------------------------------------- предпросмотр
    def render(self):
        if self.base is None:
            return
        self.gen += 1
        gen, base, ops, adj, scale = self.gen, self.base, [dict(o) for o in self.ops], dict(self.adj), self.scale
        self.canvas.busy = True
        self.canvas.update()

        def done(res):
            if sip.isdeleted(self) or gen != self.gen:
                return
            self.canvas.busy = False
            if isinstance(res, Exception):
                self.steps_lbl.setText("Не получилось: %s" % res)
                self.canvas.update()
                return
            img, w, h = res
            old = self.canvas.pm.size() if self.canvas.pm else None
            self.canvas.pm = QPixmap.fromImage(img)
            if self.canvas.cropping and old != self.canvas.pm.size():     # цвет рамку не сбивает
                self.canvas.reset_crop()
            self.canvas.update()
            self.cur = (max(1, round(w / scale)), max(1, round(h / scale)))
            self.size_lbl.setText("%d × %d  (было %d × %d)" % (*self.cur, *self.full)
                                  if self.cur != tuple(self.full) else "%d × %d" % self.cur)

        def work():
            im = K.apply_edits(base, ops, adj, scale)
            return to_qimage(im), im.width, im.height

        bg(work, done)

    def show_orig(self, on):
        self.canvas.compare = on
        self.canvas.update()

    def zoom_changed(self, z):
        self.zoom_lbl.setText("%d%%" % round(z * 100))

    def canvas_fit(self):
        self.canvas.reset_view()
        self.zoom_changed(1.0)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Backslash and not e.isAutoRepeat():
            self.show_orig(True)
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.canvas.cropping:
            self.apply_crop()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Backslash and not e.isAutoRepeat():
            self.show_orig(False)
        else:
            super().keyReleaseEvent(e)

    # ---------------------------------------------------------------- кисть
    def set_brush(self, mode):
        if mode and self.canvas.cropping:
            self.toggle_crop()
        if mode == self.canvas.brushing:
            mode = None                         # повторное нажатие - выйти из кисти
        self.canvas.brushing = mode
        self.canvas.stroke = []
        self.erase_b.setChecked(mode == "erase")
        self.restore_b.setChecked(mode == "restore")
        self.canvas.setCursor(Qt.CursorShape.CrossCursor if mode else Qt.CursorShape.ArrowCursor)
        self.canvas.update()

    def brush_size(self, d):
        self.bsize.setValue(self.bsize.value() + d)

    def brush_size_set(self, v):
        self.canvas.radius = v
        self.canvas.update()

    # ---------------------------------------------------------------- кадрирование
    def toggle_crop(self):
        c = self.canvas
        if not c.cropping:
            self.set_brush(None)
        c.cropping = not c.cropping and c.pm is not None
        self.crop_btn.setText("Отмена" if c.cropping else "Кадрировать")
        self.crop_ok.setVisible(c.cropping)
        if c.cropping:
            c.ratio = self.ratio.currentData()
            c.reset_crop()
        else:
            c.crop = None
            c.setCursor(Qt.CursorShape.ArrowCursor)
        c.update()

    def crop_changed(self):
        c = self.canvas
        if c.crop and c.pm:
            w = round((c.crop[2] - c.crop[0]) * self.cur[0])
            h = round((c.crop[3] - c.crop[1]) * self.cur[1])
            self.size_lbl.setText("Рамка: %d × %d" % (w, h))

    def apply_crop(self):
        c = self.canvas.crop
        if not self.canvas.cropping or not c:
            return
        if c == (0.0, 0.0, 1.0, 1.0):
            self.toggle_crop()
            return
        self.toggle_crop()
        self.add(op="crop", box=tuple(round(v, 5) for v in c))

    # ---------------------------------------------------------------- сохранение
    def save(self, how):
        if not self.dirty() or self.saving or not self.paths:
            return
        target = self.palette_target() if how == "palette" else None
        if how == "palette" and not target:
            return
        self.saving = True
        self.update_ui()
        paths, ops, adj = list(self.paths), [dict(o) for o in self.ops], dict(self.adj)
        copy = how == "copy"
        self.steps_lbl.setText("Сохраняю...")

        def progress(v):
            if not sip.isdeleted(self):
                self.steps_lbl.setText("Сохраняю %d из %d: %s" % (v[0] + 1, v[1], v[2]))

        def done(res):
            if isinstance(res, Exception):
                if not sip.isdeleted(self):
                    self.saving = False
                    self.update_ui()
                    self.steps_lbl.setText("Не сохранилось: %s" % res)
                return
            steps, made, bad = res
            if how == "replace":
                for old, new in made:
                    if old != new:
                        self.win.moved(old, new)        # избранное и метки - за файлом, если сменился формат
            what = {"replace": "Правка", "copy": "Копии правки", "palette": "Перекрашено"}[how]
            text = "%s: %d шт." % (what, len(made)) + ("   не вышло: %d" % len(bad) if bad else "")
            if target:
                text += " в «%s»" % os.path.relpath(target, LIB)
            if how == "replace" and made:
                was = sum(os.path.getsize(s[2]) for s in steps if s[0] == "move" and os.path.exists(s[2]))
                now = sum(os.path.getsize(n) for _o, n in made if os.path.exists(n))
                text += "   (%s -> %s)" % (human(was), human(now))
            self.win.push(text, steps)
            if self.on_saved:
                self.on_saved(text + ("   Ctrl+Z - вернуть" if steps else ""))
            if bad:
                self.win.say("Не всё сохранилось: " + "; ".join(bad))
            if not sip.isdeleted(self):
                self.saving = False
                self.accept()

        bg(lambda: save_edits(paths, ops, adj, copy, lambda v: in_main(progress, v), target), done)

    def reject(self):
        if self.saving:
            return
        if self.canvas.cropping:                # Esc при рамке - отменить рамку, а не закрыть окно
            self.toggle_crop()
            return
        if self.canvas.brushing:
            self.set_brush(None)
            return
        if self.dirty() and QMessageBox.question(self, "Правка", "Закрыть без сохранения? Правки пропадут.") \
                != QMessageBox.StandardButton.Yes:
            return
        super().reject()
