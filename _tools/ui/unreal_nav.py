"""Левая панель вкладки «Unreal»: сверху карточки видов (у каждого свой цвет), ниже - темы только
выбранного вида; темы «Дом - ...» собраны в одну раскрывающуюся группу «Дом»."""

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QButtonGroup, QLabel, QSizePolicy, QVBoxLayout, QWidget

from library import unreal as U
from ui.common import ROLE, human
from ui.theme import C, readable
from ui.thumbnails import lib_icon, lib_pix
from ui.widgets import make_tree, tree_item

ALL, FAV = "::all", "::fav"
NEW, SETS = "::new", "::sets"  # скачанное за последние дни; свои подборки
SET = "::set:"  # + имя подборки
HOME = "::home"  # все темы «Дом - ...» разом
SECTION = "::sec:"  # + раздел «Дома» (Кровати, Столы...) - по назначению, из любого источника
HOME_PREFIX = "Дом - "

# вид -> (подпись на карточке, значок, цвет)
KIND_LOOK = {
    ALL: ("Всё вместе", "game-cartridge", "#8e8ba6"),
    "tex": ("Текстуры", "paint-roller", "#f0a35e"),
    "hdri": ("Небо и фоны HDRI", "cloud", "#6cb8ff"),
    "model": ("3D-модели", "dice_3D", "#a897ff"),
    "ies": ("Свет IES", "lightning-bolt", "#ffd166"),
    FAV: ("Избранное", "star", "#ff8ac9"),
    NEW: ("Новое", "sparkles", "#7ee0a0"),
    SETS: ("Подборки", "bookmark", "#ffb86c"),
}
KIND_HINT = {
    ALL: "все виды подряд",
    "tex": "материалы: цвет, нормаль, ARM, высота",
    "hdri": "панорамы неба: фон и освещение сцены",
    "model": "FBX с текстурами",
    "ies": "профили для Point и Spot Light",
    FAV: "отмеченные звездой",
    NEW: "скачанное с прошлого открытия окна",
    SETS: "свои наборы: «Моя спальня», «Кухня» - правый щелчок по плитке -> «В подборку»",
}
THEME_ICON = {
    "Лес и природа": "bonsai-tree",
    "Город": "structure_tower",
    "Интерьер": "door",
    "Индустрия и sci-fi": "gear",
    "Средневековье и фэнтези": "tool_sword_a",
    "Пустыня и скалы": "round-cactus",
    "Зима": "snowflake",
    "Ночь и закат": "moon-stars",
    "Студия": "camera",
    "Свои профили": "lightning-bolt",
    HOME: "house",
    # разделы «Дома»
    "Кровати": "moon-stars",
    "Диваны": "heart",
    "Стулья и кресла": "pawn",
    "Столы": "card_place",
    "Шкафы и полки": "cards_stack",
    "Кухня и посуда": "coffee-mug-steam",
    "Ванная": "sweat-drop",
    "Свет": "sun",
    "Техника": "crt-monitor",
    "Декор": "figurine",
    "Растения": "snake-plant",
    "Стены, двери, окна": "structure_wall",
    "Мелочи": "toolbox",
    "Дом - мебель": "home",
    "Дом - кухня и посуда": "coffee-mug-steam",
    "Дом - декор": "figurine",
    "Дом - свет и техника": "crt-monitor",
    "Дом - растения": "snake-plant",
    "Дом - мелочи": "toolbox",
    "Дом - Kenney low-poly": "hand_cube",
    "Дом - Quaternius low-poly": "puzzle-piece",
    "Полы": "card_place",
    "Стены": "structure_wall",
    "Плитка и камень": "hexagon",
    "Ткани и кожа": "leather-boots",
}


def kind_color(kind):
    return readable(KIND_LOOK.get(kind, KIND_LOOK[ALL])[2])


def theme_label(th):
    """Имя темы в дереве: внутри группы «Дом» - без приставки."""
    if th.startswith(HOME_PREFIX):
        rest = th[len(HOME_PREFIX) :]
        for src in ("Kenney", "Quaternius"):
            if rest.startswith(src):
                return f"{src} - простые low-poly"
        return rest[:1].upper() + rest[1:]
    return th


