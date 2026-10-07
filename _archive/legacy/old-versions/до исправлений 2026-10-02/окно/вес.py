"""Вес разделов: где библиотека тяжелее всего, сколько там тяжёлых файлов и сколько уже сэкономлено
сжатием. Полосы вырастают при открытии; щелчок по разделу открывает его подразделы."""
import os
import time

import картинки as K
from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from окно.общее import HEAVY_KB, LIB, bg, human
from окно.оформление import C


def weigh():
    """В фоне: {папка: [байт, файлов, тяжёлых байт, тяжёлых файлов, [тяжёлые пути]]} для всех папок,
    вместе с подпапками - за один обход."""
    out = {}
    for d, dirs, files in os.walk(LIB):
        dirs[:] = [x for x in dirs if not x.startswith(("_", ".")) and x != K.INBOX]
        for f in files:
            if not f.lower().endswith(K.EXT) or f.startswith("_"):
                continue
            p = os.path.join(d, f)
            try:
                n = os.path.getsize(p)
            except OSError:
                continue
            heavy = n > HEAVY_KB * 1024
            up = d
            while len(up) > len(LIB):
                w = out.setdefault(up, [0, 0, 0, 0, []])
                w[0] += n
                w[1] += 1
                if heavy:
                    w[2] += n
                    w[3] += 1
                    w[4].append(p)
                up = os.path.dirname(up)
    return out


