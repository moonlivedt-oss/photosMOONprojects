"""Вкладка «Библиотека»: плитки, панель просмотра, быстрый просмотр, действия с файлами."""

import html
import os
import shutil
import time

from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QMimeData, QRectF, QSize, QStringListModel, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QCursor, QIcon, QPainter, QPainterPath, QPixmap
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

import imaging as K
from library import db, prompts
from ui.common import (
    EXT,
    FAV,
    HEAVY,
    HEAVY_KB,
    LIB,
    PIX,
    RECENT,
    ROLE,
    SETS,
    SMART,
    STAR,
    SUB,
    TAG,
    THUMB,
    TINT,
    bg,
    clean_name,
    human,
    in_main,
    reveal,
    to_trash,
    unique,
)
from ui.compress import COPY_FORMATS, CompressDialog, copy_files
from ui.editor import EditDialog
from ui.export import ExportDialog, export
from ui.theme import C
from ui.thumbnails import (
    _thumbs,
    backdrop,
    lib_icon,
    palette,
    remember,
    swatch,
    thumb,
    thumb_key,
    tile,
    tile_image,
    to_qimage,
)
from ui.widgets import (
    DestDialog,
    LibList,
    PicView,
    TagHints,
    fill_tree,
    forget_counts,
    key,
    make_tree,
    section_color,
    select_path,
)

FILTERS = (
    (
        "orient",
        "Ориентация",
        (("any", "Любая"), ("land", "Горизонтальные"), ("port", "Вертикальные"), ("square", "Квадратные")),
    ),
    ("alpha", "Прозрачность", (("any", "Любая"), ("yes", "С прозрачным фоном"), ("no", "Без прозрачности"))),
    (
        "size",
        "Размер",
        (("any", "Любой"), ("small", "Маленькие, до 128"), ("mid", "Средние"), ("big", "Большие, от 1024")),
    ),
    ("fmt", "Формат", (("any", "Любой"), ("png", "PNG"), ("webp", "WEBP"), ("jpg", "JPG"), ("svg", "SVG"))),
)
FILTER_DEFAULT = {k: "any" for k, _t, _o in FILTERS}


