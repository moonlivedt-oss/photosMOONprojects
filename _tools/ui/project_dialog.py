"""Проект: палитра сайта или игры, какие наборы библиотеки к ней подходят (library/project_fit) и проверка перед
публикацией одной кнопкой - лицензии, вес, видно ли иконки, сцена Unreal (library/publish_check)."""

import os

from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

import imaging as K
from library import credits, db, project_fit, publish_check
from library.common import in_process
from ui.common import LIB, bg, in_main
from ui.thumbnails import lib_icon, to_pix

LEVEL = {"ok": "#4cb782", "warn": "#f2c94c", "bad": "#e5484d"}


def strip(files, color, side=72):
    """Несколько картинок набора в ряд на фоне проекта."""
    out = Image.new("RGBA", (side * 4 + 12, side), color)
    for i, f in enumerate(files[:4]):
        try:
            im = K.load(f)
        except Exception:
            continue
        im.thumbnail((side - 8, side - 8), Image.Resampling.LANCZOS)
        out.alpha_composite(im, (i * (side + 4) + (side - im.width) // 2, (side - im.height) // 2))
    return out


class Chip(QPushButton):
    def __init__(self, hexv, on_click):
        super().__init__()
        self.setFixedSize(30, 30)
        self.setToolTip(f"{hexv} - щелчок: сделать фоном")
        self.setStyleSheet(f"QPushButton{{background:{hexv};border:1px solid #8888;border-radius:8px}}")
        self.clicked.connect(lambda: on_click(hexv))


class ProjectDialog(QDialog):
    def __init__(self, win, tab=0):
        super().__init__(win, Qt.WindowType.Window)
        self.win, self.cfg = win, win.cfg
        self.bg_color, self.colors, self.busy = "#ffffff", [], False
        self.bgs = []  # все фоны проекта (светлая и тёмная тема из CSS) - видно должно быть на каждом
        self.setWindowTitle("Проект: палитра и проверка перед публикацией")
        self.setWindowIcon(lib_icon("checklist"))
        self.resize(1100, 760)
        # --- папка проекта
        self.folder = QComboBox(editable=True)
        self.folder.setMinimumWidth(420)
        known = [f for f, _b, _c in db.projects()]
        for f in dict.fromkeys(known + [self.cfg.get("credits_dir", "")]):
            if f:
                self.folder.addItem(f)
        self.folder.currentTextChanged.connect(self.folder_changed)
        pick = QPushButton(lib_icon("folder"), "Выбрать...")
        pick.clicked.connect(self.pick_folder)
        top = QHBoxLayout()
        top.addWidget(QLabel("Папка проекта:"))
        top.addWidget(self.folder, 1)
        top.addWidget(pick)
        # --- палитра
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        self.hex = QLineEdit(placeholderText="#0d1117, #1f6feb, #f78166 - первый цвет - фон")
        self.hex.returnPressed.connect(self.typed)
        b_img = QPushButton(lib_icon("image-file"), "Из скриншота...")
        b_img.clicked.connect(self.from_image)
        b_css = QPushButton(lib_icon("code-file-brackets"), "Из CSS проекта")
        b_css.setToolTip("Фон страницы (светлая и тёмная тема, с переменными) и частые цвета из .css проекта")
        b_css.clicked.connect(self.from_css)
        self.b_save = QPushButton(lib_icon("save"), "Запомнить за проектом")
        self.b_save.clicked.connect(self.save_palette)
        self.bg_label = QLabel(objectName="dim")
        pal = QHBoxLayout()
        pal.addWidget(QLabel("Палитра:"))
        pal.addLayout(self.chips)
        pal.addWidget(self.hex, 1)
        pal.addWidget(b_img)
        pal.addWidget(b_css)
        pal.addWidget(self.b_save)
        # --- вкладка «Подходящие наборы»
        self.only = QComboBox()
        for t, v in (("Иконки и наклейки", "art"), ("Фоны и узоры", "bg"), ("Все наборы", "all")):
            self.only.addItem(t, v)
        self.only.currentIndexChanged.connect(self.run_fit)
        self.fit_head = QLabel("Задайте палитру проекта", objectName="title")
        self.near = QLabel(objectName="dim", wordWrap=True)
        self.list = QListWidget()
        self.list.setIconSize(QSize(300, 72))
        self.list.itemDoubleClicked.connect(lambda _it: self.show_set())
        b_show = QPushButton("Показать в библиотеке")
        b_show.clicked.connect(self.show_set)
        b_recolor = QPushButton(lib_icon("color-palette"), "Перекрасить в цвета проекта...")
        b_recolor.setToolTip("Копии картинок набора в цветах проекта (оригиналы не меняются)")
        b_recolor.clicked.connect(self.recolor)
        f_top = QHBoxLayout()
        f_top.addWidget(self.fit_head, 1)
        f_top.addWidget(self.only)
        f_foot = QHBoxLayout()
        f_foot.addWidget(b_show)
        f_foot.addWidget(b_recolor)
        f_foot.addStretch(1)
        fit_w = QWidget()
        fv = QVBoxLayout(fit_w)
        fv.addLayout(f_top)
        fv.addWidget(self.near)
        fv.addWidget(self.list, 1)
        fv.addLayout(f_foot)
        # --- вкладка «Перед публикацией»
        self.rep_head = QLabel("Выберите папку проекта", objectName="title")
        self.report = QTextBrowser(openExternalLinks=True)
        b_run = QPushButton(lib_icon("checklist"), "Проверить", objectName="accent")
        b_run.clicked.connect(self.run_check)
        b_write = QPushButton(lib_icon("save"), f"Сохранить {publish_check.REPORT}")
        b_write.clicked.connect(self.write_report)
        b_credits = QPushButton(lib_icon("Книга"), "Создать CREDITS.md")
        b_credits.clicked.connect(self.write_credits)
        r_foot = QHBoxLayout()
        r_foot.addWidget(b_run)
        r_foot.addWidget(b_write)
        r_foot.addWidget(b_credits)
        r_foot.addStretch(1)
        rep_w = QWidget()
        rv = QVBoxLayout(rep_w)
        rv.addWidget(self.rep_head)
        rv.addWidget(self.report, 1)
        rv.addLayout(r_foot)
        self.tabs = QTabWidget()
        self.tabs.addTab(fit_w, "Подходящие наборы")
        self.tabs.addTab(rep_w, "Перед публикацией")
        self.tabs.setCurrentIndex(tab)
        self.tabs.currentChanged.connect(lambda i: self.run_check() if i == 1 and self.check_res is None else None)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addLayout(pal)
        v.addWidget(self.bg_label)
        v.addWidget(self.tabs, 1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(close)
        v.addLayout(foot)
        self.res, self.check_res = None, None
        self.folder_changed(self.folder.currentText())

    # ------------------------------------------------------------ папка и палитра
    def project(self):
        p = self.folder.currentText().strip()
        return p if p and os.path.isdir(p) else None

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Папка проекта", self.project() or "")
        if d:
            if self.folder.findText(d) < 0:
                self.folder.insertItem(0, d)
            self.folder.setCurrentText(d)

    def folder_changed(self, _text):
        p = self.project()
        if not p:
            return
        got = project_fit.load(p)
        if got:
            self.set_palette(got[0], got[1], run=True)
        else:
            self.css_palette(p, quiet=True)
        if self.tabs.currentIndex() == 1:
            self.run_check()

    def set_palette(self, bg_hex, colors, run=True, note="", bgs=None):
        self.bg_color = bg_hex
        self.bgs = list(bgs) if bgs else [bg_hex]
        self.colors = list(dict.fromkeys([bg_hex] + list(colors)))[:10]
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        for c in self.colors:
            self.chips.addWidget(Chip(c, self.make_bg))
        self.hex.setText(", ".join(self.colors))
        themes = f" и {', '.join(self.bgs[1:])} (вторая тема)" if len(self.bgs) > 1 else ""
        self.bg_label.setText(
            f"Фон проекта: {bg_hex}{themes}" + (f" ({note})" if note else "") + ". Щелчок по цвету - сделать фоном."
        )
        if run:
            self.run_fit()

    def make_bg(self, hexv):
        self.set_palette(hexv, self.colors)

    def typed(self):
        try:
            cols = [project_fit.norm(c) for c in self.hex.text().replace(";", ",").split(",") if c.strip()]
        except ValueError as e:
            self.bg_label.setText(f"Не цвет: {e}")
            return
        if cols:
            self.set_palette(cols[0], cols)

    def from_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Скриншот сайта или игры", "", "Картинки (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            try:
                bg_hex, cols = project_fit.from_image(path)
            except Exception as e:
                self.bg_label.setText(f"Не открылась: {e}")
                return
            self.set_palette(bg_hex, cols, note="из скриншота")

    def css_palette(self, p, quiet=False):
        """Фоны страницы (обе темы) и частые цвета из CSS проекта. -> нашлось ли"""
        css = project_fit.css_backgrounds(p) if p else []
        if not css:
            return False
        bgs = [c for _n, c in css]
        self.set_palette(bgs[0], bgs + project_fit.css_accents(p), note="из CSS проекта", bgs=bgs)
        return True

    def from_css(self):
        p = self.project()
        if self.css_palette(p):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Файл стилей", p or "", "Стили (*.css *.scss *.html)")
        if path:
            try:
                bg_hex, cols = project_fit.from_css(path)
            except Exception as e:
                self.bg_label.setText(f"Не получилось: {e}")
                return
            self.set_palette(bg_hex, cols, note=os.path.basename(path))

    def save_palette(self):
        p = self.project()
        if not p:
            self.win.say("Сначала выберите папку проекта")
            return
        project_fit.save(p, self.bg_color, self.colors)
        self.win.say(f"Палитра запомнена за «{os.path.basename(p)}» - её возьмёт и проверка перед публикацией")

    # ------------------------------------------------------------ подходящие наборы
    def run_fit(self):
        if not self.colors or self.busy:
            return
        self.busy = True
        bg_hex, colors, only = self.bg_color, list(self.colors), self.only.currentData()
        bgs = list(self.bgs) or [bg_hex]
        self.fit_head.setText("Оцениваю наборы...")

        def step(d, t):
            in_main(lambda v: None if sip.isdeleted(self) else self.fit_head.setText("Оцениваю: %d из %d" % v), (d, t))

        def work():
            res = project_fit.fit(bgs, colors, step=step, only=only, limit=40)
            for x in res["sets"]:
                x["strip"] = strip(x["sample"], bg_hex)
            return res

        bg(work, self.fitted)

    def fitted(self, res):
        if sip.isdeleted(self):
            return
        self.busy = False
        if isinstance(res, Exception):
            self.fit_head.setText(f"Не получилось: {res}")
            return
        self.res = res
        self.fit_head.setText(f"Подходят лучше всего ({len(res['sets'])})")
        pal = res["palette"]
        self.near.setText(
            f"Ближе всего к цветам проекта палитра «{pal['name']}» из Prompts.html: новые наборы генерировать в ней "
            "или перекрасить готовые в цвета проекта."
            if pal
            else ""
        )
        self.list.clear()
        for x in res["sets"]:
            parts = [f"подходит на {round(x['total'] * 100)}%"]
            if x["contrast"] is not None:
                parts.append(f"видно на фоне: {round(x['contrast'] * 100)}%")
            parts.append(f"цвета близки: {round(x['harmony'] * 100)}%")
            it = QListWidgetItem(QIcon(to_pix(x["strip"])), f"{x['set']}  ({x['count']})\n" + ", ".join(parts))
            it.setData(Qt.ItemDataRole.UserRole, x)
            it.setForeground(QColor(LEVEL["ok" if x["total"] >= 0.7 else "warn" if x["total"] >= 0.5 else "bad"]))
            self.list.addItem(it)

    def cur_set(self):
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def show_set(self):
        x = self.cur_set()
        if x:
            self.win.tabs.setCurrentIndex(1)
            self.win.lib.show_section(x["folder"])

    def recolor(self):
        from ui.tools_dialogs import PaletteDialog

        x = self.cur_set()
        if not x:
            self.win.say("Выберите набор в списке")
            return
        files = [f for f in K.images_in(x["folder"]) if os.path.dirname(f) == x["folder"]]
        self.pal_dlg = PaletteDialog(self.win, files, colors=self.colors, title="Перекраска в цвета проекта")
        self.pal_dlg.show()

    # ------------------------------------------------------------ перед публикацией
    def run_check(self):
        p = self.project()
        if not p:
            self.rep_head.setText("Выберите папку проекта")
            return
        if credits.inside(p, LIB):
            self.rep_head.setText("Это папка библиотеки - нужна папка проекта")
            return
        self.rep_head.setText("Проверяю...")
        cfg = dict(self.cfg)
        bg(lambda: in_process(publish_check.check, p, cfg), self.checked)

    def checked(self, res):
        if sip.isdeleted(self):
            return
        if isinstance(res, Exception):
            self.rep_head.setText(f"Не получилось: {res}")
            return
        self.check_res = res
        say = {"ok": "Можно публиковать", "warn": "Есть что поправить", "bad": "Нужно поправить до публикации"}
        self.rep_head.setText(say[res["level"]])
        self.rep_head.setStyleSheet(f"color:{LEVEL[res['level']]}")
        self.report.setMarkdown(publish_check.markdown(res))

    def write_report(self):
        p = self.project()
        if not p:
            return
        try:
            res = publish_check.write(p, dict(self.cfg))
        except Exception as e:
            self.win.say(f"Не получилось: {e}")
            return
        self.checked(res)
        QDesktopServices.openUrl(QUrl.fromLocalFile(res["report"]))

    def write_credits(self):
        p = self.project()
        if not p:
            return
        try:
            res = credits.write(p, self.cfg)
        except Exception as e:
            self.win.say(f"Не получилось: {e}")
            return
        self.win.say(f"{os.path.basename(res['path'])}: картинок {res['images']}, ассетов {res['assets']}")
        self.run_check()
