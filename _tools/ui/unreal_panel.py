"""Карточка ассета Unreal - правая панель вкладки и сведения в окне 3D-просмотра.
HeroView - превью на «подиуме» в тонах самой картинки; AssetCard - плашки, цифры, шкала полигонов,
габариты рисунком рядом с человеком 180 см, палитра полосой, описание, предупреждения, анимации и метки
кнопками (анимация - играть в 3D, метка - в поиск), источник ссылкой."""

import math
import os
from html import escape as esc

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QVBoxLayout, QWidget

import imaging as K
from library import unreal as U
from ui.common import human, log_error
from ui.theme import C, readable
from ui.unreal_nav import KIND_LOOK, theme_label
from ui.widgets import PicView

KIND_NAME = {"tex": "Текстура", "hdri": "HDRI", "model": "Модель", "ies": "Свет IES"}
KIND_MANY = {"model": "моделей", "tex": "текстур", "hdri": "HDRI", "ies": "профилей IES"}
GREEN, ORANGE, BLUE, PINK = "#7ee0a0", "#ffb86c", "#6cb8ff", "#ff8ac9"
HUMAN_CM = 180


def count_text(n):
    """Полигоны коротко: 72, 1.2k, 24k (раньше 72 показывалось как «1k»)."""
    n = int(n or 0)
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{n // 1000}k"


def dims_cm(a):
    """[ширина, глубина, высота] в см: с сайта (dimensions_mm) или из FBX (dims_cm), иначе None."""
    if a.get("dimensions_mm"):
        return [x / 10 for x in a["dimensions_mm"]]
    return a.get("dims_cm") or None


def license_look(a):
    """(подпись, цвет, подсказка) плашки лицензии."""
    if U.is_cc0(a):
        return "CC0", GREEN, "Общественное достояние: в любые проекты, автора указывать не нужно"
    lic = a.get("license", "")
    if "Unreal" in lic:
        return "Только Unreal", ORANGE, lic
    return "Своя лицензия", ORANGE, lic or "Лицензия не указана - проверьте на сайте источника"


def scale_hint(a):
    """Kenney и KayKit бывают в метрах: в Unreal модель придёт крошечной или огромной."""
    dims = a.get("dims_cm")
    if not dims or a.get("dimensions_mm") or not (max(dims) < 10 or max(dims) > 5000):
        return ""
    k = "100" if max(dims) < 10 else "0.01"
    return f"Как есть модель придёт размером {max(dims):.0f} см - при импорте поставьте Import Uniform Scale {k}"


POLY_LEVELS = (  # (до скольки, оценка, цвет)
    (2000, "очень лёгкая - хоть сотня копий", "#7ee0a0"),
    (10000, "лёгкая - для игры", "#b4e07e"),
    (50000, "средняя", "#ffd166"),
    (200000, "тяжёлая - крупным планом", "#ffb86c"),
    (10**12, "очень тяжёлая - для кино и рендера", "#ff6b6b"),
)


def poly_level(n):
    return next((t, c) for lim, t, c in POLY_LEVELS if n < lim)


def mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def alpha(color, a):
    c = QColor(color)
    c.setAlpha(a)
    return c


def mosaic(paths, side=512):
    """Превью нескольких ассетов одной картинкой 2x2 (выбрано несколько)."""
    pm = QPixmap(side, side)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    gap, n = 10, min(4, len(paths))
    cell = (side - gap) // 2
    for i, path in enumerate(paths[:4]):
        im = QPixmap(path)
        if im.isNull():
            continue
        r = QRect((i % 2) * (cell + gap), (i // 2) * (cell + gap), cell, cell)
        if n == 1:
            r = QRect(0, 0, side, side)
        elif n == 2:
            r = QRect(i * (cell + gap), side // 4, cell, cell)
        clip = QPainterPath()
        clip.addRoundedRect(r.toRectF(), 18, 18)
        p.save()
        p.setClipPath(clip)
        g = QLinearGradient(QPointF(r.topLeft()), QPointF(r.bottomRight()))
        g.setColorAt(0, QColor(C["bg3"]))
        g.setColorAt(1, QColor(C["bg1"]))
        p.fillRect(r, QBrush(g))
        im = im.scaled(r.size() * 0.86, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap(r.x() + (r.width() - im.width()) // 2, r.y() + (r.height() - im.height()) // 2, im)
        p.restore()
    p.end()
    return pm


def play_icon(color):
    """Треугольник «играть» рисунком (не символом: на Windows ▶ может стать эмодзи)."""
    pm = QPixmap(24, 24)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF([QPointF(7, 5), QPointF(19, 12), QPointF(7, 19)]))
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- превью
class HeroView(PicView):
    """Превью на подиуме: фон в тонах картинки, круглая подставка с кольцами и тенью. Прозрачные превью
    (модели) стоят на подставке, непрозрачные (текстура, небо, портрет) - карточкой с тенью."""

    def __init__(self, hint="Выберите ассет"):
        super().__init__(hint)
        self.fit_aspect = True
        self.tones = []
        self.cut = False  # у картинки прозрачный фон - вырезанная модель

    def set_pixmap(self, pm):
        super().set_pixmap(pm)
        self.cut = False
        if self.pm is not None:
            im = self.pm.toImage()
            w, h = im.width(), im.height()
            corners = [im.pixelColor(x, y).alpha() for x, y in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2))]
            self.cut = max(corners) < 16

    def set_tones(self, colors):
        self.tones = list(colors or [])[:3]
        self.glow = QColor(self.tones[0]) if self.tones else None
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, 18, 18)
        p.setClipPath(clip)
        base = QColor(C["bg2"])
        t1 = QColor(self.tones[0]) if self.tones else QColor(C["acc"])
        t2 = QColor(self.tones[1]) if len(self.tones) > 1 else QColor(C["acc2"])
        top = mix(base, t2, 0.18 if self.pm else 0.06)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, top)
        g.setColorAt(1, mix(QColor(C["bg1"]), t1, 0.08))
        p.fillRect(r, QBrush(g))
        # мягкий свет сверху, как софтбокс
        rg = QRadialGradient(QPointF(r.center().x(), r.top() + r.height() * 0.18), r.width() * 0.75)
        rg.setColorAt(0, alpha(mix(t1, QColor("#ffffff"), 0.35), 70 if self.pm else 25))
        rg.setColorAt(1, alpha(t1, 0))
        p.fillRect(r, QBrush(rg))
        # подиум: эллипс с кольцами
        cx, cy = r.center().x(), r.bottom() - r.height() * 0.13
        rw, rh = r.width() * 0.42, r.height() * 0.07
        disc = QRadialGradient(QPointF(cx, cy), rw)
        disc.setColorAt(0, alpha(t1, 80))
        disc.setColorAt(0.7, alpha(t1, 22))
        disc.setColorAt(1, alpha(t1, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(disc))
        p.drawEllipse(QPointF(cx, cy), rw, rh * 1.6)
        for k, a in ((1.0, 70), (0.72, 45), (1.28, 25)):
            p.setPen(QPen(alpha(mix(t1, QColor(C["text"]), 0.4), a), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), rw * k, rh * k)
        # точечная сетка-пол
        p.setPen(Qt.PenStyle.NoPen)
        dot = alpha(C["text"], 18)
        for row in range(5):
            y = r.bottom() - 6 - row * 9
            step = 14 + row * 2
            x = r.left() + (row * 5) % step
            while x < r.right():
                p.fillRect(QRectF(x, y, 1.6, 1.6), dot)
                x += step
        t = self.t
        if self.old and t < 1:
            self.draw_hero(p, r, self.old, 1 - t, 1.0)
        if self.pm:
            self.draw_hero(p, r, self.pm, t, 0.96 + 0.04 * t)
        else:
            p.setPen(QColor(C["dim"]))
            f = QFont(self.font())
            f.setPointSizeF(f.pointSizeF() + 1)
            p.setFont(f)
            p.drawText(QRectF(r.x(), r.center().y() - 14, r.width(), 28), Qt.AlignmentFlag.AlignCenter, self.hint)
        p.setClipping(False)
        p.setPen(QPen(alpha(mix(QColor(C["line2"]), t1, 0.3), 255), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 18, 18)
        p.end()

    def draw_hero(self, p, r, pm, k, zoom):
        cut = self.cut if pm is self.pm else True
        floor = r.bottom() - r.height() * 0.13
        if cut:  # модель стоит на подиуме
            box = QRectF(r.left() + 22, r.top() + 18, r.width() - 44, floor - r.top() - 10)
        else:
            box = r.adjusted(26, 24, -26, -r.height() * 0.16)
        s = min(box.width() / pm.width(), box.height() / pm.height()) * zoom
        w, h = pm.width() * s, pm.height() * s
        x = box.center().x() - w / 2
        y = (floor + 6 - h) if cut else box.center().y() - h / 2
        img = QRectF(x, y, w, h)
        p.save()
        p.setOpacity(k)
        if cut:  # тень у ног
            sh = QRadialGradient(QPointF(img.center().x(), floor + 4), w * 0.42)
            sh.setColorAt(0, QColor(0, 0, 0, 110))
            sh.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(sh))
            p.drawEllipse(QPointF(img.center().x(), floor + 4), w * 0.42, 9)
            p.drawPixmap(img, pm, QRectF(pm.rect()))
        else:  # карточка с тенью
            for i in range(6, 0, -1):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 14))
                p.drawRoundedRect(img.adjusted(-i, -i + 4, i, i + 4), 14 + i, 14 + i)
            path = QPainterPath()
            path.addRoundedRect(img, 14, 14)
            p.setClipPath(path, Qt.ClipOperation.IntersectClip)
            p.drawPixmap(img, pm, QRectF(pm.rect()))
            p.setClipping(False)
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(img, 14, 14)
        p.restore()


