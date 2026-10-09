"""Вкладка «Unreal»: скачанные ассеты для Unreal Engine (текстуры, HDRI, модели, IES) и их загрузка.
Плитка тянется прямо в Content Browser Unreal - уходят нужные файлы ассета."""

import os
import shutil
import threading
import time

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import imaging as K
from library import unreal as U
from library.unreal_extra import added
from ui.common import ROLE, THUMB, bg, human, in_main, log_error, reveal
from ui.thumbnails import lib_icon, swatch, thumb
from ui.unreal_catalog import CatalogDialog
from ui.unreal_nav import ALL, FAV, HOME_PREFIX, KIND_LOOK, SET, SETS, THEME_ICON, Nav, kind_color, theme_label
from ui.unreal_tiles import ASSET, CARD, CardList, card_of
from ui.viewer3d import CAN_VIEW, MiniView, Viewer3D, studio_probe
from ui.widgets import PicView, key

SHORT = {"tex": "Текстура", "hdri": "HDRI", "model": "Модель", "ies": "IES"}


def drag_files(a):
    """Что уходит в Unreal при перетаскивании: главные файлы ассета (карты, .hdr, .fbx, .ies)."""
    out = [os.path.join(a["dir"], *m.split("/")) for m in a.get("main", [])]
    return [p for p in out if os.path.exists(p)]


