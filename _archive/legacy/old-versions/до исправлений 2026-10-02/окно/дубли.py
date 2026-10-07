"""Окно «Найти дубли»: лишние копии уезжают в «_дубли» (Ctrl+Z вернёт)."""
import os
import shutil

import картинки as K
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from окно.миниатюры import lib_icon, thumb
from окно.общее import LIB, human, unique


class DupesDialog(QDialog):
    """Группы одинаковых картинок: отмеченные остаются, остальные уезжают в «_дубли» (Ctrl+Z вернёт)."""

    def __init__(self, win, groups):
        super().__init__(win)
        self.win, self.boxes = win, []
        self.setWindowTitle("Одинаковые картинки: групп %d" % len(groups))
        self.resize(900, 640)
        rows = QWidget()
        rv = QVBoxLayout(rows)
        for g in groups:
            g.sort(key=self.quality, reverse=True)       # первой - самая крупная и тяжёлая: её и оставить
            row = QFrame(objectName="drop")
            h = QHBoxLayout(row)
            for i, p in enumerate(g):
                cell = QVBoxLayout()
                pic = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
                pic.setPixmap(thumb(p, 120, "chk"))
                cell.addWidget(pic)
                info = QLabel("%s\n%s" % (os.path.relpath(p, LIB), self.info(p)), objectName="dim", wordWrap=True)
                info.setFixedWidth(170)
                cell.addWidget(info)
                box = QCheckBox("Оставить")
                box.setChecked(i == 0)
                cell.addWidget(box)
                self.boxes.append((p, box))
                h.addLayout(cell)
            h.addStretch(1)
            rv.addWidget(row)
        rv.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(rows)
        hint = QLabel("Отмеченные остаются. Неотмеченные уедут в «_дубли» с той же структурой папок; "
                      "не дубли - отметьте все в группе.", objectName="dim", wordWrap=True)
        go = QPushButton(lib_icon("trash-bin"), "Убрать неотмеченные в «_дубли»", objectName="primary")
        go.clicked.connect(self.apply)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        bottom.addWidget(close)
        bottom.addWidget(go)
        v = QVBoxLayout(self)
        v.addWidget(area, 1)
        v.addLayout(bottom)

    @staticmethod
    def quality(p):
        try:
            w, h = K.size_of(p)
            return w * h, os.path.getsize(p)
        except Exception:
            return 0, 0

    @staticmethod
    def info(p):
        try:
            return "%dx%d, %s" % (K.size_of(p) + (human(os.path.getsize(p)),))
        except Exception:
            return human(os.path.getsize(p))

    def apply(self):
        steps = []
        for p, box in self.boxes:
            if not box.isChecked() and os.path.exists(p):
                dst = unique(os.path.join(LIB, "_дубли", os.path.relpath(p, LIB)))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(p, dst)
                steps.append(("move", p, dst))
        text = "В «_дубли» перенесено: %d" % len(steps)
        self.win.push(text, steps)
        self.win.lib.refresh()
        self.win.library_changed()
        self.win.say(text + ("  (Ctrl+Z - вернуть)" if steps else ""))
        self.accept()
