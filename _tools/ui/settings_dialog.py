"""Настройки окна (кнопка «Настройки» вверху, Ctrl+,): разделы слева, справа - карточки с тумблерами.

Каждый тумблер меняет то же, что и его двойник в окне (галочка во входящих, кнопка в 3D), - сразу.
Поиск сверху слева находит настройку в любом разделе. Разделы сменяются с плавным переездом."""

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QUrl, QVariantAnimation
from PyQt6.QtGui import QColor, QDesktopServices, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui import animations, theme
from ui.common import HERE
from ui.theme import C, font
from ui.thumbnails import lib_icon, mix
from ui.widgets import panel_head


# ---------------------------------------------------------------- элементы
class Switch(QAbstractButton):
    """Тумблер: ручка переезжает, дорожка наливается цветом акцента."""

    def __init__(self, on=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(bool(on))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)
        self.k = 1.0 if on else 0.0
        self.a = None
        self.toggled.connect(self._go)

    def _go(self, on):
        animations.stop(self.a)
        self.a = animations.anim(self, 200, self._set, self.k, 1.0 if on else 0.0)

    def _set(self, v):
        self.k = v
        self.update()

    def sizeHint(self):
        return QSize(44, 24)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        track = mix(QColor(C["bg3"]), QColor(C["acc"]), self.k)
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(QPen(mix(QColor(C["line2"]), QColor(C["acc"]), self.k), 1))
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.x() + 3 + (r.width() - d - 6) * self.k
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawEllipse(QRectF(x, r.y() + 4, d, d))  # тень ручки
        p.setBrush(QColor("#ffffff") if self.k > 0.5 else QColor(C["dim"]))
        p.drawEllipse(QRectF(x, r.y() + 3, d, d))
        p.end()


class Row(QFrame):
    """Карточка настройки: название, пояснение, справа - тумблер или кнопки."""

    def __init__(self, title, desc="", control=None, icon=None):
        super().__init__(objectName="setrow")
        self.words = (title + " " + desc).lower().replace("ё", "е")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 12, 10)
        h.setSpacing(12)
        if icon:
            ic = QLabel()
            ic.setPixmap(lib_icon(icon).pixmap(22, 22))
            ic.setFixedWidth(26)
            h.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title, wordWrap=True, objectName="rowtitle")
        col.addWidget(t)
        if desc:
            d = QLabel(desc, objectName="dim", wordWrap=True)
            col.addWidget(d)
        h.addLayout(col, 1)
        if control is not None:
            h.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)

    def flash(self):
        """Найденная поиском - коротко подсвечивается акцентом."""
        acc = QColor(C["acc"])

        def step(v):
            a = int(110 * math.sin(math.pi * v))
            self.setStyleSheet(
                f"QFrame#setrow{{border:1px solid rgba({acc.red()},{acc.green()},{acc.blue()},{max(40, a + 40)})}}"
            )

        animations.anim(self, 900, step, done=lambda: self.setStyleSheet(""))


