"""Окно «ИИ-помощники»: как подключить Claude, Cursor, VS Code, Windsurf, Cline и других к библиотеке, можно ли им менять картинки,
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
    QGridLayout,
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


HOME = os.path.expanduser("~")
APPDATA = os.environ.get("APPDATA", "")
VSC_STORE = os.path.join(APPDATA, "Code", "User", "globalStorage")


def vscode_entry():
    """VS Code (Copilot, режим агента) ждёт явный тип сервера."""
    return {"type": "stdio", **server_entry()}


# клиент: (подпись, файл настроек, ключ со списком серверов, запись сервера, папка «установлен ли»)
CLIENTS = [
    ("Claude Desktop", os.path.join(APPDATA, "Claude", "claude_desktop_config.json"), "mcpServers", server_entry, None),
    ("Cursor", os.path.join(HOME, ".cursor", "mcp.json"), "mcpServers", server_entry, None),
    ("VS Code (Copilot)", os.path.join(APPDATA, "Code", "User", "mcp.json"), "servers", vscode_entry, None),
    ("Windsurf", os.path.join(HOME, ".codeium", "windsurf", "mcp_config.json"), "mcpServers", server_entry, None),
    (
        "Cline",
        os.path.join(VSC_STORE, "saoudrizwan.claude-dev", "settings", "cline_mcp_settings.json"),
        "mcpServers",
        server_entry,
        os.path.join(VSC_STORE, "saoudrizwan.claude-dev"),
    ),
    (
        "Roo Code",
        os.path.join(VSC_STORE, "rooveterinaryinc.roo-cline", "settings", "mcp_settings.json"),
        "mcpServers",
        server_entry,
        os.path.join(VSC_STORE, "rooveterinaryinc.roo-cline"),
    ),
    ("LM Studio", os.path.join(HOME, ".lmstudio", "mcp.json"), "mcpServers", server_entry, None),
    ("Gemini CLI", os.path.join(HOME, ".gemini", "settings.json"), "mcpServers", server_entry, None),
]


def installed(path, home=None):
    """Клиент стоит на этом компьютере: есть его папка (у расширений VS Code - папка расширения)."""
    return os.path.isdir(home or os.path.dirname(path))


def connected(path, key):
    try:
        with open(path, encoding="utf-8") as fh:
            return NAME in (json.load(fh).get(key) or {})
    except (OSError, ValueError):
        return False


def connect(path, key, entry=server_entry):
    """Добавить сервер в настройки клиента. Старый файл - копией рядом (.bak). Остальные настройки
    клиента не трогаются; файл с комментариями (JSONC) не переписывается - тогда ошибка с путём."""
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError as e:
            raise ValueError(f"файл настроек не чистый JSON (комментарии?), правьте его вручную: {path}") from e
        if not isinstance(data, dict):
            raise ValueError(f"неожиданный формат настроек: {path}")
        shutil.copy2(path, path + ".bak")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data.setdefault(key, {})[NAME] = entry()
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
        # одной кнопкой - клиенты с файлом настроек JSON; две колонки, чтобы окно не росло в высоту
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        self.client_btns = []
        for i, (title, path, key, entry, home) in enumerate(CLIENTS):
            lbl = QLabel(objectName="dim")
            btn = QPushButton(lib_icon("plug-socket"), "")
            btn.clicked.connect(lambda _c=False, t=title, p=path, k=key, e=entry: self.connect_client(t, p, k, e))
            r, c = i // 2, (i % 2) * 3
            grid.addWidget(QLabel(title), r, c)
            grid.addWidget(lbl, r, c + 1)
            grid.addWidget(btn, r, c + 2)
            self.client_btns.append((title, path, key, home, lbl, btn))
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 1)
        cl.addLayout(grid)
        cl.addWidget(QLabel("Командой или блоком настроек", objectName="faint"))
        server = f'py -3.14 "{SERVER}"'
        grid2 = QGridLayout()
        grid2.setHorizontalSpacing(14)
        for i, (title, text, tip) in enumerate(
            (
                (
                    "Claude Code",
                    f"claude mcp add {NAME} -s user -- {server}",
                    "Команда для терминала: сервер будет доступен в любой папке. "
                    "В самой папке библиотеки он уже настроен (.mcp.json).",
                ),
                ("Codex CLI", f"codex mcp add {NAME} -- {server}", "Команда для терминала (OpenAI Codex CLI)."),
                (
                    "Другие (Zed, Continue...)",
                    config_snippet(),
                    "Блок настроек MCP - вставить в настройки помощника",
                ),
                (
                    "Командная строка и скрипты",
                    f'py -3.14 "{os.path.join(HERE, "cli.py")}" api',
                    "Те же операции без MCP: ответ - JSON. Подсказки для помощника - в AGENTS.md",
                ),
            )
        ):
            b = QPushButton(lib_icon("clipboard"), "Копировать")
            b.setToolTip(tip + "\n\n" + text)
            b.clicked.connect(lambda _c=False, t=text, n=title: self.copy(t, n))
            r, c = i // 2, (i % 2) * 3
            grid2.addWidget(QLabel(title), r, c)
            grid2.addWidget(b, r, c + 2)
        grid2.setColumnStretch(1, 1)
        grid2.setColumnStretch(4, 1)
        cl.addLayout(grid2)
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
        for title, path, key, home, lbl, btn in self.client_btns:
            ok = connected(path, key)
            lbl.setText("подключено" if ok else ("не подключено" if installed(path, home) else "не установлен"))
            btn.setText("Заново" if ok else "Подключить")
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

    def connect_client(self, title, path, key, entry=server_entry):
        try:
            connect(path, key, entry)
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
