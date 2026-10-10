"""Левая панель вкладки «Unreal»: сверху карточки видов (у каждого свой цвет), ниже - темы только
выбранного вида; темы «Дом - ...» собраны в одну раскрывающуюся группу «Дом»."""

import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractButton,
    QBoxLayout,
    QButtonGroup,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from library import unreal as U
from library import unreal_groups as G
from ui.common import ROLE, human
from ui.theme import C, font, readable
from ui.thumbnails import lib_icon, lib_pix, mix
from ui.widgets import filter_tree, make_tree, panel_head, set_shares, tree_item

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
    "Железная дорога": "card_place",
    "Дороги": "card_place",
    "Окна и двери": "door",
    "Двери и окна": "door",
    "Коридоры и двери": "door",
    "Крыши": "house",
    "Дома целиком": "house",
    "Стены и фасады": "structure_wall",
    "Стены и углы": "structure_wall",
    "Башни и ворота": "structure_tower",
    "Полы и лестницы": "card_place",
    "Платформы и лестницы": "card_place",
    "Знамёна и флаги": "bookmark",
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
        self.f1 = font("title", 10.5)  # название - Segoe UI Variable Display
        self.f2 = font("num", 8.5)  # «5890 шт., 18.7 ГБ» - ровные цифры Bahnschrift
        self.hint = hint if hint is not None else KIND_HINT[kind]
        self.compact = False
        # анимации: наведение (hv), выбор (ck), прыжок значка при выборе (bump), бегущие числа (shown)
        self.hv = self.ck = self.bump = 0.0
        self.shown, self.num_anim, self.hv_anim, self.ck_anim = "", None, None, None
        self.toggled.connect(self._checked)

    def _to(self, attr, end, ms):
        from ui.animations import anim, stop

        stop(getattr(self, attr + "_anim"))
        setattr(
            self,
            attr + "_anim",
            anim(self, ms, lambda v: (setattr(self, attr, v), self.update()), getattr(self, attr), end),
        )

    def _checked(self, on):
        self._to("ck", 1.0 if on else 0.0, 320)
        if on:  # значок коротко подпрыгивает
            from ui.animations import anim

            anim(self, 520, lambda v: (setattr(self, "bump", v), self.update()), 0.0, 1.0)

    def sizeHint(self):
        return QSize(34, 38) if self.compact else QSize(200, 50)

    def set_compact(self, on):
        """Компактно - один значок с цветной чертой снизу; название и число - во всплывающей подсказке."""
        self.compact = on
        pol = QSizePolicy.Policy
        self.setSizePolicy(pol.Fixed if on else pol.Expanding, pol.Fixed)
        self._tip()
        self.updateGeometry()
        self.update()

    def _tip(self):
        self.setToolTip(f"{self.title}: {self.sub}\n{self.hint}" if self.compact and self.sub else self.hint)

    def set_sub(self, text):
        """Новая подпись: числа в ней бегут от прежних к новым («122 шт.» -> «134 шт.»)."""
        from ui.animations import anim, stop, tween_text

        old, self.sub = self.shown or self.sub, text
        self._tip()
        stop(self.num_anim)
        if not old or old == text or not self.isVisible():
            self.shown = text
            self.update()
            return
        self.num_anim = anim(self, 650, lambda k: (setattr(self, "shown", tween_text(old, text, k)), self.update()))

    def set_stats(self, n, size):
        self.set_sub(f"{n} шт., {human(size)}" if n else "пусто")

    def enterEvent(self, e):
        self._to("hv", 1.0, 180)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._to("hv", 0.0, 260)
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 2, -1, -2)
        col = QColor(readable(self.color))  # в светлой теме пастель темнее
        if self.isChecked() and self.ck_anim is None:  # выбрана до первого показа - без анимации
            self.ck = 1.0
        # заливка непрозрачная (живой фон не просвечивает): наведение светлее, выбор - в цвет вида
        fill = mix(mix(QColor(C["bg2"]), QColor(C["bg3"]), self.hv), col, 0.22 * self.ck)
        p.setPen(QPen(mix(mix(QColor(C["line"]), col, 0.35 * self.hv), col, self.ck), 1 + 0.4 * self.ck))
        p.setBrush(fill)
        p.drawRoundedRect(r, 10, 10)
        if self.compact:
            p.setPen(Qt.PenStyle.NoPen)  # черта цвета вида снизу, значок по центру
            p.setBrush(col)
            p.drawRoundedRect(QRectF(r.center().x() - 7, r.bottom() - 6, 14, 3), 1.5, 1.5)
            pm = lib_pix(self.icon_name, 44)
            if not pm.isNull():
                p.drawPixmap(QRectF(r.center().x() - 10, r.center().y() - 13, 20, 20), pm, QRectF(pm.rect()))
            p.end()
            return
        p.setPen(Qt.PenStyle.NoPen)  # полоска цвета вида слева: у выбранной - во всю высоту
        p.setBrush(col)
        sh = (r.height() - 18) * (0.55 + 0.45 * self.ck)
        p.drawRoundedRect(QRectF(r.x() + 5, r.center().y() - sh / 2, 4, sh), 2, 2)
        pm = lib_pix(self.icon_name, 44)
        if not pm.isNull():
            z = 22 * (1 + 0.16 * math.sin(math.pi * self.bump) * (1 - self.bump * 0.4))
            p.drawPixmap(QRectF(r.x() + 28 - z / 2, r.center().y() - z / 2, z, z), pm, QRectF(pm.rect()))
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
            p.fontMetrics().elidedText(self.shown or self.sub, Qt.TextElideMode.ElideRight, w),
        )
        p.end()


