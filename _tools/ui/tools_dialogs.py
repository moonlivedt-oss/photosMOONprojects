"""Инструменты библиотеки: палитра из картинки (и перекраска в неё), сравнение версий со шторкой,
векторизация с вариантами, оформление (тема и акцент)."""

import os

import numpy as np
from PIL import Image, ImageFilter
from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import imaging as K
from ui import theme
from ui.common import bg, human, unique
from ui.compress import Compare
from ui.thumbnails import lib_icon, to_pix


# ================================================================ палитра из картинки
def extract_palette(im, n=6):
    """Главные цвета картинки (медианное сечение по непрозрачным пикселям), от тёмного к светлому."""
    im = im.convert("RGBA")
    im.thumbnail((256, 256))
    a = np.asarray(im)
    px = a[a[..., 3] > 128][:, :3]
    if not len(px):
        return []
    strip = Image.fromarray(px.reshape(1, -1, 3).astype(np.uint8), "RGB")
    q = strip.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: n * 3]
    counts = sorted(q.getcolors() or [], reverse=True)
    cols = [tuple(pal[i * 3 : i * 3 + 3]) for _c, i in counts]
    cols.sort(key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])
    return ["#%02x%02x%02x" % c for c in cols]


class Swatch(QPushButton):
    def __init__(self, hexv):
        super().__init__()
        self.hexv = hexv
        self.setFixedSize(46, 46)
        self.setToolTip(f"{hexv} - щелчок копирует")
        self.setStyleSheet(
            f"QPushButton{{background:{hexv};border:2px solid {theme.C['line2']};border-radius:12px}}"
            f"QPushButton:hover{{border-color:{theme.C['acc']}}}"
        )
        self.clicked.connect(lambda: QApplication.clipboard().setText(hexv))