class KindCard(QAbstractButton):
    """Карточка вида: цветная полоска, значок, название, «сколько, сколько весит»."""

    def __init__(self, kind, look=None, hint=None):
        """look = (название, значок, цвет) - для карточек не из KIND_LOOK (быстрый доступ библиотеки)."""
        super().__init__()
        self.kind = kind
        self.title, self.icon_name, self.color = look or KIND_LOOK[kind]
        self.sub = ""
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(hint if hint is not None else KIND_HINT[kind])
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.f1 = QFont("Segoe UI", 10)
        self.f1.setWeight(QFont.Weight.DemiBold)
        self.f2 = QFont("Segoe UI", 8)

    def sizeHint(self):
        return QSize(200, 50)

    def set_sub(self, text):
        self.sub = text
        self.update()

    def set_stats(self, n, size):
        self.sub = f"{n} шт., {human(size)}" if n else "пусто"
        self.update()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 2, -1, -2)
        col = QColor(readable(self.color))  # в светлой теме пастель темнее
        if self.isChecked():
            fill = QColor(col)
            fill.setAlpha(46)
            p.setPen(QPen(col, 1.2))
            p.setBrush(fill)
        else:
            p.setPen(QPen(QColor(C["line"]), 1))
            p.setBrush(QColor(C["bg3"] if self.underMouse() else C["bg2"]))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(Qt.PenStyle.NoPen)  # полоска цвета вида слева
        p.setBrush(col)
        p.drawRoundedRect(QRectF(r.x() + 5, r.y() + 9, 4, r.height() - 18), 2, 2)
        pm = lib_pix(self.icon_name, 44)
        if not pm.isNull():
            p.drawPixmap(QRectF(r.x() + 17, r.center().y() - 11, 22, 22), pm, QRectF(pm.rect()))
        x = int(r.x()) + 48
        w = int(r.right()) - x - 8
        p.setFont(self.f1)
        p.setPen(QColor(C["text"]))
        p.drawText(
            x,
            int(r.y()) + 5,
            w,
            20,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            p.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight, w),
        )
        p.setFont(self.f2)
        p.setPen(QColor(C["dim"]))
        p.drawText(
            x,
            int(r.y()) + 24,
            w,
            18,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            p.fontMetrics().elidedText(self.sub, Qt.TextElideMode.ElideRight, w),
        )
        p.end()


