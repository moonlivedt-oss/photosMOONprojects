"""Вкладка «Библиотека»: плитки, панель просмотра, быстрый просмотр, действия с файлами."""
import html
import os
import shutil
import time

import картинки as K
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QFile, QMimeData, QRectF, QStringListModel, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from окно.виджеты import (
    DestDialog,
    LibList,
    PicView,
    fill_tree,
    forget_counts,
    key,
    make_tree,
    select_path,
)
from окно import база, промпты
from окно.выгрузка import ExportDialog, export
from окно.миниатюры import (
    _thumbs,
    backdrop,
    lib_icon,
    palette,
    remember,
    swatch,
    thumb,
    thumb_key,
    tile_image,
    to_qimage,
)
from окно.общее import (
    EXT,
    FAV,
    HEAVY,
    HEAVY_KB,
    LIB,
    PIX,
    RECENT,
    ROLE,
    SETS,
    STAR,
    SUB,
    TAG,
    THUMB,
    bg,
    clean_name,
    human,
    in_main,
    reveal,
    unique,
)
from окно.оформление import C
from окно.правка import EditDialog
from окно.сжатие import COPY_FORMATS, CompressDialog, copy_files


class Preview(QWidget):
    """Правая панель: крупный просмотр выбранной картинки (со свечением её цвета), сведения,
    палитра и действия с ней."""

    def __init__(self, tab):
        super().__init__(objectName="panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.tab, self.cgen = tab, 0
        self.pic = PicView()
        self.name = QLabel(objectName="head", wordWrap=True)
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.where = QLabel(objectName="dim", wordWrap=True)
        self.where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.chips = QHBoxLayout()            # размер, формат, вес - плашками
        self.chips.setSpacing(5)
        self.pal_lbl = QLabel("ЦВЕТА", objectName="faint")
        self.colors = QHBoxLayout()           # главные цвета картинки: щелчок копирует HEX
        self.colors.setSpacing(6)
        self.tag_lbl = QLabel("МЕТКИ И ЗАМЕТКА", objectName="faint")
        self.tags = QLineEdit(placeholderText="метки через запятую: космос, для сайта")
        self.tags.setToolTip("Enter - сохранить. Поиск находит по меткам и заметкам, метки видны в дереве слева")
        self.tag_model = QStringListModel()
        self.completer = QCompleter(self.tag_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setWidget(self.tags)
        self.completer.activated.connect(self.complete_tag)
        self.tags.textEdited.connect(self.suggest_tag)
        self.tags.editingFinished.connect(lambda: self.tab.save_tags(self.tags.text()))
        self.note = QPlainTextEdit(placeholderText="заметка: где использована, откуда, что поправить")
        self.note.setFixedHeight(54)
        self.note_timer = QTimer(self, singleShot=True, interval=700)
        self.note_timer.timeout.connect(lambda: self.tab.save_note(self.note.toPlainText()))
        self.note.textChanged.connect(lambda: self.note_timer.start() if not self.loading_meta else None)
        self.loading_meta = False
        g = QGridLayout()
        g.setSpacing(6)
        self.btns = []
        for i, (text, icon, fn, tip) in enumerate((
                ("Открыть", "image-file", tab.open_file, "Enter или двойной щелчок по плитке"),
                ("В проводнике", "folder", tab.reveal, ""),
                ("Копировать", "camera", tab.copy_image, "Ctrl+Shift+C - картинка вставляется в любой редактор"),
                ("Путь", "clipboard", tab.copy_path, "Ctrl+C - копировать путь к файлу"),
                ("В избранное", "star", tab.toggle_fav, "Ctrl+D"),
                ("Похожие", "magnifying-glass", tab.find_similar, "Найти похожие по рисунку и пропорциям"),
                ("Выгрузить...", "upload-arrow", tab.export, "Ctrl+E - копии нужного формата и размера в папку проекта"),
                ("Просмотр", "eye", tab.look, "Пробел - на всё окно, стрелки листают"))):
            b = QPushButton(lib_icon(icon), text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
            self.btns.append(b)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        for text, icon, fn, tip in (("Редактировать", "paint-brush", tab.edit, "Ctrl+R"),
                                    ("Сжать и конвертировать", "zip-archive", tab.compress, "Ctrl+K"),
                                    ("Переименовать", "quill-pen", tab.rename, "F2"),
                                    ("Перенести в раздел", "folder", tab.move, "")):
            b = QPushButton(lib_icon(icon), "", objectName="tool")
            b.setToolTip(text + ("  (%s)" % tip if tip else ""))
            b.clicked.connect(fn)
            tools.addWidget(b)
            self.btns.append(b)
        tools.addStretch(1)
        b = QPushButton(lib_icon("trash-bin"), " В корзину", objectName="ghost")
        b.setToolTip("Del - вернуть можно из корзины Windows")
        b.clicked.connect(tab.trash)
        tools.addWidget(b)
        self.btns.append(b)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(self.pic, 1)
        v.addSpacing(4)
        v.addWidget(self.name)
        v.addWidget(self.where)
        v.addLayout(self.chips)
        v.addSpacing(2)
        v.addWidget(self.pal_lbl)
        v.addLayout(self.colors)
        v.addWidget(self.tag_lbl)
        v.addWidget(self.tags)
        v.addWidget(self.note)
        v.addSpacing(4)
        v.addLayout(g)
        v.addLayout(tools)
        self.show_paths([], "chk")

    @staticmethod
    def clear_row(row):
        while row.count():
            w = row.takeAt(0).widget()
            if w:
                w.deleteLater()

    def set_chips(self, items):
        self.clear_row(self.chips)
        for text in items:
            self.chips.addWidget(QLabel(text, objectName="chip"))
        self.chips.addStretch(1)

    # --- метки: подсказка по последнему слову списка через запятую
    def suggest_tag(self, text):
        last = text.split(",")[-1].strip()
        if last:
            self.completer.setCompletionPrefix(last)
            self.completer.complete()
        else:
            self.completer.popup().hide()

    def complete_tag(self, tag):
        parts = [x.strip() for x in self.tags.text().split(",")]
        parts[-1] = tag
        self.tags.setText(", ".join(x for x in parts if x) + ", ")

    def show_meta(self, paths):
        """Метки (у нескольких - общие) и заметка (только у одной картинки)."""
        self.loading_meta = True
        self.note_timer.stop()
        rels = [os.path.relpath(p, LIB) for p in paths]
        try:
            self.tag_model.setStringList(sorted(база.all_tags()))
            common = set(база.tags_of(rels[0])) if rels else set()
            for r in rels[1:]:
                common &= set(база.tags_of(r))
            self.tags.setText(", ".join(sorted(common)))
            self.note.setPlainText(база.note_of(rels[0]) if len(rels) == 1 else "")
        except Exception:
            pass
        self.tags.setPlaceholderText("метки через запятую: космос, для сайта" if len(rels) <= 1 else
                                     "общие метки всех выбранных - добавьте или уберите")
        for w in (self.tag_lbl, self.tags):
            w.setVisible(bool(rels))
        self.note.setVisible(len(rels) == 1)
        self.loading_meta = False

    def show_set(self, s, cover):
        """Набор (вид «Наборы»): обложка, палитры плашками."""
        for b in self.btns:
            b.setEnabled(False)
        self.show_colors(None)
        self.show_meta([])
        self.pic.set_pixmap(cover)
        self.name.setText(os.path.basename(s["path"]))
        self.where.setText("%s   ·   двойной щелчок - открыть" % os.path.relpath(os.path.dirname(s["path"]), LIB))
        self.set_chips(["%s: %d" % (f, n) for f, n, _p in s["pals"]][:8])

    def show_paths(self, paths, mode):
        self.show_meta(paths)
        for b in self.btns:
            b.setEnabled(bool(paths))
        for i in (0, 5, 10):                        # открыть, похожие, переименовать - только по одной
            self.btns[i].setEnabled(len(paths) == 1)
        fav = self.tab.cfg.get("fav", [])
        self.btns[4].setText("Из избранного" if paths and os.path.relpath(paths[0], LIB) in fav else "В избранное")
        self.show_colors(paths[0] if len(paths) == 1 else None)
        mode = None if mode == "chk" else mode      # прозрачное - прямо на свечении, без шахматки
        if not paths:
            self.pgen = getattr(self, "pgen", 0) + 1      # недогруженная прошлая картинка не всплывёт
            self.pic.set_pixmap(None)
            self.name.setText("Ничего не выбрано")
            self.where.setText("Щёлкните плитку - здесь появятся сведения, цвета и действия")
            self.set_chips([])
            return
        self.show_pic(paths[0], mode)
        if len(paths) > 1:
            self.name.setText("Выбрано: %d" % len(paths))
            self.where.setText("Действия ниже применятся ко всем выбранным")
            self.set_chips(["вместе " + human(sum(os.path.getsize(p) for p in paths if os.path.exists(p)))])
            return
        p = paths[0]
        self.name.setText(os.path.splitext(os.path.basename(p))[0])
        self.where.setText(os.path.dirname(os.path.relpath(p, LIB)).replace(os.sep, "  /  "))
        chips = []
        try:
            st = os.stat(p)
            if not p.lower().endswith(".svg"):
                chips.append("%d × %d" % K.size_of(p))
            chips += [os.path.splitext(p)[1][1:].upper(), human(st.st_size),
                      time.strftime("%d.%m.%Y", time.localtime(st.st_mtime))]
        except Exception:
            pass
        self.set_chips(chips)

    def show_pic(self, path, mode):
        """Крупная картинка - из памяти сразу, иначе в фоне: большие png раньше читались в главном
        потоке, и листание стрелками подтормаживало на каждой плитке."""
        self.pgen = getattr(self, "pgen", 0) + 1
        key = thumb_key(path, 512, mode)
        if path.lower().endswith(".svg") or key in _thumbs:
            self.pic.set_pixmap(thumb(path, 512, mode))
            return
        gen = self.pgen

        def done(img):
            if gen != self.pgen:
                return
            if isinstance(img, Exception):
                self.pic.set_pixmap(None)
                return
            pm = QPixmap.fromImage(img)
            self.pic.set_pixmap(remember(key, pm) if key else pm)

        bg(lambda: tile_image(path, 512, mode), done)

    def show_colors(self, path):
        """Палитра картинки (как в Eagle): считается в фоне, щелчок по цвету копирует его код.
        Самый заметный цвет подсвечивает просмотр."""
        self.clear_row(self.colors)
        self.cgen += 1
        self.pic.set_glow(None)
        self.pal_lbl.setVisible(False)
        if not path or path.lower().endswith(".svg"):
            return
        gen = self.cgen

        def done(res):
            if gen != self.cgen or isinstance(res, Exception) or not res:
                return
            self.pal_lbl.setVisible(True)
            self.pic.set_glow(vivid(res))
            for hexv in res:
                b = QPushButton(objectName="swatch")
                b.setFixedSize(26, 26)
                b.setStyleSheet("QPushButton#swatch{background:%s;border:2px solid %s;border-radius:13px;padding:0}"
                                "QPushButton#swatch:hover{border:2px solid #ffffff}" % (hexv, C["line2"]))
                b.setToolTip("%s - щёлкните, чтобы скопировать" % hexv)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _c=False, h=hexv: self.tab.copy_color(h))
                self.colors.addWidget(b)
            self.colors.addStretch(1)

        bg(lambda: palette(path), done)


def vivid(colors):
    """Для свечения - самый насыщенный из заметных цветов (чёрный и белый светят плохо)."""
    def score(h):
        c = QColor(h)
        return c.hsvSaturationF() * (0.4 + c.valueF())
    best = max(colors[:4], key=score)
    return best if score(best) > 0.15 else colors[0]


class Look(QDialog):
    """Быстрый просмотр на всё окно: стрелки - соседние картинки, Пробел/Esc - закрыть, B - подложка."""

    def __init__(self, tab, row):
        super().__init__(tab)
        self.tab, self.row = tab, row
        self.cache, self.loading, self.want = {}, set(), None
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)     # иначе каждое открытие копило окно в памяти
        self.mode = tab.cfg.get("bg", "chk")
        self.setWindowTitle("Просмотр")
        self.setStyleSheet("QDialog{background:#09090d}")
        self.gen = 0
        self.pic = PicView(frame=False)
        self.pic.zoomable = True
        self.title = QLabel(objectName="head", alignment=Qt.AlignmentFlag.AlignCenter)
        self.cap = QLabel(objectName="dim", alignment=Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("←  →  листать      колесо  увеличить      1 или двойной щелчок  пиксель в пиксель      "
                      "0  целиком      B  подложка      Пробел или Esc  закрыть", objectName="faint",
                      alignment=Qt.AlignmentFlag.AlignCenter)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 14)
        v.addWidget(self.pic, 1)
        v.addWidget(self.title)
        v.addWidget(self.cap)
        v.addSpacing(4)
        v.addWidget(hint)
        self.setGeometry(tab.window().geometry().adjusted(30, 30, -30, -30))
        self.show_row()

    def show_row(self):
        n = self.tab.list.count()
        if not n:
            return
        self.row %= n
        it = self.tab.list.item(self.row)
        self.tab.list.setCurrentItem(it)
        p = it.data(ROLE)
        self.title.setText(os.path.splitext(os.path.basename(p))[0])
        if p.lower().endswith(".svg"):
            self.pic.set_pixmap(QIcon(p).pixmap(1024, 1024))
        else:
            # крупная картинка - в фоне (окно не замирает на тяжёлом файле), соседи - заранее
            self.fetch(p, show=True)
            for d in (1, -1):
                nb = self.tab.list.item((self.row + d) % n)
                if nb and not nb.data(ROLE).lower().endswith(".svg"):
                    self.fetch(nb.data(ROLE))
        self.cap.setText("%s      %d из %d" % (os.path.dirname(os.path.relpath(p, LIB)).replace(os.sep, "  /  "),
                                               self.row + 1, n))
        self.gen += 1
        gen = self.gen
        self.pic.set_glow(None)
        if not p.lower().endswith(".svg"):
            bg(lambda: palette(p), lambda res: not sip.isdeleted(self) and gen == self.gen
               and isinstance(res, list) and res and self.pic.set_glow(vivid(res)))

    def fetch(self, p, show=False):
        """Картинка для просмотра: из своего маленького кэша или в фоне. show - показать, когда готова."""
        key = (p, self.mode)
        if show:
            self.want = key
        if key in self.cache:
            if show:
                self.pic.set_pixmap(self.cache[key])
            return
        if key in self.loading:
            return
        self.loading.add(key)
        mode = self.mode

        def work():
            im = K.load(p)
            im.thumbnail((2400, 2400), Image.LANCZOS)
            if mode != "chk":                       # шахматку не кладём: прозрачное висит на свечении
                back = backdrop(im.width, im.height, mode)
                back.alpha_composite(im)
                im = back
            return to_qimage(im)

        def done(img):
            if sip.isdeleted(self):                 # просмотр закрыли, пока картинка грузилась
                return
            self.loading.discard(key)
            pm = QPixmap() if isinstance(img, Exception) else QPixmap.fromImage(img)
            self.cache[key] = pm
            while len(self.cache) > 6:              # держим текущую и соседей
                self.cache.pop(next(iter(self.cache)))
            if self.want == key and self.isVisible():
                self.pic.set_pixmap(pm)

        bg(work, done)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            self.row += 1
            self.show_row()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.row -= 1
            self.show_row()
        elif k == Qt.Key.Key_B:
            self.mode = {"chk": "light", "light": "dark"}.get(self.mode, "chk")
            self.show_row()
        elif k == Qt.Key.Key_1:
            self.pic.actual_size()
        elif k == Qt.Key.Key_0:
            self.pic.set_zoom(1.0)
        elif k in (Qt.Key.Key_Space, Qt.Key.Key_Escape, Qt.Key.Key_Return):
            self.accept()
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, _e):
        self.pic.actual_size()


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return "%d %s" % (n, one)
    return "%d %s" % (n, few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many)