class PaletteDialog(QDialog):
    """Палитра из любой картинки -> перекраска выбранных картинок библиотеки в неё (копиями)."""

    def __init__(self, win, targets, source=None):
        super().__init__(win, Qt.WindowType.Window)
        self.win, self.targets = win, [p for p in targets if p != source]
        self.colors, self.src, self.small = [], None, {}
        self.setWindowTitle("Палитра из картинки")
        self.setWindowIcon(lib_icon("color-palette"))
        self.resize(980, 680)
        self.pic = QLabel(alignment=Qt.AlignmentFlag.AlignCenter, objectName="pic")
        self.pic.setMinimumSize(260, 260)
        pick = QPushButton(lib_icon("folder"), "Картинка-образец...")
        pick.clicked.connect(self.choose)
        self.n = QSlider(Qt.Orientation.Horizontal, minimum=3, maximum=8, value=6)
        self.n.setToolTip("Сколько цветов взять")
        self.n.valueChanged.connect(self.extract)
        self.sw = QHBoxLayout()
        copy = QPushButton(lib_icon("clipboard"), "Копировать HEX")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(", ".join(self.colors)))
        self.strength = QSlider(Qt.Orientation.Horizontal, minimum=20, maximum=100, value=100)
        self.strength.setToolTip("Сила перекраски")
        self.strength.valueChanged.connect(self.preview)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(150, 150))
        self.grid.setGridSize(QSize(170, 190))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.info = QLabel(objectName="dim", wordWrap=True)
        self.save = QPushButton(lib_icon("save"), "Сохранить копии", objectName="primary")
        self.save.setToolTip("Рядом с оригиналами: «имя - палитра»; Ctrl+Z отменит")
        self.save.clicked.connect(self.save_all)

        left = QVBoxLayout()
        left.addWidget(QLabel("ОБРАЗЕЦ", objectName="faint"))
        left.addWidget(self.pic, 1)
        left.addWidget(pick)
        left.addWidget(QLabel("ЦВЕТОВ"))
        left.addWidget(self.n)
        left.addWidget(QLabel("ПАЛИТРА", objectName="faint"))
        left.addLayout(self.sw)
        left.addWidget(copy)
        right = QVBoxLayout()
        right.addWidget(QLabel("ПЕРЕКРАСКА ВЫБРАННЫХ КАРТИНОК", objectName="faint"))
        right.addWidget(self.grid, 1)
        h = QHBoxLayout()
        h.addWidget(QLabel("Сила"))
        h.addWidget(self.strength)
        h.addWidget(self.save)
        right.addLayout(h)
        right.addWidget(self.info)
        lay = QHBoxLayout(self)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(320)
        lay.addWidget(lw)
        lay.addLayout(right, 1)
        if source:
            self.load(source)
        self.update_info()

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Картинка-образец", K.LIB, "Картинки (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )
        if path:
            self.load(path)

    def load(self, path):
        try:
            self.src = K.load(path)
        except Exception as e:
            self.info.setText(f"Не открылась: {e}")
            return
        pm = to_pix(self.src)
        self.pic.setPixmap(
            pm.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        self.extract()

    def extract(self):
        if self.src is None:
            return
        self.colors = extract_palette(self.src, self.n.value())
        while self.sw.count():
            w = self.sw.takeAt(0).widget()
            if w:
                w.deleteLater()
        for c in self.colors:
            self.sw.addWidget(Swatch(c))
        self.preview()

    def preview(self):
        self.grid.clear()
        if len(self.colors) < 2:
            return
        k = self.strength.value() / 100
        for p in self.targets[:24]:
            try:
                if p not in self.small:  # ползунок силы двигают часто - с диска читается один раз
                    im = K.load(p)
                    im.thumbnail((300, 300))
                    self.small[p] = im
                out = K.recolor(self.small[p], self.colors, k)
            except Exception:
                continue
            it = QListWidgetItem(QIcon(to_pix(out)), os.path.basename(p))
            it.setToolTip(p)
            self.grid.addItem(it)
        self.update_info()

    def update_info(self):
        n = len(self.targets)
        self.info.setText(
            (
                "Выберите картинки в библиотеке перед открытием окна - их и перекрасим. "
                if not n
                else f"Будет перекрашено: {n}" + (" (показаны первые 24)" if n > 24 else "") + ". "
            )
            + "Тёмное станет самым тёмным цветом палитры, светлое - самым светлым, "
            "прозрачность не трогается."
        )
        self.save.setEnabled(bool(n) and len(self.colors) >= 2)

    def save_all(self):
        cols, k, paths = list(self.colors), self.strength.value() / 100, list(self.targets)
        self.save.setEnabled(False)  # второй щелчок, пока идёт сохранение, наделал бы копий « 2»

        def work():
            out, errs = [], []
            for p in paths:  # ошибка на одной картинке не теряет уже сохранённые (их отменит Ctrl+Z)
                try:
                    im = K.load(p)
                    base, ext = os.path.splitext(p)
                    dst = unique(f"{base} - палитра{ext}")
                    K.save(K.recolor(im, cols, k), dst, K.fmt_of(p))
                    out.append(dst)
                except Exception as e:
                    errs.append(f"{os.path.basename(p)}: {e}")
            return out, errs

        def done(res):
            if isinstance(res, Exception):
                self.info.setText(f"Не вышло: {res}")
                self.update_info()
                return
            saved, errs = res
            if saved:
                self.win.push(f"Перекраска в палитру: {len(saved)}", [("new", p) for p in saved])
                self.win.lib.changed.emit()
                self.win.say(f"Перекрашено копиями: {len(saved)}", undo=True)
            if errs:
                self.info.setText("Не вышло: " + "; ".join(errs[:3]))
                self.update_info()
                return
            self.accept()

        bg(work, done)


# ================================================================ сравнение версий
def diff_image(a, b):
    """Где картинки отличаются: разница яркостью, усиленная, поверх бледного оригинала."""
    a, b = a.convert("RGBA"), b.convert("RGBA").resize(a.size, Image.Resampling.LANCZOS)
    x, y = np.asarray(a).astype(np.int16), np.asarray(b).astype(np.int16)
    d = np.abs(x - y).max(axis=2).astype(np.float32)
    d = np.clip(d * 4, 0, 255)
    base = np.asarray(a.convert("L")).astype(np.float32) * 0.25
    out = np.stack([np.maximum(base, d), base + d * 0.2, base + d * 0.6, np.full(base.shape, 255.0)], axis=2)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


class CompareDialog(QDialog):
    """Две версии рядом: шторка, разница, сведения (размер, вес, похожесть SSIM)."""

    def __init__(self, win, a, b):
        super().__init__(win, Qt.WindowType.Window)
        self.win, self.pa, self.pb = win, a, b
        self.setWindowTitle("Сравнение версий")
        self.setWindowIcon(lib_icon("magnifying-glass"))
        self.resize(1100, 780)
        self.view = Compare()
        self.mode = QCheckBox("Показать разницу")
        self.mode.setToolTip("Светятся места, где картинки отличаются")
        self.mode.toggled.connect(self.show_pair)
        swap = QPushButton(lib_icon("arrow_horizontal"), "Поменять местами")
        swap.clicked.connect(self.swap)
        self.info = QLabel(objectName="dim", wordWrap=True)
        top = QHBoxLayout()
        top.addWidget(self.mode)
        top.addWidget(swap)
        top.addStretch(1)
        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.view, 1)
        v.addWidget(self.info)
        self.load()

    def load(self):
        self.ia, self.ib = K.load(self.pa), K.load(self.pb)
        self.view.labels = tuple(os.path.splitext(os.path.basename(x))[0][:24] for x in (self.pa, self.pb))
        self.show_pair()
        b2 = self.ib.resize(self.ia.size, Image.Resampling.LANCZOS)
        try:
            same = K.ssim(self.ia, b2)
        except Exception:
            same = None
        rows = []
        for tag, p, im in (("Слева", self.pa, self.ia), ("Справа", self.pb, self.ib)):
            rows.append(f"{tag}: {os.path.relpath(p, K.LIB)} - {im.width} x {im.height}, {human(os.path.getsize(p))}")
        if same is not None:
            word = "почти одинаковые" if same > 0.98 else "похожи" if same > 0.9 else "заметно отличаются"
            rows.append(f"Похожесть (SSIM): {same:.3f} - {word}")
        self.info.setText("\n".join(rows))

    def show_pair(self):
        if self.mode.isChecked():
            d = to_pix(diff_image(self.ia, self.ib))
            self.view.set_images(d, d)
        else:
            self.view.set_images(to_pix(self.ia), to_pix(self.ib.resize(self.ia.size, Image.Resampling.LANCZOS)))

    def swap(self):
        self.pa, self.pb = self.pb, self.pa
        self.load()


