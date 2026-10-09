"""Окно «Импорт в Unreal»: прямо в проект одной кнопкой (Unreal сам, без открытия редактора) или
по-старому - файлы и import_to_unreal.py в выбранную папку. Работа - library/unreal_engine.py."""

import os

from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from library import unreal_engine as E
from library.unreal_pack import remember_use
from ui.common import bg, in_main, log_error
from ui.thumbnails import lib_icon


class ImportDialog(QDialog):
    def __init__(self, tab, assets):
        super().__init__(tab)
        self.tab, self.cfg, self.assets = tab, tab.cfg, assets
        self.setWindowTitle("Импорт в Unreal")
        self.setWindowIcon(lib_icon("export"))
        self.setMinimumWidth(560)
        self.engines = E.engines()
        self.projects = E.projects(self.cfg.get("ue_projects", []))
        self.direct = QRadioButton("Прямо в проект - Unreal импортирует сам, редактор открывать не нужно")
        self.manual = QRadioButton("Только подготовить файлы и скрипт - импортировать потом в редакторе")
        self.proj = QComboBox()
        for p in self.projects:
            self.proj.addItem(os.path.splitext(os.path.basename(p))[0] + "    " + os.path.dirname(p), p)
        last = self.cfg.get("ue_last_project")
        if last in self.projects:
            self.proj.setCurrentIndex(self.projects.index(last))
        more = QPushButton(lib_icon("folder"), "Другой проект...")
        more.clicked.connect(self.pick_project)
        self.state = QLabel(objectName="dim", wordWrap=True)
        self.proj.currentIndexChanged.connect(self.check)
        self.direct.toggled.connect(self.check)
        ok = bool(self.engines)
        self.direct.setEnabled(ok)
        (self.direct if ok and self.projects else self.manual).setChecked(True)
        go = QPushButton(lib_icon("export"), "Импортировать", objectName="primary")
        go.clicked.connect(self.go)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(self.proj, 1)
        row.addWidget(more)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(go)
        foot.addWidget(cancel)
        v = QVBoxLayout(self)
        v.addWidget(
            QLabel(
                f"Ассетов: {len(assets)}. Текстуры получат настройки (sRGB, Normalmap, Masks) и материал "
                "M_<имя>; всё - в Content/Library.",
                objectName="dim",
                wordWrap=True,
            )
        )
        v.addWidget(self.direct)
        v.addLayout(row)
        v.addWidget(self.manual)
        v.addWidget(self.state)
        v.addLayout(foot)
        self.check()

    def pick_project(self):
        p, _ = QFileDialog.getOpenFileName(self, "Проект Unreal", os.path.expanduser("~"), "Unreal (*.uproject)")
        if not p:
            return
        known = self.cfg.setdefault("ue_projects", [])
        if p not in known:
            known.append(p)
        if p not in self.projects:
            self.projects.insert(0, p)
            self.proj.insertItem(0, os.path.splitext(os.path.basename(p))[0] + "    " + os.path.dirname(p), p)
        self.proj.setCurrentIndex(self.projects.index(p))
        self.direct.setChecked(True)

    def check(self):
        if not self.engines:
            self.state.setText("Unreal Engine не найден на этом компьютере - только подготовка файлов.")
            return
        p = self.proj.currentData()
        self.proj.setEnabled(self.direct.isChecked())
        if not self.direct.isChecked() or not p:
            self.state.setText(
                "Файлы и import_to_unreal.py лягут в выбранную папку; в Unreal: Tools -> Execute Python Script."
                if self.manual.isChecked()
                else "Выберите проект."
            )
            return
        eng = E.engine_for(p, self.engines)
        notes = [f"Движок: {eng}"]
        if not E.python_enabled(p):
            notes.append(
                "В проекте выключен Python Editor Script Plugin - включу его (старый .uproject - копией .bak)."
            )
        self.state.setText("\n".join(notes))

    def go(self):
        if self.manual.isChecked() or not self.proj.currentData():
            self.accept()
            self.tab.prepare_import(self.assets)
            return
        project = self.proj.currentData()
        self.cfg["ue_last_project"] = project
        if E.editor_running(project):
            folder = E.import_folder(project)
            try:
                from library import unreal_import

                script = unreal_import.export(self.assets, folder)
            except Exception as e:
                QMessageBox.warning(self, "Импорт в Unreal", f"Не вышло подготовить файлы: {e}")
                return
            cmd = f'py "{script.replace(chr(92), "/")}"'
            QApplication.clipboard().setText(cmd)
            QMessageBox.information(
                self,
                "Импорт в Unreal",
                "Редактор Unreal сейчас открыт - пусть импортирует он сам (два процесса в одном проекте мешают "
                f"друг другу).\n\nВ Output Log (режим Cmd) вставьте команду - она уже в буфере обмена:\n{cmd}",
            )
            remember_use(self.cfg, self.assets, project)
            self.accept()
            return
        if not E.python_enabled(project):
            try:
                E.enable_python(project)
            except Exception as e:
                QMessageBox.warning(self, "Импорт в Unreal", f"Не удалось включить плагин Python: {e}")
                return
        self.accept()
        self.tab.run_direct_import(self.assets, project)


def run_direct_import(tab, assets, project):
    """Фоном: Unreal без окна импортирует ассеты; ход - в строке состояния, итог - сообщением."""
    name = os.path.splitext(os.path.basename(project))[0]
    tab.set_progress(f"импорт в {name}: Unreal запускается...")

    def work():
        return E.import_into(assets, project, log=lambda t: in_main(tab.set_progress, f"импорт в {name}: {t}"))

    def done(res):
        tab.set_progress(None)
        if isinstance(res, Exception):
            log_error("unreal import: %r" % res)
            tab.win.say(f"Импорт в {name} не удался: {res}")
            return
        remember_use(tab.cfg, assets, project)
        if res["ok"]:
            tab.win.say(f"Импортировано в {name}: {len(res['imported'])} - Content/Library, материалы M_<имя>")
        else:
            why = "; ".join(res["errors"][:2]) or f"код {res['code']}"
            tab.win.say(f"Импорт в {name}: {len(res['imported'])} из {len(assets)}. Журнал: {res['log']} ({why})")

    bg(work, done)
