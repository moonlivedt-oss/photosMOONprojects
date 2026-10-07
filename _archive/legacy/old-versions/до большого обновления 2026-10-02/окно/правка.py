"""Редактор картинки: поворот, отражение, кадрирование, цвет, убрать фон, обводка, квадрат, размер.
Правка - рецепт (цвет + шаги), он показывается на уменьшенной копии сразу, а при сохранении
применяется к полному размеру в фоне. «Сохранить» уносит оригинал в «_исходники/правка <дата>»
(Ctrl+Z в окне возвращает), «Сохранить копию» кладёт новый файл рядом. Несколько выбранных
картинок - один рецепт на все (например, обводка или квадрат для целого набора иконок)."""
import os
import shutil
import time

import картинки as K
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from окно.виджеты import flat, key
from окно.миниатюры import lib_icon, to_qimage
from окно.общее import LIB, SOURCES, bg, human, in_main, parallel, unique
from окно.оформление import C

PROXY = 1200                                # сторона копии для живого предпросмотра
RATIOS = [("Свободно", None), ("1:1", 1.0), ("4:3", 4 / 3), ("3:2", 1.5), ("16:9", 16 / 9),
          ("3:4", 3 / 4), ("9:16", 9 / 16)]
NAMES = {"rotate": "поворот", "flip": "отражение", "crop": "обрезка", "trim": "поля срезаны",
         "nobg": "фон убран", "outline": "обводка", "square": "квадрат", "resize": "размер"}


# ---------------------------------------------------------------- холст
class Canvas(QWidget):
    """Картинка на шахматке. В режиме кадрирования - рамка: тянуть по пустому месту - новая,
    за середину - двигать, за уголок - менять размер (с соблюдением пропорции, если она задана)."""
    HANDLE = 9

    def __init__(self, dlg):
        super().__init__()
        self.dlg, self.pm, self.orig, self.compare = dlg, None, None, False
        self.cropping, self.crop, self.ratio, self.drag = False, None, None, None
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
        k = min(box.width() / pm.width(), box.height() / pm.height())
        w, h = pm.width() * k, pm.height() * k
        return QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)

    # --- кадрирование
    def crop_rect(self):
        r, c = self.image_rect(), self.crop
        return QRectF(r.x() + c[0] * r.width(), r.y() + c[1] * r.height(),
                      (c[2] - c[0]) * r.width(), (c[3] - c[1]) * r.height())

    def to_norm(self, pos):
        r = self.image_rect()
        return (min(1.0, max(0.0, (pos.x() - r.x()) / r.width())),
                min(1.0, max(0.0, (pos.y() - r.y()) / r.height())))

    def corner_at(self, pos):
        if not self.crop:
            return None
        cr = self.crop_rect()
        for name, pt in (("tl", cr.topLeft()), ("tr", cr.topRight()), ("bl", cr.bottomLeft()), ("br", cr.bottomRight())):
            if abs(pos.x() - pt.x()) <= self.HANDLE + 3 and abs(pos.y() - pt.y()) <= self.HANDLE + 3:
                return name
        return None

    def fix_ratio(self, x0, y0, x1, y1, anchor_x, anchor_y):
        """Подогнать рамку под пропорцию: ширина главная, высота следует (в пикселях картинки)."""
        if not self.ratio or not self.pm:
            return x0, y0, x1, y1
        W, H = self.pm.width(), self.pm.height()
        w = abs(x1 - x0)
        h = w * W / (H * self.ratio)
        if h > 1:                               # не влезло по высоте - от высоты
            h = 1.0
            w = h * H * self.ratio / W
        sx = 1 if x1 >= x0 else -1
        sy = 1 if y1 >= y0 else -1
        x1, y1 = anchor_x + sx * w, anchor_y + sy * h
        if not 0 <= y1 <= 1:                    # упёрлись в край - сжимаем
            y1 = min(1.0, max(0.0, y1))
            h = abs(y1 - anchor_y)
            w = h * H * self.ratio / W
            x1 = anchor_x + sx * w
        if not 0 <= x1 <= 1:
            x1 = min(1.0, max(0.0, x1))
            w = abs(x1 - anchor_x)
            h = w * W / (H * self.ratio)
            y1 = anchor_y + sy * h
        return anchor_x, anchor_y, x1, y1

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

    def mousePressEvent(self, e):
        if not self.cropping or not self.pm or e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        corner = self.corner_at(pos)
        if corner:
            x0, y0, x1, y1 = self.crop
            ax = x1 if "l" in corner else x0           # противоположный угол стоит на месте
            ay = y1 if "t" in corner else y0
            self.drag = ("corner", ax, ay)
        elif self.crop and self.crop_rect().contains(pos):
            self.drag = ("move", self.to_norm(pos), self.crop)
        else:
            nx, ny = self.to_norm(pos)
            self.drag = ("corner", nx, ny)
            self.crop = (nx, ny, nx, ny)

    def mouseMoveEvent(self, e):
        pos = e.position()
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
            nx, ny = self.to_norm(pos)
            ax, ay, nx, ny = self.fix_ratio(ax, ay, nx, ny, ax, ay)
            self.crop = (min(ax, nx), min(ay, ny), max(ax, nx), max(ay, ny))
        self.update()
        self.dlg.crop_changed()

    def mouseReleaseEvent(self, _e):
        if self.drag and self.crop and (self.crop[2] - self.crop[0] < 0.01 or self.crop[3] - self.crop[1] < 0.01):
            self.reset_crop()                   # щелчок без протяжки - рамка на всю картинку
        self.drag = None

    def mouseDoubleClickEvent(self, _e):
        if self.cropping:
            self.dlg.apply_crop()

    # --- рисование
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
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
        p.end()

    def tag(self, p, text):
        fm = p.fontMetrics()
        box = QRectF(12, 12, fm.horizontalAdvance(text) + 18, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(21, 21, 28, 220))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor(C["text"]))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