# ================================================================ векторизация с вариантами
VARIANTS = (
    (
        "Детально",
        "как есть, крупнее - мелкие детали сохраняются",
        lambda im: im.resize((im.width * 2, im.height * 2), Image.Resampling.LANCZOS),
    ),
    (
        "Сглаженно",
        "16 цветов и лёгкое размытие - ровные края, файл легче",
        lambda im: _poster(im.filter(ImageFilter.SMOOTH_MORE), 16),
    ),
    ("Плоско", "8 цветов - как значок, самый лёгкий файл", lambda im: _poster(im, 8)),
)


def _poster(im, n):
    """Меньше цветов - меньше контуров у vtracer (прозрачность сохраняется)."""
    im = im.convert("RGBA")
    a = im.getchannel("A")
    q = im.convert("RGB").quantize(colors=n, method=Image.Quantize.MEDIANCUT).convert("RGB")
    q.putalpha(a.point(lambda v: 255 if v > 128 else 0))
    return q


def svg_pixmap(data, side=260):
    r = QSvgRenderer(QByteArray(data))
    pm = QPixmap(side, side)
    pm.fill(QColor(0, 0, 0, 0))
    if r.isValid():
        s = r.defaultSize()
        k = min(side / max(1, s.width()), side / max(1, s.height()))
        w, h = s.width() * k, s.height() * k
        p = QPainter(pm)
        r.render(p, QRectF((side - w) / 2, (side - h) / 2, w, h))
        p.end()
    return pm