class Bars(QWidget):
    """Строки-полосы: длина - вес раздела, яркая часть - тяжёлые файлы, справа - сэкономлено."""
    ROW = 46

    def __init__(self, dlg):
        super().__init__()
        self.dlg, self.rows, self.sel, self.hover, self.t0 = dlg, [], -1, -1, 0.0
        self.setMouseTracking(True)
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self.tick)

    def set_rows(self, rows):
        self.rows, self.sel, self.hover = rows, -1, -1
        self.t0 = time.monotonic()
        self.setMinimumHeight(max(1, len(rows)) * self.ROW + 8)
        self.timer.start()
        self.update()

    def tick(self):
        if time.monotonic() - self.t0 > 1.2:
            self.timer.stop()
        self.update()

    def row_at(self, y):
        i = int((y - 4) // self.ROW)
        return i if 0 <= i < len(self.rows) else -1

    def mouseMoveEvent(self, e):
        h = self.row_at(e.position().y())
        if h != self.hover:
            self.hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        i = self.row_at(e.position().y())
        if i >= 0:
            self.sel = i
            self.dlg.picked(self.rows[i])
            self.update()

    def mouseDoubleClickEvent(self, e):
        i = self.row_at(e.position().y())
        if i >= 0:
            self.dlg.enter(self.rows[i]["path"])

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = max((r["bytes"] for r in self.rows), default=1) or 1
        f1, f2 = QFont("Segoe UI", 10), QFont("Segoe UI", 8)
        f1.setWeight(QFont.Weight.DemiBold)
        name_w, right_w = 230, 190
        bar_w = max(40, self.width() - name_w - right_w - 40)
        for i, r in enumerate(self.rows):
            y = 4 + i * self.ROW
            row = QRectF(6, y + 2, self.width() - 12, self.ROW - 4)
            if i in (self.sel, self.hover):
                p.setPen(QPen(QColor(C["acc"] if i == self.sel else C["line2"]), 1))
                p.setBrush(QColor(C["accd"] if i == self.sel else C["bg3"]))
                p.drawRoundedRect(row, 10, 10)
            # полоса вырастает, каждая следующая чуть позже
            k = min(1.0, max(0.0, (time.monotonic() - self.t0 - i * 0.04) / 0.7))
            k = 1 - (1 - k) ** 3
            bx, by = row.x() + name_w, row.center().y() - 7
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C["bg3"]))
            p.drawRoundedRect(QRectF(bx, by, bar_w, 14), 7, 7)
            full = bar_w * r["bytes"] / top * k
            g = QLinearGradient(bx, 0, bx + bar_w, 0)
            g.setColorAt(0, QColor(C["acc"]))
            g.setColorAt(1, QColor(C["teal"]))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(QRectF(bx, by, max(full, 4), 14), 7, 7)
            if r["heavy"]:                            # тяжёлая доля - розовым поверх
                hw = full * r["heavy"] / max(1, r["bytes"])
                p.setBrush(QColor(C["acc2"]))
                p.drawRoundedRect(QRectF(bx + full - hw, by, max(hw, 4), 14), 7, 7)
            p.setPen(QColor(C["text"]))
            p.setFont(f1)
            fm = p.fontMetrics()
            p.drawText(QRectF(row.x() + 12, row.y(), name_w - 20, row.height() / 2 + 4),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                       fm.elidedText(r["name"], Qt.TextElideMode.ElideRight, name_w - 20))
            p.setFont(f2)
            p.setPen(QColor(C["dim"]))
            p.drawText(QRectF(row.x() + 12, row.center().y() + 2, name_w - 20, row.height() / 2 - 2),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       "%d шт.%s" % (r["count"], "   тяжёлых: %d" % r["heavy_n"] if r["heavy_n"] else ""))
            rx = bx + bar_w + 14
            p.setFont(f1)
            p.setPen(QColor(C["text"]))
            p.drawText(QRectF(rx, row.y(), right_w, row.height() / 2 + 4),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, human(r["bytes"]))
            if r["saved"]:
                p.setFont(f2)
                p.setPen(QColor(C["teal"]))
                p.drawText(QRectF(rx, row.center().y() + 2, right_w, row.height() / 2 - 2),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                           "сэкономлено %s" % human(r["saved"]))
        if not self.rows:
            p.setPen(QColor(C["dim"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Взвешиваю библиотеку...")
        p.end()


class WeightDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.data, self.root, self.row = win, {}, LIB, None
        self.setWindowTitle("Вес разделов")
        self.resize(860, 620)
        self.title = QLabel("Вес разделов", objectName="title")
        self.sub = QLabel(objectName="dim", wordWrap=True)
        self.back = QPushButton("Назад", objectName="ghost")
        self.back.clicked.connect(lambda: self.enter(os.path.dirname(self.root)))
        self.back.hide()
        head = QHBoxLayout()
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.back)
        legend = QLabel("Полоса - вес раздела, розовая часть - файлы тяжелее %d КБ. "
                        "Щелчок - выбрать, двойной щелчок - подразделы." % HEAVY_KB, objectName="dim", wordWrap=True)
        self.bars = Bars(self)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.bars)
        panel = QWidget(objectName="panel")
        pl = QVBoxLayout(panel)
        pl.addWidget(area)
        self.info = QLabel(objectName="dim")
        self.open_btn = QPushButton("Открыть раздел")
        self.open_btn.clicked.connect(self.open_section)
        self.comp_btn = QPushButton("Сжать тяжёлые здесь", objectName="primary")
        self.comp_btn.clicked.connect(self.compress)
        for b in (self.open_btn, self.comp_btn):
            b.setEnabled(False)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        foot = QHBoxLayout()
        foot.addWidget(self.info, 1)
        foot.addWidget(self.open_btn)
        foot.addWidget(self.comp_btn)
        foot.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addWidget(self.sub)
        lay.addWidget(legend)
        lay.addWidget(panel, 1)
        lay.addLayout(foot)
        self.refresh()

    def refresh(self):
        bg(weigh, self.weighed)

    def weighed(self, res):
        if isinstance(res, Exception):
            self.sub.setText("Не получилось: %s" % res)
            return
        self.data = res
        tops = [v for k, v in res.items() if os.path.dirname(k) == LIB]
        total, heavy = sum(v[0] for v in tops), sum(v[2] for v in tops)
        saved = sum(self.win.cfg.get("saved", {}).values())
        self.sub.setText("Всего %s в %d файлах   ·   тяжёлых %s   ·   %s" % (
            human(total), sum(v[1] for v in tops), human(heavy) if heavy else "нет",
            "сжатием уже сэкономлено " + human(saved) if saved else "сжатием пока ничего не экономили"))
        self.enter(self.root)

    def enter(self, path):
        subs = sorted((k for k in self.data if os.path.dirname(k) == path), key=lambda k: -self.data[k][0])
        if not subs:
            return
        self.root = path
        saved = self.win.cfg.get("saved", {})
        rows = []
        for k in subs:
            b, n, hb, hn, hp = self.data[k]
            rel = os.path.relpath(k, LIB)
            rows.append(dict(path=k, name=os.path.basename(k), bytes=b, count=n, heavy=hb, heavy_n=hn,
                             heavy_paths=hp, saved=saved.get(rel, 0) if os.sep not in rel else 0))
        self.title.setText("Вес разделов" if path == LIB else os.path.relpath(path, LIB))
        self.back.setVisible(path != LIB)
        self.row = None
        for b in (self.open_btn, self.comp_btn):
            b.setEnabled(False)
        self.info.setText("")
        self.bars.set_rows(rows)

    def picked(self, row):
        self.row = row
        self.open_btn.setEnabled(True)
        self.comp_btn.setEnabled(bool(row["heavy_n"]))
        self.info.setText("%s: тяжёлых %d (%s)" % (row["name"], row["heavy_n"], human(row["heavy"]))
                          if row["heavy_n"] else "%s: тяжёлых нет" % row["name"])

    def open_section(self):
        if self.row:
            self.win.tabs.setCurrentIndex(1)
            self.win.lib.show_section(self.row["path"])
            self.accept()

    def compress(self):
        if self.row and self.row["heavy_paths"]:
            self.win.lib.compress(list(self.row["heavy_paths"]))
            self.refresh()