# ---------------------------------------------------------------- сохранение
def save_edits(paths, ops, adj, copy, report):
    """В фоне, по ядрам: рецепт ко всем файлам. copy - новый файл рядом, иначе оригинал уезжает
    в _исходники/правка <дата>. Возвращает (шаги для Ctrl+Z, [(было, стало)], [ошибки])."""
    arch = os.path.join(SOURCES, "правка " + time.strftime("%Y-%m-%d"))
    steps, done, bad = [], [], []
    items = [(p, dict(ops=ops, adj=adj)) for p in paths]
    for i, (p, res) in enumerate(parallel(K.job_edit, items)):
        report((i, len(items), os.path.basename(p)))
        try:
            if isinstance(res, Exception):
                raise res
            data, fmt, _size = res
            stem = os.path.splitext(p)[0]
            if copy:
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
    def __init__(self, parent, win, paths, on_saved=None):
        super().__init__(parent)
        self.win, self.on_saved = win, on_saved
        self.paths = [p for p in paths if K.fmt_of(p) in K.EDITABLE and not K.is_animated(p)]
        self.skipped = len(paths) - len(self.paths)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Правка" + (": %d шт." % len(self.paths) if len(self.paths) > 1 else ""))
        self.resize(1180, 760)
        self.ops, self.adj = [], {k: 0 for k, _t in K.ADJ}
        self.undo_stack, self.redo_stack = [], []
        self.base = None                    # уменьшенная копия текущего файла (PIL)
        self.scale, self.full = 1.0, (1, 1)
        self.gen, self.saving = 0, False
        self.idx = 0

        self.canvas = Canvas(self)
        self.file_lbl = QLabel(objectName="dim")
        prev, nxt = flat("<", lambda: self.step_file(-1), "Предыдущий файл"), flat(">", lambda: self.step_file(1), "Следующий")
        top = QHBoxLayout()
        top.addWidget(prev)
        top.addWidget(self.file_lbl, 1)
        top.addWidget(nxt)
        for w in (prev, nxt):
            w.setVisible(len(self.paths) > 1)
        self.size_lbl = QLabel(objectName="dim")
        hint = QLabel("Удерживайте «Сравнить» или \\ - увидеть, как было.  Ctrl+Z / Ctrl+Y - шаг назад / вперёд",
                      objectName="dim")
        left = QVBoxLayout()
        left.addLayout(top)
        left.addWidget(self.canvas, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        bottom.addWidget(self.size_lbl)
        left.addLayout(bottom)

        # --- поворот
        g1 = QGridLayout()
        for i, (text, fn) in enumerate((("Влево", lambda: self.add(op="rotate", deg=270)),
                                        ("Вправо", lambda: self.add(op="rotate", deg=90)),
                                        ("Отразить", lambda: self.add(op="flip", dir="h")),
                                        ("Вверх ногами", lambda: self.add(op="flip", dir="v")))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            g1.addWidget(b, i // 2, i % 2)
        b1 = QGroupBox("Поворот и отражение")
        b1.setLayout(g1)

        # --- обрезка
        self.ratio = QComboBox()
        for t, v in RATIOS:
            self.ratio.addItem(t, v)
        self.ratio.currentIndexChanged.connect(lambda _i: self.canvas.set_ratio(self.ratio.currentData()))
        self.crop_btn = QPushButton("Кадрировать")
        self.crop_btn.setToolTip("Рамка на картинке: тянуть, двигать, уголки. Enter или двойной щелчок - обрезать")
        self.crop_btn.clicked.connect(self.toggle_crop)
        self.crop_ok = QPushButton("Обрезать", objectName="primary")
        self.crop_ok.clicked.connect(self.apply_crop)
        self.crop_ok.hide()
        trim_b = QPushButton("Срезать пустые поля")
        trim_b.setToolTip("Убрать прозрачную рамку вокруг рисунка")
        trim_b.clicked.connect(lambda: self.add(op="trim"))
        v2 = QVBoxLayout()
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Пропорции"))
        r2.addWidget(self.ratio, 1)
        v2.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(self.crop_btn)
        r3.addWidget(self.crop_ok)
        v2.addLayout(r3)
        v2.addWidget(trim_b)
        b2 = QGroupBox("Обрезка")
        b2.setLayout(v2)

        # --- цвет
        g3 = QGridLayout()
        self.sliders = {}
        for i, (k, text) in enumerate(K.ADJ):
            s = QSlider(Qt.Orientation.Horizontal, minimum=-180 if k == "hue" else -100,
                        maximum=180 if k == "hue" else 100)
            s.setToolTip("Двойной щелчок по названию - сбросить")
            val = QLabel("0", objectName="dim")
            val.setFixedWidth(34)
            lbl = QPushButton(text, objectName="flat")
            lbl.clicked.connect(lambda _c=False, sl=s: sl.setValue(0))
            s.sliderPressed.connect(self.remember)
            s.valueChanged.connect(lambda v, kk=k, vl=val: self.adj_changed(kk, v, vl))
            g3.addWidget(lbl, i, 0)
            g3.addWidget(s, i, 1)
            g3.addWidget(val, i, 2)
            self.sliders[k] = (s, val)
        reset = flat("Сбросить цвет", self.reset_color)
        g3.addWidget(reset, len(K.ADJ), 1)
        b3 = QGroupBox("Цвет")
        b3.setLayout(g3)

        # --- фон и наклейка
        self.tol = QSpinBox(minimum=5, maximum=120, value=38)
        self.tol.setToolTip("Насколько цвет может отличаться от фона по краям, чтобы считаться фоном")
        self.px = QSpinBox(minimum=1, maximum=60, value=8, suffix=" px")
        self.pad = QSpinBox(minimum=0, maximum=40, value=6, suffix=" %")
        g4 = QGridLayout()
        nobg = QPushButton("Убрать фон")
        nobg.setToolTip("Однотонный фон, связанный с краями; белые детали внутри рисунка остаются")
        nobg.clicked.connect(lambda: self.add(op="nobg", tol=self.tol.value()))
        out = QPushButton("Обводка")
        out.setToolTip("Белая обводка вокруг рисунка, как у наклеек (нужна прозрачность)")
        out.clicked.connect(lambda: self.add(op="outline", px=self.px.value()))
        sq = QPushButton("Квадрат с полями")
        sq.setToolTip("Рисунок по центру квадрата, вокруг - прозрачные поля")
        sq.clicked.connect(lambda: self.add(op="square", pad=self.pad.value() / 100))
        for i, (b, spin) in enumerate(((nobg, self.tol), (out, self.px), (sq, self.pad))):
            g4.addWidget(b, i, 0)
            g4.addWidget(spin, i, 1)
        b4 = QGroupBox("Фон и наклейка")
        b4.setLayout(g4)

        # --- размер
        self.side = QSpinBox(minimum=16, maximum=8192, singleStep=64, suffix=" px")
        self.side.setToolTip("Длинная сторона картинки после правки")
        res = QPushButton("Изменить размер")
        res.clicked.connect(lambda: self.add(op="resize", size=self.side.value()))
        r5 = QHBoxLayout()
        r5.addWidget(self.side, 1)
        r5.addWidget(res)
        b5 = QGroupBox("Размер")
        b5.setLayout(r5)

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
        self.save_b.clicked.connect(lambda: self.save(False))
        self.copy_b = QPushButton("Сохранить копию")
        self.copy_b.setToolTip("Новый файл рядом: «<имя> правка»")
        self.copy_b.clicked.connect(lambda: self.save(True))
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        sv = QHBoxLayout()
        sv.addWidget(self.cmp_b)
        sv.addWidget(self.copy_b)
        sv.addWidget(close)

        right = QVBoxLayout()
        for w in (b1, b2, b3, b4, b5):
            right.addWidget(w)
        right.addStretch(1)
        right.addWidget(self.steps_lbl)
        right.addLayout(hist)
        right.addWidget(self.save_b)
        right.addLayout(sv)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(360)
        lay = QHBoxLayout(self)
        lay.addLayout(left, 1)
        lay.addWidget(rw)

        self.timer = QTimer(self, singleShot=True, interval=40)     # слайдер крутят - считаем по паузе
        self.timer.timeout.connect(self.render)
        key("Ctrl+Z", self, self.undo)
        key("Ctrl+Y", self, self.redo)
        key("Ctrl+Shift+Z", self, self.redo)
        key("Ctrl+S", self, lambda: self.save(False))
        self.update_ui()
        self.open_file()

    # --- файл
    def step_file(self, d):
        if len(self.paths) > 1:
            self.idx = (self.idx + d) % len(self.paths)
            self.open_file()

    def open_file(self):
        if not self.paths:
            self.file_lbl.setText("Эти файлы не правятся (svg, анимация или ico)")
            self.save_b.setEnabled(False)
            self.copy_b.setEnabled(False)
            return
        p = self.paths[self.idx]
        self.file_lbl.setText(os.path.relpath(p, LIB) + ("   (%d из %d)" % (self.idx + 1, len(self.paths))
                                                        if len(self.paths) > 1 else ""))
        self.base = None
        self.canvas.pm = self.canvas.orig = None
        self.canvas.update()
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

        bg(work, done)

    # --- рецепт
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
        self.adj = dict(adj)
        for k, (s, lbl) in self.sliders.items():
            s.blockSignals(True)
            s.setValue(self.adj.get(k, 0))
            s.blockSignals(False)
            lbl.setText(str(self.adj.get(k, 0)))

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
        if self.ops or any(self.adj.values()):
            self.remember()
            self.ops = []
            self.set_adj({k: 0 for k in self.adj})
            self.changed()

    def dirty(self):
        return bool(self.ops or any(self.adj.values()))

    def changed(self):
        self.update_ui()
        self.timer.start()

    def update_ui(self):
        parts = [NAMES[o["op"]] for o in self.ops]
        if any(self.adj.values()):
            parts.insert(0, "цвет")
        self.steps_lbl.setText("Сделано: " + ", ".join(parts) if parts else "Правок пока нет")
        self.undo_b.setEnabled(bool(self.undo_stack))
        self.redo_b.setEnabled(bool(self.redo_stack))
        self.reset_b.setEnabled(self.dirty())
        n = len(self.paths)
        self.save_b.setText("Сохранить" if n <= 1 else "Применить ко всем (%d)" % n)
        self.copy_b.setText("Сохранить копию" if n <= 1 else "Копии для всех")
        for b in (self.save_b, self.copy_b):
            b.setEnabled(self.dirty() and bool(self.paths) and not self.saving)

    # --- предпросмотр
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
            fw, fh = max(1, round(w / scale)), max(1, round(h / scale))
            self.size_lbl.setText("%d × %d  (было %d × %d)" % (fw, fh, *self.full)
                                  if (fw, fh) != tuple(self.full) else "%d × %d" % (fw, fh))

        def work():
            im = K.apply_edits(base, ops, adj, scale)
            return to_qimage(im), im.width, im.height

        bg(work, done)

    def show_orig(self, on):
        self.canvas.compare = on
        self.canvas.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Backslash and not e.isAutoRepeat():
            self.show_orig(True)
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.canvas.cropping:
            self.apply_crop()
        elif e.key() == Qt.Key.Key_Escape and self.canvas.cropping:
            self.toggle_crop()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Backslash and not e.isAutoRepeat():
            self.show_orig(False)
        else:
            super().keyReleaseEvent(e)

    # --- кадрирование
    def toggle_crop(self):
        c = self.canvas
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
            w = round((c.crop[2] - c.crop[0]) * c.pm.width() / self.scale)
            h = round((c.crop[3] - c.crop[1]) * c.pm.height() / self.scale)
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

    # --- сохранение
    def save(self, copy):
        if not self.dirty() or self.saving or not self.paths:
            return
        self.saving = True
        self.update_ui()
        paths, ops, adj = list(self.paths), [dict(o) for o in self.ops], dict(self.adj)
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
            for old, new in made:
                if not copy and old != new:
                    self.win.moved(old, new)        # избранное - за файлом, если сменился формат
            what = "Копии правки" if copy else "Правка"
            text = "%s: %d шт." % (what, len(made)) + ("   не вышло: %d" % len(bad) if bad else "")
            if not copy and made:
                was = sum(os.path.getsize(s[2]) for s in steps if s[0] == "move" and os.path.exists(s[2]))
                now = sum(os.path.getsize(n) for _o, n in made if os.path.exists(n))
                text += "   (%s -> %s)" % (human(was), human(now))
            self.win.push(text + ("   Ctrl+Z - вернуть" if steps else ""), steps)
            if self.on_saved:
                self.on_saved(text + ("   Ctrl+Z - вернуть" if steps else ""))
            if bad:
                self.win.say("Не всё сохранилось: " + "; ".join(bad))
            if not sip.isdeleted(self):
                self.saving = False
                self.accept()

        bg(lambda: save_edits(paths, ops, adj, copy, lambda v: in_main(progress, v)), done)

    def reject(self):
        if self.saving:
            return
        if self.canvas.cropping:                # Esc при рамке - отменить рамку, а не закрыть окно
            self.toggle_crop()
            return
        if self.dirty() and QMessageBox.question(self, "Правка", "Закрыть без сохранения? Правки пропадут.") \
                != QMessageBox.StandardButton.Yes:
            return
        super().reject()
