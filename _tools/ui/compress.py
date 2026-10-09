"""Сжатие и конвертация: шторка до/после, подбор качества, пакетное сжатие с отменой."""
import io
import math
import os
import random
import time

from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import imaging as K
from library.batch import CAN, COPY_FORMATS, compress_files, copy_files  # noqa: F401
from ui.common import LIB, bg, human, in_main, parallel
from ui.theme import C
from ui.thumbnails import lib_icon, thumb, to_pix
from ui.widgets import flat


class Compare(QWidget):
    """До/после со шторкой, как в Squoosh: тянуть мышью - граница, колесо - масштаб,
    правая кнопка - двигать, двойной щелчок - снова целиком."""

    def __init__(self):
        super().__init__()
        self.a = self.b = None
        self.labels = ("Было", "Стало")  # подписи половин; одна картинка (a is b) - без шторки
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
        if self.b is self.a:  # одна картинка (например, карта разницы) - без шторки и подписей
            p.drawPixmap(r, self.a, QRectF(self.a.rect()))
            p.end()
            return
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
        for text, left in ((self.labels[0], True), (self.labels[1], False)):
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
    (K.BEST, "Самый лёгкий (окно выберет формат)"),
    ("webp", "webp"),
    ("avif", "avif"),
    ("png", "png"),
    ("jpg", "jpg"),
    ("clean", "Только почистить (без потерь)"),
]


def describe(info, src=None, was=None):
    """Сведения о сжатии одной строкой: формат, качество, что сделано с картинкой."""
    out = [info["fmt"]]
    if info.get("clean"):
        out.append("без потерь, без метаданных")
    elif info.get("lossless"):
        out.append("без потерь")
    elif info.get("q"):
        out.append("качество %d" % info["q"])
    if "size" in info:
        out.append("%dx%d" % tuple(info["size"]))
    if info.get("sharp"):
        out.append("рисунок: цвет без прореживания")
    if info.get("trimmed"):
        out.append("поля срезаны")
    if info.get("budget"):
        out.append("уменьшено, чтобы влезть" if info.get("scaled") else "качество снижено под лимит")
    if info.get("over"):
        out.append("в лимит не влезло даже так")
    if src is not None and info["fmt"] == "jpg" and K.has_alpha(src):
        out.append("прозрачное зальётся подложкой")
    return "   ".join(out)


