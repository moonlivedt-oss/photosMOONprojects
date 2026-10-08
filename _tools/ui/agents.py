"""Окно «ИИ-помощники»: как подключить Claude / Cursor / VS Code к библиотеке, можно ли им менять картинки,
что они сделали (с отменой) и что лежит в удалённом ими."""

import json
import os
import shutil
import sys
import time

from PyQt6.QtCore import QFile, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from imaging import clip, neural
from library import journal
from ui.common import DELETED, HERE, LIB, PARK, ROLE, human
from ui.thumbnails import lib_icon

SERVER = os.path.join(HERE, "mcp_server.py")
NAME = "image-library"


def server_entry():
    return {"command": "py", "args": ["-3.14", SERVER.replace("\\", "/")]}


def config_snippet():
    return json.dumps({"mcpServers": {NAME: server_entry()}}, ensure_ascii=False, indent=2)


# клиент: (подпись, файл настроек, ключ со списком серверов)
CLIENTS = [
    (
        "Claude Desktop",
        os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude_desktop_config.json"),
        "mcpServers",
    ),
    ("Cursor", os.path.join(os.path.expanduser("~"), ".cursor", "mcp.json"), "mcpServers"),
]


def connected(path, key):
    try:
        with open(path, encoding="utf-8") as fh:
            return NAME in (json.load(fh).get(key) or {})
    except (OSError, ValueError):
        return False


def connect(path, key):
    """Добавить сервер в настройки клиента. Старый файл - копией рядом (.bak). -> текст для пузыря."""
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError as e:
            raise ValueError(f"файл настроек испорчен, правьте его вручную: {path}") from e
        shutil.copy2(path, path + ".bak")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data.setdefault(key, {})[NAME] = server_entry()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def deleted_files():
    out = []
    for d, _dirs, files in os.walk(DELETED):
        out += [os.path.join(d, f) for f in files]
    return out


class AgentsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.cfg = win, win.cfg
        self.setWindowTitle("ИИ-помощники")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(900, 720)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel("ИИ-помощники", objectName="title"))
        lay.addWidget(
            QLabel(
                "Claude, Cursor и другие помощники умеют искать картинки этой библиотеки (и по смыслу), смотреть их, "
                "ставить метки, раскладывать, убирать фон, увеличивать, резать листы и выгружать в проекты. "
                "Всё, что они делают, всплывает внизу окна с кнопкой «Отменить» и попадает в «Историю».",
                objectName="dim",
                wordWrap=True,
            )
        )

        # --- можно ли менять
        mode = QWidget(objectName="panel")
        ml = QVBoxLayout(mode)
        ml.addWidget(QLabel("Что разрешено", objectName="big"))
        self.rw = QRadioButton("Искать, смотреть и изменять (метки, перенос, правка) - всё отменяется")
        self.ro = QRadioButton("Только искать и смотреть")
        grp = QButtonGroup(self)
        for b in (self.rw, self.ro):
            grp.addButton(b)
            ml.addWidget(b)
        (self.rw if self.cfg.get("ai_write", True) else self.ro).setChecked(True)
        self.rw.toggled.connect(self.set_write)
        lay.addWidget(mode)

        # --- подключение
        con = QWidget(objectName="panel")
        cl = QVBoxLayout(con)
        cl.addWidget(QLabel("Подключить", objectName="big"))
        models = [
            ("поиск по смыслу", clip.available()),
            ("удаление фона", neural.bg_available()),
            ("увеличение", neural.upscale_available()),
        ]
        cl.addWidget(
            QLabel(
                "Нейросети: "
                + ", ".join(f"{n} - {'есть' if ok else 'нет'}" for n, ok in models)
                + ("" if all(ok for _n, ok in models) else "   (докачать: py -3.14 _tools/get_models.py)"),
                objectName="dim",
                wordWrap=True,
            )
        )
        self.client_btns = []
        for title, path, key in CLIENTS:
            row = QHBoxLayout()
            lbl = QLabel(objectName="dim")
            btn = QPushButton(lib_icon("plug-socket"), "")
            btn.clicked.connect(lambda _c=False, t=title, p=path, k=key: self.connect_client(t, p, k))
            row.addWidget(QLabel(title), 0)
            row.addWidget(lbl, 1)
            row.addWidget(btn)
            cl.addLayout(row)
            self.client_btns.append((title, path, key, lbl, btn))
        for title, text, tip in (
            (
                "Claude Code",
                f'claude mcp add {NAME} -s user -- py -3.14 "{SERVER}"',
                "Команда для терминала: сервер будет доступен в любой папке. "
                "В самой папке библиотеки он уже настроен (.mcp.json).",
            ),
            ("Другие (VS Code, Windsurf...)", config_snippet(), "Блок настроек MCP - вставить в настройки помощника"),
            (
                "Командная строка и скрипты",
                f'py -3.14 "{os.path.join(HERE, "cli.py")}" api',
                "Те же операции без MCP: ответ - JSON. Подсказки для помощника - в AGENTS.md",
            ),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(title))
            row.addStretch(1)
            b = QPushButton(lib_icon("clipboard"), "Копировать")
            b.setToolTip(tip + "\n\n" + text)
            b.clicked.connect(lambda _c=False, t=text, n=title: self.copy(t, n))
            row.addWidget(b)
            cl.addLayout(row)
        lay.addWidget(con)

        # --- что сделали
        lay.addWidget(QLabel("Что сделали помощники", objectName="big"))
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self.update_btns)
        lay.addWidget(self.list, 1)
        self.undo_btn = QPushButton("Отменить выбранное", objectName="primary")
        self.undo_btn.clicked.connect(self.undo_selected)
        self.trash_lbl = QLabel(objectName="dim")
        self.open_btn = QPushButton(lib_icon("folder"), "Открыть удалённое")
        self.open_btn.clicked.connect(lambda: os.startfile(DELETED))
        self.clear_btn = QPushButton(lib_icon("trash-bin"), "В корзину Windows")
        self.clear_btn.setToolTip(
            "Удалённое помощниками лежит в _sources/_deleted (его можно вернуть отменой). "
            "Здесь - отправить его в корзину Windows."
        )
        self.clear_btn.clicked.connect(self.clear_deleted)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        foot = QHBoxLayout()
        foot.addWidget(self.trash_lbl, 1)
        foot.addWidget(self.open_btn)
        foot.addWidget(self.clear_btn)
        foot.addWidget(self.undo_btn)
        foot.addWidget(close)
        lay.addLayout(foot)
        self.refresh()

    def refresh(self):
        for title, path, key, lbl, btn in self.client_btns:
            ok = connected(path, key)
            lbl.setText(
                "подключено"
                if ok
                else ("не установлен" if not os.path.isdir(os.path.dirname(path)) else "не подключено")
            )
            btn.setText("Подключить заново" if ok else "Подключить")
            btn.setToolTip(
                f"Записать сервер в {path} (старый файл останется копией .bak). После этого перезапустите {title}."
            )
        self.list.clear()
        for e in journal.entries(60):
            if e["who"] == journal.WINDOW:
                continue
            when = time.strftime("%d.%m %H:%M", time.localtime(e["t"]))
            it = QListWidgetItem(f"{when}   {e['who']}:  {e['text']}" + ("   - отменено" if e["undone"] else ""))
            it.setData(ROLE, e["id"])
            if e["undone"]:
                it.setForeground(self.palette().placeholderText())
            self.list.addItem(it)
        if not self.list.count():
            it = QListWidgetItem(
                "Пока ничего. Подключите помощника и попросите, например: "
                "«найди в библиотеке картинки с котами и поставь им метку коты»."
            )
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)
        files = deleted_files()
        size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
        self.trash_lbl.setText(
            f"Удалено помощниками: {len(files)} файлов ({human(size)})" if files else "Удалённого помощниками нет"
        )
        self.clear_btn.setEnabled(bool(files))
        self.open_btn.setEnabled(bool(files))
        self.update_btns()

    def update_btns(self):
        ids = self.selected()
        self.undo_btn.setEnabled(bool(ids))

    def selected(self):
        out = []
        for it in self.list.selectedItems():
            jid = it.data(ROLE)
            e = journal.get(jid) if jid else None
            if e and not e["undone"]:
                out.append(jid)
        return out

    def set_write(self, on):
        self.cfg["ai_write"] = on
        self.win.save_settings()  # сервер читает настройки с диска - записать сразу
        self.win.say("Помощникам можно изменять библиотеку" if on else "Помощники только ищут и смотрят")

    def copy(self, text, what):
        QApplication.clipboard().setText(text)
        self.win.say(f"Скопировано: {what}")

    def connect_client(self, title, path, key):
        try:
            connect(path, key)
        except (OSError, ValueError) as e:
            self.win.say(f"Не получилось: {e}")
            return
        self.refresh()
        self.win.say(f"{title}: подключено. Перезапустите {title}, и помощник увидит библиотеку")

    def undo_selected(self):
        ids = set(self.selected())
        mine = {h[2] for h in self.win.history} & ids
        if mine:
            self.win.undo(ids=mine)
        for jid in ids - mine:  # старое, чего уже нет в истории окна
            e = journal.get(jid)
            journal.undo_steps(e["steps"], LIB, PARK)
            journal.mark(jid)
        if ids - mine:
            self.win.after_change()
        self.refresh()

    def clear_deleted(self):
        n = sum(1 for f in deleted_files() if QFile.moveToTrash(f)[0])
        for d, _dirs, _f in sorted(os.walk(DELETED), reverse=True):  # пустые папки - прочь
            try:
                os.rmdir(d)
            except OSError:
                pass
        self.refresh()
        self.win.say(f"В корзине Windows: {n} файлов")


if sys.platform != "win32":  # окно рассчитано на Windows; на других ОС подключать вручную
    CLIENTS = []
