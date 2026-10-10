"""Левая панель вкладки «Unreal»: сверху карточки видов (у каждого свой цвет), ниже - темы только
выбранного вида; темы «Дом - ...» собраны в одну раскрывающуюся группу «Дом»."""

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QButtonGroup, QComboBox, QLabel, QSizePolicy, QVBoxLayout, QWidget

from library import unreal as U
from library import unreal_groups as G
from ui.common import ROLE, human
from ui.theme import C, readable
from ui.thumbnails import lib_icon, lib_pix
from ui.widgets import make_tree, tree_item

ALL, FAV = "::all", "::fav"
NEW, SETS = "::new", "::sets"  # скачанное за последние дни; свои подборки
SET = "::set:"  # + имя подборки
HOME = "::home"  # все темы «Дом - ...» разом
SECTION = "::sec:"  # + «группа|раздел» (Дом|Кровати, Природа|Деревья) - по назначению, из любого источника
GROUP = "::grp:"  # + группа (Дом, Природа, Город и транспорт...) - library/unreal_groups.py
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
    "Инструменты": "hammer",
    "Хозяйство и уборка": "trash-bin",
    "Спорт и хобби": "trophy-cup",
    "Одежда и аксессуары": "leather-boots",
    "Мелочи": "toolbox",
    "Дом - мебель": "home",
    "Дом - кухня и посуда": "coffee-mug-steam",
    "Дом - декор": "figurine",
    "Дом - свет и техника": "crt-monitor",
    "Дом - растения": "snake-plant",
    "Дом - мелочи": "toolbox",
    "Дом - Kenney low-poly": "hand_cube",
    "Дом - Quaternius low-poly": "puzzle-piece",
    "Лес и природа - Kenney low-poly": "bonsai-tree",
    "Город - Kenney low-poly": "structure_tower",
    "Средневековье - Kenney low-poly": "tool_sword_a",
    "Космос - Kenney low-poly": "gear",
    "Еда - Kenney low-poly": "coffee-mug-steam",
    "Дом - KayKit low-poly": "hand_cube",
    "Средневековье - KayKit low-poly": "tool_sword_a",
    "Город - KayKit low-poly": "structure_tower",
    "Космос - KayKit low-poly": "gear",
    "Прототипы и уровни - KayKit low-poly": "hand_cube",
    "Персонажи - KayKit low-poly": "pawn",
    "Прототипы и уровни - Kenney low-poly": "hand_cube",
    "Персонажи - Kenney low-poly": "pawn",
    "Лес и природа - Quaternius low-poly": "bonsai-tree",
    "Город - Quaternius low-poly": "structure_tower",
    "Средневековье - Quaternius low-poly": "tool_sword_a",
    "Космос - Quaternius low-poly": "gear",
    "Еда - Quaternius low-poly": "coffee-mug-steam",
    "Животные - Quaternius low-poly": "heart",
    "Полы": "card_place",
    "Стены": "structure_wall",
    "Плитка и камень": "hexagon",
    "Ткани и кожа": "leather-boots",
    # разделы групп (library/unreal_groups.py)
    "Деревья": "bonsai-tree",
    "Камни и скалы": "round-cactus",
    "Кусты, трава, цветы": "snake-plant",
    "Земля и дорожки": "card_place",
    "Лагерь и выживание": "toolbox",
    "Транспорт": "gear",
    "Дороги и рельсы": "card_place",
    "Здания": "structure_tower",
    "Улица и детали": "sun",
    "Индустрия": "gear",
    "Гексы и карта": "hexagon",
    "Оружие и броня": "tool_sword_a",
    "Кладбище и подземелье": "moon-stars",
    "Корабли": "anchor",
    "Строения": "structure_wall",
    "Утварь и мебель": "cards_stack",
    "Карты": "cards_stack",
    "Персонажи": "pawn",
    "Корабли и транспорт": "gear",
    "Декали": "card_place",
    "Поверхность": "round-cactus",
    "Модули и стены": "structure_wall",
    "Предметы": "toolbox",
    "Животные": "heart",
    "Снаряжение и одежда": "leather-boots",
    "Фрукты и овощи": "snake-plant",
    "Выпечка и сладкое": "coffee-mug-steam",
    "Блюда": "coffee-mug-steam",
    "Напитки": "coffee-mug-steam",
    "Посуда": "coffee-mug-steam",
    "Платформер": "hand_cube",
    "Гонки": "trophy-cup",
    "Tower defense": "structure_tower",
    "Гексы": "hexagon",
    "Арена": "trophy-cup",
    "Блоки-заготовки": "hand_cube",
}


def kind_color(kind):
    return readable(KIND_LOOK.get(kind, KIND_LOOK[ALL])[2])