class Variants(QWidget):
    """Сравнение форматов на текущей картинке: карточки с кусочком 1:1 (видны артефакты),
    весом и похожестью. Щелчок по карточке выбирает формат."""

    def __init__(self, pick):
        super().__init__()
        self.pick, self.items, self.busy, self.cur, self.hover = pick, [], False, "", -1
        self.setFixedHeight(184)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self.update)

    def loading(self, n):
        self.items, self.busy = [None] * n, True
        self.timer.start()
        self.show()
        self.update()

    def set_items(self, items, cur):
        self.items, self.busy, self.cur = items, False, cur
        self.timer.stop()
        self.update()

    def cards(self):
        n = max(1, len(self.items))
        w = min(200, (self.width() - 8 * (n - 1)) / n)
        x0 = (self.width() - (w * n + 8 * (n - 1))) / 2
        return [QRectF(x0 + i * (w + 8), 4, w, self.height() - 8) for i in range(n)]

    def mouseMoveEvent(self, e):
        h = next((i for i, r in enumerate(self.cards()) if r.contains(e.position())), -1)
        if h != self.hover:
            self.hover = h
            self.update()

    def leaveEvent(self, _e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        for r, it in zip(self.cards(), self.items):
            if it and r.contains(e.position()):
                self.pick(it["fmt"])

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        smallest = min((it["bytes"] for it in self.items if it), default=0)
        f1, f2 = QFont("Segoe UI", 10), QFont("Segoe UI", 8)
        f1.setWeight(QFont.Weight.Bold)
        for i, (r, it) in enumerate(zip(self.cards(), self.items)):
            on = it is not None and it["fmt"] == self.cur
            p.setPen(QPen(QColor(C["acc"] if on else C["acc2"] if i == self.hover else C["line"]), 2 if on else 1))
            p.setBrush(QColor(C["bg2"]))
            p.drawRoundedRect(r, 12, 12)
            pic = QRectF(r.x() + 8, r.y() + 8, r.width() - 16, r.height() - 64)
            if it is None:                       # считается - перелив
                ph = (time.monotonic() * 0.8 + i * 0.15) % 1.4 - 0.2
                g = QLinearGradient(pic.topLeft(), pic.topRight())
                g.setColorAt(0, QColor(C["bg3"]))
                g.setColorAt(max(0.0, min(1.0, ph)), QColor(C["accd"]))
                g.setColorAt(1, QColor(C["bg3"]))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(g))
                p.drawRoundedRect(pic, 8, 8)
                continue
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(pic, 8, 8)
            p.setClipPath(clip)
            p.fillRect(pic, QColor("#111117"))
            pm = it["pix"]
            if pm is not None:
                k = min(pic.width() / pm.width(), pic.height() / pm.height(), 2.0)
                w, h = pm.width() * k, pm.height() * k
                p.drawPixmap(QRectF(pic.center().x() - w / 2, pic.center().y() - h / 2, w, h), pm, QRectF(pm.rect()))
            p.restore()
            p.setPen(QColor(C["text"]))
            p.setFont(f1)
            p.drawText(QRectF(r.x() + 10, r.bottom() - 52, r.width() - 20, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, it["fmt"])
            p.drawText(QRectF(r.x() + 10, r.bottom() - 52, r.width() - 20, 20),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, human(it["bytes"]))
            p.setFont(f2)
            p.setPen(QColor(C["dim"]))
            score = "похожесть %.1f%%" % (100 * it["score"]) if it.get("score") is not None else "размер другой"
            p.drawText(QRectF(r.x() + 10, r.bottom() - 30, r.width() - 20, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, score)
            if it["bytes"] == smallest:          # самый лёгкий - плашка
                tag = QRectF(r.right() - 74, r.y() + 12, 62, 20)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(C["acc"]))
                p.drawRoundedRect(tag, 10, 10)
                p.setPen(QColor(C["ink"]))
                p.drawText(tag, Qt.AlignmentFlag.AlignCenter, "легче всех")
        p.end()


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


def remember_savings(cfg, r):
    """Копит «сэкономлено сжатием» по разделам - это видно в окне «Вес разделов»."""
    saved = cfg.setdefault("saved", {})
    for sec, (was, now) in r.get("sections", {}).items():
        saved[sec] = saved.get(sec, 0) + max(0, was - now)


class Progress(QWidget):
    """Карточка поверх окна сжатия: кольцо хода работы с миниатюрой текущего файла, сколько уже
    сэкономлено; в конце - кольцо замыкается, итог «-63%» набегает счётчиком, разлетаются искры."""

    def __init__(self, dlg):
        super().__init__(dlg)
        self.dlg = dlg
        self.shown_v, self.target, self.spin = 0.0, 0.0, 0.0
        self.line1 = self.line2 = ""
        self.pm, self.result, self.t_done, self.sparks = None, None, 0.0, []
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self.tick)
        self.stop_btn = QPushButton("Остановить", self, objectName="ghost")
        self.undo_btn = QPushButton("Вернуть как было", self, objectName="ghost")
        self.ok_btn = QPushButton("Готово", self, objectName="primary")
        self.stop_btn.clicked.connect(dlg.stop_run)
        self.undo_btn.clicked.connect(dlg.undo_run)
        self.ok_btn.clicked.connect(dlg.accept)
        self.hide()

    # --- состояние
    def start(self, n):
        self.shown_v = self.target = 0.0
        self.result, self.sparks, self.pm = None, [], None
        self.line1, self.line2 = "Готовлюсь... (%d шт.)" % n, ""
        self.stop_btn.show()
        self.undo_btn.hide()
        self.ok_btn.hide()
        self.setGeometry(self.dlg.rect())
        self.raise_()
        self.show()
        self.timer.start()

    def step(self, i, n, name, before, after, path):
        self.target = i / max(1, n)
        self.line1 = "Сжимаю %d из %d, %s" % (i + 1, n, name)
        self.line2 = f"Уже сэкономлено {human(before - after)}" if before > after else ""
        try:
            self.pm = thumb(path, 256)
        except Exception:
            self.pm = None

    def finish(self, r, can_undo):
        self.target = 1.0
        self.result = r
        self.t_done = time.monotonic()
        self.pm = None
        if r["done"]:
            self.line1 = "Было {}  →  стало {}".format(human(r["before"]), human(r["after"]))
            self.line2 = "Сжато %d из %d, сэкономлено %s" % (r["done"], r["total"], human(r["before"] - r["after"]))
        else:
            self.line1 = "Сжимать нечего - файлы уже лёгкие"
            self.line2 = ""
        skipped = ", ".join("%s: %d" % kv for kv in r["skipped"].items())
        if skipped:
            self.line2 = (self.line2 + ", " if self.line2 else "") + "пропущено (" + skipped + ")"
        if r["done"]:                                   # искры из кольца
            for _k in range(46):
                a = random.uniform(0, 2 * math.pi)
                v = random.uniform(2.2, 5.5)
                self.sparks.append((math.cos(a) * v, math.sin(a) * v, random.uniform(2, 4.5), random.random()))
        self.stop_btn.hide()
        self.undo_btn.setVisible(can_undo)
        self.ok_btn.show()
        self.ok_btn.setFocus()

    def percent(self):
        r = self.result
        return round(100 * (1 - r["after"] / max(1, r["before"]))) if r and r["done"] else 0

    # --- анимация
    def tick(self):
        self.shown_v += (self.target - self.shown_v) * 0.12
        self.spin = (self.spin + 4.0) % 360
        self.update()

    def card(self):
        w, h = 440, 400
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def resizeEvent(self, _e):
        c = self.card()
        y = int(c.bottom()) - 58
        self.stop_btn.setGeometry(int(c.center().x()) - 80, y, 160, 38)
        self.undo_btn.setGeometry(int(c.x()) + 28, y, 180, 38)
        self.ok_btn.setGeometry(int(c.right()) - 28 - 160, y, 160, 38)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(9, 9, 13, 215))
        c = self.card()
        p.setPen(QPen(QColor(C["line2"]), 1))
        p.setBrush(QColor(C["bg1"]))
        p.drawRoundedRect(c, 22, 22)

        center = QPointF(c.center().x(), c.y() + 118)
        rad = 72
        ring = QRectF(center.x() - rad, center.y() - rad, 2 * rad, 2 * rad)
        done = self.result is not None
        age = time.monotonic() - self.t_done if done else 0.0

        glow = QRadialGradient(center, rad * 1.9)           # мягкий ореол за кольцом, в конце вспыхивает
        g0 = QColor(C["acc"])
        g0.setAlpha(int(70 + (70 * max(0.0, 1 - age) if done else 0)))
        glow.setColorAt(0, g0)
        g0.setAlpha(0)
        glow.setColorAt(1, g0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(center, rad * 1.9, rad * 1.9)

        if self.pm and not self.pm.isNull():               # текущий файл внутри кольца
            inner = rad - 14
            path = QPainterPath()
            path.addEllipse(center, inner, inner)
            p.save()
            p.setClipPath(path)
            k = max(2 * inner / self.pm.width(), 2 * inner / self.pm.height())
            w, h = self.pm.width() * k, self.pm.height() * k
            p.setOpacity(0.85)
            p.drawPixmap(QRectF(center.x() - w / 2, center.y() - h / 2, w, h), self.pm, QRectF(self.pm.rect()))
            p.restore()

        p.setPen(QPen(QColor(C["line2"]), 10))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring)
        grad = QConicalGradient(center, 90)
        grad.setColorAt(0, QColor(C["acc"]))
        grad.setColorAt(0.5, QColor(C["acc2"]))
        grad.setColorAt(1, QColor(C["acc"]))
        pen = QPen(QBrush(grad), 10)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(ring, 90 * 16, -int(max(0.02, self.shown_v) * 360 * 16))
        if not done:                                       # бегущая искра по кольцу - «работаю»
            a = math.radians(90 - self.spin)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(center.x() + rad * math.cos(a), center.y() - rad * math.sin(a)), 4, 4)

        if done and self.result["done"]:
            e = 1 - (1 - min(1.0, age / 0.5)) ** 3
            s = 30 * (0.6 + 0.4 * e)                       # галочка в кружке выпрыгивает
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawEllipse(center, s, s)
            tick = QPen(QColor(C["ink"]), 5)
            tick.setCapStyle(Qt.PenCapStyle.RoundCap)
            tick.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(tick)
            path = QPainterPath(QPointF(center.x() - s * 0.42, center.y() + s * 0.02))
            path.lineTo(center.x() - s * 0.1, center.y() + s * 0.34)
            path.lineTo(center.x() + s * 0.45, center.y() - s * 0.3)
            p.drawPath(path)
            if age < 1.4:                                  # искры разлетаются и гаснут
                t = age * 60
                p.setPen(Qt.PenStyle.NoPen)
                for vx, vy, size, hue in self.sparks:
                    col = QColor(C["acc"] if hue < 0.5 else C["acc2"])
                    col.setAlpha(int(255 * (1 - age / 1.4)))
                    p.setBrush(col)
                    p.drawEllipse(QPointF(center.x() + vx * t, center.y() + vy * t + 0.04 * t * t), size, size)

        f = QFont("Segoe UI", 26)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        if done:
            k = 1 - (1 - min(1.0, age / 0.9)) ** 3        # счётчик набегает
            big = "-%d%%" % round(self.percent() * k) if self.result["done"] else "0%"
        else:
            big = "%d%%" % round(self.shown_v * 100)
        top = center.y() + rad + 16
        p.setPen(QColor(C["text"]))
        p.drawText(QRectF(c.x(), top, c.width(), 44), Qt.AlignmentFlag.AlignCenter, big)
        p.setFont(QFont("Segoe UI", 10))
        fm = p.fontMetrics()
        p.setPen(QColor(C["text"] if done else C["dim"]))
        p.drawText(QRectF(c.x() + 20, top + 46, c.width() - 40, 22), Qt.AlignmentFlag.AlignCenter,
                   fm.elidedText(self.line1, Qt.TextElideMode.ElideMiddle, int(c.width() - 40)))
        p.setPen(QColor(C["dim"]))
        p.drawText(QRectF(c.x() + 20, top + 70, c.width() - 40, 22), Qt.AlignmentFlag.AlignCenter,
                   fm.elidedText(self.line2, Qt.TextElideMode.ElideRight, int(c.width() - 40)))
        p.end()


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
            fmt="", q=0, target=0.99, lossless=False, size=0, fit="fit", smaller=True,
            kind="auto", trim=False, budget=0, matte="white",
        )
        self.o.update(tab.cfg.get("comp", {}))
        self.cache, self.gen, self.stop = {}, 0, [False]
        self.setWindowTitle("Сжать и конвертировать: %d шт." % len(self.paths))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)     # оригинал в self.cache не копится в памяти
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
        self.smaller = QCheckBox("Не трогать, если не станет легче")
        self.kind = QComboBox()
        for v, t in K.KINDS:
            self.kind.addItem(t, v)
        self.kind.setToolTip("Рисунку (иконка, наклейка) цвет не прореживается - контуры не мылятся,\n"
                             "и для webp пробуется сжатие без потерь. «Само» - по прозрачности и числу цветов.")
        self.trim = QCheckBox("Срезать прозрачные поля")
        self.trim.setToolTip("Пустая прозрачная рамка вокруг рисунка весит и мешает выравнивать")
        self.budget = QSpinBox(minimum=0, maximum=50000, singleStep=50, suffix=" КБ",
                               specialValueText="без ограничения")
        self.budget.setToolTip("Не больше стольких КБ: сначала снижается качество, не хватает - размер.\n"
                               "Для лимитов телеграма, Discord, аватаров, README.")
        self.matte = QComboBox()
        for v, t, _rgb in K.MATTES:
            self.matte.addItem(t, v)
        self.matte.setToolTip("jpg не умеет прозрачность: чем залить прозрачные места")
        self.files = QComboBox()
        for p in self.paths:
            self.files.addItem(os.path.relpath(p, LIB), p)
        self.files.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.files.setMinimumContentsLength(20)
        for c in (self.fmt, self.how, self.fit, self.kind, self.matte):
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
        form.addRow("Что на ней", self.kind)
        form.addRow("Размер", self.size)
        form.addRow("Как", self.fit)
        form.addRow("", self.trim)
        form.addRow("Не больше", self.budget)
        form.addRow("Подложка", self.matte)
        form.addRow("", self.smaller)
        box = QGroupBox("Настройки")
        box.setLayout(form)
        note = QLabel(
            "Подбор качества сам ищет самое низкое качество, при котором на глаз разницы нет.\n\n"
            "Оригиналы уезжают в «_sources/compress <дата>», Ctrl+Z в окне возвращает всё как было.",
            objectName="dim",
            wordWrap=True,
        )
        self.result = QLabel(objectName="big", wordWrap=True)
        self.detail = QLabel(objectName="dim", wordWrap=True)
        self.go = QPushButton(lib_icon("zip-archive"), "", objectName="primary")
        self.go.clicked.connect(self.run)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        left = QVBoxLayout()
        left.addWidget(box)
        left.addWidget(note)
        left.addStretch(1)
        left.addWidget(self.result)
        left.addWidget(self.detail)
        left.addWidget(self.go)
        row = QHBoxLayout()
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
        self.cmp_btn = flat("Сравнить форматы", self.compare_formats,
                            "Этот файл в webp, avif, png и jpg рядом: вес, похожесть, кусочек 1:1")
        top = QHBoxLayout()
        top.addWidget(prev)
        top.addWidget(self.files, 1)
        top.addWidget(nxt)
        top.addWidget(self.cmp_btn)
        self.variants = Variants(self.pick_format)
        self.variants.hide()
        hint = QLabel(
            "Тяните мышью - шторка, колесо - увеличить, правая кнопка - двигать, двойной щелчок - целиком",
            objectName="dim",
        )
        right = QVBoxLayout()
        right.addLayout(top)
        right.addWidget(self.cmp, 1)
        right.addWidget(self.variants)
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
        self.kind.setCurrentIndex(max(0, self.kind.findData(self.o.get("kind", "auto"))))
        self.trim.setChecked(self.o.get("trim", False))
        self.budget.setValue(self.o.get("budget", 0))
        self.matte.setCurrentIndex(max(0, self.matte.findData(self.o.get("matte", "white"))))
        self.timer = QTimer(self, singleShot=True, interval=300)
        self.timer.timeout.connect(self.preview)
        for c in (self.fmt, self.how, self.fit, self.files, self.kind, self.matte):
            c.currentIndexChanged.connect(self.changed)
        for c in (self.q, self.size, self.budget):
            c.valueChanged.connect(self.changed)
        for c in (self.lossless, self.smaller, self.trim):
            c.toggled.connect(self.changed)
        self.files.currentIndexChanged.connect(lambda _i: self.variants.hide())
        self.overlay = Progress(self)
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
            kind=self.kind.currentData(),
            trim=self.trim.isChecked(),
            budget=self.budget.value(),
            matte=self.matte.currentData(),
        )

    def changed(self, *_):
        o = self.opts()
        clean = o["fmt"] == "clean"
        self.how.setEnabled(not clean and not o["lossless"])
        self.q.setEnabled(not clean and not o["lossless"] and o["q"] != 0)
        self.lossless.setEnabled(not clean and o["fmt"] in ("", "webp", "png", "avif", K.BEST))
        for w in (self.size, self.fit, self.kind, self.trim, self.budget):
            w.setEnabled(not clean)
        self.matte.setEnabled(o["fmt"] in ("jpg", K.BEST, "") and not clean)
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
                data = K.clean(p)
                return gen, src, src if data else None, data, dict(fmt=fmt, clean=True), fmt
            if fmt not in CAN and fmt != K.BEST:
                return gen, src, None, None, None, fmt
            data, info = K.compress(src, dict(o, fmt=fmt))
            out = Image.open(io.BytesIO(data))
            out.load()
            shown = K.trim(src)[0] if info.get("trimmed") else src     # шторке - тот же кадр, без полей
            return gen, shown, out, data, info, fmt

        bg(work, self.shown)

    def shown(self, res):
        if sip.isdeleted(self):                         # окно закрыли, пока считался предпросмотр
            return
        if isinstance(res, Exception):
            self.result.setText(f"Не получилось: {res}")
            return
        gen, src, out, data, info, fmt = res
        if gen != self.gen:
            return
        p = self.files.currentData()
        try:
            was = os.path.getsize(p)
        except OSError:                                 # файл уже сжат и уехал в _sources
            self.result.setText("Файла уже нет на месте")
            return
        self.cmp.set_images(to_pix(src), to_pix(out) if out is not None else None)
        if data is None:
            self.result.setText(
                "Этот файл так не сжать"
                if fmt not in CAN and fmt != K.BEST
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
        self.result.setText(f"{human(was)}  ->  {human(now)}   ({sign})")
        text = describe(info, src)
        if fmt == K.BEST:
            text = "выбран " + text
        if now >= was and self.smaller.isChecked():
            text += "   файл не станет легче - его не тронем"
        self.detail.setText(text)

    def compare_formats(self):
        p = self.files.currentData()
        if not p:
            return
        o = self.opts()
        o.update(lossless=False)
        src = self.cache.get(p)                     # оригинал уже открыт для шторки - второй раз не читаем
        fmts = ["webp", "avif", "png"] + ([] if K.has_alpha(src if src is not None else K.load(p)) else ["jpg"])
        self.variants.loading(len(fmts))
        self.vgen = getattr(self, "vgen", 0) + 1
        gen = self.vgen

        def work():
            got = {}
            for _p, res in parallel(K.job_variant, [(p, dict(o, fmt=f)) for f in fmts]):
                if isinstance(res, Exception):
                    continue
                data, info = res
                im = Image.open(io.BytesIO(data))
                im.load()
                side = 132                                   # кусочек 1:1 из середины - видны артефакты
                cx, cy = im.width // 2, im.height // 2
                crop = im.crop((max(0, cx - side // 2), max(0, cy - side // 2),
                                min(im.width, cx + side // 2), min(im.height, cy + side // 2)))
                got[info["fmt"]] = dict(fmt=info["fmt"], bytes=len(data), score=info.get("score"), img=crop)
            return [got[f] for f in fmts if f in got]

        def done(res):
            if sip.isdeleted(self) or gen != self.vgen or isinstance(res, Exception):
                return
            for it in res:
                it["pix"] = to_pix(it.pop("img"))
            self.variants.set_items(res, self.fmt.currentData())

        bg(work, done)

    def pick_format(self, fmt):
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(fmt)))
        self.variants.cur = fmt
        self.variants.update()

    def run(self):
        o = self.opts()
        self.tab.cfg["comp"] = {k: v for k, v in o.items()}
        o["stop"] = self.stop
        self.stop[0] = False
        self.go.setEnabled(False)
        self.running, self.steps = True, []
        self.overlay.start(len(self.paths))

        def progress(v):
            if not sip.isdeleted(self):
                self.overlay.step(*v)

        paths = list(self.paths)
        bg(
            lambda: compress_files(paths, o, lambda v: in_main(progress, v)),
            self.finished_batch,
        )

    def stop_run(self):
        self.stop[0] = True
        self.overlay.stop_btn.setEnabled(False)
        self.overlay.stop_btn.setText("Останавливаю...")

    def undo_run(self):
        """Вернуть сжатые файлы как было - то же, что Ctrl+Z в главном окне."""
        if self.steps:
            self.win.undo()
        self.accept()

    def reject(self):
        if not getattr(self, "running", False):         # пока сжимается, окно не закрыть - только остановить
            super().reject()

    def accept(self):
        self.overlay.timer.stop()
        super().accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.overlay.isVisible():
            self.overlay.setGeometry(self.rect())

    def finished_batch(self, res):
        self.running = False
        self.go.setEnabled(True)
        self.overlay.stop_btn.setEnabled(True)
        self.overlay.stop_btn.setText("Остановить")
        if isinstance(res, Exception):
            self.overlay.hide()
            self.overlay.timer.stop()
            QMessageBox.warning(self, "Не получилось", str(res))
            return
        steps, r = res
        remember_savings(self.tab.cfg, r)
        text = report_text(r)
        src = None
        for st in steps:
            if st[0] == "move":
                src = st[1]
            elif src and os.path.splitext(st[1])[0] == os.path.splitext(src)[0]:
                self.win.moved(src, st[1])  # избранное - за новым файлом
        self.steps = steps
        if steps:
            self.win.push("Сжатие: %d шт." % r["done"], steps)
        self.win.say(text.replace("\n", "   "))
        self.tab.done(text.split("\n")[0])
        self.overlay.finish(r, bool(steps))