class UnrealTab(QWidget):
    items_loaded = pyqtSignal()  # список ассетов прочитан (полоса ассетов в поиске библиотеки ждёт его)

    def __init__(self, win):
        super().__init__()
        self.win, self.cfg = win, win.cfg
        self.items, self.loaded, self.loading, self.again = [], False, False, False
        self.side = max(96, min(THUMB, self.cfg.get("ue_thumb", 160)))

        # «Новое» - скачанное после прошлого открытия окна (метка времени пишется с настройками)
        self.since = self.cfg.get("ue_last_visit", 0)
        self.cfg["ue_last_visit"] = time.time()
        self.nav = Nav(self.cfg)
        self.nav.since = self.since
        self.nav.changed.connect(lambda: (self.leave_special(quiet=True), self.show_assets()))
        self.q = QLineEdit(placeholderText="Поиск по имени и меткам: brick, ржавчина, wood...", objectName="search")
        self.q.setClearButtonEnabled(True)
        self.q.addAction(lib_icon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self.qt = QTimer(self, singleShot=True, interval=180)
        self.qt.timeout.connect(self.show_assets)
        self.q.textChanged.connect(lambda *_: (self.leave_special(quiet=True), self.qt.start()))
        self.sem_btn = QPushButton(lib_icon("crystal-ball-stand"), "", objectName="tool", checkable=True)
        self.sem_btn.setToolTip("Поиск по смыслу: «деревянный стул», «ржавый металл», «закат над морем»")
        self.sem_btn.setChecked(bool(self.cfg.get("ue_semantic", True)))
        self.sem_btn.toggled.connect(self.toggle_sem)
        self.sem, self.sem_busy = None, False
        try:
            from library import unreal_sem

            if unreal_sem.available():
                self.sem = unreal_sem.AssetSem()
        except Exception as e:
            log_error("unreal_sem: %r" % e)
        self.sem_btn.setVisible(self.sem is not None)
        if self.sem is not None and self.sem_btn.isChecked():
            self.q.setPlaceholderText("Поиск по смыслу: деревянный стул, ржавый металл, закат...")
        scene = QPushButton(lib_icon("sparkles"), "Подборка по описанию...", objectName="ghost")
        scene.setToolTip("ИИ соберёт комнату из скачанного: «уютная спальня в скандинавском стиле»")
        scene.clicked.connect(self.scene)
        self.scene_btn = scene
        cat = QPushButton(lib_icon("globe"), "Каталог...", objectName="ghost")
        cat.setToolTip("Весь каталог Poly Haven с картинками: отметить нужное и скачать")
        cat.clicked.connect(self.catalog)
        get = QPushButton(lib_icon("download"), "Скачать ещё...", objectName="primary")
        get.setToolTip("Бесплатные ассеты CC0 с Poly Haven и ambientCG: вид, тема, сколько")
        get.clicked.connect(self.download)
        folder = QPushButton(lib_icon("folder"), "", objectName="tool")
        folder.setToolTip("Открыть папку _Unreal")
        folder.clicked.connect(
            lambda: (os.makedirs(U.ROOT, exist_ok=True), QDesktopServices.openUrl(QUrl.fromLocalFile(U.ROOT)))
        )
        self.sort = QComboBox()
        for t, v in (
            ("По видам и темам", "kind"),
            ("По имени", "name"),
            ("Сначала новые", "new"),
            ("Сначала лёгкие", "light"),
            ("Сначала тяжёлые", "heavy"),
        ):
            self.sort.addItem(t, v)
        self.sort.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.sort.setCurrentIndex(max(0, self.sort.findData(self.cfg.get("ue_sort", "kind"))))
        self.sort.currentIndexChanged.connect(self.show_assets)
        self.slider = QSlider(Qt.Orientation.Horizontal, minimum=96, maximum=THUMB, singleStep=16, pageStep=32)
        self.slider.setFixedWidth(80)
        self.slider.setValue(self.side)
        self.slider.setToolTip("Размер плиток (Ctrl+колесо)")
        self.slider.valueChanged.connect(self.resize_tiles)
        self.poly = QComboBox()
        for t, v in (
            ("Полигоны: любые", 0),
            ("до 5k - игра, много копий", 5000),
            ("до 20k", 20000),
            ("до 100k", 100000),
        ):
            self.poly.addItem(lib_icon("dice_3D"), t, v)
        self.poly.setToolTip("Только лёгкие модели: чем меньше полигонов, тем быстрее сцена в Unreal")
        self.poly.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.poly.currentIndexChanged.connect(self.show_assets)
        self.color = QComboBox()
        self.color.addItem(lib_icon("color-palette"), "Любой цвет", "")
        for code, name, hexv in K.COLORS:
            self.color.addItem(swatch(hexv), name, code)
        self.color.setToolTip("Только ассеты, где заметен этот цвет")
        self.color.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.color.currentIndexChanged.connect(self.show_assets)
        self.colors = {}
        doc = QPushButton(lib_icon("first-aid-kit"), "", objectName="tool")
        doc.setToolTip("Проверить ассеты: битые FBX, пропавшие файлы, недокачанные папки")
        doc.clicked.connect(self.check_assets)
        self.like, self.problems = None, None  # особые списки: «похожие на», «проблемные»
        self.title = QLabel(objectName="big")
        self.info = QLabel(objectName="dim")
        self.room_btn = QPushButton(lib_icon("house"), "Комната", objectName="flat")
        self.room_btn.setToolTip("Расставить мебель подборки в комнате: пол и стены из текстур, свет из HDRI")
        self.room_btn.clicked.connect(self.room_from_set)
        self.room_btn.hide()
        self.back_btn = QPushButton(lib_icon("arrowLeft"), "Назад", objectName="flat")
        self.back_btn.clicked.connect(self.leave_special)
        self.back_btn.hide()
        self.list = CardList(self.side, lambda its: [p for it in its for p in drag_files(it.data(ASSET))])
        self.list.zoom.connect(lambda d: self.slider.setValue(self.side + 16 * d))
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.menu)
        self.list.itemSelectionChanged.connect(self.describe)
        self.list.itemDoubleClicked.connect(lambda it: self.view3d(it.data(ASSET)))
        self.viewer = None
        self.list.empty = "Здесь пусто - нажмите «Скачать ещё...»"
        self.list.empty_icon = "mascot:С карточками"

        bar = QHBoxLayout()
        bar.addWidget(self.q, 1)
        bar.addWidget(self.sem_btn)
        bar.addWidget(self.slider)
        bar.addWidget(doc)
        bar.addWidget(scene)
        bar.addWidget(cat)
        bar.addWidget(get)
        bar.addWidget(folder)
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addLayout(bar)
        th = QHBoxLayout()
        th.addWidget(self.back_btn)
        th.addWidget(self.title, 1)
        th.addWidget(self.room_btn)
        th.addWidget(self.info)
        th.addWidget(self.sort)
        th.addWidget(self.poly)
        th.addWidget(self.color)
        mv.addLayout(th)
        mv.addWidget(self.list, 1)

        # панель справа
        side = QWidget(objectName="panel")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 12, 12, 12)
        self.pic = PicView("Выберите ассет")
        self.mini = MiniView() if self.cfg.get("ue_live", True) else None
        if self.mini is not None:
            self.mini.hide()
        self.live = QPushButton(lib_icon("dice_3D"), "", objectName="tool", checkable=True)
        self.live.setToolTip("Живой 3D здесь, в панели: модель вращается, тянуть мышью - поворот")
        self.live.setChecked(self.mini is not None)
        self.live.toggled.connect(self.toggle_live)
        self.mini_t = QTimer(self, singleShot=True, interval=300)  # не грузить модель на каждый щелчок
        self.mini_t.timeout.connect(self.update_mini)
        self.name = QLabel(objectName="head", wordWrap=True)
        self.meta = QLabel(objectName="dim", wordWrap=True)
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.files = QLabel(objectName="dim", wordWrap=True)
        self.files.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.note = QLineEdit(placeholderText="Заметка: где использую, что поменять...")
        self.note.setToolTip("Своя заметка к ассету - по ней тоже ищется")
        self.note.editingFinished.connect(self.save_note)
        how_lbl = QLabel("КАК В UNREAL", objectName="faint")
        self.how = QLabel(wordWrap=True)
        self.how.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        g = QGridLayout()
        self.btns = []
        for i, (text, icon, fn, tip) in enumerate(
            (
                ("Показать файлы", "folder", self.open_dir, "Папка ассета в проводнике"),
                ("Копировать пути", "clipboard", self.copy_paths, "Пути главных файлов - для окна импорта Unreal"),
                ("Страница", "globe", self.open_page, "Страница ассета на сайте источника"),
                (
                    "Импорт в Unreal...",
                    "export",
                    self.import_ue,
                    "Скопировать в проект и написать скрипт импорта: настройки текстур и готовый материал",
                ),
            )
        ):
            b = QPushButton(lib_icon(icon), text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
            self.btns.append(b)
        self.star = QPushButton(lib_icon("star"), "", objectName="tool", checkable=True)
        self.star.setToolTip("В избранное (Ctrl+D)")
        self.star.clicked.connect(self.toggle_fav)
        self.look = QPushButton(lib_icon("dice_3D"), "Смотреть в 3D", objectName="primary")
        self.look.setToolTip(
            "Модель - вращать и приближать, текстура - на шаре со светом, HDRI - панорама 360 (двойной щелчок)"
        )
        self.look.clicked.connect(lambda: self.current() and self.view3d(self.current()[0]))
        hint = QLabel("Плитку можно перетащить прямо в Content Browser", objectName="faint", wordWrap=True)
        sv.addWidget(self.pic, 1)
        if self.mini is not None:
            sv.addWidget(self.mini, 1)
        nh = QHBoxLayout()
        nh.addWidget(self.name, 1)
        nh.addWidget(self.live, 0, Qt.AlignmentFlag.AlignTop)
        nh.addWidget(self.star, 0, Qt.AlignmentFlag.AlignTop)
        sv.addLayout(nh)
        sv.addWidget(self.meta)
        sv.addWidget(self.files)
        sv.addWidget(self.note)
        sv.addWidget(how_lbl)
        sv.addWidget(self.how)
        sv.addWidget(self.look)
        sv.addLayout(g)
        sv.addWidget(hint)

        split = QSplitter()
        split.addWidget(self.nav)
        split.addWidget(mid)
        split.addWidget(side)
        split.setStretchFactor(1, 1)
        split.setSizes([270, 680, 330])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 6)
        lay.addWidget(split)
        self.dl_lbl = QPushButton(objectName="flat")
        self.dl_lbl.setToolTip("Загрузка ассетов Unreal - открыть окно загрузки")
        self.dl_lbl.clicked.connect(self.show_downloads)
        self.dl_lbl.hide()
        win.statusBar().addPermanentWidget(self.dl_lbl)
        key("Ctrl+F", self, lambda: (self.q.setFocus(), self.q.selectAll()))
        key("Ctrl+D", self, self.toggle_fav)
        key("Delete", self.list, self.trash)
        key("Return", self.list, lambda: self.current() and self.view3d(self.current()[0]))
        self.describe()

    # ------------------------------------------------------------ данные
    def refresh(self):
        if self.loading:  # чтение уже идёт - перечитать ещё раз после него (могло скачаться новое)
            self.again = True
            return
        self.loading, self.again = True, False

        def done(res):
            self.loading = False
            if self.again:
                QTimer.singleShot(0, self.refresh)
            if isinstance(res, Exception):
                log_error("unreal: %r" % res)
                res = []
            self.items, self.loaded = res, True
            self.items_loaded.emit()
            self.nav.set_items(res, self.favs())
            self.show_assets()
            self.build_sem()
            if self.sem is not None and not self.sem_busy:
                self.ai_sections()  # векторы уже посчитаны - разложить «Мелочи» сразу
            self.draw_previews()
            self.build_colors()

        bg(U.assets, done)

    def draw_previews(self):
        """Моделям без картинки (Quaternius) превью рисуется 3D-сценой - по одной, окно не замирает."""
        from ui.render_previews import PreviewRenderer, needs_preview

        todo = [a for a in self.items if needs_preview(a)]
        if not todo or getattr(self, "drawing", False):
            return
        self.drawing = True
        if getattr(self, "renderer", None) is None:
            self.renderer = PreviewRenderer(self)
            self.renderer.done.connect(self.previews_done)
        self.info.setText(f"рисую превью моделей: {len(todo)}")
        self.renderer.run(todo, studio_probe(self.items, self.cfg))

    def previews_done(self, n):
        self.drawing = False
        if n:
            self.win.say(f"Нарисованы превью моделей: {n}")
            self.refresh()

    # ------------------------------------------------------------ поиск по смыслу
    def toggle_sem(self, on):
        self.cfg["ue_semantic"] = on
        self.q.setPlaceholderText(
            "Поиск по смыслу: деревянный стул, ржавый металл, закат..."
            if on and self.sem
            else "Поиск по имени и меткам: brick, ржавчина, wood..."
        )
        self.show_assets()

    def build_sem(self):
        if self.sem is None or self.sem_busy or not self.sem.missing(self.items):
            return
        self.sem_busy = True
        items = list(self.items)

        def prog(v):
            if not self.q.text().strip():
                self.info.setText(f"готовлю поиск по смыслу: {v[0]} из {v[1]}")

        def done(_res):
            self.sem_busy = False
            if isinstance(_res, Exception):
                log_error("unreal_sem build: %r" % _res)
            self.show_assets()
            self.ai_sections()

        bg(lambda: self.sem.build(items, lambda d, t: in_main(prog, (d, t))), done)

    def ai_sections(self):
        """Модели «Дома», которым по имени и меткам раздел не нашёлся («Мелочи»): раздел по превью и имени
        (CLIP) - только где ИИ уверен. Помечаются section_ai, в подсказке плитки видно."""
        if self.sem is None:
            return
        other = [
            a
            for a in self.items
            if a.get("kind") == "model"
            and a.get("theme", "").startswith(HOME_PREFIX)
            and a.get("section") == U.HOME_OTHER
        ]
        if not other:
            return
        from library import unreal_sem

        def done(got):
            if isinstance(got, Exception):
                log_error("unreal ai sections: %r" % got)
                return
            for a in other:
                if a["dir"] in got:
                    a["section"], a["section_ai"] = got[a["dir"]], True
            if got:
                self.nav.set_items(self.items, self.favs())
                self.show_assets()

        bg(lambda: unreal_sem.classify(self.sem, other), done)

    def chosen(self):
        if self.problems is not None:
            return [a for a, _why in self.problems if a is not None]
        if self.like is not None and self.sem is not None:
            return [a for a, _s in self.sem.similar(self.like, self.items)]
        out = self.filters(self.nav.chosen())
        words = self.q.text().lower().split()
        if words and self.sem is not None and self.sem_btn.isChecked():
            ranked = self.sem.rank(self.q.text(), out)
            if ranked:  # по смыслу - в порядке похожести, без сортировки
                return [a for a, _s in ranked]
        if words:

            def hay(a):
                return " ".join(
                    [
                        a.get("name", ""),
                        a.get("id", ""),
                        a.get("theme", ""),
                        a.get("source", ""),
                        U.KINDS.get(a.get("kind"), ("", ""))[1],
                        *a.get("tags", []),
                        *a.get("categories", []),
                        a.get("description", ""),
                        self.cfg.get("ue_notes", {}).get(a.get("id"), ""),
                    ]
                ).lower()

            out = [a for a in out if all(w in hay(a) for w in words)]
        order = list(U.KINDS)
        how = self.sort.currentData()
        self.cfg["ue_sort"] = how
        if how == "name":
            return sorted(out, key=lambda a: a.get("name", "").lower())
        if how == "new":
            return sorted(out, key=lambda a: -added(a))
        if how in ("light", "heavy"):
            return sorted(out, key=lambda a: a.get("size", 0), reverse=how == "heavy")
        return sorted(
            out,
            key=lambda a: (
                order.index(a["kind"]) if a.get("kind") in order else 9,
                a.get("theme", ""),
                a.get("name", "").lower(),
            ),
        )

    def filters(self, lst):
        """Полигоны (только модели) и цвет превью."""
        poly = self.poly.currentData()
        if poly:
            lst = [a for a in lst if a.get("kind") == "model" and (a.get("polycount") or 0) <= poly]
        code = self.color.currentData()
        if code:
            from library.unreal_extra import color_of

            lst = [a for a in lst if code in color_of(a, self.colors)]
        return lst

    def build_colors(self):
        from library import unreal_extra as X

        items = list(self.items)

        def done(res):
            if not isinstance(res, Exception):
                self.colors = res
                if self.color.currentData():
                    self.show_assets()

        bg(lambda: X.build_colors(items), done)

    # ------------------------------------------------------------ особые списки
    def leave_special(self, quiet=False):
        if self.like is None and self.problems is None:
            return
        self.like = self.problems = None
        self.back_btn.hide()
        if not quiet:
            self.show_assets()

    def show_similar(self, a):
        if self.sem is None:
            self.win.say("Похожие ищутся моделью смысла - она не загружена (get_models.py clip)")
            return
        self.like, self.problems = a, None
        self.back_btn.show()
        self.show_assets()

    def check_assets(self):
        from library import unreal_extra as X

        self.info.setText("проверяю ассеты...")

        def done(res):
            if isinstance(res, Exception):
                self.win.say(f"Проверка не удалась: {res}")
                return
            gone = [why for a, why in res if a is None]
            bad = [(a, why) for a, why in res if a is not None]
            if not bad:
                self.win.say("Все ассеты в порядке" + (f", убрано недокачанного: {len(gone)}" if gone else ""))
                self.leave_special()
                return
            self.problems, self.like = bad, None
            self.back_btn.show()
            self.show_assets()
            self.win.say(f"Проблемных ассетов: {len(bad)} - они на экране; правый щелчок: перекачать или в корзину")

        bg(lambda: X.check(self.items), done)

    def show_assets(self):
        lst = self.chosen()
        in_set = self.nav.kind == SETS and self.like is None and self.problems is None
        self.room_btn.setVisible(in_set and any(a.get("kind") == "model" for a in lst))
        self.title.setText(
            self.nav.title()
            if self.like is None and self.problems is None
            else f"Похожие на «{self.like.get('name', '')}»"
            if self.like is not None
            else f"Проблемные ассеты: {len(lst)}"
        )
        self.title.setStyleSheet(f"color: {kind_color(self.nav.kind)}")
        size = sum(a.get("size", 0) for a in lst)
        self.info.setText(f"{len(lst)} шт., {human(size)}")
        self.list.clear()
        self.list.reset_anim()
        self.list.one_kind = len({a.get("kind") for a in lst}) == 1
        favs = self.favs()
        todo = []
        for i, a in enumerate(lst):
            prev = os.path.join(a["dir"], "preview.webp")
            li = QListWidgetItem(a.get("name", ""))
            li.setData(ROLE, prev)
            li.setData(ASSET, a)
            res = (a.get("res") or "").upper()
            sub = theme_label(a.get("theme", ""))
            if a.get("section"):  # дом: раздел и откуда модель
                low = a.get("source") in ("Kenney", "Quaternius")
                sub = a["section"] + (f", {a['source']}" if low else "")
            if a.get("polycount"):
                sub += f", {a['polycount'] // 1000 or 1}k полиг."
            if self.problems is not None:
                sub = next((why for x, why in self.problems if x is a), sub)
            li.setData(
                CARD, card_of(a.get("kind"), a.get("name", ""), sub, res, human(a.get("size", 0)), a.get("id") in favs)
            )
            ai = "\nРаздел подобран ИИ по картинке и имени" if a.get("section_ai") else ""
            li.setToolTip(f"{a.get('name', '')}\n{a['dir']}{ai}")
            self.list.addItem(li)
            if os.path.exists(prev):
                todo.append((i, prev))
        self.list.load_tiles(todo, THUMB, None)
        self.describe()

        # ------------------------------------------------------------ избранное

    def favs(self):
        return set(self.cfg.get("ue_fav", []))

    def toggle_fav(self):
        cur = self.current()
        if not cur:
            return
        favs = self.favs()
        add = not all(a.get("id") in favs for a in cur)
        for a in cur:
            (favs.add if add else favs.discard)(a.get("id"))
        self.cfg["ue_fav"] = sorted(favs)
        for it in self.list.selectedItems():
            d = dict(it.data(CARD))
            d["fav"] = add
            it.setData(CARD, d)
        self.nav.set_items(self.items, favs)
        if self.nav.kind == FAV:
            self.show_assets()
        self.describe()
        self.win.say(("В избранном: " if add else "Убрано из избранного: ") + str(len(cur)))

    def resize_tiles(self, side):
        self.side = max(96, min(THUMB, side))
        self.cfg["ue_thumb"] = self.side
        self.list.set_base(self.side)

    # ------------------------------------------------------------ панель
    def current(self):
        sel = self.list.selectedItems()
        return [it.data(ASSET) for it in sel]

    def view3d(self, a):
        """Двойной щелчок и «Смотреть в 3D». IES в 3D не показать - тогда файл в проводнике."""
        if a.get("kind") not in CAN_VIEW:
            files = drag_files(a)
            reveal(files[0] if files else a["dir"])
            return
        if self.viewer is None:
            self.viewer = Viewer3D(self)
        if not self.viewer.show_asset(a):
            self.win.say("3D-просмотр не запустился - подробности в _tools/_errors.log")

    def toggle_live(self, on):
        self.cfg["ue_live"] = on
        if on and self.mini is None:
            self.mini = MiniView()
            self.pic.parentWidget().layout().insertWidget(1, self.mini, 1)
        self.describe()

    def update_mini(self):
        cur = self.current()
        if self.mini is None or len(cur) != 1:
            return
        self.mini.show_asset(cur[0], studio_probe(self.items, self.cfg))

    def save_note(self):
        cur = self.current()
        if len(cur) != 1:
            return
        notes = self.cfg.setdefault("ue_notes", {})
        text = self.note.text().strip()
        if text:
            notes[cur[0]["id"]] = text
        else:
            notes.pop(cur[0]["id"], None)

    def describe(self):
        cur = self.current()
        self.note.setEnabled(len(cur) == 1)
        self.note.setText(self.cfg.get("ue_notes", {}).get(cur[0]["id"], "") if len(cur) == 1 else "")
        live = (
            self.mini is not None
            and self.live.isChecked()
            and len(cur) == 1
            and cur[0].get("kind") in CAN_VIEW
            and self.isVisible()
        )
        if self.mini is not None:
            self.mini.setVisible(live)
            self.mini.pause(not live)
        self.pic.setVisible(not live)
        if live:
            self.mini_t.start()
        for b in self.btns:
            b.setEnabled(bool(cur))
        self.look.setEnabled(len(cur) == 1 and cur[0].get("kind") in CAN_VIEW)
        self.star.setEnabled(bool(cur))
        on = bool(cur) and all(a.get("id") in self.favs() for a in cur)
        self.star.setToolTip("Убрать из избранного (Ctrl+D)" if on else "В избранное (Ctrl+D)")
        self.star.setChecked(on)
        if not cur:
            self.pic.set_pixmap(None)
            self.name.setText("")
            self.meta.setText(
                "Ассеты для Unreal Engine: PBR-текстуры, небо HDRI, модели, профили света.\n"
                "Источники - Poly Haven и ambientCG, лицензия CC0: можно в любые проекты."
            )
            self.files.setText("")
            self.how.setText("")
            return
        if len(cur) > 1:
            self.pic.set_pixmap(None)
            self.name.setText(f"Выбрано: {len(cur)}")
            self.meta.setText(human(sum(a.get("size", 0) for a in cur)))
            self.files.setText("")
            self.how.setText("Перетащите все разом в Content Browser.")
            return
        a = cur[0]
        prev = os.path.join(a["dir"], "preview.webp")
        self.pic.set_pixmap(thumb(prev, 512) if os.path.exists(prev) else QPixmap())
        self.name.setText(a.get("name", ""))
        lines = [f"{U.KINDS.get(a.get('kind'), ('', '?'))[1]} / {a.get('theme', '')}"]
        if a.get("res"):
            lines.append(f"Разрешение {a['res'].upper()}, {human(a.get('size', 0))}")
        if a.get("polycount"):
            lines.append(f"Полигонов: {a['polycount']:,}".replace(",", " "))
        if a.get("dimensions_mm"):
            lines.append("Размер: " + " x ".join(f"{x / 10:g}" for x in a["dimensions_mm"]) + " см")
        if a.get("description"):
            lines.append(a["description"])
        src = a.get("source", "")
        authors = [x for x in a.get("authors", []) if x != src]
        if authors:
            src += ", " + ", ".join(authors)
        lines.append(src)
        if a.get("tags"):
            lines.append("Метки: " + ", ".join(a["tags"][:10]))
        used = self.cfg.get("ue_used", {}).get(a.get("id"), [])
        if used:  # куда ассет уже уходил: копия, импорт, пакет
            lines.append("Использовано в: " + "; ".join(os.path.basename(x.rstrip("/\\")) or x for x in used[-3:]))
        self.meta.setText("\n".join(lines))
        self.files.setText("Файлы: " + ", ".join(a.get("main", [])))
        self.how.setText(U.howto(a))

    def open_dir(self):
        for a in self.current()[:5]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(a["dir"]))

    def copy_paths(self):
        paths = [p for a in self.current() for p in drag_files(a)]
        QApplication.clipboard().setText("\n".join(paths))
        self.win.say(f"Скопировано путей: {len(paths)}")

    def open_page(self):
        for a in self.current()[:5]:
            if a.get("url"):
                QDesktopServices.openUrl(QUrl(a["url"]))

    def to_project(self):
        self.copy_to_project(self.current())

    def copy_to_project(self, assets):
        if not assets:
            return
        start = self.cfg.get("ue_project", "")
        dst = QFileDialog.getExistingDirectory(self, "Папка в проекте Unreal (например, Content/Assets)", start)
        if not dst:
            return
        self.cfg["ue_project"] = dst
        from library.unreal_pack import remember_use

        remember_use(self.cfg, assets, dst)
        for a in assets:
            shutil.copytree(
                a["dir"],
                os.path.join(dst, os.path.basename(a["dir"])),
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("asset.json", "preview.webp"),
            )
        self.win.say(f"Скопировано в проект: {len(assets)}. В Unreal - Import или перетащить файлы в Content Browser")

    def menu(self, pos):
        if not self.current():
            return
        m = QMenu(self)
        sel = self.current()
        a = self.current()[0]
        if a.get("kind") in CAN_VIEW:
            m.addAction(lib_icon("dice_3D"), "Смотреть в 3D", lambda: self.view3d(a))
        on = all(x.get("id") in self.favs() for x in self.current())
        m.addAction(lib_icon("star"), "Убрать из избранного" if on else "В избранное", self.toggle_fav)
        if len(sel) == 1 and self.sem is not None:
            m.addAction(lib_icon("crystal-ball-stand"), "Похожие по виду", lambda: self.show_similar(sel[0]))
        if len(sel) == 1 and sel[0].get("kind") == "hdri":
            m.addAction(lib_icon("sun"), "Освещать этим HDRI в 3D-просмотре", lambda: self.use_light(sel[0]))
        sets = m.addMenu(lib_icon("bookmark"), "В подборку")
        for name in sorted(self.nav.sets(), key=str.lower):
            sets.addAction(name, lambda n=name: self.add_to_set(n, sel))
        sets.addSeparator()
        sets.addAction(lib_icon("plus"), "Новая подборка...", lambda: self.add_to_set(None, sel))
        if self.nav.kind == SETS and self.nav.theme and self.nav.theme.startswith(SET):
            m.addAction(
                lib_icon("minus"),
                "Убрать из этой подборки",
                lambda: self.remove_from_set(self.nav.theme[len(SET) :], sel),
            )
        m.addAction(lib_icon("export"), "Импорт в Unreal (скрипт с материалами)...", self.import_ue)
        m.addAction(
            lib_icon("zip-archive"), "Пакет для проекта (файлы, авторы, скрипт)...", lambda: self.pack_assets(sel)
        )
        if any(x.get("kind") == "model" for x in sel):
            m.addAction(lib_icon("house"), "Собрать комнату из выбранного", lambda: self.room(sel, "Выбранное"))
        m.addSeparator()
        m.addAction(lib_icon("folder"), "Показать файлы", self.open_dir)
        m.addAction(lib_icon("clipboard"), "Копировать пути", self.copy_paths)
        m.addAction(lib_icon("globe"), "Страница ассета", self.open_page)
        m.addAction(lib_icon("export"), "Скопировать в проект Unreal...", self.to_project)
        sel = self.current()
        if any(U.can_refetch(x) for x in sel):
            sub = m.addMenu(lib_icon("download"), "Перекачать в разрешении")
            for r in U.RES:
                sub.addAction(r.upper(), lambda r=r: self.refetch(r))
        m.addSeparator()
        m.addAction(lib_icon("cross-circle"), "В корзину (Del)", self.trash)
        m.exec(self.list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ подборки, свет, импорт
    def add_to_set(self, name, assets):
        from PyQt6.QtWidgets import QInputDialog

        if name is None:
            name, ok = QInputDialog.getText(self, "Новая подборка", "Название (например, «Моя спальня»):")
            name = name.strip()
            if not ok or not name:
                return
        lst = self.nav.sets().setdefault(name, [])
        n = 0
        for a in assets:
            if a.get("id") not in lst:
                lst.append(a.get("id"))
                n += 1
        self.nav.set_items(self.items, self.favs())
        self.win.say(f"В подборке «{name}»: +{n}, всего {len(lst)}")

    def remove_from_set(self, name, assets):
        ids = {a.get("id") for a in assets}
        sets = self.nav.sets()
        sets[name] = [i for i in sets.get(name, []) if i not in ids]
        if not sets[name]:
            del sets[name]
            self.nav.theme = None
        self.nav.set_items(self.items, self.favs())
        self.show_assets()

    def use_light(self, a):
        path = os.path.join(a["dir"], a["main"][0])
        self.cfg["ue_env"] = path
        if self.viewer is not None:
            self.viewer.env.clear()  # список неба перечитается с новым выбором
        if self.mini is not None:
            self.mini.shown = None
            self.describe()
        self.win.say(f"3D-просмотр освещается небом «{a.get('name', '')}»")

    def pack_assets(self, assets, title=None):
        """Пакет для проекта: файлы, import_to_unreal.py, CREDITS.md и manifest.json одной папкой (или zip)."""
        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        from library import unreal_pack

        if not assets:
            return
        name, ok = QInputDialog.getText(
            self, "Пакет для проекта", "Название пакета (станет именем папки):", text=title or assets[0].get("name", "")
        )
        if not ok or not name.strip():
            return
        dst = QFileDialog.getExistingDirectory(self, "Куда положить пакет", self.cfg.get("ue_pack_dir", ""))
        if not dst:
            return
        self.cfg["ue_pack_dir"] = dst
        zip_it = (
            QMessageBox.question(self, "Пакет для проекта", "Упаковать ещё и в zip-архив (удобно передать)?")
            == QMessageBox.StandardButton.Yes
        )

        def done(res):
            if isinstance(res, Exception):
                self.win.say(f"Пакет не собран: {res}")
                return
            unreal_pack.remember_use(self.cfg, assets, dst)
            reveal(res)
            self.win.say(f"Пакет готов: {os.path.basename(res)} - ассетов {len(assets)}, авторы в CREDITS.md")
            self.describe()

        bg(lambda: unreal_pack.pack(assets, dst, name.strip(), zip_it), done)

    def import_ue(self):
        self.import_assets(self.current())

    def import_assets(self, cur):
        """Копия файлов в проект + import_to_unreal.py: настройки текстур и материалы делает сам Unreal."""
        from library import unreal_import

        if not cur:
            return
        start = self.cfg.get("ue_import_dir", self.cfg.get("ue_project", ""))
        dst = QFileDialog.getExistingDirectory(
            self, "Куда положить файлы для импорта (лучше папка рядом с проектом, не внутри Content)", start
        )
        if not dst:
            return
        self.cfg["ue_import_dir"] = dst
        from library.unreal_pack import remember_use

        remember_use(self.cfg, cur, dst)

        def done(res):
            if isinstance(res, Exception):
                self.win.say(f"Импорт не подготовлен: {res}")
                return
            cmd = f'py "{res.replace(chr(92), "/")}"'
            QApplication.clipboard().setText(cmd)
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.information(
                self,
                "Импорт в Unreal",
                f"Файлы скопированы, скрипт: {res}\n\nВ Unreal: Tools -> Execute Python Script и выбрать этот файл.\n"
                f"Или в Output Log (режим Cmd) вставить команду - она уже в буфере обмена:\n{cmd}\n\n"
                "Ассеты появятся в Content/Library, у текстур - готовый материал M_<имя>. "
                "Нужен включённый плагин Python Editor Script Plugin.",
            )

        bg(lambda: unreal_import.export(cur, dst), done)

    # ------------------------------------------------------------ ход загрузок в строке состояния
    def set_progress(self, text):
        """text - ход загрузки (когда окно загрузки закрыто), None - загрузка кончилась."""
        if text:
            self.dl_lbl.setText("Unreal: " + text)
            self.dl_lbl.show()
        else:
            self.dl_lbl.hide()

    def go_to(self, a, query="", again=True):
        """Открыть вкладку на ассете: из полосы в поиске библиотеки и из общего поиска (Ctrl+P)."""
        self.win.tabs.setCurrentIndex(2)
        self.leave_special(quiet=True)
        self.q.setText(query)
        self.show_assets()
        for i in range(self.list.count()):
            if self.list.item(i).data(ASSET)["dir"] == a["dir"]:
                self.list.setCurrentRow(i)
                self.list.scrollToItem(self.list.item(i))
                return
        if again:  # ассет скрыт выбранным видом или темой - показать всё и найти ещё раз
            self.nav.kind, self.nav.theme = ALL, None
            self.nav.set_items(self.items, self.favs())
            self.go_to(a, "", again=False)

    def show_downloads(self):
        for d in (getattr(self, "get_dlg", None), getattr(self, "cat_dlg", None)):
            if d is not None and d.busy:
                d.show()
                d.raise_()
                return

    def room(self, assets, title="Комната"):
        from ui.room3d import RoomDialog

        models = [a for a in assets if a.get("kind") == "model"]
        if not models:
            self.win.say("В комнату ставятся модели - в выбранном их нет")
            return
        self.room_dlg = RoomDialog(self, assets, title)
        self.room_dlg.show()

    def room_from_set(self):
        theme = self.nav.theme or ""
        name = theme[len(SET) :] if theme.startswith(SET) else "Подборка"
        self.room(self.nav.chosen(), name)

    def trash(self):
        """Папки ассетов - в корзину Windows (вернуть можно оттуда)."""
        cur = self.current()
        if not cur:
            return
        from PyQt6.QtCore import QFile
        from PyQt6.QtWidgets import QMessageBox

        names = ", ".join(a.get("name", "") for a in cur[:4]) + (" ..." if len(cur) > 4 else "")
        if (
            QMessageBox.question(
                self,
                "В корзину",
                f"Убрать в корзину Windows: {names}?\nВсего {len(cur)}, {human(sum(a.get('size', 0) for a in cur))}.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        n = sum(1 for a in cur if QFile.moveToTrash(a["dir"])[0])
        self.win.say(f"В корзине: {n}" + ("" if n == len(cur) else f", не вышло: {len(cur) - n}"))
        self.refresh()

    def refetch(self, res):
        cur = [a for a in self.current() if U.can_refetch(a)]
        if not cur:
            return
        self.win.say(f"Перекачиваю в {res.upper()}: {len(cur)} шт. - ход в строке над плитками")

        def prog(v):
            self.info.setText(v)

        def work():
            ok, errs = 0, []
            for i, a in enumerate(cur):
                try:
                    U.refetch(
                        a,
                        res,
                        lambda f, t, i=i, a=a: in_main(prog, f"{a['name']} ({i + 1} из {len(cur)}): {int(f * 100)}%"),
                    )
                    ok += 1
                except Exception as e:
                    errs.append(f"{a['name']}: {e}")
            return ok, errs

        def done(r):
            if isinstance(r, Exception):
                self.win.say(f"Не вышло: {r}")
            else:
                self.win.say(
                    f"Перекачано в {res.upper()}: {r[0]}" + (f"; ошибки: {'; '.join(r[1][:2])}" if r[1] else "")
                )
            self.refresh()

        bg(work, done)

    def scene(self):
        from ui.scene_dialog import SceneDialog

        d = getattr(self, "scene_dlg", None)
        if d is None:
            d = self.scene_dlg = SceneDialog(self)
        d.show()
        d.raise_()
        d.q.setFocus()

    def catalog(self):
        d = getattr(self, "cat_dlg", None)
        if d is None:
            d = self.cat_dlg = CatalogDialog(self)
            d.downloaded.connect(self.refresh)
        d.show()
        d.raise_()
        d.activateWindow()

    def download(self):
        if getattr(self, "get_dlg", None) is not None and self.get_dlg.busy:
            self.get_dlg.show()  # загрузка ещё идёт - показать её ход
            self.get_dlg.raise_()
            return
        d = self.get_dlg = GetDialog(self)
        d.finished_ok.connect(self.refresh)
        if self.nav.kind in U.KINDS:
            d.kind.setCurrentIndex(max(0, d.kind.findData(self.nav.kind)))
        if self.nav.theme and not str(self.nav.theme).startswith("::"):
            d.theme.setCurrentIndex(max(0, d.theme.findData(self.nav.theme)))
        d.show()  # не модальное: окно можно закрыть, загрузка продолжится


class GetDialog(QDialog):
    """Скачать ещё: вид, тема (или все), сколько, разрешение. Работает в фоне, можно остановить."""

    finished_ok = pyqtSignal()

    def __init__(self, tab):
        super().__init__(tab)
        self.tab, self.cfg = tab, tab.cfg
        self.setWindowTitle("Скачать ассеты для Unreal")
        self.setMinimumWidth(460)
        self.stop, self.busy, self.errs = threading.Event(), False, []
        self.kind = QComboBox()
        for k, (_f, title, _t) in U.KINDS.items():
            self.kind.addItem(lib_icon(KIND_LOOK[k][1]), title, k)
        self.theme = QComboBox()
        self.theme.addItem(lib_icon("globe"), "Все темы", "все")
        for th in U.THEMES:
            self.theme.addItem(
                lib_icon(THEME_ICON.get(th, "folder")),
                ("Дом: " if th.startswith(HOME_PREFIX) else "") + theme_label(th),
                th,
            )
        self.count = QSpinBox(minimum=1, maximum=50, value=self.cfg.get("ue_count", 4))
        self.res = QComboBox()
        for r in U.RES:
            self.res.addItem(r.upper(), r)
        self.res.setCurrentIndex(self.res.findData(self.cfg.get("ue_res", "2k")))
        self.avail = QLabel(objectName="dim", wordWrap=True)
        self.bar = QProgressBar()
        self.bar.hide()
        self.status = QLabel(objectName="dim", wordWrap=True)
        self.go = QPushButton(lib_icon("download"), "Скачать", objectName="primary")
        self.go.clicked.connect(self.start)
        self.close_btn = QPushButton("Закрыть")
        self.close_btn.clicked.connect(self.close_or_stop)
        for w in (self.kind, self.theme, self.count, self.res):
            sig = w.valueChanged if isinstance(w, QSpinBox) else w.currentIndexChanged
            sig.connect(self.update_hint)

        g = QGridLayout()
        for i, (t, w) in enumerate(
            (("Что", self.kind), ("Тема", self.theme), ("Сколько на тему", self.count), ("Разрешение", self.res))
        ):
            g.addWidget(QLabel(t), i, 0)
            g.addWidget(w, i, 1)
        lic = QLabel(
            "Poly Haven и ambientCG - лицензия CC0: бесплатно, для любых проектов, "
            "указывать автора не нужно. IES-профили рисуются самой библиотекой.",
            objectName="faint",
            wordWrap=True,
        )
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(self.go)
        btns.addWidget(self.close_btn)
        v = QVBoxLayout(self)
        v.addLayout(g)
        v.addWidget(self.avail)
        v.addWidget(lic)
        v.addWidget(self.bar)
        v.addWidget(self.status)
        v.addLayout(btns)
        self.update_hint()

    def update_hint(self):
        k = self.kind.currentData()
        ies = k == "ies"
        for w in (self.theme, self.count, self.res):
            w.setEnabled(not ies)
        if ies:
            self.avail.setText("12 профилей: узкий луч, кольца, уличный фонарь, полосы... Повторно - перезапишутся.")
            return
        themes = list(U.THEMES) if self.theme.currentData() == "все" else [self.theme.currentData()]
        themes = [t for t in themes if U.THEMES[t].get(k)]
        n = self.count.value() * len(themes)
        mb = U.estimate(k, self.res.currentData()) * n
        if not themes:
            self.avail.setText("У этой темы нет такого вида - выберите другую.")
        else:
            self.avail.setText(f"До {n} шт., примерно {mb:.0f} МБ. Уже скачанные пропускаются.")
        self.go.setEnabled(bool(themes))

    def start(self):
        k, res, count = self.kind.currentData(), self.res.currentData(), self.count.value()
        self.cfg["ue_count"], self.cfg["ue_res"] = count, res
        themes = list(U.THEMES) if self.theme.currentData() == "все" else [self.theme.currentData()]
        themes = [t for t in themes if k == "ies" or U.THEMES[t].get(k)]
        if k == "ies":
            themes = themes[:1]
        self.busy = True
        self.stop.clear()
        self.go.setEnabled(False)
        self.close_btn.setText("Остановить")
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.show()
        got, errs = [], []
        self.errs = errs

        def prog(frac, text, i):
            in_main(self.show_prog, ((i + frac) / len(themes), text))

        def work():
            for i, th in enumerate(themes):
                if self.stop.is_set():
                    break
                got.extend(
                    U.get_many(
                        k,
                        th,
                        count,
                        res,
                        lambda f, t, i=i, th=th: prog(f, f"{th}: {t}", i),
                        self.stop,
                        log=lambda s: s.startswith("  !") and errs.append(s.strip()),
                    )
                )
            return got

        bg(work, self.done)

    def show_prog(self, val):
        frac, text = val
        self.tab.set_progress(f"{int(frac * 100)}% - {text}" if not self.isVisible() else None)
        if not self.isVisible():
            return
        self.bar.setValue(int(frac * 1000))
        self.status.setText(text)

    def done(self, res):
        self.busy = False
        self.tab.set_progress(None)
        self.close_btn.setText("Закрыть")
        self.go.setEnabled(True)
        if isinstance(res, Exception):
            text = f"Не вышло: {res}"
            log_error("unreal download: %r" % res)
        else:
            self.bar.setValue(1000)
            text = f"Готово: {len(res)} шт." + ("" if res else " Новых не нашлось - всё уже скачано или нет сети.")
            if self.errs:
                text += "\nНе скачалось: " + "; ".join(self.errs[:3])
        self.status.setText(text)
        if not self.isVisible():  # окно закрыли во время загрузки - сказать в главном окне
            self.tab.win.say("Ассеты Unreal: " + text.replace("\n", " "))
        self.finished_ok.emit()

    def close_or_stop(self):
        """Кнопка «Остановить» во время загрузки, «Закрыть» - после."""
        if self.busy:
            self.stop.set()
            self.status.setText("Останавливаю после текущего файла...")
        else:
            self.hide()

    def reject(self):
        """Esc и крестик закрывают всегда; загрузка, если идёт, продолжается в фоне. Окно только
        прячется (его держит вкладка), поэтому ответ фоновой задачи придёт в живой объект."""
        self.hide()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
