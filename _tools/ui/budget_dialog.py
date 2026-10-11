"""Бюджет сцены (вкладка «Unreal», правый щелчок по выбранным или по разделу): треугольники, память видеокарты
под текстуры, что включить с Nanite, что упростить - и упрощение в Blender одной кнопкой (library/budget)."""

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from library import budget
from ui.common import bg

LEVEL = {"ok": ("#4cb782", "лёгкая"), "nanite": ("#f2c94c", "Nanite"), "heavy": ("#e5484d", "тяжёлая")}


def num(n):
    return f"{n:,}".replace(",", " ")


class BudgetDialog(QDialog):
    def __init__(self, win, assets, title="Подборка"):
        super().__init__(win)
        self.win, self.assets, self.busy = win, list(assets), False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"Бюджет сцены: {title}")
        self.resize(980, 640)
        self.head = QLabel("Считаю...", objectName="title")
        self.notes = QLabel(objectName="dim", wordWrap=True)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Ассет", "Треугольники", "Текстуры", "Видеопамять", "Что делать"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.selected)
        self.target = QSpinBox(minimum=1000, maximum=2_000_000, singleStep=10_000, value=100_000)
        self.target.setSuffix(" треуг.")
        self.target.setToolTip("Сколько треугольников оставить")
        self.b_simplify = QPushButton("Упростить в Blender")
        self.b_simplify.setToolTip(
            "Рядом с оригиналом появится упрощённая копия <имя>_<N>k.fbx - при импорте и в пакете возьмётся она. "
            "Оригинал не меняется."
        )
        self.b_simplify.clicked.connect(self.simplify)
        self.b_orig = QPushButton("Брать оригинал")
        self.b_orig.setToolTip("Упрощённая копия остаётся на диске, но импортируется снова оригинал")
        self.b_orig.clicked.connect(self.original)
        self.tip = QLabel(objectName="dim", wordWrap=True)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        foot = QHBoxLayout()
        foot.addWidget(QLabel("Оставить:"))
        foot.addWidget(self.target)
        foot.addWidget(self.b_simplify)
        foot.addWidget(self.b_orig)
        foot.addStretch(1)
        foot.addWidget(close)
        v = QVBoxLayout(self)
        v.addWidget(self.head)
        v.addWidget(self.notes)
        v.addWidget(self.table, 1)
        v.addWidget(self.tip)
        v.addLayout(foot)
        self.res = None
        self.run()

    def run(self):
        assets = self.assets
        self.head.setText("Считаю...")
        bg(lambda: budget.scene(assets), self.done)

    def done(self, res):
        if sip.isdeleted(self):
            return
        if isinstance(res, Exception):
            self.head.setText(f"Не получилось: {res}")
            return
        self.res = res
        t = res["total"]
        self.head.setText(
            f"{t['assets']} шт.: {num(t['triangles'])} треугольников, текстуры ~{t['gpu_mb']} МБ видеопамяти, "
            f"на диске {t['disk_mb']} МБ"
        )
        self.notes.setText("\n".join(res["notes"]))
        order = {"heavy": 0, "nanite": 1, "ok": 2}
        rows = sorted(enumerate(res["items"]), key=lambda x: (order[x[1]["level"]], -x[1]["triangles"]))
        self.table.setRowCount(len(rows))
        for r, (i, x) in enumerate(rows):
            color, word = LEVEL[x["level"]]
            name = QTableWidgetItem(x["name"] + (f"  (упрощена: {len(x['simplified'])})" if x["simplified"] else ""))
            name.setData(Qt.ItemDataRole.UserRole, i)
            tris = QTableWidgetItem(num(x["triangles"]) if x["triangles"] else "-")
            tris.setForeground(QColor(color))
            tris.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tex = QTableWidgetItem(f"{x['textures']} до {x['max_tex']} px" if x["textures"] else "-")
            mem = QTableWidgetItem(f"{x['gpu_mb']} МБ")
            mem.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            adv = QTableWidgetItem(f"{word}: {x['advice']}" if x["advice"] else word)
            adv.setForeground(QColor(color))
            for c, it in enumerate((name, tris, tex, mem, adv)):
                self.table.setItem(r, c, it)
        self.selected()

    def cur(self):
        rows = self.table.selectionModel().selectedRows() if self.res else []
        if not rows:
            return None, None
        i = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return self.assets[i], self.res["items"][i]

    def selected(self):
        a, x = self.cur()
        model = bool(a) and a.get("kind") == "model" and x["triangles"] > 0
        self.b_simplify.setEnabled(model and not a.get("rigged") and not self.busy)
        self.b_orig.setEnabled(bool(a) and bool(budget.active(a)) and not self.busy)
        if model:
            self.target.setValue(min(max(1000, x["triangles"] // 4 // 1000 * 1000), 2_000_000))
            on = budget.active(a)
            self.tip.setText(
                f"Сейчас при импорте берётся: {on or 'оригинал'}."
                + (" Со скелетом - не упрощается." if a.get("rigged") else "")
            )
        else:
            self.tip.setText("Выберите модель - её можно упростить в Blender.")

    def simplify(self):
        a, _x = self.cur()
        if a is None:
            return
        target = self.target.value()
        self.busy = True
        self.selected()
        self.tip.setText(f"Упрощаю «{a.get('name')}» в Blender... (тяжёлая модель - минута-другая)")
        bg(lambda: budget.simplify(a, target), self.simplified)

    def simplified(self, res):
        if sip.isdeleted(self):
            return
        self.busy = False
        if isinstance(res, Exception):
            self.tip.setText(f"Не получилось: {res}")
            self.selected()
            return
        self.win.say(f"Упрощено: {res['file']} - {num(res['triangles'])} треугольников; при импорте возьмётся она")
        self.run()

    def original(self):
        a, _x = self.cur()
        if a is not None:
            budget.set_active(a, None)
            self.win.say(f"«{a.get('name')}»: при импорте снова оригинал")
            self.run()
