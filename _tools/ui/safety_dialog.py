"""Окно «Проверка и восстановление»: состояние настроек, базы, копий, моделей и места; починка одной
кнопкой; резервные копии с возвратом; журнал ошибок. Сама работа - в library/safety.py."""

import os
import sys
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from library import safety
from ui.common import HERE, LOG, ROLE, bg, reveal
from ui.theme import C
from ui.thumbnails import _thumbs, lib_icon


class SafetyDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Проверка и восстановление")
        self.setWindowIcon(lib_icon("first-aid-kit"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Проверка и восстановление", objectName="title"))
        lay.addWidget(
            QLabel(
                "Метки, заметки, избранное, умные папки, журнал отмены и настройки каждый день копируются в "
                "_tools/_backups (последние 10). Повреждённый файл не стирается: он отодвигается рядом, "
                "а окно берёт последнюю целую копию само.",
                objectName="dim",
                wordWrap=True,
            )
        )
        state = QWidget(objectName="panel")
        self.grid = QGridLayout(state)
        self.grid.setHorizontalSpacing(14)
        lay.addWidget(state)

        lay.addWidget(QLabel("Резервные копии", objectName="big"))
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self.update_btns)
        lay.addWidget(self.list, 1)
        self.restore_btn = QPushButton(lib_icon("arrow_counterclockwise"), "Вернуть выбранную...")
        self.restore_btn.setToolTip("Текущее состояние сначала само уйдёт в копию - вернуть можно и его")
        self.restore_btn.clicked.connect(self.restore)
        make = QPushButton(lib_icon("save"), "Сделать копию сейчас")
        make.clicked.connect(lambda: self.run_fix("backup"))
        folder = QPushButton(lib_icon("folder"), "Папка копий")
        folder.clicked.connect(lambda: reveal(safety.backups_dir()) if os.path.isdir(safety.backups_dir()) else None)
        row = QHBoxLayout()
        row.addWidget(make)
        row.addWidget(folder)
        row.addStretch(1)
        row.addWidget(self.restore_btn)
        lay.addLayout(row)

        foot = QHBoxLayout()
        log = QPushButton(lib_icon("clipboard"), "Журнал ошибок")
        log.setToolTip(LOG)
        log.clicked.connect(lambda: os.path.exists(LOG) and os.startfile(LOG))
        thumbs = QPushButton(lib_icon("trash-bin"), "Сбросить кэш миниатюр")
        thumbs.setToolTip("Если плитки показывают не те картинки: кэш в памяти очищается, файлы пересчитаются")
        thumbs.clicked.connect(self.reset_thumbs)
        close = QPushButton("Закрыть", objectName="primary")
        close.clicked.connect(self.accept)
        foot.addWidget(log)
        foot.addWidget(thumbs)
        foot.addStretch(1)
        foot.addWidget(close)
        lay.addLayout(foot)
        self.refresh()

    # ------------------------------------------------------------
    def refresh(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.grid.addWidget(QLabel("Проверяю...", objectName="dim"), 0, 0)

        def done(rows):
            while self.grid.count():
                w = self.grid.takeAt(0).widget()
                if w:
                    w.deleteLater()
            if isinstance(rows, Exception):
                self.grid.addWidget(QLabel(f"Проверка не удалась: {rows}", objectName="dim"), 0, 0)
                return
            for i, r in enumerate(rows):
                mark = QLabel("в порядке" if r["ok"] else "проблема")
                mark.setStyleSheet(f"color: {C['teal'] if r['ok'] else C['acc2']}; font-weight: 700")
                self.grid.addWidget(QLabel(r["name"]), i, 0)
                self.grid.addWidget(mark, i, 1)
                text = QLabel(r["text"], objectName="dim", wordWrap=True)
                self.grid.addWidget(text, i, 2)
                if r["fix"]:
                    b = QPushButton(lib_icon("wrench"), "Починить")
                    b.clicked.connect(lambda _c=False, k=r["fix"]: self.run_fix(k))
                    self.grid.addWidget(b, i, 3)
            self.grid.setColumnStretch(2, 1)

        bg(safety.check, done)
        self.list.clear()
        for d, t, has in safety.backups():
            name = os.path.basename(d)
            what = ", ".join({"library.db": "база", "settings.json": "настройки"}[f] for f in has)
            it = QListWidgetItem(f"{time.strftime('%d.%m.%Y %H:%M', time.localtime(t))}    {what}    {name[18:]}")
            it.setData(ROLE, d)
            self.list.addItem(it)
        if not self.list.count():
            it = QListWidgetItem("Копий пока нет - «Сделать копию сейчас»")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)
        self.update_btns()

    def update_btns(self):
        it = self.list.currentItem()
        self.restore_btn.setEnabled(bool(it and it.data(ROLE)))

    def run_fix(self, kind):
        try:
            text = safety.fix(kind)
        except Exception as e:
            text = f"Не вышло: {e}"
        self.win.say(text)
        if "перезапустите" in text:
            self.offer_restart(text)
        self.refresh()

    def restore(self):
        it = self.list.currentItem()
        src = it.data(ROLE) if it else None
        if not src:
            return
        if (
            QMessageBox.question(
                self,
                "Вернуть копию",
                f"Вернуть базу и настройки из копии {it.text().split('    ')[0]}?\n\n"
                "Метки, заметки и избранное станут как тогда. Текущее состояние сначала само уйдёт в копию "
                "«перед восстановлением» - передумать можно. Окно перезапустится.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.win.cfg_frozen = True  # окно не должно записать старые настройки поверх возвращённых
        try:
            safety.restore(src)
        except Exception as e:
            self.win.cfg_frozen = False
            self.win.say(f"Не вышло: {e}")
            return
        self.restart()

    def offer_restart(self, text):
        if QMessageBox.question(self, "Перезапуск", text + ".\n\nПерезапустить окно сейчас?") == (
            QMessageBox.StandardButton.Yes
        ):
            self.win.cfg_frozen = True
            self.restart()

    def restart(self):
        import subprocess

        exe = sys.executable.replace("python.exe", "pythonw.exe")
        subprocess.Popen([exe if os.path.exists(exe) else sys.executable, os.path.join(HERE, "app.py")])
        self.win.close()

    def reset_thumbs(self):
        _thumbs.clear()
        self.win.lib.refresh()
        self.win.say("Кэш миниатюр сброшен")
