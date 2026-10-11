"""Проверки манеры: «Выбивается из набора» (другие цвета, нет обводки, больше деталей - imaging.style) и
«Контраст на фонах» (видно ли иконку на фоне палитры, белом и тёмном - WCAG, imaging.contrast)."""

import os

from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import imaging as K
from library import style_check
from ui.common import EXT, LIB, ROLE, SUB, THUMB, bg, in_main
from ui.thumbnails import to_pix
from ui.widgets import LibList

VERDICT = {"хорошо": "#4cb782", "так себе": "#f2c94c", "плохо видно": "#e5484d"}


def show_in_library(win, p):
    """Открыть раздел картинки во вкладке «Библиотека» и выделить её."""
    win.tabs.setCurrentIndex(1)
    win.lib.show_section(os.path.dirname(p))
    lst = win.lib.list
    for i in range(lst.count()):
        if lst.item(i).data(ROLE) == p:
            lst.setCurrentRow(i)
            lst.scrollToItem(lst.item(i))
            break


# ================================================================ выбивается из набора
class OddDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.found, self.stop, self.busy = win, [], [False], False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Выбивается из набора")
        self.resize(1000, 700)
        self.head = QLabel("Сравниваю наборы...", objectName="title")
        self.sub = QLabel(objectName="dim", wordWrap=True)
        self.sub.setText(
            "Набор - папка с картинками (от 6 штук). Сравнивается манера, а не смысл: цвета и оттенок, обводка, "
            "плотность рисунка, мелкие детали, поле прозрачности. Чем выше в списке - тем сильнее отличие."
        )
        self.imported = QCheckBox("И чужие наборы (Kenney, Hero Patterns)")
        self.imported.setToolTip("В чужих наборах в одной папке бывают разные виды деталей - находок будет много")
        self.imported.toggled.connect(self.run)
        self.list = LibList(140)
        self.list.empty = "Сравниваю наборы..."
        self.list.itemDoubleClicked.connect(lambda it: self.show_it(it.data(ROLE)))
        self.list.itemSelectionChanged.connect(self.selected)
        self.tip = QLabel(objectName="dim", wordWrap=True)
        b_show = QPushButton("Показать в библиотеке")
        b_show.clicked.connect(lambda: self.show_it(self.cur()))
        b_edit = QPushButton("Редактировать")
        b_edit.clicked.connect(self.edit)
        self.acts = (b_show, b_edit)
        again = QPushButton("Проверить заново")
        again.clicked.connect(self.run)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        top = QHBoxLayout()
        top.addWidget(self.head, 1)
        top.addWidget(self.imported)
        foot = QHBoxLayout()
        for w in self.acts:
            foot.addWidget(w)
        foot.addStretch(1)
        foot.addWidget(again)
        foot.addWidget(close)
        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.sub)
        v.addWidget(self.list, 1)
        v.addWidget(self.tip)
        v.addLayout(foot)
        self.selected()
        self.run()

    def run(self):
        if self.busy:
            return
        self.busy, self.stop[0] = True, False
        self.head.setText("Сравниваю наборы...")
        self.list.clear()
        imported, stop = self.imported.isChecked(), self.stop

        def step(done, total):
            in_main(
                lambda v: None if sip.isdeleted(self) else self.head.setText("Сравниваю: %d из %d" % v), (done, total)
            )

        bg(lambda: style_check.odd_ones(None, imported, stop, step), self.done)

    def done(self, res):
        if sip.isdeleted(self):
            return
        self.busy = False
        if isinstance(res, Exception):
            self.head.setText("Не получилось: %s" % res)
            return
        self.found = res
        self.head.setText("Выбивается: %d" % len(res) if res else "Все наборы ровные")
        self.list.clear()
        self.list.reset_anim()
        todo = []
        for i, x in enumerate(res):
            p = x["path"]
            it = QListWidgetItem(os.path.splitext(os.path.basename(p))[0])
            it.setData(ROLE, p)
            it.setData(SUB, x["reasons"][0][2])
            it.setData(EXT, os.path.splitext(p)[1][1:].upper())
            pals = f"\nТак же в палитрах: {', '.join(x['palettes'])}" if len(x["palettes"]) > 1 else ""
            it.setToolTip(f"{x['set']}\n" + "\n".join("- " + w for _n, _s, w in x["reasons"]) + pals)
            self.list.addItem(it)
            todo.append((i, p))
        self.list.empty = "Ничего не выбивается - наборы ровные."
        self.list.load_tiles(todo, THUMB, "odd")
        self.selected()

    def cur(self):
        it = self.list.currentItem()
        return it.data(ROLE) if it and it.isSelected() else None

    def selected(self):
        p = self.cur()
        for b in self.acts:
            b.setEnabled(bool(p))
        x = next((x for x in self.found if x["path"] == p), None)
        if x:
            self.tip.setText(
                f"Набор «{x['set']}»: "
                + "; ".join(w for _n, _s, w in x["reasons"])
                + ". Если так задумано - пропустить; иначе перегенерировать или поправить цвет в редакторе."
            )
        else:
            self.tip.setText("Выберите картинку - здесь будет, чем она отличается от остальных в наборе.")

    def show_it(self, p):
        if p:
            show_in_library(self.win, p)
            self.accept()

    def edit(self):
        from ui.editor import EditDialog

        p = self.cur()
        if p:
            EditDialog(self, self.win, [p], on_saved=lambda text: (self.win.lib.done(text), self.run())).exec()

    def reject(self):
        self.stop[0] = True
        super().reject()


