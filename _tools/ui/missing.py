"""Чего не хватает: карточки Prompts.html (наборы и одиночные) против палитр - что уже лежит
в библиотеке, что сделано частично, чего нет. По ячейке: копировать промпт или имя файла с меткой,
открыть папку, а если набор уже есть в другой палитре - перекрасить его в эту без генерации."""
import os

from PyQt6 import sip
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from library import prompts
from ui.common import LIB, bg
from ui.editor import EditDialog, swatch_icon
from ui.theme import C


def short_name(name):
    """Подпись столбца: палитра коротко («Фиолетовая ночь» -> «Фиолет.»)."""
    return name if len(name) <= 7 else name[:6].rstrip() + "."


class MissingDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Чего не хватает в наборах")
        self.resize(1280, 760)
        data = prompts.load() or {"cards": [], "node": False}
        self.pals = prompts.palettes()
        self.cards = [c for c in data["cards"] if prompts.has_pal(c)]
        self.stat, self.cur, self.node = {}, None, bool(data.get("node"))

        self.head = QLabel("Считаю...", objectName="title")
        self.sub = QLabel(objectName="dim", wordWrap=True)
        if not data.get("node"):
            self.sub.setText("Карточки берутся из Prompts.html через node - он не найден. Поставьте Node.js "
                             "(nodejs.org) и откройте окно снова; палитры для перекраски работают и без него.")
        self.sec = QComboBox()
        self.sec.addItem("Все разделы", "")
        for s in dict.fromkeys(c["sec"] for c in self.cards):
            self.sec.addItem(s, s)
        self.sec.currentIndexChanged.connect(self.fill)
        self.only = QCheckBox("Только где чего-то нет")
        self.only.setChecked(True)
        self.only.toggled.connect(self.fill)
        self.mine = QCheckBox("Только задуманная палитра")
        self.mine.setToolTip("Палитра, в которой карточка задумана на странице («Как задумано»)")
        self.mine.toggled.connect(self.fill)
        top = QHBoxLayout()
        top.addWidget(self.head, 1)
        for w in (self.sec, self.only, self.mine):
            top.addWidget(w)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setDefaultSectionSize(64)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setIconSize(QSize(30, 12))
        self.table.horizontalHeader().setMinimumHeight(46)
        self.table.currentCellChanged.connect(lambda r, c, *_: self.pick(r, c))

        # справа - про выбранную ячейку
        self.title = QLabel(objectName="head", wordWrap=True)
        self.info = QLabel(objectName="dim", wordWrap=True)
        self.miss = QLabel(objectName="dim", wordWrap=True)
        self.miss.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.b_prompt = QPushButton("Копировать промпт", objectName="primary")
        self.b_prompt.clicked.connect(self.copy_prompt)
        self.b_label = QPushButton("Копировать имя файла")
        self.b_label.setToolTip("Назовите так сгенерированный лист - окно само нарежет и разложит его")
        self.b_label.clicked.connect(self.copy_label)
        self.src = QComboBox()
        self.src.setToolTip("Готовая палитра этого набора - из неё перекрасить")
        self.b_recolor = QPushButton("Перекрасить из готовой")
        self.b_recolor.setToolTip("Взять набор из выбранной готовой палитры и перекрасить в эту - без генерации.\n"
                                  "Откроется редактор: можно поправить силу перекраски и сохранить.")
        self.b_recolor.clicked.connect(self.recolor)
        self.b_open = QPushButton("Открыть папку")
        self.b_open.clicked.connect(self.open_folder)
        side = QWidget()
        sv = QVBoxLayout(side)
        for w in (self.title, self.info, self.miss, self.b_prompt, self.b_label):
            sv.addWidget(w)
        sv.addSpacing(10)
        sv.addWidget(QLabel("ПЕРЕКРАСКА", objectName="faint"))
        sv.addWidget(self.src)
        sv.addWidget(self.b_recolor)
        sv.addSpacing(10)
        sv.addWidget(self.b_open)
        sv.addStretch(1)
        legend = QLabel("Ячейка: «есть» - готово (2/3 имён и больше), число - сделано частично, пусто - нет. "
                        "Жирным и точкой - задуманная палитра карточки.", objectName="dim", wordWrap=True)
        sv.addWidget(legend)
        side.setMinimumWidth(300)
        split = QSplitter()
        split.addWidget(self.table)
        split.addWidget(side)
        split.setStretchFactor(0, 1)
        split.setSizes([920, 320])
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(close)
        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.sub)
        v.addWidget(split, 1)
        v.addLayout(foot)
        self.pick(-1, -1)
        self.refresh()

    def refresh(self):
        cards, pals = self.cards, self.pals

        def work():
            return {(i, p[0]): prompts.status(c, p[0]) for i, c in enumerate(cards) for p in pals}

        def done(res):
            if sip.isdeleted(self) or isinstance(res, Exception):
                return
            self.stat = res
            ready = sum(1 for g in res.values() if prompts.done(*g))
            mine = sum(1 for i, c in enumerate(cards) if prompts.done(*res.get((i, c["pal"]), (0, 1))))
            self.head.setText("Готово: %d из %d" % (ready, len(res)))
            if self.node:
                self.sub.setText("Карточек: %d, палитр: %d. В задуманных палитрах готово %d из %d."
                                 % (len(cards), len(pals), mine, len(cards)))
            self.fill()

        bg(work, done)

    def rows(self):
        sec = self.sec.currentData()
        out = []
        for i, c in enumerate(self.cards):
            if sec and c["sec"] != sec:
                continue
            cols = [p for p in self.pals if not self.mine.isChecked() or p[0] == c["pal"]]
            if self.only.isChecked() and self.stat and all(prompts.done(*self.stat.get((i, p[0]), (0, 1))) for p in cols):
                continue
            out.append(i)
        return out

    def fill(self):
        if not self.stat:
            return
        rows = self.rows()
        pals = self.pals
        self.shown = rows
        t = self.table
        t.blockSignals(True)
        t.clear()
        t.setRowCount(len(rows))
        t.setColumnCount(len(pals))
        for j, (_pid, name, _f, cols) in enumerate(pals):
            h = QTableWidgetItem(swatch_icon(cols, 30, 12), short_name(name))
            h.setToolTip(name)
            t.setHorizontalHeaderItem(j, h)
        bold = QFont()
        bold.setBold(True)
        for r, i in enumerate(rows):
            c = self.cards[i]
            vh = QTableWidgetItem(c["title"])
            vh.setToolTip("{}, {}".format(c["sec"], c["title"]))
            t.setVerticalHeaderItem(r, vh)
            for j, (pid, name, _f, _cols) in enumerate(pals):
                got, total = self.stat.get((i, pid), (0, 1))
                it = QTableWidgetItem()
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if prompts.done(got, total):
                    it.setBackground(QBrush(QColor(C["teal"]).darker(260)))
                    it.setForeground(QColor(C["teal"]))
                    it.setText("есть")
                elif got:
                    it.setBackground(QBrush(QColor(C["accd"])))
                    it.setText("%d/%d" % (got, total))
                if pid == c["pal"]:
                    it.setFont(bold)
                    if not got:
                        it.setText("-")
                it.setToolTip("%s - %s: %d из %d%s" % (c["title"], name, got, total,
                                                      "   (задуманная палитра)" if pid == c["pal"] else ""))
                t.setItem(r, j, it)
        t.blockSignals(False)
        if rows:
            t.setCurrentCell(0, 0)
        else:
            self.pick(-1, -1)

    def pick(self, r, c):
        ok = r >= 0 and c >= 0 and getattr(self, "shown", None) and r < len(self.shown)
        for w in (self.b_prompt, self.b_label, self.b_open, self.b_recolor, self.src):
            w.setEnabled(bool(ok))
        if not ok:
            self.cur = None
            self.title.setText("Выберите ячейку")
            self.info.setText("Строка - карточка из Prompts.html, столбец - палитра.")
            self.miss.setText("")
            return
        card, pal = self.cards[self.shown[r]], self.pals[c]
        self.cur = (self.shown[r], card, pal)
        got, total = self.stat.get((self.shown[r], pal[0]), (0, 1))
        self.title.setText("{}, {}".format(card["title"], pal[1]))
        d = prompts.dest(card, pal[0])
        self.info.setText("%s\nСделано: %d из %d%s" % (os.path.relpath(d, LIB) if d else "", got, total,
                                                       "   (задуманная палитра)" if pal[0] == card["pal"] else ""))
        names = prompts.names(card)
        have = set()
        if d and os.path.isdir(d):
            stems = [os.path.splitext(f)[0] for f in os.listdir(d)]
            have = {n for n in names if any(s == n or s.startswith(n + "_") for s in stems)}
        missing = [n for n in names if n not in have]
        self.miss.setText(("Нет: " + ", ".join(missing)) if missing and len(names) > 1 else
                          "" if not missing else "Картинки пока нет")
        self.b_open.setEnabled(bool(d and os.path.isdir(d)))
        self.src.clear()
        for p in self.pals:                             # готовые палитры этой карточки - источники перекраски
            if p[0] != pal[0] and prompts.done(*self.stat.get((self.shown[r], p[0]), (0, 1))):
                self.src.addItem(swatch_icon(p[3]), p[1], p[0])
        can = self.src.count() > 0 and len(missing) > 0
        self.src.setEnabled(can)
        self.b_recolor.setEnabled(can)
        self.b_recolor.setText("Перекрасить из готовой" if self.src.count() else "Нет готовой палитры")

    def copy_prompt(self):
        if self.cur:
            _i, card, pal = self.cur
            QApplication.clipboard().setText(prompts.prompt(card, pal[0]))
            self.win.say("Промпт скопирован: {}, {}".format(card["title"], pal[1]))

    def copy_label(self):
        if self.cur:
            _i, card, pal = self.cur
            text = prompts.file_label(card, pal[0])
            QApplication.clipboard().setText(text)
            self.win.say("Имя файла скопировано: " + text)

    def open_folder(self):
        if self.cur:
            d = prompts.dest(self.cur[1], self.cur[2][0])
            if d and os.path.isdir(d):
                os.startfile(d)

    def recolor(self):
        if not self.cur or not self.src.currentData():
            return
        _i, card, pal = self.cur
        src_dir = prompts.dest(card, self.src.currentData())
        names = prompts.names(card)
        files = sorted(os.path.join(src_dir, f) for f in os.listdir(src_dir)
                       if any(os.path.splitext(f)[0] == n or os.path.splitext(f)[0].startswith(n + "_") for n in names))
        if not files:
            return
        op = dict(op="recolor", colors=pal[3], k=1.0, pal=pal[0], folder=pal[2])
        EditDialog(self, self.win, files, on_saved=self.saved, ops=[op], target=prompts.dest(card, pal[0])).exec()

    def saved(self, text):
        self.win.lib.done(text)
        self.refresh()
