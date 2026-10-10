"""Настройки окна в одном месте (кнопка «Настройки» вверху): оформление, входящие, Unreal и 3D, ИИ-помощники.
Каждый переключатель меняет то же, что и его двойник в окне (галочка во входящих, кнопка в 3D), - сразу."""

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.common import HERE
from ui.thumbnails import lib_icon
from ui.widgets import panel_head


class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.cfg = win, win.cfg
        self.setWindowTitle("Настройки")
        self.setWindowIcon(lib_icon("gear"))
        self.resize(620, 720)
        body = QWidget()
        self.v = QVBoxLayout(body)
        self.v.setContentsMargins(18, 14, 18, 14)
        self.v.setSpacing(8)

        # --- оформление
        self.head("ОФОРМЛЕНИЕ")
        row = QHBoxLayout()
        self.theme_btns = {}
        for key, (name, pal) in theme.THEMES.items():
            b = QPushButton(name, checkable=True)
            b.setMinimumSize(140, 58)
            b.setStyleSheet(
                f"QPushButton{{background:{pal['bg1']};color:{pal['text']};border:2px solid {pal['line2']};"
                f"border-radius:14px;font-weight:600}}QPushButton:checked{{border-color:{theme.C['acc']}}}"
            )
            b.clicked.connect(lambda _c=False, k=key: self.pick(theme_key=k))
            self.theme_btns[key] = b
            row.addWidget(b)
        row.addStretch(1)
        self.v.addLayout(row)
        row2 = QHBoxLayout()
        self.acc_btns = {}
        for key, (name, a, a2) in theme.ACCENTS.items():
            b = QPushButton(name, checkable=True)
            b.setMinimumHeight(38)
            b.setStyleSheet(
                f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {a},stop:1 {a2});"
                f"color:#16131f;font-weight:700;border:2px solid transparent;border-radius:12px;padding:4px 12px}}"
                f"QPushButton:checked{{border-color:{theme.C['text']}}}"
            )
            b.clicked.connect(lambda _c=False, k=key: self.pick(accent=k))
            self.acc_btns[key] = b
            row2.addWidget(b)
        row2.addStretch(1)
        self.v.addLayout(row2)
        self.check(
            "Живой фон - плывущие пятна цвета (F9)",
            self.cfg.get("live_bg", True),
            self.set_live_bg,
            "Выключите на слабом компьютере или если отвлекает",
        )

        # --- входящие
        self.head("ВХОДЯЩИЕ")
        gen = QHBoxLayout()
        self.gen_lbl = QLabel(wordWrap=True, objectName="dim")
        pick = QPushButton(lib_icon("folder"), "Выбрать...")
        pick.clicked.connect(lambda: (win.pick_gen(), self.show_gen()))
        off = QPushButton("Не следить")
        off.clicked.connect(self.gen_off)
        gen.addWidget(self.gen_lbl, 1)
        gen.addWidget(pick)
        gen.addWidget(off)
        self.v.addWidget(QLabel("Папка генератора - новые картинки из неё сами приходят во входящие:"))
        self.v.addLayout(gen)
        self.show_gen()
        inbox = win.inbox
        if inbox.auto_tags.isVisible() or win.sem.ok:
            self.check(
                "Ставить подсказанные метки при сохранении", inbox.auto_tags.isChecked(), inbox.auto_tags.setChecked
            )
        self.check("Исходный лист после нарезки убирать в _sources", inbox.keep.isChecked(), inbox.keep.setChecked)

        # --- Unreal и 3D
        self.head("UNREAL И 3D")
        ue = win.unreal
        self.check(
            "Живой 3D в панели вкладки «Unreal»",
            ue.live.isChecked(),
            ue.live.setChecked,
            "Модель вращается прямо в карточке справа; выключите, если видеокарта слабая",
        )
        self.check(
            "Карточки видов - значками в одну строку",
            ue.nav.compact_btn.isChecked(),
            ue.nav.compact_btn.setChecked,
        )
        self.check("Окно 3D: подиум, тень и сетка (G)", self.cfg.get("ue_floor", True), self.set_floor)
        self.check("Окно 3D: человек 180 см рядом для масштаба (H)", self.cfg.get("ue_human", False), self.set_human)

        # --- ИИ-помощники
        self.head("ИИ-ПОМОЩНИКИ")
        self.check(
            "Разрешить помощникам менять библиотеку (иначе - только поиск и просмотр)",
            self.cfg.get("ai_write", True),
            self.set_ai_write,
        )
        ai = QPushButton(lib_icon("sparkles"), "Подключить помощников и что они сделали...")
        ai.clicked.connect(win.agents)
        self.v.addWidget(ai, 0, Qt.AlignmentFlag.AlignLeft)

        # --- данные
        self.head("ДАННЫЕ")
        data = QHBoxLayout()
        safe = QPushButton(lib_icon("first-aid-kit"), "Проверка и восстановление...")
        safe.clicked.connect(win.safety)
        folder = QPushButton(lib_icon("folder"), "Папка настроек")
        folder.setToolTip("settings.json, база library.db и резервные копии")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(HERE)))
        data.addWidget(safe)
        data.addWidget(folder)
        data.addStretch(1)
        self.v.addLayout(data)
        self.v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.addWidget(scroll, 1)
        ok = QPushButton("Готово", objectName="primary")
        ok.clicked.connect(self.accept)
        lay.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        self.mark()

    # ------------------------------------------------------------
    def head(self, text):
        self.v.addSpacing(6)
        self.v.addWidget(panel_head(text))

    def check(self, text, on, fn, tip=""):
        c = QCheckBox(text)
        c.setChecked(bool(on))
        c.setToolTip(tip)
        c.toggled.connect(fn)
        self.v.addWidget(c)
        return c

    def mark(self):
        for k, b in self.theme_btns.items():
            b.setChecked(k == theme.CURRENT["theme"])
        for k, b in self.acc_btns.items():
            b.setChecked(k == theme.CURRENT["accent"])

    def pick(self, theme_key=None, accent=None):
        self.cfg["theme"] = theme_key or self.cfg.get("theme", "dark")
        self.cfg["accent"] = accent or self.cfg.get("accent", "lavender")
        self.win.apply_theme()
        self.mark()

    def set_live_bg(self, on):
        self.cfg["live_bg"] = on
        self.win.aurora.set_live(on)

    def show_gen(self):
        d = self.cfg.get("gen_dir")
        self.gen_lbl.setText(d if d else "не задана")

    def gen_off(self):
        self.cfg["gen_dir"] = ""
        self.win.show_gen()
        self.show_gen()

    def viewer(self):
        return getattr(self.win.unreal, "viewer", None)

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