# ---------------------------------------------------------------- рисунки в карточке
class PolyMeter(QWidget):
    """Шкала «лёгкая - тяжёлая» по полигонам (лог. шкала 100 - 1 млн) с меткой этой модели."""

    def __init__(self, n):
        super().__init__()
        self.n = n
        self.setFixedHeight(30)
        self.setToolTip(f"{n:,}".replace(",", " ") + " полигонов")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        bar = QRectF(1, 6, w - 2, 6)
        g = QLinearGradient(bar.topLeft(), bar.topRight())
        for i, (_l, _t, c) in enumerate(POLY_LEVELS):
            g.setColorAt(i / (len(POLY_LEVELS) - 1), alpha(readable(c), 150))
        path = QPainterPath()
        path.addRoundedRect(bar, 3, 3)
        p.fillPath(path, QBrush(g))
        k = min(1.0, max(0.0, (math.log10(max(self.n, 100)) - 2) / 4))
        x = bar.left() + k * bar.width()
        text, col = poly_level(self.n)
        col = QColor(readable(col))
        halo = QRadialGradient(QPointF(x, bar.center().y()), 12)
        halo.setColorAt(0, alpha(col, 140))
        halo.setColorAt(1, alpha(col, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(x, bar.center().y()), 12, 12)
        p.setBrush(QColor(C["bg1"]))
        p.setPen(QPen(col, 2.5))
        p.drawEllipse(QPointF(x, bar.center().y()), 5.5, 5.5)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(0, 15, w, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        p.end()


class SizeFigure(QWidget):
    """Габариты рисунком: коробка модели в изометрии и рядом силуэт человека 180 см в том же масштабе."""

    def __init__(self, dims, color):
        super().__init__()
        self.w, self.d, self.h = (max(0.01, float(x)) for x in dims)
        self.color = QColor(readable(color))
        self.setFixedHeight(150)
        self.setToolTip("Размер, каким модель придёт в Unreal, рядом с человеком ростом 180 см")

    @staticmethod
    def draw_human(p, x, floor, hh):
        """Силуэт человека (в долях роста): голова, шея, торс с плечами, руки, ноги."""
        u = hh / 180
        col = alpha(C["dim"], 150)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)

        def rr(cx, top, w, h, r):
            p.drawRoundedRect(QRectF(x + (cx - w / 2) * u, floor - top * u, w * u, h * u), r * u, r * u)

        p.drawEllipse(QPointF(x, floor - 166 * u), 11 * u, 13 * u)  # голова
        rr(0, 154, 9, 8, 3)  # шея
        rr(0, 148, 40, 58, 12)  # торс
        rr(-24, 145, 10, 66, 5)  # руки
        rr(24, 145, 10, 66, 5)
        rr(-9, 94, 15, 93, 6)  # ноги
        rr(9, 94, 15, 93, 6)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cos, sin = math.cos(math.radians(30)), math.sin(math.radians(30))

        def iso(x, y, z):
            return QPointF((x - y) * cos, (x + y) * sin - z)

        w, d, h = self.w, self.d, self.h
        hw = 60  # ширина силуэта с руками (в см)
        gap = max(w, d, HUMAN_CM) * 0.42  # место под подпись ширины коробки
        # рамка всего рисунка в единицах «см» до масштаба: человек слева, коробка справа
        pts = [iso(x, y, z) for x in (0, w) for y in (0, d) for z in (0, h)]
        bx0, bx1 = min(q.x() for q in pts), max(q.x() for q in pts)
        by0, by1 = min(q.y() for q in pts), max(q.y() for q in pts)
        total_w = hw + gap + (bx1 - bx0)
        total_h = max(by1 - by0, HUMAN_CM)
        top_pad, bot_pad = 10, 24
        s = min((self.width() - 70) / total_w, (self.height() - top_pad - bot_pad) / max(total_h, 1))
        base_y = self.height() - bot_pad
        left = (self.width() - total_w * s) / 2
        # человек
        hx = left + hw * s / 2
        hh = HUMAN_CM * s
        self.draw_human(p, hx, base_y, hh)
        # коробка: начало так, чтобы низ стоял на линии пола
        ox = left + (hw + gap) * s - bx0 * s
        oy = base_y - by1 * s

        def P(x, y, z):
            q = iso(x, y, z)
            return QPointF(ox + q.x() * s, oy + q.y() * s)

        c = self.color
        faces = (
            ([P(0, d, 0), P(w, d, 0), P(w, d, h), P(0, d, h)], 50),  # передняя левая
            ([P(w, 0, 0), P(w, d, 0), P(w, d, h), P(w, 0, h)], 30),  # передняя правая
            ([P(0, 0, h), P(w, 0, h), P(w, d, h), P(0, d, h)], 75),  # верх
        )
        for poly, a in faces:
            p.setBrush(alpha(c, a))
            p.setPen(QPen(alpha(c, 220), 1.4))
            p.drawPolygon(QPolygonF(poly))
        p.setPen(QPen(alpha(c, 70), 1, Qt.PenStyle.DashLine))
        for a_, b_ in ((P(0, 0, 0), P(w, 0, 0)), (P(0, 0, 0), P(0, d, 0)), (P(0, 0, 0), P(0, 0, h))):
            p.drawLine(a_, b_)
        # подписи
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)

        def label(pt, text, align):
            p.setPen(QColor(C["text"]))
            r = QRectF(pt.x() - 60, pt.y() - 9, 120, 18)
            if align == "l":
                r = QRectF(pt.x() + 6, pt.y() - 9, 90, 18)
            p.drawText(
                r,
                (Qt.AlignmentFlag.AlignLeft if align == "l" else Qt.AlignmentFlag.AlignCenter)
                | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

        def cm(v):
            return f"{v / 100:.2g} м" if v >= 1000 else (f"{v:.0f} см" if v >= 10 else f"{v:g} см")

        mid = lambda a_, b_: QPointF((a_.x() + b_.x()) / 2, (a_.y() + b_.y()) / 2)  # noqa: E731
        label(mid(P(0, d, 0), P(w, d, 0)) + QPointF(-26, 10), cm(w), "c")
        label(mid(P(w, d, 0), P(w, 0, 0)) + QPointF(26, 10), cm(d), "c")
        label(mid(P(w, 0, 0), P(w, 0, h)), cm(h), "l")
        p.setPen(QColor(C["dim"]))
        p.drawText(QRectF(hx - 40, base_y + 4, 80, 16), Qt.AlignmentFlag.AlignCenter, f"{HUMAN_CM} см")
        p.setPen(QPen(alpha(C["text"], 40), 1))
        p.drawLine(QPointF(8, base_y), QPointF(self.width() - 8, base_y))
        p.end()


class PaletteBar(QWidget):
    """Главные цвета превью одной полосой; наведение - код цвета, щелчок - скопировать."""

    picked = pyqtSignal(str)

    def __init__(self, colors):
        super().__init__()
        self.colors = colors
        self.hover = -1
        self.setFixedHeight(26)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def at(self, x):
        return min(len(self.colors) - 1, max(0, int(x / max(1, self.width()) * len(self.colors))))

    def mouseMoveEvent(self, e):
        i = self.at(e.position().x())
        if i != self.hover:
            self.hover = i
            self.setToolTip(f"{self.colors[i]} - щелчок копирует")
            self.update()

    def leaveEvent(self, _e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        self.picked.emit(self.colors[self.at(e.position().x())])

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 3.5, -0.5, -3.5)
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        p.setClipPath(path)
        n = len(self.colors)
        for i, c in enumerate(self.colors):
            seg = QRectF(r.left() + r.width() * i / n, r.top(), r.width() / n + 1, r.height())
            p.fillRect(seg, QColor(c))
            if i == self.hover:
                p.fillRect(seg, QColor(255, 255, 255, 40))
                col = QColor(c)
                p.setPen(QColor("#111111") if col.lightness() > 150 else QColor("#ffffff"))
                f = QFont(self.font())
                f.setPointSizeF(7.5)
                f.setBold(True)
                p.setFont(f)
                p.drawText(seg, Qt.AlignmentFlag.AlignCenter, c.upper())
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 9, 9)
        p.end()


