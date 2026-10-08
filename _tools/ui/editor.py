"""Редактор картинки. Правка - рецепт (цвет + шаги): он показывается на уменьшенной копии сразу,
а при сохранении применяется к полному размеру в фоне, по ядрам.
«Сохранить» уносит оригинал в «_sources/edit <дата>» (Ctrl+Z в окне возвращает), «Сохранить копию»
кладёт новый файл рядом, а после перекраски можно сохранить в папку новой палитры рядом с исходной
(так набор, сделанный в одной палитре, появляется в другой без генерации).
Несколько выбранных картинок - один рецепт на все. Рецепты можно сохранять и применять одной кнопкой
(в том числе к кускам листа во входящих).
Вкладки: Основное (поворот, обрезка, размер), Цвет (коррекция, перекраска в палитру), Фон (убрать фон,
кайма, кисть, обводка, квадрат), Эффекты (тень, свечение, скругление), Рецепты.
Холст: колесо - увеличение под курсором, правая или средняя кнопка - двигать, двойной щелчок - целиком,
Ctrl+0 - целиком, Ctrl+1 - пиксель в пиксель, B - подложка, «Шторка» - было/стало рядом.
Шаги видны списком: галка выключает шаг, Del убирает, стрелки двигают выше/ниже.
У кнопок цвета правая кнопка мыши - пипетка: взять цвет с картинки."""
import os

import numpy as np
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QStyleOptionSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import imaging as K
from imaging import neural
from library import prompts
from library.batch import save_edits
from ui.animations import TabBar
from ui.common import LIB, bg, human, in_main
from ui.theme import C
from ui.thumbnails import lib_icon, to_qimage
from ui.widgets import flat, key

PROXY = 1200                                # сторона копии для живого предпросмотра
BACKDROPS = [("шахматка", None), ("тёмная", "#16161d"), ("светлая", "#e8e8ee"), ("белая", "#ffffff"),
             ("чёрная", "#000000")]
RATIOS = [("Свободно", None), ("1:1", 1.0), ("4:3", 4 / 3), ("3:2", 1.5), ("16:9", 16 / 9),
          ("3:4", 3 / 4), ("9:16", 9 / 16)]
NAMES = {"rotate": "поворот", "flip": "отражение", "crop": "обрезка", "trim": "поля срезаны",
         "nobg": "фон убран", "outline": "обводка", "square": "квадрат", "resize": "размер",
         "recolor": "перекраска", "defringe": "кайма убрана", "brush": "кисть", "shadow": "тень",
         "glow": "свечение", "round": "скругление", "center": "квадрат по центру",
         "angle": "наклон", "fill": "заливка фона", "pad": "поля", "nobg_ai": "фон убран нейросетью",
         "upscale": "увеличение нейросетью"}
ADJ_TIPS = {"shadows": "Плюс - вытянуть тёмные места, минус - сделать глубже",
            "highlights": "Плюс - ярче светлое, минус - вернуть пересвеченное",
            "sharp": "Плюс - резче, минус - размыть",
            "opacity": "Насколько прозрачнее сделать всю картинку"}

# Рецепты из коробки: имя, шаги. Размеры в пикселях - для кусков 256 px (так режутся листы).
RECIPES = [
    ("Наклейка: убрать фон, кайма, обводка, квадрат",
     [dict(op="nobg", tol=38), dict(op="defringe", px=1), dict(op="outline", px=8), dict(op="square", pad=0.06)]),
    ("Иконка: срезать поля и в квадрат", [dict(op="trim"), dict(op="square", pad=0.06)]),
    ("Чистый край: убрать кайму", [dict(op="defringe", px=1)]),
    ("Карточка: скругление и тень", [dict(op="round", rad=0.08), dict(op="shadow", dx=4, dy=6, blur=8, a=0.45)]),
    ("Аватар: круг", [dict(op="center"), dict(op="round", rad=0.5)]),
]


def step_text(o):
    """Шаг словами, с главным числом: «обводка 8 px», «поворот 90°»."""
    k, n = o["op"], NAMES.get(o["op"], o["op"])
    extra = {"rotate": lambda: "%d°" % o["deg"], "angle": lambda: "%+d°" % o["deg"],
             "outline": lambda: "%d px" % o["px"], "resize": lambda: "%d px" % o["size"],
             "nobg": lambda: "допуск %d" % o.get("tol", 38), "recolor": lambda: o.get("pal", ""),
             "fill": lambda: o.get("color", ""), "pad": lambda: "%d%%" % round(o.get("k", 0.1) * 100),
             "square": lambda: "поля %d%%" % round(o.get("pad", 0.06) * 100),
             "round": lambda: "%d%%" % round(o["rad"] * 100), "brush": lambda: "стереть" if o["mode"] == "erase" else "вернуть",
             "flip": lambda: "по горизонтали" if o["dir"] == "h" else "по вертикали",
             "upscale": lambda: "x%d" % o.get("x", 4)}.get(k)
    try:
        return n + (" " + extra() if extra and extra() else "")
    except (KeyError, TypeError):
        return n


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