def theme_label(th):
    """Имя темы в дереве: внутри группы «Дом» - без приставки."""
    if th.startswith(HOME_PREFIX):
        rest = th[len(HOME_PREFIX) :]
        for src in U.LOW_POLY:
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
        self.style = QComboBox()  # реалистичные / low-poly / один источник - до дерева, числа в дереве с ним
        for key, text in G.STYLES:
            self.style.addItem(text, key)
        self.style.setCurrentIndex(max(0, self.style.findData(cfg.get("ue_style", "all"))))
        self.style.setToolTip("Реалистичные PBR-модели (Poly Haven) или простые low-poly наборы")
        self.style.currentIndexChanged.connect(self.pick_style)
        v.addWidget(self.style)
        self.tree = make_tree()
        self.tree.currentItemChanged.connect(self.pick_theme)
        v.addWidget(self.tree, 1)

    # ------------------------------------------------------------
    def pick_style(self, _i=None):
        self.cfg["ue_style"] = self.style.currentData()
        self.set_items(self.items, self.favs)
        self.changed.emit()

    def of_kind(self, kind, styled=True):
        items = self.items
        st = self.style.currentData() if styled else "all"
        if st != "all":
            items = [a for a in items if G.style_ok(a, st)]
        return self._of_kind(kind, items)

    def _of_kind(self, kind, items):
        if kind == ALL:
            return items
        if kind == FAV:
            return [a for a in items if a.get("id") in self.favs]
        if kind == NEW:
            from library.unreal_extra import added

            return [a for a in items if added(a) > self.since]
        if kind == SETS:
            ids = {i for lst in self.sets().values() for i in lst}
            return [a for a in items if a.get("id") in ids]
        return [a for a in items if a.get("kind") == kind]

    def set_items(self, items, favs):
        self.items, self.favs = items, favs
        for a in items:  # раздел «Дома» считается один раз на загрузку
            if a.get("theme", "").startswith(HOME_PREFIX) and "section" not in a:
                # модели - по назначению; у текстур дома тема и есть раздел (полы, стены, плитка, ткани)
                a["section"] = U.home_section(a) if a.get("kind") == "model" else theme_label(a["theme"])
        G.annotate(items)  # группа и раздел для дерева (_g, _s)
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
        from library import unreal_sets

        return unreal_sets.load(self.cfg)  # общий файл: подборки ИИ-помощника видны сразу

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
        """Группы и их разделы (library/unreal_groups.py) для выбранного вида и стиля."""
        if self.kind == SETS:
            self.fill_sets()
            return
        lst = self.of_kind(self.kind)
        self._legacy_theme()
        groups, secs = {}, {}
        for a in lst:
            groups[a["_g"]] = groups.get(a["_g"], 0) + 1
            secs[(a["_g"], a["_s"])] = secs.get((a["_g"], a["_s"]), 0) + 1
        col = QColor(kind_color(self.kind))
        self.tree.blockSignals(True)
        self.tree.clear()
        top = tree_item(self.tree, "Все группы", None, lib_icon("menuGrid"), len(lst))
        pick = top
        for g in G.group_order():
            if g not in groups:
                continue
            it = tree_item(self.tree, g, GROUP + g, lib_icon(G.GROUP_ICON.get(g, "folder")), groups[g])
            if self.theme == GROUP + g:
                pick = it
            order = G.section_order(g)
            names = [x for x in order if (g, x) in secs] + sorted(x for (gg, x) in secs if gg == g and x not in order)
            if len(names) > 1:  # один раздел - в дереве не нужен
                for sec in names:
                    key = SECTION + g + "|" + sec
                    ch = tree_item(it, sec, key, lib_icon(THEME_ICON.get(sec, "folder")), secs[(g, sec)])
                    if self.theme == key:
                        pick = ch
                        it.setExpanded(True)
        for i in range(self.tree.topLevelItemCount()):  # число справа - цветом вида
            self._tint(self.tree.topLevelItem(i), col)
        self.tree.setCurrentItem(pick)
        self.theme = pick.data(0, ROLE)
        self.tree.blockSignals(False)
        title = KIND_LOOK[self.kind][0].upper()
        self.theme_lbl.setText(f"ГРУППЫ: {title}" if self.kind != ALL else "ГРУППЫ")

    def _legacy_theme(self):
        """Сохранённый выбор из прежнего дерева (тема, «Дом», раздел Дома) -> группа или раздел."""
        th = self.theme
        if not th or th.startswith((GROUP, SET)) or (th.startswith(SECTION) and "|" in th):
            return
        if th == HOME:
            self.theme = GROUP + "Дом"
        elif th.startswith(SECTION):
            self.theme = SECTION + "Дом|" + th[len(SECTION) :]
        else:
            self.theme = GROUP + G.group_of(th)

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
        th = self.theme
        if th and th.startswith(SET):
            ids = set(self.sets().get(th[len(SET) :], []))
            return [a for a in lst if a.get("id") in ids]
        if th and th.startswith(GROUP):
            g = th[len(GROUP) :]
            return [a for a in lst if a.get("_g") == g]
        if th and th.startswith(SECTION) and "|" in th:
            g, sec = th[len(SECTION) :].split("|", 1)
            return [a for a in lst if a.get("_g") == g and a.get("_s") == sec]
        return lst

    def title(self):
        name = KIND_LOOK[self.kind][0]
        th = self.theme
        style = self.style.currentText() if self.style.currentData() != "all" else ""
        tail = f"  ({style})" if style else ""
        if th and th.startswith(SET):
            return f"Подборка / {th[len(SET) :]}"
        if th and th.startswith(GROUP):
            return f"{name} / {th[len(GROUP) :]}{tail}"
        if th and th.startswith(SECTION) and "|" in th:
            g, sec = th[len(SECTION) :].split("|", 1)
            return f"{name} / {g} / {sec}{tail}"
        return name + tail