# ================================================================ контраст на фонах
CELL = 104


def on_bg(path, color, side=CELL - 8):
    im = K.load(path)
    im.thumbnail((side - 12, side - 12), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (side, side), color)
    out.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return out


class ContrastDialog(QDialog):
    """Каждая картинка - на каждом фоне, под ней - контраст края и вердикт (WCAG для значков - от 3:1)."""

    def __init__(self, win, paths):
        super().__init__(win)
        self.win, self.paths, self.extra = win, list(paths)[:40], []
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Контраст на фонах")
        self.resize(900, 640)
        self.head = QLabel("Считаю...", objectName="title")
        sub = QLabel(
            "Смотрится край рисунка - по силуэту глаз и находит значок. Для значков WCAG требует контраст от 3:1: "
            "«хорошо» - так у большей части края, «так себе» - только от 2:1 (видно, но бледно), «плохо видно» - "
            "меньше. Если белая обводка сливается с фоном, смотрится рисунок под ней. Фон палитры - основа палитры папки.",
            objectName="dim",
            wordWrap=True,
        )
        add = QPushButton("Свой фон...")
        add.setToolTip("Цвет фона сайта или игры - добавится столбцом")
        add.clicked.connect(self.add_bg)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setSpacing(6)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.body)
        foot = QHBoxLayout()
        foot.addWidget(add)
        foot.addStretch(1)
        foot.addWidget(close)
        v = QVBoxLayout(self)
        v.addWidget(self.head)
        v.addWidget(sub)
        v.addWidget(scroll, 1)
        v.addLayout(foot)
        self.run()

    def add_bg(self):
        c = QColorDialog.getColor(parent=self, title="Цвет фона")
        if c.isValid():
            self.extra.append(c.name())
            self.run()

    def run(self):
        paths, extra = self.paths, list(self.extra)

        def work():
            res = style_check.contrast_of(paths, extra)
            pics = {}
            for p, r in res.items():
                if r:
                    pics[p] = {b["color"]: on_bg(p, b["color"]) for b in r["bgs"]}
            return res, pics

        self.head.setText("Считаю...")
        bg(work, self.done)

    def done(self, res):
        if sip.isdeleted(self):
            return
        if isinstance(res, Exception):
            self.head.setText("Не получилось: %s" % res)
            return
        res, pics = res
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        rows = [(p, r) for p, r in res.items() if r]
        skipped = len(res) - len(rows)
        bad = sum(1 for _p, r in rows if r["worst"]["verdict"] == "плохо видно")
        self.head.setText(
            f"Проверено: {len(rows)}"
            + (f", плохо видно хотя бы на одном фоне: {bad}" if bad else ", везде видно")
            + (f"  (без прозрачности, пропущено: {skipped})" if skipped else "")
        )
        if not rows:
            return
        for col, b in enumerate(rows[0][1]["bgs"], 1):
            lab = QLabel(b["name"], objectName="dim", alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
            lab.setFixedWidth(CELL)
            self.grid.addWidget(lab, 0, col)
        for row, (p, r) in enumerate(rows, 1):
            name = QLabel(os.path.splitext(os.path.basename(p))[0], wordWrap=True)
            name.setFixedWidth(140)
            name.setToolTip(os.path.relpath(p, LIB))
            self.grid.addWidget(name, row, 0)
            for col, b in enumerate(r["bgs"], 1):
                cell = QWidget()
                cv = QVBoxLayout(cell)
                cv.setContentsMargins(0, 0, 0, 0)
                cv.setSpacing(2)
                pic = QLabel()
                pic.setPixmap(to_pix(pics[p][b["color"]]))
                pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pic.setToolTip(
                    f"{b['color']}: край с контрастом от 3:1 - {round(b['share'] * 100)}%"
                    + ("\n" + b["note"] if b.get("note") else "")
                )
                txt = QLabel(f"{b['ratio']}:1  {b['verdict']}", alignment=Qt.AlignmentFlag.AlignCenter)
                txt.setStyleSheet(f"color:{VERDICT[b['verdict']]};font-size:9pt")
                cv.addWidget(pic)
                cv.addWidget(txt)
                cell.setFixedWidth(CELL)
                self.grid.addWidget(cell, row, col)
        self.grid.setRowStretch(len(rows) + 1, 1)
        self.grid.setColumnStretch(len(rows[0][1]["bgs"]) + 1, 1)