class VectorDialog(QDialog):
    """Картинка -> SVG в трёх вариантах рядом: видно, какой лучше; сохраняется выбранный."""

    def __init__(self, win, paths):
        super().__init__(win, Qt.WindowType.Window)
        self.win, self.paths, self.i = win, list(paths), 0
        self.results = {}
        self.setWindowTitle("Векторизация в SVG")
        self.setWindowIcon(lib_icon("drawing_pen"))
        self.resize(1180, 560)
        self.title = QLabel(objectName="head")
        self.grid = QGridLayout()
        self.cards = []
        for col, (name, hint, _fn) in enumerate((("Оригинал", "растровая картинка", None),) + VARIANTS):
            pic = QLabel(alignment=Qt.AlignmentFlag.AlignCenter, objectName="pic")
            pic.setFixedSize(270, 270)
            cap = QLabel(
                f"<b>{name}</b><br>{hint}", objectName="dim", wordWrap=True, alignment=Qt.AlignmentFlag.AlignCenter
            )
            btn = QPushButton(lib_icon("save"), "Сохранить этот SVG") if col else QLabel("")
            if col:
                btn.clicked.connect(lambda _c=False, k=col - 1: self.save(k))
            self.grid.addWidget(pic, 0, col)
            self.grid.addWidget(cap, 1, col)
            self.grid.addWidget(btn, 2, col)
            self.cards.append((pic, cap, btn))
        prev = QPushButton(lib_icon("arrowLeft"), "")
        prev.clicked.connect(lambda: self.go(-1))
        nxt = QPushButton(lib_icon("arrowRight"), "")
        nxt.clicked.connect(lambda: self.go(1))
        self.info = QLabel(objectName="dim", wordWrap=True)
        top = QHBoxLayout()
        top.addWidget(prev)
        top.addWidget(nxt)
        top.addWidget(self.title, 1)
        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addLayout(self.grid)
        v.addWidget(self.info)
        self.run()

    def go(self, d):
        if self.paths:
            self.i = (self.i + d) % len(self.paths)
            self.run()

    def run(self):
        p = self.paths[self.i]
        self.title.setText(f"{os.path.basename(p)}   ({self.i + 1} из {len(self.paths)})")
        im = K.load(p)
        self.cards[0][0].setPixmap(
            to_pix(im).scaled(260, 260, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        self.cards[0][1].setText(f"<b>Оригинал</b><br>{human(os.path.getsize(p))}")
        for pic, _cap, _b in self.cards[1:]:
            pic.setText("считаю...")
            pic.setPixmap(QPixmap())
        self.info.setText("vtracer обводит контуры; для плоских значков и наклеек - отлично, для фото - каша.")

        def work():
            out = []
            for _name, _hint, fn in VARIANTS:
                try:
                    out.append(K.to_svg(fn(im)))
                except ImportError:
                    raise
                except Exception as e:
                    out.append(e)
            return out

        def done(res, p=p):
            if p != self.paths[self.i]:
                return
            if isinstance(res, ImportError):
                self.info.setText("Нужен vtracer: py -3.14 -m pip install vtracer")
                return
            if isinstance(res, Exception):
                self.info.setText(f"Не вышло: {res}")
                return
            self.results[p] = res
            for (pic, cap, _b), (name, hint, _fn), svg in zip(self.cards[1:], VARIANTS, res):
                if isinstance(svg, Exception):
                    pic.setText("не вышло")
                    continue
                pic.setPixmap(svg_pixmap(svg))
                paths = svg.count(b"<path")
                cap.setText(f"<b>{name}</b><br>{hint}<br>{human(len(svg))}, контуров: {paths}")

        bg(work, done)

    def save(self, k):
        p = self.paths[self.i]
        res = self.results.get(p)
        if not res or isinstance(res[k], Exception):
            return
        dst = unique(os.path.splitext(p)[0] + ".svg")
        with open(dst, "wb") as fh:
            fh.write(res[k])
        self.win.push(f"SVG: {os.path.basename(dst)}", [("new", dst)])
        self.win.lib.changed.emit()
        self.win.say(f"Сохранено рядом: {os.path.basename(dst)} ({VARIANTS[k][0].lower()})", undo=True)


# ================================================================ оформление
class ThemeDialog(QDialog):
    """Тема (тёмная / светлая) и акцент; меняется сразу, без перезапуска."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Оформление")
        self.setWindowIcon(lib_icon("color-palette"))
        v = QVBoxLayout(self)
        v.addWidget(QLabel("ТЕМА", objectName="faint"))
        row = QHBoxLayout()
        self.theme_btns = {}
        for key, (name, pal) in theme.THEMES.items():
            b = QPushButton(name, checkable=True)
            b.setMinimumSize(150, 70)
            b.setStyleSheet(
                f"QPushButton{{background:{pal['bg1']};color:{pal['text']};border:2px solid {pal['line2']};"
                f"border-radius:14px;font-weight:600}}QPushButton:checked{{border-color:{theme.C['acc']}}}"
            )
            b.clicked.connect(lambda _c=False, k=key: self.pick(theme=k))
            self.theme_btns[key] = b
            row.addWidget(b)
        v.addLayout(row)
        v.addWidget(QLabel("АКЦЕНТ", objectName="faint"))
        row2 = QHBoxLayout()
        self.acc_btns = {}
        for key, (name, a, a2) in theme.ACCENTS.items():
            b = QPushButton(name, checkable=True)
            b.setMinimumHeight(44)
            b.setStyleSheet(
                f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {a},stop:1 {a2});"
                f"color:#16131f;font-weight:700;border:2px solid transparent;border-radius:12px;padding:6px 14px}}"
                f"QPushButton:checked{{border-color:{theme.C['text']}}}"
            )
            b.clicked.connect(lambda _c=False, k=key: self.pick(accent=k))
            self.acc_btns[key] = b
            row2.addWidget(b)
        v.addLayout(row2)
        v.addWidget(
            QLabel(
                "Меняется сразу. Часть мелочей (значки в списках) обновится после перезапуска окна.",
                objectName="dim",
                wordWrap=True,
            )
        )
        ok = QPushButton("Готово", objectName="primary")
        ok.clicked.connect(self.accept)
        v.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        self.mark()

    def mark(self):
        for k, b in self.theme_btns.items():
            b.setChecked(k == theme.CURRENT["theme"])
        for k, b in self.acc_btns.items():
            b.setChecked(k == theme.CURRENT["accent"])

    def pick(self, theme=None, accent=None):  # noqa: A002
        cfg = self.win.cfg
        cfg["theme"] = theme or cfg.get("theme", "dark")
        cfg["accent"] = accent or cfg.get("accent", "lavender")
        self.win.apply_theme()
        self.mark()