# ---------------------------------------------------------------- раскладка и мелкие виджеты
class Flow(QLayout):
    """Раскладка «строками с переносом» - для плашек и меток."""

    def __init__(self, parent=None, gap=5):
        super().__init__(parent)
        self.items, self.gap = [], gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self.place(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self.place(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def place(self, r, test):
        x, y, line = r.x(), r.y(), 0
        for it in self.items:
            hint = it.sizeHint()
            if x + hint.width() > r.right() + 1 and line > 0:
                x, y, line = r.x(), y + line + self.gap, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.gap
            line = max(line, hint.height())
        return y + line - r.y()


def pill(text, color, tip=""):
    w = QLabel(text)
    c = QColor(readable(color))
    w.setStyleSheet(
        f"background:rgba({c.red()},{c.green()},{c.blue()},34);color:{c.name()};"
        f"border:1px solid rgba({c.red()},{c.green()},{c.blue()},80);border-radius:10px;"
        "padding:2px 10px;font-size:8pt;font-weight:700;letter-spacing:1px"
    )
    if tip:
        w.setToolTip(tip)
    return w


def figure(value, caption, color=None, tip=""):
    """Цифра крупно, подпись мелко - без рамки (рамка у всего блока)."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    val = QLabel(value, objectName="statv")
    if color:
        val.setStyleSheet(f"color:{readable(color)}")
    v.addWidget(val)
    v.addWidget(QLabel(caption, objectName="statk"))
    if tip:
        w.setToolTip(tip)
    return w


def vline():
    f = QFrame(objectName="vline")
    f.setFixedWidth(1)
    return f


def notice(text, color, title=""):
    c = QColor(readable(color))
    head = f'<b style="color:{c.name()}">{esc(title)}</b><br>' if title else ""
    w = QLabel(head + esc(text), wordWrap=True)
    w.setStyleSheet(
        f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba({c.red()},{c.green()},{c.blue()},40),"
        f"stop:1 rgba({c.red()},{c.green()},{c.blue()},8));border:1px solid rgba({c.red()},{c.green()},{c.blue()},60);"
        "border-radius:12px;padding:8px 11px"
    )
    return w


class AssetCard(QWidget):
    """Сведения об ассете. Пересобирается на каждый выбор - виджетов немного."""

    tag_clicked = pyqtSignal(str)  # метка -> поиск во вкладке
    anim_clicked = pyqtSignal(str)  # анимация -> играть в 3D
    said = pyqtSignal(str)  # сообщение в строку состояния (скопирован цвет)

    def __init__(self, compact=False):
        super().__init__()
        self.compact = compact  # окно 3D: без строки раздела (она в шапке окна)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(10)
        self.palettes = {}  # путь превью -> главные цвета
        self.more_anims = False
        self.last = None  # (a, new, used, size_text) - пересобрать при «ещё N»

    # ------------------------------------------------------------ сборка
    def clear(self):
        while self.v.count():
            it = self.v.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                self._drop(it.layout())

    def _drop(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
            elif it.layout() is not None:
                self._drop(it.layout())
        lay.deleteLater()

    def flow(self, widgets, gap=5):
        box = QWidget()
        f = Flow(box, gap)
        for w in widgets:
            f.addWidget(w)
        self.v.addWidget(box)
        return box

    def section(self, text, extra=""):
        lb = QLabel(
            text + (f'  <span style="color:{C["faint"]}">{esc(extra)}</span>' if extra else ""), objectName="sect"
        )
        self.v.addWidget(lb)

    def text(self, html, obj="dim", links=False):
        lb = QLabel(html, objectName=obj, wordWrap=True)
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lb.setOpenExternalLinks(links)
        self.v.addWidget(lb)
        return lb

    def spec(self, figures, extra=()):
        """Блок цифр: строка цифр через тонкие разделители, под ней - шкала, рисунок."""
        box = QFrame(objectName="spec")
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(12)
        for i, f in enumerate(figures):
            if i:
                row.addWidget(vline())
            row.addWidget(f)
        row.addStretch(1)
        v.addLayout(row)
        for w in extra:
            v.addWidget(w)
        self.v.addWidget(box)

    def chips(self, names, signal, limit, tip, icon=None, prefix=""):
        out = []
        shown = names if self.more_anims and icon is not None else names[:limit]
        for n in shown:
            b = QPushButton(prefix + n, objectName="chip")
            if icon is not None:
                b.setIcon(icon)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c, x=n: signal.emit(x))
            out.append(b)
        if len(names) > len(shown):
            more = QPushButton(f"ещё {len(names) - len(shown)}", objectName="flat")
            more.setCursor(Qt.CursorShape.PointingHandCursor)
            more.setToolTip(", ".join(names[len(shown) :]))
            if icon is not None:
                more.clicked.connect(self.expand_anims)
            out.append(more)
        self.flow(out)

    def expand_anims(self):
        self.more_anims = True
        if self.last:
            self.show_asset(*self.last)

    def colors_of(self, a):
        prev = os.path.join(a["dir"], "preview.webp")
        if not os.path.exists(prev) or a.get("kind") == "ies":
            return []
        if prev not in self.palettes:
            try:
                self.palettes[prev] = K.main_colors(prev, 6)
            except Exception as e:
                log_error("palette: %r" % e)
                self.palettes[prev] = []
        return self.palettes[prev]

    # ------------------------------------------------------------ виды
    def show_asset(self, a, new=False, used=(), size_text=""):
        """Один ассет. size_text - габариты модели из сцены 3D (если размера в см нет). -> главные цвета."""
        if (self.last or (None,))[0] is not a:
            self.more_anims = False
        self.last = (a, new, used, size_text)
        self.clear()
        kind = a.get("kind", "")
        kc = KIND_LOOK.get(kind, KIND_LOOK["model"])[2]
        if not self.compact:
            where = theme_label(a.get("theme", "")) + (f"  /  {a['section']}" if a.get("section") else "")
            self.text(f'<span style="color:{readable(kc)}">{esc(where)}</span>', "where")
        lic, lic_c, lic_tip = license_look(a)
        pills = [pill(KIND_NAME.get(kind, "?").upper(), kc), pill(lic.upper(), lic_c, lic_tip)]
        if a.get("rigged") or a.get("animations"):
            pills.append(pill("СКЕЛЕТ", PINK, "Skeletal Mesh: импортируется со скелетом и анимациями"))
        if a.get("source") in U.LOW_POLY:
            pills.append(pill("LOW-POLY", BLUE, "Простой стиль: цвета в материалах или одной текстуре"))
        if new:
            pills.append(pill("НОВОЕ", GREEN, "Скачано после прошлого открытия окна"))
        self.flow(pills)

        figs, extra = [], []
        if a.get("res"):
            figs.append(figure(a["res"].upper(), "разрешение", kc))
        if kind == "tex":
            figs.append(figure(str(len(a.get("main", []))), "карт"))
        if a.get("polycount"):
            figs.append(figure(count_text(a["polycount"]), "полигонов"))
        if a.get("animations"):
            figs.append(figure(str(len(a["animations"])), "анимаций", PINK))
        figs.append(figure(human(a.get("size", 0)), "на диске"))
        if a.get("polycount"):
            extra.append(PolyMeter(a["polycount"]))
        dims = dims_cm(a)
        if dims and kind == "model":
            extra.append(SizeFigure(dims, kc))
        elif size_text:
            extra.append(QLabel(f"Габариты в единицах файла: {esc(size_text)}", objectName="dim"))
        self.spec(figs, extra)

        cols = self.colors_of(a)
        if cols:
            bar = PaletteBar(cols)
            bar.picked.connect(lambda h: (QApplication.clipboard().setText(h), self.said.emit(f"Скопирован цвет {h}")))
            self.v.addWidget(bar)
        if a.get("description"):
            self.text(esc(a["description"]), "body")
        hint = scale_hint(a)
        if hint:
            self.v.addWidget(notice(hint, BLUE, "Масштаб"))
        if not U.is_cc0(a) and a.get("license"):
            self.v.addWidget(notice(a["license"], ORANGE, "Лицензия"))
        if a.get("animations"):
            self.section("АНИМАЦИИ", "щелчок играет в 3D")
            self.chips(a["animations"], self.anim_clicked, 9, "Играть в окне 3D", icon=play_icon(readable(PINK)))
        if a.get("tags"):
            self.section("МЕТКИ")
            self.chips(a["tags"], self.tag_clicked, 10, "Найти ассеты с этой меткой", prefix="#")

        src = esc(a.get("source", ""))
        if a.get("url"):
            src = f'<a href="{esc(a["url"])}" style="color:{C["acc"]};text-decoration:none">{src}</a>'
        authors = [x for x in a.get("authors", []) if x != a.get("source")]
        if authors:
            src += ", " + esc(", ".join(authors))
        rows = [f"Источник: {src}"] if src else []
        if a.get("added"):
            rows.append(f"Скачан: {esc(a['added'])}")
        if used:  # куда ассет уже уходил: копия, импорт, пакет
            rows.append("Использован в: " + esc("; ".join(os.path.basename(x.rstrip("/\\")) or x for x in used[-3:])))
        if rows:
            self.text("<br>".join(rows), "dim", links=True)
        return cols

    def show_many(self, lst):
        self.last = None
        self.clear()
        kinds = {}
        for a in lst:
            kinds[a.get("kind")] = kinds.get(a.get("kind"), 0) + 1
        self.flow(
            [
                pill(f"{KIND_NAME.get(k, '?').upper()}: {n}", KIND_LOOK.get(k, KIND_LOOK["model"])[2])
                for k, n in kinds.items()
            ]
        )
        figs = [figure(str(len(lst)), "выбрано"), figure(human(sum(a.get("size", 0) for a in lst)), "на диске")]
        poly = sum(a.get("polycount", 0) or 0 for a in lst)
        extra = []
        if poly:
            figs.insert(1, figure(count_text(poly), "полигонов вместе"))
            extra.append(PolyMeter(poly))
        self.spec(figs, extra)
        if any(not U.is_cc0(a) for a in lst):
            self.v.addWidget(
                notice("Среди выбранных есть ассеты не CC0 - смотрите лицензию у каждого", ORANGE, "Лицензия")
            )
        self.text("Перетащите все разом в Content Browser или нажмите «В Unreal...».", "dim")

    def show_empty(self, items):
        """Ничего не выбрано: сколько чего в библиотеке."""
        self.last = None
        self.clear()
        count, size = {}, 0
        for a in items:
            count[a.get("kind")] = count.get(a.get("kind"), 0) + 1
            size += a.get("size", 0)
        if items:
            figs = [
                figure(str(count[k]), KIND_MANY[k], KIND_LOOK[k][2])
                for k in ("model", "tex", "hdri", "ies")
                if count.get(k)
            ]
            self.spec(figs, [QLabel(f"Всего на диске: {human(size)}", objectName="dim")])
        self.text(
            "Ассеты для Unreal Engine: PBR-текстуры, небо HDRI, модели, профили света. "
            "Источники - Poly Haven, ambientCG, Kenney, Quaternius, KayKit, Megascans.<br><br>"
            "Щелчок по плитке - сведения здесь, двойной - 3D-просмотр, перетаскивание - прямо в Content Browser.",
            "dim",
        )