def find_sets():
    """Наборы: папки, в которых есть подпапки палитр с картинками («04 Иконки/Космос/Tokyo Night»).
    -> [{path, pals: [(папка, число, путь)], count, mt}]"""
    pals = set(промпты.pal_by_folder())
    found = {}
    for d, dirs, files in os.walk(LIB):
        dirs[:] = sorted(x for x in dirs if not x.startswith(("_", ".")) and x != K.INBOX)
        name = os.path.basename(d)
        if name not in pals or os.path.dirname(d) == LIB:
            continue
        n = sum(1 for f in files if f.lower().endswith(K.EXT) and not f.startswith("_"))
        if n:
            s = found.setdefault(os.path.dirname(d), dict(path=os.path.dirname(d), pals=[], count=0, mt=0))
            s["pals"].append((name, n, d))
            s["count"] += n
            s["mt"] = max(s["mt"], os.path.getmtime(d))
    out = list(found.values())
    for s in out:
        s["pals"].sort(key=lambda x: -x[1])
    return sorted(out, key=lambda s: os.path.relpath(s["path"], LIB).lower())


def set_cover(s, side=256):
    """Обложка набора: первые 12 картинок самой полной палитры сеткой 4x3 (в фоне)."""
    folder = s["pals"][0][2]
    files = [f for f in K.images_in(folder) if not f.lower().endswith(".svg")][:12]
    cols, rows = 4, 3
    cell = side // cols
    sheet = Image.new("RGBA", (cell * cols, cell * rows), (0, 0, 0, 0))
    for i, p in enumerate(files):
        try:
            im = K.load(p)
        except Exception:
            continue
        im.thumbnail((cell - 4, cell - 4), Image.LANCZOS)
        sheet.alpha_composite(im, ((i % cols) * cell + (cell - im.width) // 2, (i // cols) * cell + (cell - im.height) // 2))
    return sheet


def mtime(p):
    """Для сортировки: файл могли перенести, пока строился список."""
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def fsize(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


class LibTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.side = max(64, min(THUMB, self.cfg.get("thumb", 128)))
        self.like = None                    # "Похожие на ...": путь картинки-образца
        self.tree = make_tree()
        self.tree.currentItemChanged.connect(lambda *_: self.leave_similar())
        self.q = QLineEdit(placeholderText="Поиск по всей библиотеке  (Ctrl+F)", objectName="search")
        self.q.setClearButtonEnabled(True)
        self.q.addAction(lib_icon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self.qt = QTimer(self, singleShot=True, interval=180)        # не перерисовывать на каждую букву
        self.qt.timeout.connect(self.show_files)
        self.q.textChanged.connect(lambda *_: self.qt.start())
        self.color = QComboBox()
        self.color.addItem(lib_icon("color-palette"), "Любой цвет", "")
        for code, name, hexv in K.COLORS:
            self.color.addItem(swatch(hexv), name, code)
        self.color.setToolTip("Показать только картинки, где заметен этот цвет")
        self.color.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.color.currentIndexChanged.connect(self.show_files)
        self.sort = QComboBox()
        for t, v in (("По имени", "name"), ("Сначала новые", "new"), ("Сначала тяжёлые", "size")):
            self.sort.addItem(t, v)
        self.sort.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.sort.setCurrentIndex(max(0, self.sort.findData(self.cfg.get("sort", "name"))))
        self.sort.currentIndexChanged.connect(self.show_files)
        self.back = QPushButton(objectName="tool")
        self.back.setToolTip("Подложка под прозрачными картинками: шахматка / светлая / тёмная (B)")
        self.back.clicked.connect(self.cycle_back)
        self.slider = QSlider(Qt.Orientation.Horizontal, minimum=72, maximum=THUMB, singleStep=16, pageStep=32)
        self.slider.setFixedWidth(70)
        self.slider.setValue(self.side)
        self.slider.setToolTip("Размер плиток (Ctrl+колесо)")
        self.slider.valueChanged.connect(self.resize_tiles)
        self.list = LibList(self.side)
        self.list.zoom.connect(lambda d: self.slider.setValue(self.side + 16 * d))
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.menu)
        self.list.itemDoubleClicked.connect(self.double_click)
        self.list.itemSelectionChanged.connect(self.describe)
        self.sets_view, self.covers = False, {}
        self.info = QLabel("", objectName="dim")
        self.title = QLabel(objectName="big")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bar = QHBoxLayout()
        self.q.setMinimumWidth(110)
        bar.addWidget(self.q, 1)
        bar.addWidget(self.color)
        bar.addWidget(self.sort)
        bar.addWidget(self.back)
        bar.addWidget(self.slider)
        mid = QWidget()
        rv = QVBoxLayout(mid)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(bar)
        rv.addWidget(self.title)
        rv.addWidget(self.list, 1)
        rv.addWidget(self.info)
        self.preview = Preview(self)
        self.split = QSplitter()
        for w in (self.tree, mid, self.preview):
            self.split.addWidget(w)
        self.split.setStretchFactor(1, 1)
        sizes = list(self.cfg.get("split_lib", [250, 720, 300]))
        sizes[0] = max(sizes[0], 210)           # уже - имена разделов и числа не помещаются
        self.split.setSizes(sizes)
        lay = QVBoxLayout(self)
        lay.addWidget(self.split)
        key("F2", self.list, self.rename)
        key("Delete", self.list, self.trash)
        key("Ctrl+C", self.list, self.copy_path)
        key("Ctrl+Shift+C", self.list, self.copy_image)
        key("Return", self.list, self.open_file)
        key("Ctrl+F", self, lambda: (self.q.setFocus(), self.q.selectAll()))
        key("Space", self.list, self.look)
        key("Ctrl+D", self.list, self.toggle_fav)
        key("Ctrl+E", self.list, self.export)
        key("Ctrl+K", self.list, self.compress)
        key("Ctrl+R", self.list, self.edit)
        key("B", self.list, self.cycle_back)
        key("Ctrl+A", self.list, self.list.selectAll)
        key("Escape", self, self.escape)
        key("Alt+Left", self, self.go_back)
        for w in (self.list.viewport(), self.tree.viewport()):     # кнопка мыши «назад»
            w.installEventFilter(self)
        self.tree.setAcceptDrops(True)          # плитки можно бросить на раздел - перенос
        self.past, self.here = [], None         # прошлые разделы для Alt+← и кнопки мыши «назад»
        self.tree.currentItemChanged.connect(self.track)
        self.show_back()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.refresh()

    def refresh(self):
        """Пересобрать дерево и плитки один раз (без сигналов дерево перестраивалось бы с плитками по 2-3 раза)."""
        self.tree.blockSignals(True)
        fill_tree(self.tree, planned=False, recent=True)
        if not self.tree.currentItem():         # раздел, открытый в прошлый раз
            select_path(self.tree, self.cfg.get("lib_section"))
        if not self.tree.currentItem():         # или первый раздел библиотеки
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it.data(0, ROLE) and os.path.isdir(it.data(0, ROLE)):
                    self.tree.setCurrentItem(it)
                    break
        self.tree.blockSignals(False)
        cur = self.tree.currentItem()
        self.here = cur.data(0, ROLE) if cur else None
        self.leave_similar()

    def cycle_back(self):
        mode = {"chk": "light", "light": "dark"}.get(self.cfg.get("bg", "chk"), "chk")
        self.cfg["bg"] = mode
        i = self.win.inbox.bg.findData(mode)          # во входящих та же подложка
        if i >= 0:
            self.win.inbox.bg.setCurrentIndex(i)
        self.show_back()
        self.show_files()

    def show_back(self):
        mode = self.cfg.get("bg", "chk")
        pm = QPixmap(18, 18)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(1, 1, 16, 16), 4, 4)
        p.setClipPath(clip)
        if mode == "chk":
            for y in range(0, 18, 6):
                for x in range(0, 18, 6):
                    p.fillRect(x, y, 6, 6, QColor("#4a4860" if (x + y) // 6 % 2 else "#23232f"))
        else:
            p.fillRect(0, 0, 18, 18, QColor("#f4f2fa" if mode == "light" else "#000000"))
        p.end()
        self.back.setIcon(QIcon(pm))
    # --- навигация
    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.BackButton:
            self.go_back()
            return True
        if obj is self.tree.viewport() and t in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return self.tree_drop(e, t)
        if obj is self.tree.viewport() and t == QEvent.Type.DragLeave:
            self.drop_hint(None)
        return False

    def tree_drop(self, e, t):
        """Плитки библиотеки на раздел дерева - перенос туда (Ctrl+Z вернёт)."""
        if e.source() is not self.list or self.sets_view:
            e.ignore()
            return True
        it = self.tree.itemAt(e.position().toPoint())
        role = it.data(0, ROLE) if it else None
        ok = bool(role and os.path.isdir(role))
        if t == QEvent.Type.Drop:
            self.drop_hint(None)
            if ok:
                e.acceptProposedAction()
                self.move_to(role, self.paths())
            return True
        self.drop_hint(it if ok else None)
        if ok:
            e.acceptProposedAction()
        else:
            e.ignore()
        return True

    def drop_hint(self, it):
        """Подсветка раздела, на который сейчас бросят плитки."""
        old = getattr(self, "hint_item", None)
        if old is it:
            return
        try:
            if old is not None:
                old.setBackground(0, QBrush())
        except RuntimeError:
            pass
        self.hint_item = it
        if it is not None:
            it.setBackground(0, QColor(C["accd"]))

    def track(self, cur, _prev=None):
        """Запоминает пройденные разделы для «назад»."""
        role = cur.data(0, ROLE) if cur else None
        if role and role != self.here:
            if self.here and not getattr(self, "going_back", False):
                self.past = (self.past + [self.here])[-30:]
            self.here = role

    def go_back(self):
        if self.like:                           # из «Похожих» - туда, откуда пришли
            self.leave_similar()
            return
        while self.past:
            role = self.past.pop()
            self.going_back = True
            try:
                if select_path(self.tree, role):
                    return
            finally:
                self.going_back = False

    def escape(self):
        if self.q.text():
            self.q.clear()
        elif self.like:
            self.leave_similar()
        elif self.color.currentIndex():
            self.color.setCurrentIndex(0)
        else:
            self.list.clearSelection()

    def remember_section(self):
        it = self.tree.currentItem()
        if it and it.data(0, ROLE):
            self.cfg["lib_section"] = it.data(0, ROLE)

    def show_section(self, role):
        self.q.clear()
        self.color.setCurrentIndex(0)
        select_path(self.tree, role)

    def all_shown(self):
        return [self.list.item(i).data(ROLE) for i in range(self.list.count())]

    def tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it or not it.data(0, ROLE):         # подпись группы
            return
        self.tree.setCurrentItem(it)
        files = self.all_shown()
        role = it.data(0, ROLE)
        m = QMenu(self)
        if os.path.isdir(role):
            m.addAction("Открыть папку в проводнике", lambda: os.startfile(role))
        if files:
            m.addSeparator()
            m.addAction("Сжать весь раздел (%d)..." % len(files), lambda: self.compress(files))
            m.addAction("Выгрузить раздел в папку...", lambda: self.export(files))
            m.addAction("Лист превью раздела...", lambda: self.preview_sheet(files))
        if m.isEmpty():
            return
        m.exec(self.tree.mapToGlobal(pos))
        self.show_files()

    def resize_tiles(self, v):
        self.side = v
        self.cfg["thumb"] = v
        self.list.set_base(v)

    def show_files(self):
        tokens = self.q.text().strip().lower().replace("ё", "е").split()
        minus = [t[1:] for t in tokens if t.startswith("-") and len(t) > 1]     # «кот -png»: без png
        words = [t for t in tokens if not t.startswith("-")]
        it = self.tree.currentItem()
        root = LIB if tokens else (it.data(0, ROLE) if it else None)
        keep = set(self.paths())
        self.list.clear()
        self.list.reset_anim()
        fav = set(self.cfg.get("fav", []))
        self.sets_view = root == SETS and not tokens and not self.like
        if self.sets_view:
            self.show_sets()
            return
        if self.like:
            root = RECENT                   # порядок задаёт похожесть, сортировку не применяем
            files = self.win.sigs.similar(self.like)
        elif isinstance(root, str) and root.startswith(TAG):
            files = [os.path.join(LIB, r) for r in база.with_tag(root[len(TAG):])
                     if os.path.exists(os.path.join(LIB, r))]
        elif root == RECENT:
            files = sorted(K.images_in(LIB), key=mtime, reverse=True)[:120]
        elif root == HEAVY:
            files = sorted((f for f in K.images_in(LIB) if fsize(f) > HEAVY_KB * 1024),
                           key=fsize, reverse=True)
        elif root == FAV:
            files = [os.path.join(LIB, r) for r in sorted(fav) if os.path.exists(os.path.join(LIB, r))]
        elif root and os.path.isdir(root):
            files = K.images_in(root)
        elif root and not os.path.isdir(root) and not root.startswith("::"):    # раздел пропал (перенесли)
            files = []
        else:
            files = []
        if tokens:
            extra = база.search_text()      # метки и заметки: «#космос» или просто «космос»
            words = [w.lstrip("#") for w in words]

            def hit(p):
                rel = os.path.relpath(p, LIB)
                s = rel.lower().replace("ё", "е") + " " + extra.get(rel, "")
                return all(w in s for w in words) and not any(w in s for w in minus)
            files = [p for p in files if hit(p)]
        code = self.color.currentData()
        if code:
            files = [p for p in files if self.win.sigs.has_color(p, code)]
        how = self.sort.currentData()
        self.cfg["sort"] = how
        if how == "new" and root not in (RECENT, HEAVY):
            files.sort(key=mtime, reverse=True)
        elif how == "size":
            files.sort(key=fsize, reverse=True)
        mode = self.cfg.get("bg", "chk")
        base = root if root and os.path.isdir(root) and not tokens else LIB
        todo = []
        self.list.setUpdatesEnabled(False)
        for i, p in enumerate(files):
            rel = os.path.relpath(p, LIB)
            stem, ext = os.path.splitext(os.path.basename(p))
            item = QListWidgetItem(stem)
            item.setData(ROLE, p)
            item.setData(STAR, rel in fav)
            item.setData(SUB, self.caption(p, base, ext, how))
            item.setData(EXT, ext[1:].upper())
            item.setToolTip(rel)
            if thumb_key(p, THUMB, mode) in _thumbs or p.lower().endswith(".svg"):
                item.setData(PIX, thumb(p, THUMB, mode))
            else:
                todo.append((i, p))
            self.list.addItem(item)
            if p in keep:
                item.setSelected(True)
        self.list.setUpdatesEnabled(True)
        self.show_title(root, words + ["-" + w for w in minus], code, len(files))
        self.list.load_tiles(todo, THUMB, mode)
        self.describe()

    @staticmethod
    def caption(p, base, ext, how):
        """Вторая строка плитки: подпапка внутри открытого раздела и формат (у тяжёлых - и вес).
        Иначе в «01 Фоны» десяток плиток подписаны одинаково - «Боковая панель»."""
        folder = os.path.relpath(os.path.dirname(p), base)
        parts = [] if folder == "." else [os.path.basename(folder)]       # весь путь - во всплывающей подсказке
        if not parts:
            parts.append(ext[1:].upper())
        if how == "size":
            try:
                parts.append(human(os.path.getsize(p)))
            except OSError:
                pass
        return "  ·  ".join(parts)

    def show_title(self, root, words, code, n):
        """Заголовок над плитками и подсказка, если показывать нечего."""
        names = {RECENT: "Недавние", FAV: "Избранное", HEAVY: "Тяжёлые (больше %d КБ)" % HEAVY_KB, SETS: "Наборы"}
        if isinstance(root, str) and root.startswith(TAG):
            names[root] = "Метка: " + root[len(TAG):]
        if self.like:
            head = "Похожие на «%s»" % os.path.basename(self.like)
        elif words:
            head = "Поиск: %s" % self.q.text().strip()
        elif root in names:
            head = names[root]
        elif root:
            head = os.path.relpath(root, LIB).replace(os.sep, "  /  ")
        else:
            head = ""
        if code:
            head += "  -  " + self.color.currentText().lower()
        self.title.setText("%s   <span style='color:#8a879a;font-weight:400'>%d</span>" % (html.escape(head), n) if head else "")
        if n:
            self.list.empty = ""
        elif words or code:
            self.list.empty = "Ничего не нашлось. Поиск идёт по именам файлов и папок во всей библиотеке."
        elif root == FAV:
            self.list.empty = "Избранного пока нет.\nВыберите картинку и нажмите Ctrl+D или «В избранное» справа."
        elif root == HEAVY:
            self.list.empty = "Тяжёлых файлов нет - всё уже сжато."
        else:
            self.list.empty = "В этом разделе пока пусто.\nКартинки сюда попадают из вкладки «Входящие»."
        self.list.empty_icon = "magnifying-glass" if words or code else "star" if root == FAV else "folder"
        self.list.viewport().update()

    def paths(self):
        if self.sets_view:                  # в «Наборах» плитки - папки, действия с файлами к ним не применяются
            return []
        return [i.data(ROLE) for i in self.list.selectedItems()]

    def double_click(self, it):
        p = it.data(ROLE)
        if self.sets_view:
            self.show_section(p)
        else:
            os.startfile(p)

    # --- наборы
    def show_sets(self):
        """Вид «Наборы»: каждая папка набора - одна плитка-обложка (12 картинок сеткой), палитры - в подписи."""
        sets = find_sets()
        self.list.clear()
        self.list.reset_anim()
        todo = []
        for i, s in enumerate(sets):
            item = QListWidgetItem(os.path.basename(s["path"]))
            item.setData(ROLE, s["path"])
            item.setData(SUB, "%s  ·  %d шт." % (plural(len(s["pals"]), "палитра", "палитры", "палитр"), s["count"]))
            item.setToolTip(os.path.relpath(s["path"], LIB) + "\n" + ", ".join(f for f, _n, _p in s["pals"]))
            key = ("set", s["path"], s["mt"])
            if key in self.covers:
                item.setData(PIX, self.covers[key])
            else:
                todo.append((i, s, key))
            self.list.addItem(item)
        self.set_info = {s["path"]: s for s in sets}
        self.show_title(SETS, [], "", len(sets))
        if not sets:
            self.list.empty = "Наборов пока нет. Набор - папка с подпапками палитр, например «04 Иконки/Космос/Tokyo Night»."
        self.load_covers(todo)
        self.describe()

    def load_covers(self, todo):
        self.cgen = getattr(self, "cgen", 0) + 1
        gen = self.cgen
        for i, s, ck in todo:
            def done(img, i=i, s=s, ck=ck):
                it = self.list.item(i)
                if gen != self.cgen or isinstance(img, Exception) or not it or it.data(ROLE) != s["path"]:
                    return
                pm = QPixmap.fromImage(img)
                self.covers[ck] = pm
                it.setData(PIX, pm)
                self.list.loaded(i)
            bg(lambda s=s: to_qimage(set_cover(s)), done)

    def describe(self):
        if self.sets_view:
            items = self.list.selectedItems()
            s = self.set_info.get(items[0].data(ROLE)) if len(items) == 1 else None
            if s:
                self.preview.show_set(s, items[0].data(PIX))
            else:
                self.preview.show_paths([], self.cfg.get("bg", "chk"))
            self.info.setText("Наборов: %d   Двойной щелчок - открыть папку набора" % self.list.count())
            return
        sel = self.paths()
        self.preview.show_paths(sel, self.cfg.get("bg", "chk"))
        if self.like and not sel:
            self.info.setText("Похожие на «%s» - щёлкните раздел слева, чтобы вернуться" % os.path.basename(self.like))
        elif sel:
            self.info.setText("Выбрано: %d из %d" % (len(sel), self.list.count()))
        else:
            self.info.setText("Картинок: %d   Перетащите плитку в другую программу, чтобы вставить туда файл"
                              % self.list.count())

    def menu(self, pos):
        if not self.paths():
            return
        m = QMenu(self)
        m.addAction("Открыть\tEnter", self.open_file)
        m.addAction("Быстрый просмотр\tПробел", self.look)
        m.addAction("Показать в проводнике", self.reveal)
        m.addSeparator()
        fav = os.path.relpath(self.paths()[0], LIB) in self.cfg.get("fav", [])
        m.addAction("Убрать из избранного\tCtrl+D" if fav else "В избранное\tCtrl+D", self.toggle_fav)
        m.addAction("Найти похожие", self.find_similar)
        m.addAction("Выгрузить в папку...\tCtrl+E", self.export)
        m.addSeparator()
        m.addAction("Переименовать\tF2", self.rename)
        m.addAction("Перенести в раздел...", self.move)
        m.addAction("Копировать путь\tCtrl+C", self.copy_path)
        m.addAction("Копировать картинку\tCtrl+Shift+C", self.copy_image)
        m.addAction("Копировать как Markdown", self.copy_markdown)
        m.addAction("Редактировать...\tCtrl+R", self.edit)
        m.addAction("Сжать и конвертировать...\tCtrl+K", self.compress)
        m.addAction("Лист превью...", self.preview_sheet)
        conv = m.addMenu("Сделать копию в формате")
        for fmt, text in COPY_FORMATS:
            conv.addAction(text, lambda f=fmt: self.convert(f))
        m.addSeparator()
        m.addAction("В корзину\tDel", self.trash)
        m.exec(self.list.mapToGlobal(pos))

    def done(self, text):
        forget_counts()
        self.refresh()
        self.changed.emit()
        self.win.say(text)

    def leave_similar(self):
        self.like = None
        self.show_files()

    def find_similar(self):
        sel = self.paths()
        if not sel:
            return
        if os.path.relpath(sel[0], LIB) not in self.win.sigs.data:
            self.win.say("Отпечаток этой картинки ещё считается - попробуйте через пару секунд")
            return
        self.like = sel[0]
        self.q.blockSignals(True)
        self.q.clear()
        self.q.blockSignals(False)
        self.show_files()
        self.list.scrollToTop()

    def toggle_fav(self):
        sel = [os.path.relpath(p, LIB) for p in self.paths()]
        if not sel:
            return
        fav = self.cfg.setdefault("fav", [])
        add = any(r not in fav for r in sel)
        for r in sel:
            if add and r not in fav:
                fav.append(r)
            elif not add and r in fav:
                fav.remove(r)
        self.show_files()
        self.win.say(("В избранном: +%d" if add else "Убрано из избранного: %d") % len(sel))

    def look(self):
        if self.list.count():
            Look(self, max(0, self.list.currentRow())).exec()

    def export(self, files=None):
        sel = files or self.paths()
        if not sel:
            return
        d = ExportDialog(self, len(sel), self.cfg)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        folder, o = self.cfg["export_dir"], dict(self.cfg["export"])

        def progress(v):
            self.win.say("Выгружаю %d из %d: %s" % (v[0] + 1, v[1], v[2]))

        def finished(res):
            if isinstance(res, Exception):
                QMessageBox.warning(self, "Не выгрузилось", str(res))
                return
            self.win.say("Выгружено: %d шт. в %s" % (res, folder))
            if self.cfg.get("export_open"):
                os.startfile(folder)

        bg(lambda: export(sel, folder, o, lambda v: in_main(progress, v)), finished)

    def edit(self):
        sel = self.paths()
        if not sel:
            self.win.say("Выберите картинку (или несколько - правка применится ко всем)")
            return
        d = EditDialog(self, self.win, sel, on_saved=self.done)
        if d.skipped:
            self.win.say("Не правятся (svg, ico, анимация): %d - пропущены" % d.skipped)
        d.exec()

    def compress(self, files=None):
        sel = files or self.paths()
        if not sel:
            self.win.say("Выберите картинки или щёлкните раздел слева правой кнопкой - «Сжать весь раздел»")
            return
        CompressDialog(self, sel).exec()

    def preview_sheet(self, files=None):
        sel = files or self.paths()
        if not sel:
            return
        start = os.path.join(self.cfg.get("export_dir", "") or os.path.expanduser("~"), "Превью.png")
        p, _ = QFileDialog.getSaveFileName(self, "Лист превью: %d шт." % len(sel), start, "PNG (*.png)")
        if not p:
            return
        try:
            K.contact_sheet(sel[:200]).save(p, "PNG", optimize=True)
        except Exception as e:
            QMessageBox.warning(self, "Не получилось", str(e))
            return
        self.win.say("Лист превью сохранён: " + p)
        os.startfile(p)

    def open_file(self):
        sel = self.paths()
        if sel:
            os.startfile(sel[0])

    def reveal(self):
        sel = self.paths()
        if sel:
            reveal(sel[0])

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
        try:
            os.rename(sel[0], dst)
        except OSError as e:                     # файл открыт в другой программе
            QMessageBox.warning(self, "Переименовать", "Не получилось: %s" % (e.strerror or e))
            return
        self.win.moved(sel[0], dst)
        self.win.push("Переименовано: " + name + ext, [("move", sel[0], dst)])
        self.done("Переименовано: " + name + ext)

    def move(self):
        sel = self.paths()
        if not sel:
            return
        d = DestDialog(self, "Перенести: %d шт." % len(sel))
        if d.exec() != QDialog.DialogCode.Accepted or not d.path():
            return
        self.move_to(d.path(), sel)

    def move_to(self, dest, sel):
        if not sel:
            return
        os.makedirs(dest, exist_ok=True)
        steps, bad = [], 0
        for p in sel:
            if os.path.dirname(p) != dest:
                dst = unique(os.path.join(dest, os.path.basename(p)))
                try:
                    shutil.move(p, dst)
                except OSError:                  # занят другой программой - остальные переносим
                    bad += 1
                    continue
                self.win.moved(p, dst)
                steps.append(("move", p, dst))
        text = "Перенесено: %d шт. в «%s»" % (len(steps), os.path.relpath(dest, LIB))
        if bad:
            text += "   не вышло: %d (файл занят)" % bad
        self.win.push(text, steps)
        self.done(text)

    def save_tags(self, text):
        sel = self.paths()
        if not sel:
            return
        rels = [os.path.relpath(p, LIB) for p in sel]
        new = {база.clean_tag(t) for t in text.split(",")} - {""}
        before = set(база.all_tags())
        if len(rels) == 1:
            if set(база.tags_of(rels[0])) == new:
                return
            база.set_tags(rels, new)
        else:
            common = set(база.tags_of(rels[0]))
            for r in rels[1:]:
                common &= set(база.tags_of(r))
            if common == new:
                return
            база.set_tags(rels, common - new, "remove")
            база.set_tags(rels, new - common, "add")
        self.win.say("Метки: %s" % (", ".join(sorted(new)) or "убраны"))
        if set(база.all_tags()) != before:      # новая или исчезнувшая метка - дерево слева обновить
            self.tree.blockSignals(True)
            fill_tree(self.tree, planned=False, recent=True)
            self.tree.blockSignals(False)

    def save_note(self, text):
        sel = self.paths()
        if len(sel) == 1:
            база.set_note(os.path.relpath(sel[0], LIB), text)

    def copy_color(self, hexv):
        QApplication.clipboard().setText(hexv)
        self.win.say("Цвет скопирован: " + hexv)

    def copy_path(self):
        sel = self.paths()
        if sel:
            QApplication.clipboard().setText("\n".join(sel))
            self.win.say("Путь скопирован" if len(sel) == 1 else "Скопировано путей: %d" % len(sel))

    def copy_markdown(self):
        """![имя](путь) для README: путь со слешами, пробелы закодированы - так понимают GitHub и VS Code."""
        sel = self.paths()
        if not sel:
            return
        lines = ["![%s](%s)" % (os.path.splitext(os.path.basename(p))[0], p.replace("\\", "/").replace(" ", "%20"))
                 for p in sel]
        QApplication.clipboard().setText("\n".join(lines))
        self.win.say("Markdown скопирован: %d шт.  (путь абсолютный - поправьте под свой проект)" % len(sel))

    def copy_image(self):
        sel = self.paths()
        if not sel:
            return
        try:
            img = QIcon(sel[0]).pixmap(512, 512).toImage() if sel[0].lower().endswith(".svg") \
                else to_qimage(K.load(sel[0]))
        except Exception as e:
            self.win.say("Не скопировалось: %s" % e)
            return
        md = QMimeData()
        md.setImageData(img)
        md.setUrls([QUrl.fromLocalFile(sel[0])])      # проводник и мессенджеры вставят файл, редакторы - картинку
        QApplication.clipboard().setMimeData(md)
        self.win.say("Картинка скопирована: " + os.path.basename(sel[0]))

    def convert(self, fmt):
        """Копии в другом формате: в фоне, по ядрам, с подбором качества; Ctrl+Z их убирает."""
        sel = self.paths()
        if not sel:
            return
        name = dict(COPY_FORMATS).get(fmt, fmt)
        self.win.say("Делаю копии (%s): %d шт." % (name, len(sel)))

        def progress(v):
            self.win.say("Копия (%s): %d из %d - %s" % (name, v[0] + 1, v[1], v[2]))

        def finished(res):
            if isinstance(res, Exception):
                QMessageBox.warning(self, "Копии не получились", str(res))
                return
            steps, made, bad = res
            self.win.push("Копии (%s): %d шт." % (name, made), steps)
            self.done("Сделано копий (%s): %d" % (name, made) + ("   не вышло: %d" % bad if bad else "")
                      + ("   Ctrl+Z - убрать" if made else ""))

        bg(lambda: copy_files(sel, fmt, lambda v: in_main(progress, v)), finished)

    def trash(self):
        sel = self.paths()
        if not sel:
            return
        what = os.path.basename(sel[0]) if len(sel) == 1 else "%d шт." % len(sel)
        if QMessageBox.question(self, "В корзину", "Отправить в корзину: %s?\n(вернуть можно из корзины Windows)"
                                % what) != QMessageBox.StandardButton.Yes:
            return
        gone = [p for p in sel if QFile.moveToTrash(p)]
        n = len(gone)
        fav = self.cfg.get("fav", [])
        for p in gone:                      # из избранного тоже, иначе там копятся пути к удалённым
            rel = os.path.relpath(p, LIB)
            if rel in fav:
                fav.remove(rel)
            база.forget(rel)
        self.done("В корзине: %d шт." % n)