class ColorButton(QPushButton):
    """Кнопка-образец цвета: щелчок - выбрать цвет."""
    def __init__(self, color, title, dlg=None):
        super().__init__()
        self.color, self.title, self.dlg = color, title, dlg
        self.setFixedWidth(44)
        self.setToolTip(title + ("\nПравая кнопка - пипетка: взять цвет с картинки" if dlg else ""))
        self.clicked.connect(self.pick)
        self.paint()

    def contextMenuEvent(self, _e):
        if self.dlg:
            self.dlg.pipette(self)

    def set(self, color):
        self.color = color
        self.paint()

    def pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, self.title)
        if c.isValid():
            self.color = c.name()
            self.paint()

    def paint(self):
        self.setStyleSheet("background:{};border:1px solid {}".format(self.color, C["line2"]))


class ZeroSlider(QSlider):
    """Ползунок, у которого заливка идёт от нуля к значению (влево - минус, вправо - плюс),
    с меткой нуля посередине. Двойной щелчок - сбросить в ноль. Ручка подрастает при наведении."""

    def __init__(self, lo, hi):
        super().__init__(Qt.Orientation.Horizontal, minimum=lo, maximum=hi)
        self.setMinimumHeight(22)
        self.hover = False
        self.setMouseTracking(True)

    def enterEvent(self, _e):
        self.hover = True
        self.update()

    def leaveEvent(self, _e):
        self.hover = False
        self.update()

    def mouseDoubleClickEvent(self, _e):
        self.setValue(max(self.minimum(), min(self.maximum(), 0)))

    def paintEvent(self, _e):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        st = self.style()
        handle = QRectF(st.subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self))
        half = handle.width() / 2
        x0, x1 = half, self.width() - half
        y = self.height() / 2

        def at(v):
            return x0 + (x1 - x0) * (v - self.minimum()) / max(1, self.maximum() - self.minimum())

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["line2"]))
        p.drawRoundedRect(QRectF(x0, y - 2, x1 - x0, 4), 2, 2)
        zero = max(self.minimum(), min(self.maximum(), 0))
        zx, vx = at(zero), handle.center().x()
        if self.minimum() < 0:                  # метка нуля
            p.setBrush(QColor(C["faint"]))
            p.drawRoundedRect(QRectF(zx - 1, y - 6, 2, 12), 1, 1)
        if abs(vx - zx) > 0.5:
            g = QLinearGradient(zx, 0, vx, 0)
            g.setColorAt(0, QColor(C["acc"]))
            g.setColorAt(1, QColor(C["acc2"]))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(QRectF(min(zx, vx), y - 2, abs(vx - zx), 4), 2, 2)
        on = self.value() != zero
        rad = 7.5 if (self.hover or self.isSliderDown()) else 6.5
        if self.isSliderDown():                 # мягкий ореол под пальцем
            p.setBrush(QColor(168, 151, 255, 60))
            p.drawEllipse(QPointF(vx, y), rad + 5, rad + 5)
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor(C["acc"] if on or self.hover else C["line2"]), 3))
        p.drawEllipse(QPointF(vx, y), rad, rad)
        p.end()


def dot_icon(a, b, side=16):
    """Кружок с градиентом - значок строки «цвет» в списке шагов (вровень с галками)."""
    pm = QPixmap(side, side)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, side, side)
    g.setColorAt(0, QColor(a))
    g.setColorAt(1, QColor(b))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(QRectF(1, 1, side - 2, side - 2), 5, 5)
    p.end()
    return QIcon(pm)