class ThemeCard(QAbstractButton):
    """Тема - миниатюрой окна в её цветах: шапка, дерево слева, плитки."""

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.name, self.pal = theme.THEMES[key]
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(190, 132)
        self.hv = 0.0

    def enterEvent(self, e):
        animations.anim(self, 160, lambda v: (setattr(self, "hv", v), self.update()), self.hv, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        animations.anim(self, 220, lambda v: (setattr(self, "hv", v), self.update()), self.hv, 0.0)
        super().leaveEvent(e)

    def paintEvent(self, _e):
        P, acc = self.pal, QColor(C["acc"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2 - 2 * self.hv, -2, -24 - 2 * self.hv)
        p.setPen(QPen(acc if self.isChecked() else mix(QColor(P["line2"]), acc, 0.5 * self.hv), 2))
        p.setBrush(QColor(P["bg0"]))
        p.drawRoundedRect(r, 12, 12)
        inner = r.adjusted(8, 8, -8, -8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(P["bg1"]))  # шапка
        p.drawRoundedRect(QRectF(inner.x(), inner.y(), inner.width(), 12), 4, 4)
        p.setBrush(acc)  # выбранная вкладка - таблетка акцента
        p.drawRoundedRect(QRectF(inner.x() + 6, inner.y() + 3, 22, 6), 3, 3)
        side = QRectF(inner.x(), inner.y() + 17, 34, inner.height() - 17)
        p.setBrush(QColor(P["bg1"]))
        p.drawRoundedRect(side, 4, 4)
        for i in range(4):  # строки дерева
            p.setBrush(QColor(P["dim"]) if i else acc)
            p.drawRoundedRect(QRectF(side.x() + 5, side.y() + 6 + i * 9, 22 - 5 * (i % 2), 3), 1.5, 1.5)
        tiles = QRectF(side.right() + 6, side.y(), inner.right() - side.right() - 6, side.height())
        w = (tiles.width() - 8) / 3
        for i in range(6):
            x, y = tiles.x() + (i % 3) * (w + 4), tiles.y() + (i // 3) * (tiles.height() / 2 + 1)
            p.setBrush(QColor(P["bg2"]))
            p.drawRoundedRect(QRectF(x, y, w, tiles.height() / 2 - 3), 4, 4)
            p.setBrush(mix(QColor(P["bg3"]), acc, 0.35 if i == 1 else 0.0))
            p.drawEllipse(QPointF(x + w / 2, y + tiles.height() / 4 - 1), w / 4, w / 4)
        p.setPen(QColor(C["text"]))
        p.setFont(font("title", 10))
        p.drawText(QRectF(0, self.height() - 22, self.width(), 20), Qt.AlignmentFlag.AlignCenter, self.name)
        p.end()


class AccentDot(QAbstractButton):
    """Акцент - кружком со своим градиентом; выбранный - в кольце, подпись снизу."""

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.name, self.a, self.b = theme.ACCENTS[key]
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(70, 66)
        self.setToolTip(self.name)
        self.k = 0.0
        self.toggled.connect(lambda on: animations.anim(self, 260, self._set, self.k, 1.0 if on else 0.0))

    def _set(self, v):
        self.k = v
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, 22)
        g = QLinearGradient(c.x() - 16, c.y() - 16, c.x() + 16, c.y() + 16)
        g.setColorAt(0, QColor(self.a))
        g.setColorAt(1, QColor(self.b))
        if self.k > 0.01 or self.isChecked():
            p.setPen(QPen(QColor(C["text"]), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rr = 17 + 4 * self.k
            p.drawEllipse(c, rr, rr)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        r = 15 - 2 * self.k
        p.drawEllipse(c, r, r)
        p.setPen(QColor(C["text"] if self.isChecked() else C["dim"]))
        p.setFont(font("title", 8.5))
        p.drawText(QRectF(0, 46, self.width(), 18), Qt.AlignmentFlag.AlignCenter, self.name)
        p.end()


# ---------------------------------------------------------------- окно
PAGES = (
    ("look", "Оформление", "color-palette", "Тема, акцент и движение в окне"),
    ("inbox", "Входящие", "Задачи", "Откуда приходят листы и что делать при сохранении"),
    ("ue", "Unreal и 3D", "dice_3D", "Живой просмотр, окно 3D, карточки видов"),
    ("ai", "ИИ-помощники", "sparkles", "Что им можно и что они сделали"),
    ("data", "Данные", "first-aid-kit", "Проверка, резервные копии, папка настроек"),
)


class SettingsDialog(QDialog):
    def __init__(self, win, page="look"):
        super().__init__(win)
        self.win, self.cfg = win, win.cfg
        self.setWindowTitle("Настройки")
        self.setWindowIcon(lib_icon("gear"))
        self.resize(860, 640)
        self.setStyleSheet(
            f"QFrame#setrow{{background:{C['bg2']};border:1px solid {C['line']};border-radius:12px}}"
            f"QFrame#setrow:hover{{border-color:{C['line2']}}}"
            f"QListWidget#setnav{{background:{C['bg1']};border:1px solid {C['line']};border-radius:14px;padding:6px}}"
            f"QListWidget#setnav::item{{padding:9px 8px;border-radius:9px;margin:1px 0}}"
            f"QListWidget#setnav::item:selected{{background:{C['accd']};color:{C['selt']}}}"
            # шрифты - стилем: общий QWidget{font:...} окна перебивает setFont
            'QListWidget#setnav{font:600 10.5pt "Segoe UI Variable Display"}'
            'QLabel#pagetitle{font:600 18pt "Segoe UI Variable Display"}'
            'QLabel#rowtitle{font:600 10.5pt "Segoe UI Variable Display"}'
        )
        self.rows = {}  # раздел -> [Row]
        # --- слева: поиск и разделы
        self.find = QLineEdit(placeholderText="Найти настройку...")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self.search)
        self.nav = QListWidget(objectName="setnav")
        self.nav.setIconSize(QSize(20, 20))
        self.nav.setFixedWidth(210)
        for key, name, icon, _sub in PAGES:
            it = QListWidgetItem(lib_icon(icon), name)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(it)
        left = QVBoxLayout()
        left.addWidget(self.find)
        left.addWidget(self.nav, 1)
        # --- справа: страницы
        self.stack = QStackedWidget()
        self.pages = {}
        for key, name, _icon, sub in PAGES:
            self.pages[key] = self.page(key, name, sub)
        self.build_look()
        self.build_inbox()
        self.build_ue()
        self.build_ai()
        self.build_data()
        for key, _p in self.pages.items():
            self.pages[key].layout().addStretch(1)
        self.nav.currentRowChanged.connect(self.go)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(14)
        lay.addLayout(left)
        right = QVBoxLayout()
        right.addWidget(self.stack, 1)
        ok = QPushButton("Готово", objectName="primary")
        ok.clicked.connect(self.accept)
        right.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        lay.addLayout(right, 1)
        self.nav.setCurrentRow(next((i for i, p in enumerate(PAGES) if p[0] == page), 0))
        self.mark()

    # --- страницы
    def page(self, key, name, sub):
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(4, 2, 10, 10)
        v.setSpacing(8)
        title = QLabel(name, objectName="pagetitle")
        v.addWidget(title)
        v.addWidget(QLabel(sub, objectName="dim"))
        v.addSpacing(6)
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.stack.addWidget(scroll)
        self.rows[key] = []
        return body

    def add(self, key, row):
        self.pages[key].layout().addWidget(row)
        self.rows[key].append(row)
        return row

    def head(self, key, text):
        lay = self.pages[key].layout()
        lay.addSpacing(6)
        lay.addWidget(panel_head(text), 0, Qt.AlignmentFlag.AlignLeft)

    def switch(self, key, title, desc, on, fn, icon=None):
        sw = Switch(on)
        sw.toggled.connect(fn)
        self.add(key, Row(title, desc, sw, icon))
        return sw

    def build_look(self):
        k = "look"
        self.head(k, "ТЕМА")
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)
        self.theme_cards = {}
        for key in theme.THEMES:
            c = ThemeCard(key)
            c.clicked.connect(lambda _c=False, kk=key: self.pick(theme_key=kk))
            self.theme_cards[key] = c
            h.addWidget(c)
        h.addStretch(1)
        self.pages[k].layout().addWidget(box)
        self.head(k, "АКЦЕНТ")
        box2 = QWidget()
        h2 = QHBoxLayout(box2)
        h2.setContentsMargins(0, 0, 0, 0)
        h2.setSpacing(4)
        self.acc_dots = {}
        for key in theme.ACCENTS:
            d = AccentDot(key)
            d.clicked.connect(lambda _c=False, kk=key: self.pick(accent=kk))
            self.acc_dots[key] = d
            h2.addWidget(d)
        h2.addStretch(1)
        self.pages[k].layout().addWidget(box2)
        self.head(k, "ДВИЖЕНИЕ")
        self.switch(
            k,
            "Живой фон",
            "Плывущие пятна цвета за окном (F9). Выключите на слабом компьютере или если отвлекает.",
            self.cfg.get("live_bg", True),
            self.set_live_bg,
            "moon-stars",
        )
        self.switch(
            k,
            "Плавные анимации",
            "Карточки, числа, звёзды избранного, перелёт камеры в 3D, смена разделов здесь. "
            "Выключено - всё встаёт на место сразу.",
            animations.MOTION["on"],
            self.set_motion,
            "sparkles",
        )

    def build_inbox(self):
        k, inbox = "inbox", self.win.inbox
        self.gen_lbl = QLabel(objectName="dim")
        pick = QPushButton(lib_icon("folder"), "Выбрать...")
        pick.clicked.connect(lambda: (self.win.pick_gen(), self.show_gen()))
        off = QPushButton("Не следить")
        off.clicked.connect(self.gen_off)
        btns = QWidget()
        bh = QHBoxLayout(btns)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.addWidget(pick)
        bh.addWidget(off)
        row = self.add(k, Row("Папка генератора", "Новые картинки из неё сами приходят во входящие.", btns, "eye"))
        row.layout().itemAt(1).layout().addWidget(self.gen_lbl)
        self.show_gen()
        if self.win.sem.ok:
            self.switch(
                k,
                "Ставить подсказанные метки",
                "При сохранении нарезанных картинок - метки, которые подсказал поиск по смыслу.",
                inbox.auto_tags.isChecked(),
                inbox.auto_tags.setChecked,
                "bookmark",
            )
        self.switch(
            k,
            "Исходный лист - в _sources",
            "После нарезки лист не удаляется, а уходит в папку исходников (можно вернуться).",
            inbox.keep.isChecked(),
            inbox.keep.setChecked,
            "zip-archive",
        )

    def build_ue(self):
        k, ue = "ue", self.win.unreal
        self.switch(
            k,
            "Живой 3D в панели",
            "Модель вращается прямо в карточке справа во вкладке «Unreal». Выключите, если видеокарта слабая.",
            ue.live.isChecked(),
            ue.live.setChecked,
            "dice_3D",
        )
        self.switch(
            k,
            "Карточки видов - значками",
            "«Всё вместе», «Текстуры», «3D-модели»... - строкой значков: дереву больше места.",
            ue.nav.compact_btn.isChecked(),
            ue.nav.compact_btn.setChecked,
            "menuGrid",
        )
        self.switch(
            k,
            "Цвета одной плиткой",
            "«Banner red», «Banner blue»... - одна плитка с цветными точками: щелчок по точке меняет вариант.",
            self.cfg.get("ue_variants", True),
            self.set_variants,
            "color-palette",
        )
        self.head(k, "ОКНО 3D")
        self.switch(
            k, "Подиум, тень и сетка", "Клавиша G в окне 3D.", self.cfg.get("ue_floor", True), self.set_floor, "card"
        )
        self.switch(
            k,
            "Человек 180 см рядом",
            "Силуэт в том же масштабе - сразу видно размер модели (H).",
            self.cfg.get("ue_human", False),
            self.set_human,
            "user-silhouette",
        )

    def build_ai(self):
        k = "ai"
        self.switch(
            k,
            "Помощникам можно менять библиотеку",
            "Выключено - «Только чтение»: Claude, Cursor и другие только ищут и смотрят.",
            self.cfg.get("ai_write", True),
            self.set_ai_write,
            "sparkles",
        )
        feed = QPushButton("Открыть ленту")
        feed.clicked.connect(lambda: (self.accept(), self.win.ai_drawer.toggle()))
        self.add(
            k, Row("Что они сделали", "Все действия помощников с кнопкой «Отменить» у каждого.", feed, "clipboard")
        )
        conn = QPushButton("Подключить...")
        conn.clicked.connect(self.win.agents)
        self.add(
            k,
            Row(
                "Подключить помощников",
                "Claude Desktop, Cursor, VS Code, Windsurf, Cline и другие - одной кнопкой.",
                conn,
                "gear",
            ),
        )

    def build_data(self):
        k = "data"
        safe = QPushButton("Проверить...")
        safe.clicked.connect(self.win.safety)
        self.add(
            k,
            Row(
                "Проверка и восстановление",
                "База, настройки и резервные копии: найти и починить, вернуть из копии.",
                safe,
                "first-aid-kit",
            ),
        )
        folder = QPushButton("Открыть")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(HERE)))
        self.add(k, Row("Папка настроек", "settings.json, база library.db и резервные копии.", folder, "folder"))

    # --- смена раздела: прежняя уходит, новая въезжает снизу, карточки - лесенкой
    def go(self, i):
        if i < 0:
            return
        self.stack.setCurrentIndex(i)
        page = self.stack.currentWidget()
        key = PAGES[i][0]
        if not animations.MOTION["on"]:
            return
        eff = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(eff)
        a = QVariantAnimation(page, startValue=0.0, endValue=1.0, duration=260)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(eff.setOpacity)
        a.finished.connect(lambda: page.setGraphicsEffect(None))
        a.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
        for n, row in enumerate(self.rows[key]):
            self.rise(row, 60 + n * 45)

    def rise(self, w, delay):
        """Карточка всплывает: появляется и поднимается на 10 px."""
        from PyQt6.QtCore import QTimer

        eff = QGraphicsOpacityEffect(w)
        eff.setOpacity(0.0)
        w.setGraphicsEffect(eff)
        base = w.layout().contentsMargins()

        def step(v):
            eff.setOpacity(v)
            w.layout().setContentsMargins(base.left(), base.top() + int(10 * (1 - v)), base.right(), base.bottom())

        def done():
            w.setGraphicsEffect(None)
            w.layout().setContentsMargins(base)

        QTimer.singleShot(delay, lambda: animations.anim(w, 320, step, done=done))

    # --- поиск по всем разделам
    def search(self, text):
        q = text.strip().lower().replace("ё", "е")
        hit_page = None
        for i, (key, _n, _ic, _s) in enumerate(PAGES):
            hits = [r for r in self.rows[key] if q and q in r.words]
            self.nav.item(i).setHidden(bool(q) and not hits)
            if hits and hit_page is None:
                hit_page = (i, hits)
        if hit_page:
            self.nav.setCurrentRow(hit_page[0])
            for r in hit_page[1]:
                r.flash()

    # --- действия
    def mark(self):
        for k, c in self.theme_cards.items():
            c.setChecked(k == theme.CURRENT["theme"])
        for k, d in self.acc_dots.items():
            d.setChecked(k == theme.CURRENT["accent"])

    def pick(self, theme_key=None, accent=None):
        self.cfg["theme"] = theme_key or self.cfg.get("theme", "dark")
        self.cfg["accent"] = accent or self.cfg.get("accent", "lavender")
        self.win.apply_theme()
        self.mark()
        for c in self.theme_cards.values():
            c.update()

    def set_live_bg(self, on):
        self.cfg["live_bg"] = on
        self.win.aurora.set_live(on)

    def set_motion(self, on):
        self.cfg["motion"] = on
        self.win.apply_motion()

    def show_gen(self):
        d = self.cfg.get("gen_dir")
        self.gen_lbl.setText(d if d else "Не задана")

    def gen_off(self):
        self.cfg["gen_dir"] = ""
        self.win.show_gen()
        self.show_gen()

    def viewer(self):
        return getattr(self.win.unreal, "viewer", None)

    def set_variants(self, on):
        self.cfg["ue_variants"] = on
        if self.win.unreal.loaded:
            self.win.unreal.show_assets()

    def set_floor(self, on):
        self.cfg["ue_floor"] = on
        v = self.viewer()
        if v is not None:
            v.floor.setChecked(on)

    def set_human(self, on):
        self.cfg["ue_human"] = on
        v = self.viewer()
        if v is not None:
            v.human.setChecked(on)

    def set_ai_write(self, on):
        self.cfg["ai_write"] = on
        self.win.update_ai_status()