def passes(path, f, meta):
    """Подходит ли картинка под фильтры. meta = (ширина, высота, прозрачность) или None - ещё не посчитано:
    такую не прячем по размеру и прозрачности (иначе свежие картинки пропадали бы до пересчёта)."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if f["fmt"] != "any" and {"jpeg": "jpg"}.get(ext, ext) != f["fmt"]:
        return False
    if meta is None or not meta[0]:
        return True
    w, h, alpha = meta
    if f["orient"] == "land" and not w > h * 1.05:
        return False
    if f["orient"] == "port" and not h > w * 1.05:
        return False
    if f["orient"] == "square" and (w > h * 1.05 or h > w * 1.05):
        return False
    if f["alpha"] != "any" and bool(alpha) != (f["alpha"] == "yes"):
        return False
    side = max(w, h)
    if f["size"] == "small" and side > 128 or f["size"] == "big" and side < 1024:
        return False
    return not (f["size"] == "mid" and not 128 < side < 1024)


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
        self.used = QLabel(objectName="dim", wordWrap=True)
        self.used.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.used.hide()
        self.where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.chips = QHBoxLayout()  # размер, формат, вес - плашками
        self.chips.setSpacing(5)
        self.pal_lbl = QLabel("ЦВЕТА", objectName="faint")
        self.colors = QHBoxLayout()  # главные цвета картинки: щелчок копирует HEX
        self.ver_lbl = QLabel("ВЕРСИИ", objectName="faint")
        self.ver_lbl.setToolTip("Прошлые версии после правки и сжатия: сравнить или вернуть")
        self.vers = QHBoxLayout()  # прошлые версии из _sources: щелчок - сравнить или вернуть
        self.vers.setSpacing(6)
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
        self.hints = TagHints()
        self.hints.picked.connect(self.add_hint)
        self.hint_gen = 0
        self.note = QPlainTextEdit(placeholderText="заметка: где использована, откуда, что поправить")
        self.note.setFixedHeight(54)
        self.note_timer = QTimer(self, singleShot=True, interval=700)
        self.note_timer.timeout.connect(lambda: self.tab.save_note(self.note.toPlainText()))
        self.note.textChanged.connect(lambda: self.note_timer.start() if not self.loading_meta else None)
        self.loading_meta = False
        # главное действие - крупно, остальное - строкой значков, редкое - в «Ещё»
        self.btns = []

        def tool(text, icon, fn, tip=""):
            b = QPushButton(lib_icon(icon), "", objectName="tool")
            b.setToolTip(text + (f"  ({tip})" if tip else ""))
            b.clicked.connect(fn)
            self.btns.append(b)
            return b

        main = QHBoxLayout()
        main.setSpacing(6)
        self.export_btn = QPushButton(lib_icon("upload-arrow"), "Выгрузить в проект...", objectName="primary")
        self.export_btn.setToolTip("Ctrl+E - копии нужного формата и размера в папку проекта")
        self.export_btn.clicked.connect(tab.export)
        self.btns.append(self.export_btn)
        self.look_btn = QPushButton(lib_icon("eye"), "Просмотр")
        self.look_btn.setToolTip("Пробел - на всё окно, стрелки листают")
        self.look_btn.clicked.connect(tab.look)
        self.btns.append(self.look_btn)
        main.addWidget(self.export_btn, 1)
        main.addWidget(self.look_btn)
        tools = QHBoxLayout()
        tools.setSpacing(4)
        self.open_btn = tool("Открыть", "image-file", tab.open_file, "Enter или двойной щелчок по плитке")
        self.fav_btn = tool("В избранное", "star", tab.toggle_fav, "Ctrl+D")
        self.similar_btn = tool("Похожие по рисунку и пропорциям", "magnifying-glass", tab.find_similar)
        for b in (
            self.open_btn,
            tool("Показать в проводнике", "folder", tab.reveal),
            tool("Копировать картинку", "camera", tab.copy_image, "Ctrl+Shift+C"),
            tool("Копировать путь", "clipboard", tab.copy_path, "Ctrl+C"),
            self.fav_btn,
            self.similar_btn,
            tool("Редактировать", "paint-brush", tab.edit, "Ctrl+R"),
            tool("Сжать и конвертировать", "zip-archive", tab.compress, "Ctrl+K"),
        ):
            tools.addWidget(b)
        tools.addStretch(1)
        more = QPushButton(lib_icon("menuGrid"), "Ещё", objectName="ghost")
        mm = QMenu(self)
        self.rename_act = mm.addAction(lib_icon("quill-pen"), "Переименовать\tF2", tab.rename)
        mm.addAction(lib_icon("folder"), "Перенести в раздел...", tab.move)
        mm.addSeparator()
        mm.addAction(lib_icon("trash-bin"), "В корзину\tDel", tab.trash)
        more.setMenu(mm)
        more.setToolTip("Переименовать, перенести, в корзину")
        self.btns.append(more)
        tools.addWidget(more)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(self.pic, 3)
        v.addSpacing(4)
        v.addWidget(self.name)
        v.addWidget(self.where)
        v.addWidget(self.used)
        v.addLayout(self.chips)
        v.addSpacing(2)
        v.addWidget(self.pal_lbl)
        v.addLayout(self.colors)
        v.addWidget(self.ver_lbl)
        v.addLayout(self.vers)
        v.addWidget(self.tag_lbl)
        v.addWidget(self.tags)
        v.addWidget(self.hints)
        v.addWidget(self.note)
        v.addSpacing(4)
        v.addLayout(main)
        v.addLayout(tools)
        v.addStretch(1)  # картинка не выше своих пропорций - свободное место уходит вниз
        self.pic.fit_aspect = True
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
            self.tag_model.setStringList(sorted(db.all_tags()))
            common = set(db.tags_of(rels[0])) if rels else set()
            for r in rels[1:]:
                common &= set(db.tags_of(r))
            self.tags.setText(", ".join(sorted(common)))
            self.note.setPlainText(db.note_of(rels[0]) if len(rels) == 1 else "")
        except Exception:
            pass
        self.tags.setPlaceholderText(
            "метки через запятую: космос, для сайта"
            if len(rels) <= 1
            else "общие метки всех выбранных - добавьте или уберите"
        )
        for w in (self.tag_lbl, self.tags):
            w.setVisible(bool(rels))
        self.note.setVisible(len(rels) == 1)
        self.loading_meta = False
        self.suggest(paths)

    def suggest(self, paths):
        """Метки по смыслу для выбранного (векторы уже в индексе - считается за доли секунды, в фоне)."""
        self.hint_gen += 1
        gen, win = self.hint_gen, self.tab.win
        self.hints.set_tags([])
        vecs = win.sem.vecs_of(paths[:50]) if paths and win.sem.ok else []
        if not len(vecs):
            return
        have = {t.strip() for t in self.tags.text().split(",") if t.strip()}
        bg(
            lambda: win.tagger.suggest_vecs(vecs, have),
            lambda res: gen == self.hint_gen and self.hints.set_tags(res if isinstance(res, list) else [], have),
        )

    def add_hint(self, tag):
        tags = [t.strip() for t in self.tags.text().split(",") if t.strip()]
        if tag not in tags:
            self.tags.setText(", ".join(tags + [tag]))
            self.tab.save_tags(self.tags.text())

    def show_set(self, s, cover):
        """Набор (вид «Наборы»): обложка, палитры плашками."""
        for b in self.btns:
            b.setEnabled(False)
        self.show_colors(None)
        self.show_meta([])
        self.pic.set_pixmap(cover)
        self.name.setText(os.path.basename(s["path"]))
        self.where.setText("{}, двойной щелчок - открыть".format(os.path.relpath(os.path.dirname(s["path"]), LIB)))
        self.set_chips(["%s: %d" % (f, n) for f, n, _p in s["pals"]][:8])

    def show_paths(self, paths, mode):
        self.show_meta(paths)
        self.show_used(paths[0] if len(paths) == 1 else None)
        for b in self.btns:
            b.setEnabled(bool(paths))
        for b in (self.open_btn, self.similar_btn):  # только по одной
            b.setEnabled(len(paths) == 1)
        self.rename_act.setEnabled(bool(paths))  # несколько - одно имя с номерами
        fav = db.favs() if paths else ()
        on = bool(paths) and os.path.relpath(paths[0], LIB) in fav
        self.fav_btn.setToolTip("Убрать из избранного  (Ctrl+D)" if on else "В избранное  (Ctrl+D)")
        self.show_colors(paths[0] if len(paths) == 1 else None)
        self.show_versions(paths[0] if len(paths) == 1 else None)
        mode = None if mode == "chk" else mode  # прозрачное - прямо на свечении, без шахматки
        if not paths:
            self.pgen = getattr(self, "pgen", 0) + 1  # недогруженная прошлая картинка не всплывёт
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
            chips += [
                os.path.splitext(p)[1][1:].upper(),
                human(st.st_size),
                time.strftime("%d.%m.%Y", time.localtime(st.st_mtime)),
            ]
        except Exception:
            pass
        self.set_chips(chips)

    def show_used(self, path):
        """Куда картинка выгружалась (Ctrl+E): видно, в каких проектах она уже живёт."""
        rows = []
        if path:
            try:
                rows = db.exports_of(os.path.relpath(path, LIB))
            except Exception:
                rows = []
        names = []
        for dest, t in rows[:3]:
            parts = os.path.normpath(dest).split(os.sep)
            names.append("%s (%s)" % (" / ".join(parts[-2:]), time.strftime("%d.%m.%Y", time.localtime(t))))
        self.used.setText("Выгружено в: " + ", ".join(names) + (" и ещё %d" % (len(rows) - 3) if len(rows) > 3 else ""))
        self.used.setToolTip("\n".join(d for d, _t in rows))
        self.used.setVisible(bool(rows))

    def show_pic(self, path, mode):
        """Крупная картинка - из памяти сразу, иначе в фоне (листание стрелками не тормозит)."""
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

    def show_versions(self, path):
        """Прошлые версии картинки (правка, сжатие) - маленькими превью; нет версий - строки нет."""
        from library import versions

        self.clear_row(self.vers)
        vs = versions.versions(path)[:6] if path else []
        self.ver_lbl.setVisible(bool(vs))
        for vinfo in vs:
            b = QPushButton(objectName="tool")
            b.setIcon(QIcon(thumb(vinfo["path"], 64)))
            b.setIconSize(QSize(34, 34))
            b.setToolTip(f"{vinfo['kind']} {vinfo['date']}, {human(vinfo['size'])} - щелчок: сравнить или вернуть")
            b.clicked.connect(lambda _c=False, vp=vinfo["path"], cur=path: self.version_menu(cur, vp))
            self.vers.addWidget(b)
        self.vers.addStretch(1)

    def version_menu(self, cur, ver):
        m = QMenu(self)
        m.addAction(lib_icon("magnifying-glass"), "Сравнить с текущей", lambda: self.tab.compare([ver, cur]))
        m.addAction(
            lib_icon("arrow_counterclockwise"), "Вернуть эту версию", lambda: self.tab.restore_version(cur, ver)
        )
        m.addAction(lib_icon("folder"), "Показать в проводнике", lambda: reveal(ver))
        m.exec(QCursor.pos())

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
                b.setStyleSheet(
                    "QPushButton#swatch{{background:{};border:2px solid {};border-radius:13px;padding:0}}"
                    "QPushButton#swatch:hover{{border:2px solid #ffffff}}".format(hexv, C["line2"])
                )
                b.setToolTip(f"{hexv} - щёлкните, чтобы скопировать")
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
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # иначе каждое открытие копило окно в памяти
        self.mode = tab.cfg.get("bg", "chk")
        self.setWindowTitle("Просмотр")
        self.setStyleSheet("QDialog{background:#09090d}")
        self.gen = 0
        self.pic = PicView(frame=False)
        self.pic.zoomable = True
        self.title = QLabel(objectName="head", alignment=Qt.AlignmentFlag.AlignCenter)
        self.cap = QLabel(objectName="dim", alignment=Qt.AlignmentFlag.AlignCenter)
        hint = QLabel(
            "←  →  листать      колесо  увеличить      1 или двойной щелчок  пиксель в пиксель      "
            "0  целиком      B  подложка      Пробел или Esc  закрыть",
            objectName="faint",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
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
        self.cap.setText(
            "%s      %d из %d" % (os.path.dirname(os.path.relpath(p, LIB)).replace(os.sep, "  /  "), self.row + 1, n)
        )
        self.gen += 1
        gen = self.gen
        self.pic.set_glow(None)
        if not p.lower().endswith(".svg"):
            bg(
                lambda: palette(p),
                lambda res: (
                    not sip.isdeleted(self)
                    and gen == self.gen
                    and isinstance(res, list)
                    and res
                    and self.pic.set_glow(vivid(res))
                ),
            )

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
            if mode != "chk":  # шахматку не кладём: прозрачное висит на свечении
                back = backdrop(im.width, im.height, mode)
                back.alpha_composite(im)
                im = back
            return to_qimage(im)

        def done(img):
            if sip.isdeleted(self):  # просмотр закрыли, пока картинка грузилась
                return
            self.loading.discard(key)
            pm = QPixmap() if isinstance(img, Exception) else QPixmap.fromImage(img)
            self.cache[key] = pm
            while len(self.cache) > 6:  # держим текущую и соседей
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
    pals = set(prompts.pal_by_folder())
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
        sheet.alpha_composite(
            im, ((i % cols) * cell + (cell - im.width) // 2, (i // cols) * cell + (cell - im.height) // 2)
        )
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


def rename_file(src, dst):
    """Переименовать; если файл на миг занят (дочитывается миниатюра) - ещё раз чуть позже."""
    for wait in (0.15, 0.4, None):
        try:
            os.rename(src, dst)
            return
        except PermissionError:
            if wait is None:
                raise
            time.sleep(wait)


class LibTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.side = max(64, min(THUMB, self.cfg.get("thumb", 128)))
        self.like = None  # "Похожие на ...": путь картинки-образца
        self.ai_show = None  # (пути, заголовок, кто) - список, который показал ИИ-помощник (show)
        self.like_sem = False  # похожие по смыслу (CLIP), а не по рисунку; like - может быть и не из библиотеки
        self.tree = make_tree()
        self.tree.currentItemChanged.connect(lambda *_: self.leave_similar())
        self.q = QLineEdit(placeholderText="Поиск по всей библиотеке  (Ctrl+F)", objectName="search")
        self.q.setClearButtonEnabled(True)
        self.q.addAction(lib_icon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self.qt = QTimer(self, singleShot=True, interval=180)  # не перерисовывать на каждую букву
        self.qt.timeout.connect(self.show_files)
        self.q.textChanged.connect(lambda *_: self.qt.start())
        if win.sem.ok:
            self.q.setPlaceholderText("Поиск по всей библиотеке  (Ctrl+F), можно бросить сюда картинку")
            self.q.installEventFilter(self)
        self.sem = QPushButton(lib_icon("crystal-ball-stand"), "", objectName="tool", checkable=True)
        self.sem.setToolTip("Поиск по смыслу (Ctrl+M): «кот в космосе», «уютная ночная улица»")
        self.sem.setChecked(bool(self.cfg.get("semantic")) and win.sem.ok)
        self.sem.setVisible(win.sem.ok)
        self.sem.toggled.connect(self.toggle_sem)
        self.save_q = QPushButton(lib_icon("bookmark"), "", objectName="tool")
        self.save_q.setToolTip("Сохранить поиск как умную папку")
        self.save_q.clicked.connect(self.save_smart)
        self.color = QComboBox()
        self.color.addItem(lib_icon("color-palette"), "Любой цвет", "")
        for code, name, hexv in K.COLORS:
            self.color.addItem(swatch(hexv), name, code)
        self.color.setToolTip("Показать только картинки, где заметен этот цвет")
        self.color.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.color.currentIndexChanged.connect(self.show_files)
        # фильтры: ориентация, прозрачность, размер, формат (размер и прозрачность - из отпечатков)
        self.filt = dict(FILTER_DEFAULT, **self.cfg.get("lib_filters", {}))
        self.filt_btn = QPushButton(lib_icon("menuList"), "Фильтры", objectName="ghost")
        self.filt_btn.setToolTip("Ориентация, прозрачность, размер, формат")
        self.filt_menu = QMenu(self)
        self.filt_btn.setMenu(self.filt_menu)
        self.filt_menu.aboutToShow.connect(self.fill_filters)
        self.show_filter_count()
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
        self.list.quick_action = self.quick_tile
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
        bar.addWidget(self.sem)
        bar.addWidget(self.save_q)
        bar.addWidget(self.color)
        bar.addWidget(self.filt_btn)
        bar.addWidget(self.sort)
        bar.addWidget(self.back)
        bar.addWidget(self.slider)
        mid = QWidget()
        rv = QVBoxLayout(mid)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(bar)
        rv.addWidget(self.title)
        # общий поиск: подходящие по смыслу ассеты Unreal - полосой над картинками
        self.ue_box = QWidget()
        ub = QVBoxLayout(self.ue_box)
        ub.setContentsMargins(0, 0, 0, 4)
        self.ue_lbl = QLabel(objectName="faint")
        self.ue_strip = QListWidget()
        self.ue_strip.setViewMode(QListWidget.ViewMode.IconMode)
        self.ue_strip.setFlow(QListWidget.Flow.LeftToRight)
        self.ue_strip.setWrapping(False)
        self.ue_strip.setMovement(QListWidget.Movement.Static)
        self.ue_strip.setIconSize(QSize(84, 84))
        self.ue_strip.setGridSize(QSize(112, 122))
        self.ue_strip.setFixedHeight(146)
        self.ue_strip.setHorizontalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.ue_strip.itemClicked.connect(self.open_ue)
        ub.addWidget(self.ue_lbl)
        ub.addWidget(self.ue_strip)
        self.ue_box.hide()
        self.ue_t = QTimer(self, singleShot=True, interval=450)
        self.ue_t.timeout.connect(self.update_ue_strip)
        self.q.textChanged.connect(lambda *_: self.ue_t.start())
        rv.addWidget(self.ue_box)
        rv.addWidget(self.list, 1)
        rv.addWidget(self.info)
        self.preview = Preview(self)
        # слева: карточки быстрого доступа (как виды во вкладке Unreal) и дерево разделов
        from ui.unreal_nav import KindCard

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        lv.addWidget(QLabel("БЫСТРЫЙ ДОСТУП", objectName="faint"))
        grid = QGridLayout()
        grid.setSpacing(4)
        self.quick = {}
        for i, (text, role, icon, color, hint) in enumerate(
            (
                ("Недавние", RECENT, "hourglass", "#6cb8ff", "последние сохранённые картинки"),
                ("Избранное", FAV, "star", "#ff8ac9", "отмечено звездой (Ctrl+D)"),
                ("Наборы", SETS, "color-palette", "#a897ff", "папки с палитрами - одной обложкой"),
                ("Тяжёлые", HEAVY, "zip-archive", "#f0a35e", "тяжелее 500 КБ - можно сжать"),
            )
        ):
            c = KindCard(role, (text, icon, color), hint)
            c.set_sub(
                {RECENT: "последние сохранённые", FAV: "отмечено звездой", SETS: "по палитрам", HEAVY: "можно сжать"}[
                    role
                ]
            )
            c.clicked.connect(lambda _c=False, r=role: self.show_section(r))
            self.quick[role] = c
            grid.addWidget(c, i, 0)
        lv.addLayout(grid)
        lv.addSpacing(6)
        lv.addWidget(self.tree, 1)
        self.tree.currentItemChanged.connect(self.sync_quick)
        self.split = QSplitter()
        for w in (left, mid, self.preview):
            self.split.addWidget(w)
        self.split.setStretchFactor(1, 1)
        sizes = list(self.cfg.get("split_lib", [250, 720, 300]))
        sizes[0] = max(sizes[0], 210)  # уже - имена разделов и числа не помещаются
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
        key("Ctrl+M", self, lambda: self.sem.isVisible() and self.sem.toggle())
        key("Alt+Left", self, self.go_back)
        for w in (self.list.viewport(), self.tree.viewport()):  # кнопка мыши «назад»
            w.installEventFilter(self)
        self.tree.setAcceptDrops(True)  # плитки можно бросить на раздел - перенос
        self.past, self.here = [], None  # прошлые разделы для Alt+← и кнопки мыши «назад»
        self.tree.currentItemChanged.connect(self.track)
        self.show_back()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.refresh()

    def refresh(self):
        """Пересобрать дерево и плитки один раз (без сигналов дерево перестраивалось бы с плитками по 2-3 раза)."""
        self.tree.blockSignals(True)
        fill_tree(self.tree, planned=False, recent=True)
        if not self.tree.currentItem():  # раздел, открытый в прошлый раз
            select_path(self.tree, self.cfg.get("lib_section"))
        if not self.tree.currentItem():  # или первый раздел библиотеки
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
        i = self.win.inbox.bg.findData(mode)  # во входящих та же подложка
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
        if obj is self.q and t in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return self.search_drop(e, t)
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
        if self.like or self.ai_show:  # из «Похожих» и списка помощника - туда, откуда пришли
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
        elif self.like or self.ai_show:
            self.leave_similar()
        elif self.color.currentIndex():
            self.color.setCurrentIndex(0)
        else:
            self.list.clearSelection()

    def remember_section(self):
        it = self.tree.currentItem()
        if it and it.data(0, ROLE):
            self.cfg["lib_section"] = it.data(0, ROLE)

    def fill_filters(self):
        m = self.filt_menu
        m.clear()
        for i, (fk, title, opts) in enumerate(FILTERS):
            if i:
                m.addSeparator()
            m.addAction(title.upper()).setEnabled(False)  # addSection в этом стиле заголовок не рисует
            for val, text in opts:
                a = m.addAction(text, lambda k=fk, v=val: self.set_filter(k, v))
                a.setCheckable(True)
                a.setChecked(self.filt[fk] == val)
        m.addSeparator()
        m.addAction(lib_icon("cross"), "Сбросить фильтры", lambda: self.set_filter(None, None))

    def set_filter(self, key, val):
        if key is None:
            self.filt = dict(FILTER_DEFAULT)
        else:
            self.filt[key] = val
        self.cfg["lib_filters"] = {k: v for k, v in self.filt.items() if v != FILTER_DEFAULT[k]}
        self.show_filter_count()
        self.show_files()

    def show_filter_count(self):
        n = sum(1 for k, v in self.filt.items() if v != FILTER_DEFAULT[k])
        self.filt_btn.setText(f"Фильтры: {n}" if n else "Фильтры")

    def sync_quick(self, it, _prev=None):
        role = it.data(0, ROLE) if it else None
        for r, c in self.quick.items():
            c.setChecked(r == role)

    # ------------------------------------------------------------ общий поиск с ассетами Unreal
    def update_ue_strip(self):
        text = self.q.text().strip()
        ue = getattr(self.win, "unreal", None)
        if not text or ue is None:
            self.ue_box.hide()
            return
        if not ue.loaded:  # вкладку Unreal ещё не открывали - подгрузит список и сама обновит полосу (loaded)
            ue.refresh()
            return
        if not ue.items:
            self.ue_box.hide()
            return
        if ue.sem is not None:
            found = [a for a, _s in ue.sem.rank(text, ue.items)][:16]
        else:
            words = text.lower().split()
            found = [
                a
                for a in ue.items
                if all(w in (a.get("name", "") + " " + " ".join(a.get("tags", []))).lower() for w in words)
            ][:16]
        self.ue_strip.clear()
        for a in found:
            prev = os.path.join(a["dir"], "preview.webp")
            # квадратом: высокое превью (фонарь) иначе сдвигает подпись ниже соседних
            try:
                icon = QIcon(tile(K.load(prev), 96))
            except Exception:  # нет превью или битое - плитка без картинки
                icon = QIcon()
            it = QListWidgetItem(icon, a.get("name", ""))
            it.setData(ROLE, a)
            it.setToolTip(f"{a.get('name', '')}, {a.get('theme', '')} - открыть во вкладке Unreal")
            self.ue_strip.addItem(it)
        self.ue_lbl.setText(f"АССЕТЫ UNREAL ПО ЗАПРОСУ: {len(found)}  -  щелчок открывает во вкладке Unreal")
        self.ue_box.setVisible(bool(found))

    def open_ue(self, it):
        self.win.unreal.go_to(it.data(ROLE), self.q.text())

    def go_to(self, folder, path=None, tries=12):
        """Показать раздел и (если задан) выбрать в нём картинку - для общего поиска (Ctrl+P)."""
        if tries == 12:
            self.win.tabs.setCurrentIndex(1)
            self.q.clear()
            select_path(self.tree, folder)
        if not path:
            return
        for i in range(self.list.count()):
            if os.path.normcase(self.list.item(i).data(ROLE) or "") == os.path.normcase(path):
                self.list.clearSelection()
                self.list.setCurrentRow(i)
                self.list.scrollToItem(self.list.item(i))
                return
        if tries:  # плитки раздела ещё грузятся
            QTimer.singleShot(150, lambda: self.go_to(folder, path, tries - 1))

    # ------------------------------------------------------------ инструменты: палитра, сравнение, svg
    def palette_from(self, source=None, targets=None):
        from ui.tools_dialogs import PaletteDialog

        targets = self.paths() if targets is None else targets
        self.pal_dlg = PaletteDialog(self.win, targets, source)
        self.pal_dlg.show()

    def restore_version(self, cur, ver):
        """Вернуть прошлую версию: текущая сама станет версией, Ctrl+Z отменит."""
        from library import versions

        try:
            new, steps = versions.restore(cur, ver)
        except Exception as e:
            self.win.say(f"Не вышло: {e}")
            return
        self.win.push(f"Возвращена версия: {os.path.basename(new)}", steps)
        forget_counts()
        self.show_files()
        self.win.say("Возвращена прошлая версия - текущая сохранена в истории", undo=True)

    def compare(self, paths=None):
        from ui.tools_dialogs import CompareDialog

        paths = paths or self.paths()
        if len(paths) != 2:
            self.win.say("Для сравнения выберите ровно две картинки (Ctrl+щелчок)")
            return
        self.cmp_dlg = CompareDialog(self.win, paths[0], paths[1])
        self.cmp_dlg.show()

    def vectorize(self, paths=None):
        from ui.tools_dialogs import VectorDialog

        paths = [p for p in (paths or self.paths()) if not p.lower().endswith(".svg")]
        if not paths:
            self.win.say("Выберите картинки для перевода в SVG")
            return
        self.vec_dlg = VectorDialog(self.win, paths)
        self.vec_dlg.show()

    def show_section(self, role):
        self.q.clear()
        self.color.setCurrentIndex(0)
        select_path(self.tree, role)

    def all_shown(self):
        return [self.list.item(i).data(ROLE) for i in range(self.list.count())]

    def tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it or not it.data(0, ROLE):  # подпись группы
            return
        self.tree.setCurrentItem(it)
        files = self.all_shown()
        role = it.data(0, ROLE)
        m = QMenu(self)
        if os.path.isdir(role):
            m.addAction("Открыть папку в проводнике", lambda: os.startfile(role))
        if role.startswith(TAG):
            m.addAction("Убрать метку у всех картинок", lambda: self.delete_tag(role[len(TAG) :]))
        if role.startswith(SMART):
            m.addAction("Переименовать умную папку...", lambda: self.rename_smart(role[len(SMART) :]))
            m.addAction("Удалить умную папку", lambda: self.delete_smart(role[len(SMART) :]))
        if files:
            m.addSeparator()
            m.addAction("Сжать весь раздел (%d)..." % len(files), lambda: self.compress(files))
            m.addAction("Выгрузить раздел в папку...", lambda: self.export(files))
            m.addAction("Лист превью раздела...", lambda: self.preview_sheet(files))
            if self.win.sem.ready():
                m.addAction("Поставить подсказанные метки (%d)..." % len(files), lambda: self.auto_tag(files))
        if m.isEmpty():
            return
        m.exec(self.tree.mapToGlobal(pos))
        self.show_files()

    def auto_tag(self, files):
        """Каждой картинке - её подсказанные метки (по готовым векторам, без чтения файлов). Сначала
        показывается, что получится; метки по одной потом снимаются правым щелчком в дереве."""
        sem, tagger = self.win.sem, self.win.tagger
        self.win.say("Подбираю метки для %d картинок..." % len(files))

        def work():
            plan = {}
            for p in files:
                v = sem.vecs_of([p])
                if len(v):
                    rel = os.path.relpath(p, LIB)
                    tags = tagger.suggest_vecs(v, set(db.tags_of(rel)))
                    if tags:
                        plan[rel] = tags
            return plan

        def done(plan):
            if isinstance(plan, Exception) or not plan:
                self.win.say("Подсказать нечего" if not isinstance(plan, Exception) else f"Не вышло: {plan}")
                return
            count = {}
            for tags in plan.values():
                for t in tags:
                    count[t] = count.get(t, 0) + 1
            top = sorted(count, key=count.get, reverse=True)
            text = "\n".join("%s - %d" % (t, count[t]) for t in top[:15]) + ("\n..." if len(top) > 15 else "")
            ask = QMessageBox.question(
                self,
                "Поставить метки",
                "Картинок с подсказками: %d, разных меток: %d.\n\n%s\n\nПоставить?" % (len(plan), len(top), text),
            )
            if ask != QMessageBox.StandardButton.Yes:
                return
            steps = []
            for rel, tags in plan.items():
                before = db.tags_of(rel)
                db.set_tags([rel], tags, "add")
                steps.append(["tags", rel, before, db.tags_of(rel)])
            self.win.push("Подсказанные метки: %d картинок" % len(plan), steps)  # Ctrl+Z снимет все разом
            fill_tree(self.tree, planned=False, recent=True)
            self.describe()
            self.win.say(
                "Метки поставлены: %d картинок. Ctrl+Z снимет все разом, лишнюю метку - правый щелчок в дереве"
                % len(plan),
                undo=True,
            )

        bg(work, done)

    def delete_tag(self, tag):
        if (
            QMessageBox.question(self, "Метка", "Убрать метку «%s» у всех картинок?" % tag)
            != QMessageBox.StandardButton.Yes
        ):
            return
        n = db.delete_tag(tag)
        fill_tree(self.tree, planned=False, recent=True)
        self.win.say("Метка «%s» убрана у %d картинок" % (tag, n))

    def toggle_sem(self, on):
        self.cfg["semantic"] = on
        if on and not self.win.sem.ready():
            self.win.say("Поиск по смыслу ещё учит картинки - ход внизу окна")
        if self.q.text().strip():
            self.show_files()

    def save_smart(self):
        text, code, sem, smart = self.query()
        if smart or not (text or code):
            self.win.say("Сначала наберите поиск или выберите цвет - их и запомнит умная папка")
            return
        name, ok = QInputDialog.getText(self, "Умная папка", "Название:", text=text or self.color.currentText())
        name = clean_name(name)
        if not ok or not name:
            return
        db.save_smart(name, text, code or "", sem)
        self.q.clear()
        self.color.setCurrentIndex(0)
        fill_tree(self.tree, planned=False, recent=True)
        select_path(self.tree, SMART + name)
        self.win.say(f"Умная папка «{name}» - в дереве слева, сама пополняется")

    def rename_smart(self, old):
        name, ok = QInputDialog.getText(self, "Умная папка", "Новое название:", text=old)
        name = clean_name(name)
        if not ok or not name or name == old:
            return
        for n, q, col, sem in db.smart_folders():
            if n == old:
                db.save_smart(name, q, col, sem)
                db.delete_smart(old)
        fill_tree(self.tree, planned=False, recent=True)
        select_path(self.tree, SMART + name)

    def delete_smart(self, name):
        db.delete_smart(name)
        fill_tree(self.tree, planned=False, recent=True)
        self.win.say(f"Умная папка «{name}» удалена (картинки на месте)")

    def resize_tiles(self, v):
        self.side = v
        self.cfg["thumb"] = v
        self.list.set_base(v)

    def query(self):
        """(текст, цвет, по смыслу, умная папка): из поля поиска или из выбранной умной папки."""
        text, code, sem = self.q.text().strip(), self.color.currentData(), self.sem.isChecked()
        it = self.tree.currentItem()
        role = it.data(0, ROLE) if it else None
        if not text and isinstance(role, str) and role.startswith(SMART):
            for name, q, col, s in db.smart_folders():
                if SMART + name == role:
                    return q, code or col, s, name
        return text, code, sem, None

    def show_files(self):
        text, code, sem, smart = self.query()
        tokens = text.lower().replace("ё", "е").split()
        minus = [t[1:] for t in tokens if t.startswith("-") and len(t) > 1]  # «кот -png»: без png
        words = [t for t in tokens if not t.startswith("-")]
        sem = sem and bool(words) and self.win.sem.ready()
        it = self.tree.currentItem()
        root = LIB if tokens or smart else (it.data(0, ROLE) if it else None)
        keep = set(self.paths())
        self.list.clear()
        self.list.reset_anim()
        fav = db.favs()
        self.sets_view = root == SETS and not tokens and not self.like and not self.ai_show
        if self.sets_view:
            self.show_sets()
            return
        if self.ai_show:  # список от ИИ-помощника - в его порядке
            root = RECENT
            files = [p for p in self.ai_show[0] if os.path.exists(p)]
        elif self.like:
            root = RECENT  # порядок задаёт похожесть, сортировку не применяем
            files = self.win.sem.similar(self.like) if self.like_sem else self.win.sigs.similar(self.like)
        elif sem:
            root = RECENT
            files = self.win.sem.search(" ".join(words))
        elif isinstance(root, str) and root.startswith(TAG):
            files = [
                os.path.join(LIB, r) for r in db.with_tag(root[len(TAG) :]) if os.path.exists(os.path.join(LIB, r))
            ]
        elif root == RECENT:
            files = sorted(K.images_in(LIB), key=mtime, reverse=True)[:120]
        elif root == HEAVY:
            files = sorted((f for f in K.images_in(LIB) if fsize(f) > HEAVY_KB * 1024), key=fsize, reverse=True)
        elif root == FAV:
            files = [os.path.join(LIB, r) for r in sorted(fav) if os.path.exists(os.path.join(LIB, r))]
        elif root and os.path.isdir(root):
            files = K.images_in(root)
        elif root and not os.path.isdir(root) and not root.startswith("::"):  # раздел пропал (перенесли)
            files = []
        else:
            files = []
        if tokens and sem:
            files = [p for p in files if not any(w in os.path.relpath(p, LIB).lower() for w in minus)]
        elif tokens:
            extra = db.search_text()  # метки и заметки: «#космос» или просто «космос»
            words = [w.lstrip("#") for w in words]

            def hit(p):
                rel = os.path.relpath(p, LIB)
                s = rel.lower().replace("ё", "е") + " " + extra.get(rel, "")
                return all(w in s for w in words) and not any(w in s for w in minus)

            files = [p for p in files if hit(p)]
            if not files and words and not minus and self.win.sem.ready() and not smart:
                files, sem, root = self.win.sem.search(" ".join(words)), "fallback", RECENT  # по именам пусто
        if code:
            files = [p for p in files if self.win.sigs.has_color(p, code)]
        if any(self.filt[k] != v for k, v in FILTER_DEFAULT.items()):
            files = [p for p in files if passes(p, self.filt, self.win.sigs.meta_of(p))]
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
            item.setData(TINT, section_color(p))
            item.setToolTip(rel)
            if thumb_key(p, THUMB, mode) in _thumbs or p.lower().endswith(".svg"):
                item.setData(PIX, thumb(p, THUMB, mode))
            else:
                todo.append((i, p))
            self.list.addItem(item)
            if p in keep:
                item.setSelected(True)
        self.list.setUpdatesEnabled(True)
        self.show_title(root, words + ["-" + w for w in minus], code, len(files), text, sem, smart)
        self.list.load_tiles(todo, THUMB, mode)
        self.describe()

    @staticmethod
    def caption(p, base, ext, how):
        """Вторая строка плитки: подпапка внутри открытого раздела и формат (у тяжёлых - и вес).
        Иначе в «01 Фоны» десяток плиток подписаны одинаково - «Боковая панель»."""
        folder = os.path.relpath(os.path.dirname(p), base)
        parts = [] if folder == "." else [os.path.basename(folder)]  # весь путь - во всплывающей подсказке
        if not parts:
            parts.append(ext[1:].upper())
        if how == "size":
            try:
                parts.append(human(os.path.getsize(p)))
            except OSError:
                pass
        return ", ".join(parts)

    def show_title(self, root, words, code, n, text="", sem=False, smart=None):
        """Заголовок над плитками и подсказка, если показывать нечего."""
        names = {RECENT: "Недавние", FAV: "Избранное", HEAVY: "Тяжёлые (больше %d КБ)" % HEAVY_KB, SETS: "Наборы"}
        if isinstance(root, str) and root.startswith(TAG):
            names[root] = "Метка: " + root[len(TAG) :]
        if self.ai_show:
            head = f"{self.ai_show[1]}  ({self.ai_show[2]})"
        elif self.like:
            head = ("Похожие по смыслу на «%s»" if self.like_sem else "Похожие на «%s»") % os.path.basename(self.like)
        elif smart:
            head = f"Умная папка: {smart}"
        elif words:
            head = (
                "По именам ничего - по смыслу: " if sem == "fallback" else "По смыслу: " if sem else "Поиск: "
            ) + text
        elif root in names:
            head = names[root]
        elif root:
            head = os.path.relpath(root, LIB).replace(os.sep, "  /  ")
        else:
            head = ""
        if code:
            head += "  -  " + dict((c, n) for c, n, _h in K.COLORS).get(code, "").lower()
        self.title.setText(
            "%s   <span style='color:#8a879a;font-weight:400'>%d</span>" % (html.escape(head), n) if head else ""
        )
        if n:
            self.list.empty = ""
        elif words or code:
            self.list.empty = "Ничего не нашлось. Поиск идёт по именам файлов и папок, меткам и заметкам." + (
                "\nКнопка-шар справа от поиска ищет по смыслу: «кот в космосе», «уютная улица»."
                if self.win.sem.ok and not sem
                else ""
            )
        elif root == FAV:
            self.list.empty = "Избранного пока нет.\nВыберите картинку и нажмите Ctrl+D или «В избранное» справа."
        elif root == HEAVY:
            self.list.empty = "Тяжёлых файлов нет - всё уже сжато."
        else:
            self.list.empty = "В этом разделе пока пусто.\nКартинки сюда попадают из вкладки «Входящие»."
        self.list.empty_icon = (  # пустой экран - маскот библиотеки по случаю
            "mascot:Поиск"
            if words or code
            else "mascot:Привет"
            if root == FAV
            else "mascot:Победа"
            if root == HEAVY
            else "mascot:Думает"
        )
        self.list.viewport().update()

    def paths(self):
        if self.sets_view:  # в «Наборах» плитки - папки, действия с файлами к ним не применяются
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
            item.setData(SUB, "%s, %d шт." % (plural(len(s["pals"]), "палитра", "палитры", "палитр"), s["count"]))
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
            self.list.empty = (
                "Наборов пока нет. Набор - папка с подпапками палитр, например «04 Иконки/Космос/Tokyo Night»."
            )
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
        if self.ai_show and not sel:
            self.info.setText("Показал ИИ-помощник - Esc или раздел слева, чтобы вернуться")
        elif self.like and not sel:
            self.info.setText(f"Похожие на «{os.path.basename(self.like)}» - щёлкните раздел слева, чтобы вернуться")
        elif sel:
            self.info.setText("Выбрано: %d из %d" % (len(sel), self.list.count()))
        else:
            self.info.setText(
                "Картинок: %d   Перетащите плитку в другую программу, чтобы вставить туда файл" % self.list.count()
            )

    def menu(self, pos):
        if not self.paths():
            return
        m = QMenu(self)
        sel = self.paths()
        tools = m.addMenu(lib_icon("toolbox"), "Инструменты")
        if len(sel) == 2:
            tools.addAction(lib_icon("magnifying-glass"), "Сравнить эти две", lambda: self.compare(sel))
        tools.addAction(
            lib_icon("color-palette"),
            "Палитра из этой картинки (перекрасить другие)...",
            lambda: self.palette_from(sel[0], []),
        )
        tools.addAction(
            lib_icon("color-palette"),
            "Перекрасить выбранные в палитру картинки...",
            lambda: self.palette_from(None, sel),
        )
        tools.addAction(lib_icon("drawing_pen"), "Векторизация в SVG (три варианта)...", lambda: self.vectorize(sel))
        m.addSeparator()
        m.addAction("Открыть\tEnter", self.open_file)
        m.addAction("Быстрый просмотр\tПробел", self.look)
        m.addAction("Показать в проводнике", self.reveal)
        m.addSeparator()
        fav = os.path.relpath(self.paths()[0], LIB) in db.favs()
        m.addAction("Убрать из избранного\tCtrl+D" if fav else "В избранное\tCtrl+D", self.toggle_fav)
        m.addAction("Найти похожие", self.find_similar)
        if self.win.sem.ready():
            m.addAction("Похожие по смыслу", lambda: self.find_similar(sem=True))
            m.addAction("Поставить подсказанные метки", lambda: self.auto_tag(self.paths()))
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

    def done(self, text, undo=False):
        """После действия: перерисовать, сообщить; undo - в пузыре кнопка «Отменить»."""
        forget_counts()
        self.refresh()
        self.changed.emit()
        self.win.say(text, undo=undo)

    def search_drop(self, e, t):
        """Картинка (файл из проводника или плитка) в строку поиска - похожие по смыслу на неё."""
        urls = [u.toLocalFile() for u in e.mimeData().urls()] if e.mimeData().hasUrls() else []
        pics = [p for p in urls if p.lower().endswith(K.EXT) and not p.lower().endswith(".svg")]
        if not pics:
            return False  # текст бросают как обычно
        e.acceptProposedAction()
        if t == QEvent.Type.Drop:
            self.search_by_image(pics[0])
        return True

    def search_by_image(self, path):
        sem = self.win.sem
        if not sem.ready():
            self.win.say("Поиск по смыслу ещё учит картинки - ход внизу окна")
            return
        self.win.say("Ищу похожие на «%s»..." % os.path.basename(path))

        def done(res):
            if isinstance(res, Exception):
                self.win.say(f"Не открылась картинка: {res}")
                return
            self.like, self.like_sem = path, True
            self.q.blockSignals(True)
            self.q.clear()
            self.q.blockSignals(False)
            self.show_files()

        bg(lambda: sem.embed_file(path), done)

    def leave_similar(self):
        self.like, self.like_sem, self.ai_show = None, False, None
        self.show_files()

    def show_ai(self, rels, title, who):
        """Список от ИИ-помощника (операция show): отдельным экраном, как «Похожие»."""
        self.like, self.like_sem = None, False
        self.ai_show = ([os.path.join(LIB, *r.split("/")) for r in rels], title, who)
        self.q.blockSignals(True)
        self.q.clear()
        self.q.blockSignals(False)
        self.show_files()
        self.list.scrollToTop()

    def find_similar(self, sem=False):
        sel = self.paths()
        if not sel:
            return
        index = self.win.sem.data if sem else self.win.sigs.data
        if os.path.relpath(sel[0], LIB) not in index:
            self.win.say("Эта картинка ещё не посчитана - попробуйте через пару секунд")
            return
        self.like, self.like_sem = sel[0], sem
        self.q.blockSignals(True)
        self.q.clear()
        self.q.blockSignals(False)
        self.show_files()
        self.list.scrollToTop()

    def quick_tile(self, row, name):
        """Кружок на плитке: «просмотр» - на всё окно, «избранное» - звезда этой картинке."""
        it = self.list.item(row)
        if it is None or not it.data(ROLE) or self.sets_view:  # в «Наборах» плитки - папки
            return
        self.list.clearSelection()
        self.list.setCurrentRow(row)
        if name == "look":
            self.look()
        elif name == "fav":
            self.toggle_fav()

    def toggle_fav(self):
        sel = [os.path.relpath(p, LIB) for p in self.paths()]
        if not sel:
            return
        fav = db.favs()
        add = any(r not in fav for r in sel)
        db.set_fav(sel, add)
        text = ("В избранном: +%d" if add else "Убрано из избранного: %d") % len(sel)
        self.win.push(text, [["fav", r, r in fav, add] for r in sel])
        self.show_files()
        self.win.say(text)

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
            rels = [os.path.relpath(p, LIB) for p in sel if os.path.splitdrive(p)[0] == os.path.splitdrive(LIB)[0]]
            db.log_export(rels, folder)
            self.describe()
            if self.cfg.get("export_open"):
                os.startfile(folder)

        bg(lambda: export(sel, folder, o, lambda v: in_main(progress, v)), finished)

    def edit(self):
        sel = self.paths()
        if not sel:
            self.win.say("Выберите картинку (или несколько - правка применится ко всем)")
            return
        d = EditDialog(self, self.win, sel, on_saved=lambda t: self.done(t, undo=True))
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
        if len(sel) > 1:
            self.rename_many(sel)
            return
        if not sel:
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
            rename_file(sel[0], dst)
        except OSError as e:  # файл открыт в другой программе
            QMessageBox.warning(self, "Переименовать", "Не получилось: %s" % (e.strerror or e))
            return
        self.win.moved(sel[0], dst)
        self.win.push("Переименовано: " + name + ext, [("move", sel[0], dst)])
        self.done("Переименовано: " + name + ext, undo=True)

    def rename_many(self, sel):
        """Несколько картинок - одно имя с номерами по порядку плиток: «кот 01», «кот 02»..."""
        order = {p: i for i, p in enumerate(self.all_shown())}
        sel = sorted(sel, key=lambda p: order.get(p, 0))
        common = os.path.commonprefix([os.path.splitext(os.path.basename(p))[0] for p in sel]).rstrip(" _-")
        name, ok = QInputDialog.getText(
            self, "Переименовать: %d шт." % len(sel), "Общее имя (номера добавятся сами):", text=common
        )
        name = clean_name(name)
        if not ok or not name:
            return
        width = max(2, len(str(len(sel))))
        steps, bad = [], 0
        for i, p in enumerate(sel, 1):
            dst = unique(os.path.join(os.path.dirname(p), "%s %0*d%s" % (name, width, i, os.path.splitext(p)[1])))
            try:
                rename_file(p, dst)
            except OSError:
                bad += 1
                continue
            self.win.moved(p, dst)
            steps.append(("move", p, dst))
        text = "Переименовано: %d шт. («%s 01»...)" % (len(steps), name) + ("   не вышло: %d" % bad if bad else "")
        self.win.push(text, steps)
        self.done(text, undo=bool(steps))

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
                except OSError:  # занят другой программой - остальные переносим
                    bad += 1
                    continue
                self.win.moved(p, dst)
                steps.append(("move", p, dst))
        text = "Перенесено: %d шт. в «%s»" % (len(steps), os.path.relpath(dest, LIB))
        if bad:
            text += "   не вышло: %d (файл занят)" % bad
        self.win.push(text, steps)
        self.done(text, undo=bool(steps))

    def save_tags(self, text):
        sel = self.paths()
        if not sel:
            return
        rels = [os.path.relpath(p, LIB) for p in sel]
        new = {db.clean_tag(t) for t in text.split(",")} - {""}
        before = set(db.all_tags())
        was = {r: db.tags_of(r) for r in rels}
        if len(rels) == 1:
            if set(db.tags_of(rels[0])) == new:
                return
            db.set_tags(rels, new)
        else:
            common = set(db.tags_of(rels[0]))
            for r in rels[1:]:
                common &= set(db.tags_of(r))
            if common == new:
                return
            db.set_tags(rels, common - new, "remove")
            db.set_tags(rels, new - common, "add")
        steps = [["tags", r, was[r], now] for r in rels if (now := db.tags_of(r)) != was[r]]
        text = "Метки: %s" % (", ".join(sorted(new)) or "убраны")
        self.win.push(text, steps)  # Ctrl+Z вернёт метки как были
        self.win.say(text, undo=bool(steps))
        if set(db.all_tags()) != before:  # новая или исчезнувшая метка - дерево слева обновить
            self.tree.blockSignals(True)
            fill_tree(self.tree, planned=False, recent=True)
            self.tree.blockSignals(False)

    def save_note(self, text):
        sel = self.paths()
        if len(sel) == 1:
            rel = os.path.relpath(sel[0], LIB)
            before = db.note_of(rel)
            if before == text or (not before and not text.strip()):
                return
            db.set_note(rel, text)
            self.win.push_note(rel, before, text)

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
        lines = [
            "![{}]({})".format(os.path.splitext(os.path.basename(p))[0], p.replace("\\", "/").replace(" ", "%20"))
            for p in sel
        ]
        QApplication.clipboard().setText("\n".join(lines))
        self.win.say("Markdown скопирован: %d шт.  (путь абсолютный - поправьте под свой проект)" % len(sel))

    def copy_image(self):
        sel = self.paths()
        if not sel:
            return
        try:
            img = (
                QIcon(sel[0]).pixmap(512, 512).toImage()
                if sel[0].lower().endswith(".svg")
                else to_qimage(K.load(sel[0]))
            )
        except Exception as e:
            self.win.say(f"Не скопировалось: {e}")
            return
        md = QMimeData()
        md.setImageData(img)
        md.setUrls([QUrl.fromLocalFile(sel[0])])  # проводник и мессенджеры вставят файл, редакторы - картинку
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
            self.done(
                "Сделано копий (%s): %d" % (name, made)
                + ("   не вышло: %d" % bad if bad else "")
                + ("   Ctrl+Z - убрать" if made else "")
            )

        bg(lambda: copy_files(sel, fmt, lambda v: in_main(progress, v)), finished)

    def trash(self):
        """Без вопроса «точно?»: всё возвращается кнопкой «Отменить» в пузыре или Ctrl+Z."""
        sel = self.paths()
        if not sel:
            return
        n, steps = to_trash(sel)
        text = "В корзине: %d шт." % n
        self.win.push(text, steps)
        self.done(text, undo=bool(steps))
