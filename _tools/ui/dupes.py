"""Окно «Найти дубли»: лишние копии уезжают в «_duplicates» (Ctrl+Z вернёт)."""
import os
import shutil

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

import imaging as K
from ui.common import LIB, human, unique
from ui.thumbnails import lib_icon, thumb


class DupesDialog(QDialog):
    """Группы одинаковых картинок: отмеченные остаются, остальные уезжают в «_duplicates» (Ctrl+Z вернёт)."""

    def __init__(self, win, groups):
        super().__init__(win)
        self.win, self.boxes = win, []
        self.setWindowTitle("Одинаковые картинки: групп %d" % len(groups))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
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
                info = QLabel(f"{os.path.relpath(p, LIB)}\n{self.info(p)}", objectName="dim", wordWrap=True)
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
        hint = QLabel("Отмеченные остаются. Неотмеченные уедут в «_duplicates» с той же структурой папок; "
                      "не дубли - отметьте все в группе.", objectName="dim", wordWrap=True)
        go = QPushButton(lib_icon("trash-bin"), "Убрать неотмеченные в «_duplicates»", objectName="primary")
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
        steps, bad = [], 0
        for p, box in self.boxes:
            if not box.isChecked() and os.path.exists(p):
                dst = unique(os.path.join(LIB, "_duplicates", os.path.relpath(p, LIB)))
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.move(p, dst)
                except OSError:                 # открыт в другой программе - остальные переносим
                    bad += 1
                    continue
                self.win.moved(p, dst)
                steps.append(("move", p, dst))
        text = "В «_duplicates» перенесено: %d" % len(steps) + ("   не вышло: %d (файл занят)" % bad if bad else "")
        self.win.push(text, steps)
        self.win.lib.refresh()
        self.win.library_changed()
        self.win.say(text + ("  (Ctrl+Z - вернуть)" if steps else ""))
        self.accept()
