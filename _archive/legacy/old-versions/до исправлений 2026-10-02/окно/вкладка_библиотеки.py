"""Вкладка «Библиотека»: плитки, панель просмотра, быстрый просмотр, действия с файлами."""
import html
import os
import shutil
import time

import картинки as K
from PIL import Image
from PyQt6.QtCore import QFile, QMimeData, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
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
    key,
    make_tree,
    select_path,
)
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
    to_pix,
    to_qimage,
)
from окно.общее import (
    CLOSING,
    EXT,
    FAV,
    HEAVY,
    HEAVY_KB,
    LIB,
    PIX,
    RECENT,
    ROLE,
    STAR,
    SUB,
    THUMB,
    bg,
    clean_name,
    human,
    in_main,
    reveal,
    unique,
)
from окно.оформление import C
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
        for text, icon, fn, tip in (("Сжать и конвертировать", "zip-archive", tab.compress, "Ctrl+K"),
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

    def show_paths(self, paths, mode):
        for b in self.btns:
            b.setEnabled(bool(paths))
        for i in (0, 5, 9):                         # открыть, похожие, переименовать - только по одной
            self.btns[i].setEnabled(len(paths) == 1)
        fav = self.tab.cfg.get("fav", [])
        self.btns[4].setText("Из избранного" if paths and os.path.relpath(paths[0], LIB) in fav else "В избранное")
        self.show_colors(paths[0] if len(paths) == 1 else None)
        mode = None if mode == "chk" else mode      # прозрачное - прямо на свечении, без шахматки
        if not paths:
            self.pic.set_pixmap(None)
            self.name.setText("Ничего не выбрано")
            self.where.setText("Щёлкните плитку - здесь появятся сведения, цвета и действия")
            self.set_chips([])
            return
        self.pic.set_pixmap(thumb(paths[0], 512, mode))
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
        self.tab, self.row, self.src = tab, row, None
        self.mode = tab.cfg.get("bg", "chk")
        self.setWindowTitle("Просмотр")
        self.setStyleSheet("QDialog{background:#09090d}")
        self.gen = 0
        self.pic = PicView(frame=False)
        self.title = QLabel(objectName="head", alignment=Qt.AlignmentFlag.AlignCenter)
        self.cap = QLabel(objectName="dim", alignment=Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("←  →  листать      B  подложка      Пробел или Esc  закрыть", objectName="faint",
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
        try:
            if p.lower().endswith(".svg"):
                self.src = QIcon(p).pixmap(1024, 1024)
            else:
                im = K.load(p)
                im.thumbnail((2400, 2400), Image.LANCZOS)
                if self.mode != "chk":              # шахматку не кладём: прозрачное висит на свечении
                    back = backdrop(im.width, im.height, self.mode)
                    back.alpha_composite(im)
                    im = back
                self.src = to_pix(im)
        except Exception:
            self.src = QPixmap()
        self.pic.set_pixmap(self.src)
        self.title.setText(os.path.splitext(os.path.basename(p))[0])
        self.cap.setText("%s      %d из %d" % (os.path.dirname(os.path.relpath(p, LIB)).replace(os.sep, "  /  "),
                                               self.row + 1, n))
        self.gen += 1
        gen = self.gen
        self.pic.set_glow(None)
        if not p.lower().endswith(".svg"):
            bg(lambda: palette(p), lambda res: gen == self.gen and isinstance(res, list) and res
               and self.pic.set_glow(vivid(res)))

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
        elif k in (Qt.Key.Key_Space, Qt.Key.Key_Escape, Qt.Key.Key_Return):
            self.accept()
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, _e):
        self.accept()


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
        self.list.itemDoubleClicked.connect(lambda it: os.startfile(it.data(ROLE)))
        self.list.itemSelectionChanged.connect(self.describe)
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
        key("B", self.list, self.cycle_back)
        self.show_back()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.refresh()

    def refresh(self):
        """Пересобрать дерево и плитки один раз (без сигналов дерево перестраивалось бы с плитками по 2-3 раза)."""
        self.tree.blockSignals(True)
        fill_tree(self.tree, planned=False, recent=True)
        if not self.tree.currentItem():         # первый раздел библиотеки
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it.data(0, ROLE) and os.path.isdir(it.data(0, ROLE)):
                    self.tree.setCurrentItem(it)
                    break
        self.tree.blockSignals(False)
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
        if not files:
            return
        m = QMenu(self)
        m.addAction("Сжать весь раздел (%d)..." % len(files), lambda: self.compress(files))
        m.addAction("Выгрузить раздел в папку...", lambda: self.export(files))
        m.addAction("Лист превью раздела...", lambda: self.preview_sheet(files))
        m.exec(self.tree.mapToGlobal(pos))
        self.show_files()

    def resize_tiles(self, v):
        self.side = v
        self.cfg["thumb"] = v
        self.list.set_base(v)

    def show_files(self):
        words = self.q.text().strip().lower().replace("ё", "е").split()
        it = self.tree.currentItem()
        root = LIB if words else (it.data(0, ROLE) if it else None)
        keep = set(self.paths())
        self.list.clear()
        self.list.reset_anim()
        fav = set(self.cfg.get("fav", []))
        if self.like:
            root = RECENT                   # порядок задаёт похожесть, сортировку не применяем
            files = self.win.sigs.similar(self.like)
        elif root == RECENT:
            files = sorted(K.images_in(LIB), key=os.path.getmtime, reverse=True)[:120]
        elif root == HEAVY:
            files = sorted((f for f in K.images_in(LIB) if os.path.getsize(f) > HEAVY_KB * 1024),
                           key=os.path.getsize, reverse=True)
        elif root == FAV:
            files = [os.path.join(LIB, r) for r in sorted(fav) if os.path.exists(os.path.join(LIB, r))]
        elif root and os.path.isdir(root):
            files = K.images_in(root)
        else:
            files = []
        if words:
            files = [p for p in files
                     if all(w in os.path.relpath(p, LIB).lower().replace("ё", "е") for w in words)]
        code = self.color.currentData()
        if code:
            files = [p for p in files if self.win.sigs.has_color(p, code)]
        how = self.sort.currentData()
        self.cfg["sort"] = how
        if how == "new" and root not in (RECENT, HEAVY):
            files.sort(key=os.path.getmtime, reverse=True)
        elif how == "size":
            files.sort(key=os.path.getsize, reverse=True)
        mode = self.cfg.get("bg", "chk")
        base = root if root and os.path.isdir(root) and not words else LIB
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
        self.show_title(root, words, code, len(files))
        self.load_tiles(todo, mode)
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
        names = {RECENT: "Недавние", FAV: "Избранное", HEAVY: "Тяжёлые (больше %d КБ)" % HEAVY_KB}
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

    def load_tiles(self, todo, mode):
        """Плитки, которых нет в памяти, дорисовываются в фоне порциями - окно не замирает."""
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
                        out.append((i, p, tile_image(p, THUMB, mode)))
                    except Exception:
                        out.append((i, p, None))
                return out

            def done(res):
                if gen != self.tgen or isinstance(res, Exception):
                    return
                for i, p, img in res:
                    it = self.list.item(i)
                    if img is None or not it or it.data(ROLE) != p:
                        continue
                    key = thumb_key(p, THUMB, mode)
                    pm = remember(key, QPixmap.fromImage(img)) if key else QPixmap.fromImage(img)
                    it.setData(PIX, pm)
                    self.list.loaded(i)
                step()

            bg(work, done)

        step()

    def paths(self):
        return [i.data(ROLE) for i in self.list.selectedItems()]

    def describe(self):
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
        m.addAction("Сжать и конвертировать...\tCtrl+K", self.compress)
        m.addAction("Лист превью...", self.preview_sheet)
        conv = m.addMenu("Сделать копию в формате")
        for fmt, text in COPY_FORMATS:
            conv.addAction(text, lambda f=fmt: self.convert(f))
        m.addSeparator()
        m.addAction("В корзину\tDel", self.trash)
        m.exec(self.list.mapToGlobal(pos))

    def done(self, text):
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
        os.rename(sel[0], dst)
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
        os.makedirs(d.path(), exist_ok=True)
        steps = []
        for p in sel:
            if os.path.dirname(p) != d.path():
                dst = unique(os.path.join(d.path(), os.path.basename(p)))
                shutil.move(p, dst)
                self.win.moved(p, dst)
                steps.append(("move", p, dst))
        text = "Перенесено: %d шт. в «%s»" % (len(steps), os.path.relpath(d.path(), LIB))
        self.win.push(text, steps)
        self.done(text)

    def copy_color(self, hexv):
        QApplication.clipboard().setText(hexv)
        self.win.say("Цвет скопирован: " + hexv)

    def copy_path(self):
        sel = self.paths()
        if sel:
            QApplication.clipboard().setText("\n".join(sel))
            self.win.say("Путь скопирован" if len(sel) == 1 else "Скопировано путей: %d" % len(sel))

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
        self.done("В корзине: %d шт." % n)
