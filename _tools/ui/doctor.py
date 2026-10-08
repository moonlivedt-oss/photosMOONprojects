"""Доктор библиотеки: находит картинки, с которыми что-то не так (не открывается, пустая, мелкая,
фон не убран, рисунок обрезан краем, кусок соседа у края, светлая кайма), по всем ядрам.
Найденное можно открыть в редакторе (там есть «Убрать кайму», кисть, кадрирование), показать
в библиотеке или убрать в корзину."""
import os

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

import imaging as K
from ui.common import EXT, LIB, ROLE, SUB, THUMB, bg, in_main, parallel, to_trash
from ui.editor import EditDialog
from ui.widgets import LibList

NAMES = dict(K.PROBLEMS)
HELP = {
    "broken": "файл битый или не картинка - убрать или перегенерировать",
    "empty": "почти ничего не нарисовано - скорее всего, неудачный кусок нарезки",
    "small": "меньше 64 px - для плиток и значков мало",
    "bg": "иконка или наклейка без прозрачности - «Убрать фон» в редакторе",
    "edge": "рисунок упирается в край - обрезан при нарезке; поправить рамку во входящих",
    "neighbor": "у края висит мелкий кусочек - вероятно, от соседа по листу; стереть кистью",
    "fringe": "светлый ореол от старого фона - «Убрать кайму» в редакторе",
}


class DoctorDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.found, self.stop, self.busy = win, {}, [False], False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Доктор библиотеки")
        self.resize(1000, 700)
        self.head = QLabel("Проверяю...", objectName="title")
        self.sub = QLabel(objectName="dim", wordWrap=True)
        self.kind = QComboBox()
        self.kind.currentIndexChanged.connect(self.show_list)
        self.list = LibList(140)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.empty = "Проверяю картинки..."
        self.list.itemDoubleClicked.connect(lambda it: self.edit([it.data(ROLE)]))
        self.list.itemSelectionChanged.connect(self.selected)
        self.tip = QLabel(objectName="dim", wordWrap=True)
        b_edit = QPushButton("Редактировать")
        b_edit.setToolTip("Открыть выбранные в редакторе (двойной щелчок - одну)")
        b_edit.clicked.connect(lambda: self.edit(self.paths()))
        b_show = QPushButton("Показать в библиотеке")
        b_show.clicked.connect(self.show_in_lib)
        b_trash = QPushButton("В корзину")
        b_trash.clicked.connect(self.trash)
        self.again = QPushButton("Проверить заново")
        self.again.clicked.connect(self.run)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        self.acts = (b_edit, b_show, b_trash)
        top = QHBoxLayout()
        top.addWidget(self.head, 1)
        top.addWidget(QLabel("Показать:"))
        top.addWidget(self.kind)
        foot = QHBoxLayout()
        for w in (b_edit, b_show, b_trash):
            foot.addWidget(w)
        foot.addStretch(1)
        foot.addWidget(self.again)
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
        self.again.setEnabled(False)
        self.head.setText("Проверяю...")
        files = [f for f in K.images_in(LIB) if not f.lower().endswith(".svg")]
        stop = self.stop

        def progress(v):
            if not sip.isdeleted(self):
                self.sub.setText("Проверено %d из %d" % v)

        def work():
            out = {}
            for i, (p, res) in enumerate(parallel(K.job_doctor, [(p, None) for p in files], stop)):
                if isinstance(res, list) and res:
                    out[p] = res
                if i % 50 == 0:
                    in_main(progress, (i, len(files)))
            return out, len(files)

        bg(work, self.checked)

    def checked(self, res):
        if sip.isdeleted(self):
            return
        self.busy = False
        self.again.setEnabled(True)
        if isinstance(res, Exception):
            self.head.setText("Не получилось")
            self.sub.setText(str(res))
            return
        self.found, total = res
        counts = {}
        for codes in self.found.values():
            for c in codes:
                counts[c] = counts.get(c, 0) + 1
        self.head.setText("Найдено: %d из %d" % (len(self.found), total) if self.found else "Всё в порядке")
        self.sub.setText("   ·   ".join("%s: %d" % (NAMES[c], counts[c]) for c, _n in K.PROBLEMS if c in counts)
                         or "Проверено %d картинок - проблем нет." % total)
        cur = self.kind.currentData()
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItem("Всё найденное (%d)" % len(self.found), "")
        for c, name in K.PROBLEMS:
            if c in counts:
                self.kind.addItem("%s (%d)" % (name, counts[c]), c)
        self.kind.setCurrentIndex(max(0, self.kind.findData(cur)))
        self.kind.blockSignals(False)
        self.show_list()

    def show_list(self):
        code = self.kind.currentData()
        files = sorted(p for p, codes in self.found.items() if not code or code in codes)
        self.list.clear()
        self.list.reset_anim()
        todo = []
        for i, p in enumerate(files):
            it = QListWidgetItem(os.path.splitext(os.path.basename(p))[0])
            it.setData(ROLE, p)
            it.setData(SUB, ", ".join(NAMES[c].lower() for c in self.found[p]))
            it.setData(EXT, os.path.splitext(p)[1][1:].upper())
            it.setToolTip(os.path.relpath(p, LIB) + "\n" + "\n".join("- " + HELP[c] for c in self.found[p]))
            self.list.addItem(it)
            if "broken" not in self.found[p]:
                todo.append((i, p))
        self.list.empty = "Здесь пусто - проблем такого вида нет." if not self.busy else "Проверяю картинки..."
        self.list.load_tiles(todo, THUMB, "chk")
        self.selected()

    def paths(self):
        return [it.data(ROLE) for it in self.list.selectedItems()]

    def selected(self):
        sel = self.paths()
        for b in self.acts:
            b.setEnabled(bool(sel))
        self.acts[1].setEnabled(len(sel) == 1)
        if len(sel) == 1:
            self.tip.setText("Что делать: " + "; ".join(HELP[c] for c in self.found.get(sel[0], [])))
        else:
            self.tip.setText("Выберите картинку - здесь будет подсказка, что с ней сделать. "
                             "Наведите на плитку - причина во всплывающей подсказке.")

    def edit(self, paths):
        paths = [p for p in paths if "broken" not in self.found.get(p, [])]
        if paths:
            EditDialog(self, self.win, paths, on_saved=self.after_edit).exec()

    def after_edit(self, text):
        self.win.lib.done(text)
        self.run()

    def show_in_lib(self):
        sel = self.paths()
        if len(sel) != 1:
            return
        p = sel[0]
        self.win.tabs.setCurrentIndex(1)
        self.win.lib.show_section(os.path.dirname(p))
        lst = self.win.lib.list
        for i in range(lst.count()):
            if lst.item(i).data(ROLE) == p:
                lst.setCurrentRow(i)
                lst.scrollToItem(lst.item(i))
                break
        self.accept()

    def trash(self):
        sel = self.paths()
        if not sel or QMessageBox.question(self, "В корзину", "Убрать в корзину: %d шт.?\n(вернуть можно из корзины Windows)"
                                           % len(sel)) != QMessageBox.StandardButton.Yes:
            return
        n, steps = to_trash(sel)
        for p in sel:
            if not os.path.exists(p):
                self.found.pop(p, None)
        self.win.push("В корзине: %d шт." % n, steps)
        self.win.lib.done("В корзине: %d шт." % n + ("   Ctrl+Z - вернуть" if steps else ""))
        self.show_list()

    def reject(self):
        self.stop[0] = True                 # проверка по ядрам бросается, если окно закрыли
        super().reject()