def glow_color(im):
    """Главный яркий цвет рисунка - для свечения за картинкой на холсте."""
    a = np.asarray(im.convert("RGBA").resize((48, 48))).reshape(-1, 4).astype(np.float32)
    a = a[a[:, 3] > 128][:, :3]
    if not len(a):
        return None
    sat = a.max(1) - a.min(1)
    top = a[sat >= np.percentile(sat, 75)]
    c = top.mean(0) if len(top) else a.mean(0)
    return QColor(*(int(v) for v in c))


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
        self.backdrop, self.split, self.split_drag = 0, None, False
        self.img, self.picking = None, None   # QImage результата (для пипетки и цвета под курсором)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumSize(420, 360)
        self.setMouseTracking(True)
        self.glow = None                    # главный цвет картинки - мягкое свечение за ней
        chk = QPixmap(20, 20)
        chk.fill(QColor("#1c1c26"))
        p = QPainter(chk)
        p.fillRect(0, 0, 10, 10, QColor("#252531"))
        p.fillRect(10, 10, 10, 10, QColor("#252531"))
        p.end()
        self.chk = chk

    def image_rect(self, pm=None):
        pm = pm or self.pm
        if not pm or pm.isNull():
            return QRectF()
        box = QRectF(self.rect()).adjusted(28, 28, -28, -28)
        k = min(box.width() / pm.width(), box.height() / pm.height()) * self.zoom
        w, h = pm.width() * k, pm.height() * k
        return QRectF(box.center().x() - w / 2 + self.off.x(), box.center().y() - h / 2 + self.off.y(), w, h)

    def reset_view(self):
        self.zoom, self.off = 1.0, QPointF(0, 0)
        self.update()

    def actual_size(self, full_w):
        """Пиксель картинки (полного размера) = пиксель экрана, насколько позволяет увеличение."""
        if not self.pm:
            return
        self.zoom, self.off = 1.0, QPointF(0, 0)
        self.zoom = max(1.0, min(16.0, full_w / max(1.0, self.image_rect().width())))
        self.update()

    def split_x(self):
        r = self.image_rect()
        return r.x() + self.split * r.width()

    def color_at(self, pos):
        if self.img is None or self.img.isNull():
            return None
        x, y = self.to_norm(pos, clamp=False)
        if not (0 <= x < 1 and 0 <= y < 1):
            return None
        return self.img.pixelColor(min(self.img.width() - 1, int(x * self.img.width())),
                                   min(self.img.height() - 1, int(y * self.img.height())))

    def keyPressEvent(self, e):
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if self.cropping and self.crop and self.pm and e.key() in arrows:
            dx, dy = arrows[e.key()]
            k = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1     # Shift - по 10 пикселей
            x0, y0, x1, y1 = self.crop
            dx = min(1 - x1, max(-x0, dx * k / self.pm.width()))
            dy = min(1 - y1, max(-y0, dy * k / self.pm.height()))
            self.crop = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
            self.update()
            self.dlg.crop_changed()
            return
        super().keyPressEvent(e)

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
        if self.picking:
            c = self.color_at(pos)
            if c is not None:
                self.picking(c)
            self.picking = None
            self.setCursor(Qt.CursorShape.CrossCursor if self.brushing or self.cropping else Qt.CursorShape.ArrowCursor)
            return
        if self.split is not None and not self.brushing and not self.cropping and abs(pos.x() - self.split_x()) < 12:
            self.split_drag = True
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
        self.dlg.pointer(self.to_norm(pos, clamp=False), self.color_at(pos))
        if self.split_drag:
            r = self.image_rect()
            self.split = min(1.0, max(0.0, (pos.x() - r.x()) / max(1.0, r.width())))
            self.update()
            return
        if self.picking:
            return
        if self.brushing:
            self.cursor_at = pos
            if self.stroke and e.buttons() & Qt.MouseButton.LeftButton:
                self.stroke.append(self.to_norm(pos, clamp=False))
            self.update()
            return
        if not self.cropping:
            near = self.split is not None and abs(pos.x() - self.split_x()) < 12
            self.setCursor(Qt.CursorShape.SplitHCursor if near else Qt.CursorShape.ArrowCursor)
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
        if self.split_drag:
            self.split_drag = False
            return
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
        self.dlg.pointer(None, None)
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
        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(panel, 14, 14)
        p.fillPath(clip, QColor(C["bg1"]))
        p.setPen(QPen(QColor(C["line"]), 1))
        p.drawPath(clip)
        p.setClipPath(clip)
        pm = self.orig if self.compare and self.orig else self.pm
        if not pm or pm.isNull():
            p.setPen(QColor(C["dim"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Открываю картинку...")
            p.end()
            return
        r = self.image_rect(pm)
        if self.glow is not None:               # свечение главного цвета, как в просмотре библиотеки
            g = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.95)
            c = QColor(self.glow)
            for t, al in ((0, 130), (0.55, 60), (1, 0)):
                c.setAlpha(al)
                g.setColorAt(t, c)
            p.fillRect(panel, QBrush(g))
        if self.split is not None and self.orig and not self.compare:
            x = self.split_x()
            ro = self.image_rect(self.orig)
            p.save()
            p.setClipRect(QRectF(x, 0, self.width(), self.height()))
            self.paint_back(p, r)
            p.drawPixmap(r, pm, QRectF(pm.rect()))
            p.restore()
            p.save()
            p.setClipRect(QRectF(0, 0, x, self.height()))
            self.paint_back(p, ro)
            p.drawPixmap(ro, self.orig, QRectF(self.orig.rect()))
            p.restore()
            top, bot = min(r.top(), ro.top()), max(r.bottom(), ro.bottom())
            p.setPen(QPen(QColor(255, 255, 255, 230), 2))
            p.drawLine(QPointF(x, top), QPointF(x, bot))
            mid = QPointF(x, (top + bot) / 2)
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.setBrush(QColor(C["acc"]))
            p.drawEllipse(mid, 12, 12)
            pen = QPen(QColor(C["ink"]), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            for d in (-1, 1):                   # стрелки «тяни в стороны»
                p.drawPolyline([mid + QPointF(d * 2, -4), mid + QPointF(d * 6, 0), mid + QPointF(d * 2, 4)])
            self.tag(p, "Было  |  Стало")
        else:
            self.paint_back(p, r)
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

    def paint_back(self, p, r):
        col = BACKDROPS[self.backdrop][1]
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.fillPath(path, QColor(col) if col else QBrush(self.chk))

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
        """Подпись-таблетка в левом верхнем углу холста."""
        fm = p.fontMetrics()
        box = QRectF(14, 14, fm.horizontalAdvance(text) + 30, 26)
        p.setPen(QPen(QColor(168, 151, 255, 90), 1))
        p.setBrush(QColor(20, 20, 28, 225))
        p.drawRoundedRect(box, 13, 13)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C["acc2"] if text == "Считаю..." else C["acc"]))
        p.drawEllipse(QPointF(box.left() + 13, box.center().y()), 3.5, 3.5)
        p.setPen(QColor(C["text"]))
        p.drawText(box.adjusted(16, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, text)


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

        self.canvas = Canvas(self)
        self.file_lbl = QLabel()
        self.file_lbl.setTextFormat(Qt.TextFormat.RichText)
        prev, nxt = flat("<", lambda: self.step_file(-1), "Предыдущий файл"), flat(">", lambda: self.step_file(1), "Следующий")
        self.zoom_lbl = flat("100%", self.canvas_fit, "Целиком (Ctrl+0, двойной щелчок по картинке)")
        self.one_b = flat("1:1", self.canvas_actual, "Пиксель в пиксель (Ctrl+1)")
        self.back_b = flat("Подложка: шахматка", self.cycle_backdrop, "Под прозрачным: шахматка, тёмная, светлая... (B)")
        self.split_b = flat("Шторка", self.toggle_split, "Было слева, стало справа; линию можно тянуть мышью")
        self.split_b.setCheckable(True)
        seg = QWidget(objectName="seg")          # панель инструментов холста - одна таблетка
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 3, 4, 3)
        sl.setSpacing(2)
        for w in (self.split_b, self.back_b, self.one_b, self.zoom_lbl):
            sl.addWidget(w)
        top = QHBoxLayout()
        top.setContentsMargins(4, 0, 0, 2)
        top.addWidget(prev)
        top.addWidget(self.file_lbl, 1)
        top.addWidget(nxt)
        top.addWidget(seg)
        for w in (prev, nxt):
            w.setVisible(len(self.paths) > 1)
        self.size_lbl = QLabel(objectName="chip")
        hint = QLabel("Колесо - увеличить, правая кнопка - двигать.  \\ - как было.  Ctrl+Z / Ctrl+Y - шаг",
                      objectName="dim")
        self.pos_lbl = QLabel(objectName="chip")
        self.pos_lbl.hide()
        hint.setStyleSheet("font-size:9pt")
        left = QVBoxLayout()
        left.addLayout(top)
        left.addWidget(self.canvas, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        bottom.addWidget(self.pos_lbl)
        bottom.addWidget(self.size_lbl)
        left.addLayout(bottom)

        self.tabs = QTabWidget()
        self.tabs.setTabBar(TabBar())          # «жидкая» таблетка, как в главном окне
        self.tabs.tabBar().setUsesScrollButtons(False)       # все пять вкладок видны сразу
        self.tabs.tabBar().setExpanding(True)
        self.tabs.setStyleSheet("QTabBar::tab{padding:7px 6px;margin:8px 3px 6px 3px}")
        self.tabs.addTab(self.page_main(), "Основное")
        self.tabs.addTab(self.page_color(), "Цвет")
        self.tabs.addTab(self.page_bg(), "Фон")
        self.tabs.addTab(self.page_fx(), "Эффекты")
        self.tabs.addTab(self.page_recipes(), "Рецепты")
        self.tabs.currentChanged.connect(lambda _i: self.set_brush(None))

        # --- шаги и сохранение
        self.steps_lbl = QLabel(objectName="dim", wordWrap=True)
        self.step_list = QListWidget()
        self.step_list.setMaximumHeight(150)
        self.step_list.setMinimumHeight(96)
        self.step_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.step_list.setToolTip("Галка - включить/выключить шаг, Del - убрать, кнопки - выше/ниже")
        self.step_list.itemChanged.connect(self.step_toggled)
        self.step_list.currentRowChanged.connect(lambda _r: self.step_buttons())
        key("Delete", self.step_list, self.remove_step)
        self.up_b = flat("Выше", lambda: self.move_step(-1), "Шаг раньше")
        self.down_b = flat("Ниже", lambda: self.move_step(1), "Шаг позже")
        self.del_step_b = flat("Убрать", self.remove_step, "Убрать выбранный шаг (Del)")
        srow = QHBoxLayout()
        srow.addWidget(QLabel("ШАГИ", objectName="faint"), 1)
        for w in (self.up_b, self.down_b, self.del_step_b):
            srow.addWidget(w)
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
        right.addLayout(srow)
        right.addWidget(self.step_list)
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
        key("Ctrl+0", self, self.canvas_fit)
        key("Ctrl+1", self, self.canvas_actual)
        key("B", self, self.cycle_backdrop)
        for i in range(5):
            key("Alt+%d" % (i + 1), self, lambda i=i: self.tabs.setCurrentIndex(i))
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
        self.angle = QSpinBox(minimum=-45, maximum=45, value=0, suffix=" °")
        self.angle.setToolTip("Наклон по часовой стрелке (минус - против). Чтобы выровнять горизонт")
        self.angle_fit = QCheckBox("срезать углы")
        self.angle_fit.setChecked(True)
        self.angle_fit.setToolTip("Обрезать прозрачные клинья, что появляются по углам после наклона")
        r4 = QHBoxLayout()
        r4.addWidget(self.angle)
        r4.addWidget(self.angle_fit)
        r4.addWidget(self.button("Наклонить", self.add_angle), 1)
        self.side = QSpinBox(minimum=16, maximum=8192, singleStep=64, suffix=" px")
        self.side.setToolTip("Длинная сторона картинки после правки")
        r5 = QHBoxLayout()
        r5.addWidget(self.side, 1)
        r5.addWidget(self.button("Изменить размер", lambda: self.add(op="resize", size=self.side.value())))
        self.up_kind = QComboBox()
        for t, v in (("Само определит", "auto"), ("Рисунок, наклейка", "art"), ("Фон, фото", "photo")):
            self.up_kind.addItem(t, v)
        self.up_kind.setToolTip("Модель для рисунков бережёт контуры и заливки, для фото - текстуры")
        r6 = QHBoxLayout()
        r6.addWidget(self.up_kind, 1)
        for x in (2, 4):
            b = self.button("x%d" % x, lambda _c=False, x=x: self.add(op="upscale", x=x, kind=self.up_kind.currentData()),
                            "Увеличить в %d раза нейросетью (Real-ESRGAN): чётко, а не мыльно" % x)
            b.setEnabled(neural.upscale_available())
            r6.addWidget(b)
        r5w = QVBoxLayout()
        r5w.addLayout(r5)
        r5w.addLayout(r6)
        g1w = QVBoxLayout()
        g1w.addLayout(g1)
        g1w.addLayout(r4)
        return self.page(self.box("Поворот и отражение", g1w), self.box("Обрезка", v2), self.box("Размер", r5w))

    def page_color(self):
        g3 = QGridLayout()
        self.sliders = {}
        for i, (k, text) in enumerate(K.ADJ):
            lo, hi = K.ADJ_RANGE.get(k, (-100, 100))
            s = ZeroSlider(lo, hi)
            s.setToolTip("Двойной щелчок - сбросить")
            val = QLabel("0", objectName="dim")
            val.setFixedWidth(38)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl = QPushButton(text, objectName="flat")
            lbl.setStyleSheet("text-align:left;padding-left:2px")
            lbl.setToolTip((ADJ_TIPS[k] + "\n" if k in ADJ_TIPS else "") + "Щелчок - сбросить")
            lbl.clicked.connect(lambda _c=False, sl=s: sl.setValue(0))
            s.sliderPressed.connect(self.remember)
            s.valueChanged.connect(lambda v, kk=k, vl=val: self.adj_changed(kk, v, vl))
            g3.addWidget(lbl, i, 0)
            g3.addWidget(s, i, 1)
            g3.addWidget(val, i, 2)
            self.sliders[k] = (s, val)
        g3.addWidget(flat("Сбросить цвет", self.reset_color), len(K.ADJ), 1)

        self.pal = QComboBox()
        for pid, name, folder, cols in prompts.palettes():
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
            v.addWidget(QLabel("Палитры берутся из Prompts.html - страница не найдена", objectName="dim"))
        return self.page(self.box("Цвет", g3), self.box("Перекрасить в палитру", v))

    def page_bg(self):
        self.tol = QSpinBox(minimum=5, maximum=120, value=38)
        self.tol.setToolTip("Насколько цвет может отличаться от фона по краям, чтобы считаться фоном")
        self.fringe = QSpinBox(minimum=0, maximum=4, value=1, suffix=" px")
        self.fringe.setToolTip("На сколько пикселей поджать край; цвет края берётся у рисунка, а не у старого фона")
        self.px = QSpinBox(minimum=1, maximum=60, value=8, suffix=" px")
        self.outline_c = ColorButton("#ffffff", "Цвет обводки", self)
        self.pad = QSpinBox(minimum=0, maximum=40, value=6, suffix=" %")
        self.margin = QSpinBox(minimum=1, maximum=50, value=10, suffix=" %")
        self.margin.setToolTip("Ширина полей - доля длинной стороны")
        self.fill_c = ColorButton("#ffffff", "Цвет фона", self)
        self.ai_bg = self.button("Убрать фон нейросетью", lambda: self.add(op="nobg_ai"),
                                 "Любой фон, не только однотонный (BiRefNet). Первый раз - секунд 10")
        if not neural.bg_available():
            self.ai_bg.setEnabled(False)
            self.ai_bg.setToolTip("Нет модели: py -3.14 _tools/get_models.py")
        g4 = QGridLayout()
        rows = ((self.button("Убрать фон", lambda: self.add(op="nobg", tol=self.tol.value()),
                             "Однотонный фон, связанный с краями; белые детали внутри рисунка остаются"), self.tol),
                (self.ai_bg,),
                (self.button("Убрать кайму", lambda: self.add(op="defringe", px=self.fringe.value()),
                             "Светлый ореол от старого фона вокруг рисунка"), self.fringe),
                (self.button("Обводка", lambda: self.add(op="outline", px=self.px.value(), color=self.outline_c.color),
                             "Обводка вокруг рисунка, как у наклеек (нужна прозрачность)"), self.px, self.outline_c),
                (self.button("Квадрат с полями", lambda: self.add(op="square", pad=self.pad.value() / 100),
                             "Рисунок по центру квадрата, вокруг - прозрачные поля"), self.pad),
                (self.button("Поля вокруг", lambda: self.add(op="pad", k=self.margin.value() / 100),
                             "Расширить холст: прозрачные поля со всех сторон"), self.margin),
                (self.button("Залить фон", lambda: self.add(op="fill", color=self.fill_c.color),
                             "Подложить сплошной цвет под прозрачное (например, для jpg или превью)"), self.fill_c))
        for i, row in enumerate(rows):
            for j, w in enumerate(row):
                g4.addWidget(w, i, j)
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
        if len(self.paths) > 1:                 # мазок у каждой картинки свой - на пачку не годится
            for b in (self.erase_b, self.restore_b):
                b.setEnabled(False)
                b.setToolTip("Кисть - только для одной картинки: мазок лёг бы на все файлы в одно место")
        return self.page(self.box("Фон и наклейка", g4), self.box("Кисть", g5))

    def page_fx(self):
        self.sh_size = QSpinBox(minimum=1, maximum=20, value=3, suffix=" %")
        self.sh_size.setToolTip("Размытие и сдвиг тени - доля длинной стороны")
        self.sh_a = QSpinBox(minimum=10, maximum=100, value=45, suffix=" %")
        self.glow_r = QSpinBox(minimum=1, maximum=20, value=3, suffix=" %")
        self.glow_btn = ColorButton("#ffffff", "Цвет свечения", self)
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
        folder, name = os.path.split(os.path.relpath(p, LIB))
        self.file_lbl.setText("<span style='color:{}'>{} / </span><b>{}</b>{}".format(
            C["faint"], folder.replace(os.sep, " / "), name,
            "<span style='color:%s'>&nbsp;&nbsp;%d из %d</span>" % (C["dim"], self.idx + 1, len(self.paths))
            if len(self.paths) > 1 else ""))
        self.file_lbl.setToolTip(p)
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
            return im, full, glow_color(im)

        def done(res):
            if sip.isdeleted(self) or gen != self.gen:
                return
            if isinstance(res, Exception):
                self.file_lbl.setText(f"Не открылось: {res}")
                return
            self.base, self.full, self.canvas.glow = res
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

    def add_recolor(self):
        d = self.pal.currentData()
        if d:
            pid, folder, cols = d
            self.add(op="recolor", colors=cols, k=self.strength.value() / 100, pal=pid, folder=folder)

    # тень и свечение - долями длинной стороны (rel): в пачке файлов разного размера выглядят одинаково
    def add_shadow(self):
        s = self.sh_size.value() / 100
        self.add(op="shadow", rel=True, dx=round(s * 0.5, 4), dy=round(s * 0.8, 4), blur=round(s, 4),
                 a=self.sh_a.value() / 100)

    def add_glow(self):
        self.add(op="glow", rel=True, r=round(self.glow_r.value() / 100, 4), color=self.glow_btn.color, a=0.85)

    def add_angle(self):
        if self.angle.value():
            self.add(op="angle", deg=self.angle.value(), fit=self.angle_fit.isChecked())

    def add_stroke(self, pts, r):
        mode = self.canvas.brushing
        self.add(op="brush", mode=mode, r=round(r, 5), pts=[(round(x, 5), round(y, 5)) for x, y in pts])
        self.canvas.brushing = mode             # add() не выходит из режима кисти

    def adj_changed(self, k, v, lbl):
        lbl.setText("%+d" % v if v else "0")
        lbl.setObjectName("" if v else "dim")         # тронутое значение - ярче
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)
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
            s.update()
            v = self.adj[k]
            lbl.setText("%+d" % v if v else "0")
            lbl.setObjectName("" if v else "dim")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

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
        return bool(self.live_ops() or any(self.adj.values()))

    def changed(self):
        self.update_ui()
        self.timer.start()

    def palette_target(self):
        """Папка новой палитры рядом с исходной, если после перекраски это имеет смысл."""
        if self.target:
            return self.target
        rec = [o for o in self.live_ops() if o["op"] == "recolor" and o.get("folder")]
        if not rec or not self.paths:
            return None
        parent = os.path.dirname(self.paths[0])
        if os.path.basename(parent) not in prompts.pal_by_folder() or os.path.basename(parent) == rec[-1]["folder"]:
            return None
        if any(os.path.dirname(p) != parent for p in self.paths):
            return None
        return os.path.join(os.path.dirname(parent), rec[-1]["folder"])

    def fill_steps(self):
        lst = self.step_list
        row = lst.currentRow()
        lst.blockSignals(True)
        lst.clear()
        if any(self.adj.values()):
            it = QListWidgetItem("цвет: " + ", ".join("%s %+d" % (t.lower(), self.adj[k]) for k, t in K.ADJ if self.adj[k]))
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            it.setIcon(dot_icon(C["acc"], C["acc2"]))
            it.setData(Qt.ItemDataRole.UserRole, -1)
            lst.addItem(it)
        for i, o in enumerate(self.ops):
            it = QListWidgetItem("%d. %s" % (i + 1, step_text(o)))
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked if o.get("off") else Qt.CheckState.Checked)
            it.setData(Qt.ItemDataRole.UserRole, i)
            lst.addItem(it)
        lst.setCurrentRow(min(row, lst.count() - 1))
        lst.blockSignals(False)
        self.step_buttons()

    def step_index(self):
        it = self.step_list.currentItem()
        return None if it is None else it.data(Qt.ItemDataRole.UserRole)

    def step_buttons(self):
        i = self.step_index()
        self.del_step_b.setEnabled(i is not None)
        self.up_b.setEnabled(i is not None and i > 0)
        self.down_b.setEnabled(i is not None and 0 <= i < len(self.ops) - 1)

    def step_toggled(self, it):
        i = it.data(Qt.ItemDataRole.UserRole)
        if i is None or i < 0:
            return
        self.remember()
        self.ops[i]["off"] = it.checkState() != Qt.CheckState.Checked
        if not self.ops[i]["off"]:
            self.ops[i].pop("off")
        self.changed()

    def remove_step(self):
        i = self.step_index()
        if i is None:
            return
        if i < 0:
            self.reset_color()
            return
        self.remember()
        self.ops.pop(i)
        self.changed()

    def move_step(self, d):
        i = self.step_index()
        if i is None or i < 0 or not 0 <= i + d < len(self.ops):
            return
        self.remember()
        self.ops[i], self.ops[i + d] = self.ops[i + d], self.ops[i]
        self.changed()
        self.step_list.setCurrentRow(self.step_list.currentRow() + d)

    def live_ops(self):
        """Шаги без выключенных - то, что пойдёт в файл и в рецепт."""
        return [{k: v for k, v in o.items() if k != "off"} for o in self.ops if not o.get("off")]

    def update_ui(self):
        self.fill_steps()
        self.steps_lbl.setText("" if self.dirty() else "Правок пока нет")
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
            self.pal_b.setText("Сохранить в «{}»".format(os.path.relpath(t, LIB).replace(os.sep, " / ")))
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
        ops = [o for o in self.live_ops() if o["op"] != "brush"]
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
                self.steps_lbl.setText(f"Не получилось: {res}")
                self.canvas.update()
                return
            img, w, h, scale = res
            old = self.canvas.pm.size() if self.canvas.pm else None
            self.canvas.img = img
            self.canvas.pm = QPixmap.fromImage(img)
            if self.canvas.cropping and old != self.canvas.pm.size():     # цвет рамку не сбивает
                self.canvas.reset_crop()
            self.canvas.update()
            self.cur = (max(1, round(w / scale)), max(1, round(h / scale)))
            self.size_lbl.setText("%d × %d  (было %d × %d)" % (*self.cur, *self.full)
                                  if self.cur != tuple(self.full) else "%d × %d" % self.cur)
            self.zoom_changed()

        def work():
            info = {}
            im = K.apply_edits(base, ops, adj, scale, info)
            return to_qimage(im), im.width, im.height, info.get("scale", scale)

        bg(work, done)

    def show_orig(self, on):
        self.canvas.compare = on
        self.canvas.update()

    def zoom_changed(self, _z=None):
        """Настоящий масштаб: сколько точек экрана на пиксель полного размера."""
        r = self.canvas.image_rect()
        if r.width() and self.cur[0] > 1:
            self.zoom_lbl.setText("%d%%" % round(r.width() / self.cur[0] * 100))

    def canvas_fit(self):
        self.canvas.reset_view()
        self.zoom_changed()

    def canvas_actual(self):
        self.canvas.actual_size(self.cur[0])
        self.zoom_changed()

    def cycle_backdrop(self):
        c = self.canvas
        c.backdrop = (c.backdrop + 1) % len(BACKDROPS)
        self.back_b.setText("Подложка: " + BACKDROPS[c.backdrop][0])
        c.update()

    def toggle_split(self):
        c = self.canvas
        c.split = 0.5 if c.split is None else None
        self.split_b.setChecked(c.split is not None)
        c.update()

    def pointer(self, norm, color):
        """Строка под холстом: где курсор (в пикселях полного размера) и какой там цвет."""
        if norm is None or color is None:
            self.pos_lbl.hide()
            return
        x, y = int(norm[0] * self.cur[0]), int(norm[1] * self.cur[1])
        self.pos_lbl.setText("<span style='color:%s'>&#9632;</span> %s &nbsp;<span style='color:%s'>x</span> %d "
                             "<span style='color:%s'>y</span> %d%s" % (
                                 color.name() if color.alpha() else C["faint"], color.name(), C["dim"], x, C["dim"], y,
                                 "" if color.alpha() == 255 else " &nbsp;<span style='color:%s'>альфа</span> %d%%"
                                 % (C["dim"], round(color.alpha() / 2.55))))
        self.pos_lbl.show()

    def pipette(self, btn):
        def got(c):
            btn.set(c.name())
            self.win.say("Цвет взят: " + c.name())
        self.canvas.picking = got
        self.canvas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.win.say("Щёлкните по картинке, чтобы взять цвет")

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
        paths, ops, adj = list(self.paths), self.live_ops(), dict(self.adj)
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
                    self.steps_lbl.setText(f"Не сохранилось: {res}")
                return
            steps, made, bad = res
            if how == "replace":
                for old, new in made:
                    if old != new:
                        self.win.moved(old, new)        # избранное и метки - за файлом, если сменился формат
            what = {"replace": "Правка", "copy": "Копии правки", "palette": "Перекрашено"}[how]
            text = "%s: %d шт." % (what, len(made)) + ("   не вышло: %d" % len(bad) if bad else "")
            if target:
                text += f" в «{os.path.relpath(target, LIB)}»"
            if how == "replace" and made:
                was = sum(os.path.getsize(s[2]) for s in steps if s[0] == "move" and os.path.exists(s[2]))
                now = sum(os.path.getsize(n) for _o, n in made if os.path.exists(n))
                text += f"   ({human(was)} -> {human(now)})"
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