class Nav(QWidget):
    """kind - ALL / FAV / вид; theme - None (все темы) / HOME / имя темы."""

    changed = pyqtSignal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.items, self.favs = [], set()
        self.kind = cfg.get("ue_kind", ALL)
        self.theme = cfg.get("ue_theme")
        self.cards = {}
        self.since = 0  # «Новое» - позже этого времени (прошлое открытие окна)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(QLabel("ЧТО ПОКАЗАТЬ", objectName="faint"))
        for k in (ALL, "tex", "hdri", "model", "ies", FAV, NEW, SETS):
            c = KindCard(k)
            c.clicked.connect(lambda _c=False, k=k: self.pick_kind(k))
            self.group.addButton(c)
            self.cards[k] = c
            v.addWidget(c)
        v.addSpacing(8)
        self.theme_lbl = QLabel("ТЕМЫ", objectName="faint")
        v.addWidget(self.theme_lbl)
        self.tree = make_tree()
        self.tree.currentItemChanged.connect(self.pick_theme)
        v.addWidget(self.tree, 1)

    # ------------------------------------------------------------
    def of_kind(self, kind):
        if kind == ALL:
            return self.items
        if kind == FAV:
            return [a for a in self.items if a.get("id") in self.favs]
        if kind == NEW:
            from library.unreal_extra import added

            return [a for a in self.items if added(a) > self.since]
        if kind == SETS:
            ids = {i for lst in self.sets().values() for i in lst}
            return [a for a in self.items if a.get("id") in ids]
        return [a for a in self.items if a.get("kind") == kind]

    def set_items(self, items, favs):
        self.items, self.favs = items, favs
        for a in items:  # раздел «Дома» считается один раз на загрузку
            if a.get("theme", "").startswith(HOME_PREFIX) and "section" not in a:
                # модели - по назначению; у текстур дома тема и есть раздел (полы, стены, плитка, ткани)
                a["section"] = U.home_section(a) if a.get("kind") == "model" else theme_label(a["theme"])
        for k, c in self.cards.items():
            lst = self.of_kind(k)
            c.set_stats(len(lst), sum(a.get("size", 0) for a in lst))
        for k in (FAV, NEW, SETS):  # пустые особые карточки не показываются
            self.cards[k].setVisible(bool(self.of_kind(k)) or (k == SETS and bool(self.sets())))
        if self.kind not in self.cards or self.cards[self.kind].isHidden():  # isVisible ложно, пока вкладка скрыта
            self.kind = ALL
        self.cards[self.kind].setChecked(True)
        self.fill_themes()

    def pick_kind(self, k):
        if k == self.kind:
            return
        self.kind = self.cfg["ue_kind"] = k
        self.fill_themes()
        self.changed.emit()

    def sets(self):
        return self.cfg.setdefault("ue_sets", {})

    def fill_sets(self):
        """Вместо тем - подборки."""
        col = QColor(kind_color(SETS))
        self.tree.blockSignals(True)
        self.tree.clear()
        lst = self.of_kind(SETS)
        pick = tree_item(self.tree, "Все подборки", None, lib_icon("menuGrid"), len(lst))
        ids = {a.get("id") for a in self.items}
        for name, members in sorted(self.sets().items(), key=lambda kv: kv[0].lower()):
            it = tree_item(self.tree, name, SET + name, lib_icon("bookmark"), sum(1 for i in members if i in ids))
            if self.theme == SET + name:
                pick = it
        for i in range(self.tree.topLevelItemCount()):
            self._tint(self.tree.topLevelItem(i), col)
        self.tree.setCurrentItem(pick)
        self.theme = pick.data(0, ROLE)
        self.tree.blockSignals(False)
        self.theme_lbl.setText("ПОДБОРКИ")

    def fill_themes(self):
        """Темы только выбранного вида, в порядке библиотеки; «Дом - ...» - одной группой."""
        if self.kind == SETS:
            self.fill_sets()
            return
        lst = self.of_kind(self.kind)
        counts = {}
        for a in lst:
            counts[a.get("theme", "")] = counts.get(a.get("theme", ""), 0) + 1
        order = [t for t in U.THEMES if t in counts] + sorted(t for t in counts if t not in U.THEMES)
        col = QColor(kind_color(self.kind))
        self.tree.blockSignals(True)
        self.tree.clear()
        top = tree_item(self.tree, "Все темы", None, lib_icon("menuGrid"), len(lst))
        pick = top
        home = None
        for th in order:
            if th.startswith(HOME_PREFIX):
                if home is None:  # «Дом» - по разделам назначения, а не по источникам
                    home_items = [a for a in lst if a.get("theme", "").startswith(HOME_PREFIX)]
                    home = tree_item(self.tree, "Дом", HOME, lib_icon(THEME_ICON[HOME]), len(home_items))
                    home.setToolTip(0, "Всё для дома по назначению: кровати, столы, шкафы, кухня, ванная...")
                    if self.theme == HOME:
                        pick = home
                    secs = {}
                    for a in home_items:
                        secs[a.get("section", U.HOME_OTHER)] = secs.get(a.get("section", U.HOME_OTHER), 0) + 1
                    for sec in list(U.HOME_ORDER) + sorted(x for x in secs if x not in U.HOME_ORDER):
                        if sec in secs:
                            it = tree_item(home, sec, SECTION + sec, lib_icon(THEME_ICON.get(sec, "folder")), secs[sec])
                            if self.theme == SECTION + sec:
                                pick = it
                continue
            it = tree_item(self.tree, theme_label(th), th, lib_icon(THEME_ICON.get(th, "folder")), counts[th])
            it.setToolTip(0, th)
            if th == self.theme:
                pick = it
        if home is not None:
            for src in ("Kenney", "Quaternius"):  # простые модели отдельно - для черновой расстановки
                th = f"Дом - {src} low-poly"
                mine = [a for a in lst if a.get("theme") == th]
                if mine:
                    it = tree_item(home, f"Только {src}", th, lib_icon(THEME_ICON[th]), len(mine))
                    it.setToolTip(0, f"Low-poly модели {src}: без текстур, лёгкие - расставить комнату начерно")
                    if self.theme == th:
                        pick = it
            home.setExpanded(True)
        for i in range(self.tree.topLevelItemCount()):  # число справа - цветом вида
            self._tint(self.tree.topLevelItem(i), col)
        self.tree.setCurrentItem(pick)
        self.theme = pick.data(0, ROLE)
        self.tree.blockSignals(False)
        title = KIND_LOOK[self.kind][0].upper()
        self.theme_lbl.setText(f"ТЕМЫ: {title}" if self.kind != ALL else "ТЕМЫ")

    def _tint(self, it, col):
        it.setForeground(1, col)
        for i in range(it.childCount()):
            self._tint(it.child(i), col)

    def pick_theme(self, it, _prev=None):
        self.theme = it.data(0, ROLE) if it else None
        self.cfg["ue_theme"] = self.theme
        self.changed.emit()

    # ------------------------------------------------------------
    def chosen(self):
        lst = self.of_kind(self.kind)
        if self.theme == HOME:
            return [a for a in lst if a.get("theme", "").startswith(HOME_PREFIX)]
        if self.theme and self.theme.startswith(SET):
            ids = set(self.sets().get(self.theme[len(SET) :], []))
            return [a for a in lst if a.get("id") in ids]
        if self.theme and self.theme.startswith(SECTION):
            sec = self.theme[len(SECTION) :]
            return [a for a in lst if a.get("theme", "").startswith(HOME_PREFIX) and a.get("section") == sec]
        if self.theme:
            return [a for a in lst if a.get("theme") == self.theme]
        return lst

    def title(self):
        name = KIND_LOOK[self.kind][0]
        if self.theme == HOME:
            return f"{name} / Дом"
        if self.theme and self.theme.startswith(SET):
            return f"Подборка / {self.theme[len(SET) :]}"
        if self.theme and self.theme.startswith(SECTION):
            return f"{name} / Дом / {self.theme[len(SECTION) :]}"
        if self.theme:
            return (
                f"{name} / {theme_label(self.theme)}"
                if not self.theme.startswith(HOME_PREFIX)
                else f"{name} / Дом / {theme_label(self.theme)}"
            )
        return name