DIM = Qt.ItemDataRole.UserRole + 42  # строка «Прочее» - бледно


# стиль -> (подпись, цвет точки)
STYLE_LOOK = {
    "all": ("Любой", "#b9b6c8"),
    "real": ("PBR", "#6cb8ff"),
    "low": ("Low-poly", "#a897ff"),
    "Kenney": ("Kenney", "#f0a35e"),
    "Quaternius": ("Quaternius", "#7ee0a0"),
    "KayKit": ("KayKit", "#ff8ac9"),
}


class StyleSegments(QWidget):
    """Стиль ассетов - сегментами 3x2 в общей рамке: у каждого стиля цветная точка, выбранный подсвечен его
    цветом, стили без ассетов у выбранного вида - бледные. currentData / currentText - как у прежнего списка."""

    changed = pyqtSignal()
    COLS, ROW, PAD, GAP = 3, 28, 4, 3

    def __init__(self, current):
        super().__init__()
        self.keys = [k for k, _t in G.STYLES]
        self.texts = dict(G.STYLES)
        self.cur = current if current in self.keys else "all"
        self.counts = {}
        self.hover = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        rows = -(-len(self.keys) // self.COLS)
        self.setFixedHeight(2 * self.PAD + rows * self.ROW + (rows - 1) * self.GAP)
        self.f = font("title", 9)
        self.fn = font("num", 7.5)

    def currentData(self):
        return self.cur

    def currentText(self):
        return self.texts.get(self.cur, "")

    def set_counts(self, counts):
        """{стиль: сколько у выбранного вида} - для подсказки и бледных пустых сегментов."""
        self.counts = counts
        self.update()

    def cell(self, i):
        w = (self.width() - 2 * self.PAD - (self.COLS - 1) * self.GAP) / self.COLS
        r, c = divmod(i, self.COLS)
        return QRectF(self.PAD + c * (w + self.GAP), self.PAD + r * (self.ROW + self.GAP), w, self.ROW)

    def at(self, pos):
        for i in range(len(self.keys)):
            if self.cell(i).contains(QPointF(pos)):
                return i
        return None

    def mouseMoveEvent(self, e):
        i = self.at(e.position().toPoint())
        if i != self.hover:
            self.hover = i
            k = self.keys[i] if i is not None else None
            n = self.counts.get(k)
            self.setToolTip(f"{self.texts[k]}: {n} шт." if k and n is not None else (self.texts[k] if k else ""))
            self.update()

    def leaveEvent(self, _e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        i = self.at(e.position().toPoint())
        if i is not None and self.keys[i] != self.cur:
            from ui.animations import anim, stop

            self.slide_from = self.pill_rect()  # выделение переезжает с прежнего сегмента на новый
            self.cur = self.keys[i]
            stop(getattr(self, "slide", None))
            self.slide_k = 0.0
            self.slide = anim(self, 300, lambda v: (setattr(self, "slide_k", v), self.update()))
            self.changed.emit()

    def pill_rect(self):
        """Где сейчас рисуется выделение: на полпути между прежним и новым сегментом, пока едет."""
        to = self.cell(self.keys.index(self.cur))
        a, k = getattr(self, "slide_from", None), getattr(self, "slide_k", 1.0)
        if a is None or k >= 1:
            return to
        return QRectF(
            a.x() + (to.x() - a.x()) * k,
            a.y() + (to.y() - a.y()) * k,
            a.width() + (to.width() - a.width()) * k,
            a.height() + (to.height() - a.height()) * k,
        )

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(C["line"]), 1))
        p.setBrush(QColor(C["bg1"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        cur_col = QColor(readable(C["acc"] if self.cur == "all" else STYLE_LOOK.get(self.cur, ("", C["dim"]))[1]))
        fill = QColor(cur_col)
        fill.setAlpha(60)
        p.setPen(QPen(cur_col, 1.2))
        p.setBrush(fill)
        p.drawRoundedRect(self.pill_rect().adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        for i, k in enumerate(self.keys):
            r = self.cell(i)
            text, color = STYLE_LOOK.get(k, (k, C["dim"]))
            if k == "all":  # «Любой» - цветом акцента темы, а не серым
                color = C["acc"]
            col = QColor(readable(color))
            empty = self.counts.get(k, 1) == 0 and k != self.cur
            if i == self.hover and k != self.cur:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(C["bg3"]))
                p.drawRoundedRect(r, 9, 9)
            p.setFont(self.f)
            fm = p.fontMetrics()
            label = fm.elidedText(text, Qt.TextElideMode.ElideRight, int(r.width()) - 20)
            tw = fm.horizontalAdvance(label)
            x = r.center().x() - (tw + 11) / 2  # точка и подпись - вместе по центру сегмента
            dot = QColor(col)
            if empty:
                dot.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QPointF(x + 3, r.center().y()), 3, 3)
            tc = QColor(C["selt"] if k == self.cur else (C["faint"] if empty else C["text"]))
            p.setPen(tc)
            p.drawText(QRectF(x + 11, r.y(), tw + 2, r.height()), Qt.AlignmentFlag.AlignVCenter, label)
        p.end()


class Nav(QWidget):
    """kind - ALL / FAV / вид; theme - None (все темы) / HOME / имя темы."""

    changed = pyqtSignal()
    node_menu = pyqtSignal(object, str)  # правый щелчок по группе или разделу: (ключ узла, подпись)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setMinimumWidth(250)  # уже - подписи карточек, стилей и разделов обрезаются
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
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(panel_head("ЧТО ПОКАЗАТЬ"))
        head.addStretch(1)
        self.compact_btn = QPushButton(lib_icon("menuGrid"), "", objectName="tool", checkable=True)
        self.compact_btn.setToolTip("Карточки видов - значками в одну строку (больше места дереву)")
        self.compact_btn.setFixedSize(26, 22)
        self.compact_btn.setChecked(bool(cfg.get("ue_compact")))
        self.compact_btn.toggled.connect(self.set_compact)
        head.addWidget(self.compact_btn)
        v.addLayout(head)
        self.cards_box = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self.cards_box.setSpacing(4)
        for k in (ALL, "tex", "hdri", "model", "ies", FAV, NEW, SETS):
            c = KindCard(k)
            c.clicked.connect(lambda _c=False, k=k: self.pick_kind(k))
            self.group.addButton(c)
            self.cards[k] = c
            self.cards_box.addWidget(c)
        v.addLayout(self.cards_box)
        v.addSpacing(8)
        v.addWidget(panel_head("СТИЛЬ"))
        # стиль - переключателем в один щелчок: реалистичные / low-poly / один источник; числа в дереве - с ним
        self.style = StyleSegments(cfg.get("ue_style", "all"))
        self.style.changed.connect(self.pick_style)
        v.addWidget(self.style)
        v.addSpacing(4)
        self.theme_lbl = panel_head("ГРУППЫ")
        v.addWidget(self.theme_lbl)
        self.find = QLineEdit(placeholderText="Найти раздел: кровати, деревья...")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(lambda t: filter_tree(self.tree, t))
        v.addWidget(self.find)
        self.tree = make_tree()
        self.tree.currentItemChanged.connect(self.pick_theme)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._node_menu)
        v.addWidget(self.tree, 1)
        self.set_compact(self.compact_btn.isChecked())

    def set_compact(self, on):
        self.cfg["ue_compact"] = on
        box = self.cards_box
        box.setDirection(QBoxLayout.Direction.LeftToRight if on else QBoxLayout.Direction.TopToBottom)
        for c in self.cards.values():
            c.set_compact(on)
        for i in reversed(range(box.count())):  # растяжка нужна только строке
            if box.itemAt(i).spacerItem():
                box.takeAt(i)
        if on:
            box.addStretch(1)

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
        self.style_counts()
        for k in (FAV, NEW, SETS):  # пустые особые карточки не показываются
            self.cards[k].setVisible(bool(self.of_kind(k)) or (k == SETS and bool(self.sets())))
        if self.kind not in self.cards or self.cards[self.kind].isHidden():  # isVisible ложно, пока вкладка скрыта
            self.kind = ALL
        self.cards[self.kind].setChecked(True)
        self.fill_themes()

    def style_counts(self):
        lst = self._of_kind(self.kind, self.items)
        self.style.set_counts({k: sum(1 for a in lst if G.style_ok(a, k)) for k in self.style.keys})

    def pick_kind(self, k):
        if k == self.kind:
            return
        self.kind = self.cfg["ue_kind"] = k
        self.style_counts()
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
        self._finish(pick)
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
                    if sec == G.OTHER:  # неразобранное - бледно: тут ещё есть что разложить
                        ch.setData(0, DIM, True)
                        ch.setToolTip(0, "Не узнано по имени - можно разобрать (правый щелчок по группе)")
                    if self.theme == key:
                        pick = ch
                        it.setExpanded(True)
        for i in range(self.tree.topLevelItemCount()):  # число справа - цветом вида
            self._tint(self.tree.topLevelItem(i), col)
        self._finish(pick)
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

    def _finish(self, pick):
        set_shares(self.tree)
        self.tree.setCurrentItem(pick)
        self.theme = pick.data(0, ROLE)
        if self.find.text():
            filter_tree(self.tree, self.find.text())
        self.tree.blockSignals(False)

    def _tint(self, it, col):
        if it.data(0, DIM):
            faint = QColor(C["faint"])
            it.setForeground(0, faint)
            it.setForeground(1, faint)
        else:
            it.setForeground(1, col)
        for i in range(it.childCount()):
            self._tint(it.child(i), col)

    def pick_theme(self, it, _prev=None):
        self.theme = it.data(0, ROLE) if it else None
        self.cfg["ue_theme"] = self.theme
        self.changed.emit()

    # ------------------------------------------------------------
    def _node_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is not None:
            self.node_menu.emit(it.data(0, ROLE), it.text(0))

    def chosen(self, theme=False):
        """Ассеты выбранного узла дерева (или узла theme - для меню по правому щелчку)."""
        lst = self.of_kind(self.kind)
        th = self.theme if theme is False else theme
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
