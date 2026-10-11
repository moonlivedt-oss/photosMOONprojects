"""Масштаб моделей (вкладка «Unreal»): какие наборы и модели сделаны не в сантиметрах и во сколько раз их
поправить (library/scale_check). Галочка - применить; множитель можно поменять. Файлы не меняются."""

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from library import scale_check
from library import unreal_extra as X
from ui.common import bg


class ScaleDialog(QDialog):
    def __init__(self, win, items, on_done=None):
        super().__init__(win)
        self.win, self.items, self.on_done, self.rows = win, items, on_done, []
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Масштаб моделей")
        self.resize(1040, 680)
        self.head = QLabel("Проверяю...", objectName="title")
        sub = QLabel(
            "Размер из FBX сравнивается с настоящим: стул - 70-110 см высотой, дверь - 180-290, кровать - 180-240 "
            "длиной. Наборы сделаны в одной единице - поэтому сначала общий множитель на весь набор. Файлы не "
            "меняются: множитель берут размеры в окне и импорт в Unreal (Import Uniform Scale).",
            objectName="dim",
            wordWrap=True,
        )
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Набор или модель", "Сейчас", "Должно быть", "Множитель", "Подходит"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        apply = QPushButton("Применить отмеченное", objectName="accent")
        apply.clicked.connect(self.apply)
        reset = QPushButton("Вернуть как в файле")
        reset.setToolTip("Убрать множитель у отмеченных наборов и моделей")
        reset.clicked.connect(lambda: self.apply(reset=True))
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        foot = QHBoxLayout()
        foot.addWidget(apply)
        foot.addWidget(reset)
        foot.addStretch(1)
        foot.addWidget(close)
        v = QVBoxLayout(self)
        v.addWidget(self.head)
        v.addWidget(sub)
        v.addWidget(self.table, 1)
        v.addLayout(foot)
        self.run()

    def run(self):
        items = self.items
        bg(lambda: scale_check.check(X.apply_meta(items)), self.done)

    def done(self, res):
        if sip.isdeleted(self):
            return
        if isinstance(res, Exception):
            self.head.setText(f"Не получилось: {res}")
            return
        packs, singles = res["packs"], res["items"]
        self.head.setText(
            f"Наборов не в сантиметрах: {len(packs)}, отдельных моделей: {len(singles)}"
            if packs or singles
            else "Все модели в своём масштабе"
        )
        cache = X.load_scale()
        fixed = {}
        for a in self.items:
            if a.get("kind") == "model" and X.scale_of(a, cache) != 1:
                fixed.setdefault((scale_check.pack_of(a), X.scale_of(a, cache)), []).append(a)
        self.rows = []
        self.table.setRowCount(len(packs) + len(singles) + len(fixed))
        for r, p in enumerate(packs):
            ex = p["examples"][0]
            kit = p["url"].rstrip("/").split("/")[-1] or p["theme"]
            self._row(
                r,
                f"Набор {p['source']} «{kit}»: {p['wrong']} из {p['checked']} не того размера",
                f"{ex['name']}: {ex['what']} {ex['cm']} см",
                f"{ex['expected']} см",
                p["factor"],
                f"{p['fixed']} из {p['checked']}",
                True,
            )
            self.rows.append(("pack", p))
        for r, x in enumerate(singles, len(packs)):
            self._row(
                r,
                f"{x['name']}  ({x['asset'].get('source', '')})",
                f"{x['what']} {x['cm']} см",
                f"{x['expected']} см",
                x["factor"],
                "",
                False,
            )
            self.rows.append(("item", x))
        for r, ((key, f), lst) in enumerate(fixed.items(), len(packs) + len(singles)):
            kit = key.split("|", 1)[1].rstrip("/").split("/")[-1]
            self._row(r, f"Уже поправлено: {key.split('|')[0]} «{kit}», {len(lst)} шт.", "", "", f, "", False)
            self.rows.append(("fixed", lst))

    def _row(self, r, name, now, want, factor, fits, checked):
        it = QTableWidgetItem(name)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.table.setItem(r, 0, it)
        self.table.setItem(r, 1, QTableWidgetItem(now))
        self.table.setItem(r, 2, QTableWidgetItem(want))
        spin = QDoubleSpinBox(decimals=3, minimum=0.001, maximum=1000, value=factor)
        spin.setSingleStep(0.1 if factor < 1 else 1)
        spin.setPrefix("x ")
        self.table.setCellWidget(r, 3, spin)
        self.table.setItem(r, 4, QTableWidgetItem(fits))

    def apply(self, reset=False):
        n = models = 0
        for r, (kind, x) in enumerate(self.rows):
            if self.table.item(r, 0).checkState() != Qt.CheckState.Checked:
                continue
            f = None if reset else self.table.cellWidget(r, 3).value()
            if kind == "pack":
                assets = scale_check.pack_members(self.items, x["pack"])
            else:
                assets = x if kind == "fixed" else [x["asset"]]
            n += X.set_scale(assets, f)
            models += len(assets)
        if not models:
            self.win.say("Ничего не отмечено")
            return
        self.win.say(
            f"Масштаб {'убран' if reset else 'поправлен'}: {n} моделей - при импорте в Unreal и в размерах окна"
        )
        if self.on_done:
            self.on_done()
        self.run()
