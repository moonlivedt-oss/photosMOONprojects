"""Общий поиск по окну (Ctrl+P): команды («сжать», «тема», «дубли»), разделы, картинки библиотеки и ассеты
Unreal - в одной строке. Стрелки выбирают, Enter выполняет, Esc закрывает."""

import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

import imaging as K
from ui.common import LIB
from ui.thumbnails import lib_icon, thumb

ACT = Qt.ItemDataRole.UserRole + 40


def commands(win):
    """[(название, ключевые слова, значок, действие)] - всё, что есть в кнопках и меню окна."""
    lib, ue = win.lib, win.unreal
    tab = win.tabs.setCurrentIndex
    return [
        ("Входящие", "листы нарезка вкладка", "download-arrow", lambda: tab(0)),
        ("Библиотека", "картинки вкладка", "image-file", lambda: tab(1)),
        ("Unreal", "ассеты 3d модели текстуры hdri вкладка", "game-cartridge", lambda: tab(2)),
        ("Оформление: тема и акцент", "тема светлая тёмная цвет акцент дизайн", "color-palette", win.theme_dialog),
        ("ИИ-помощники", "claude cursor mcp агенты подключить", "sparkles", win.agents),
        ("Справка", "помощь клавиши f1", "question-mark-bubble", win.show_help),
        ("Галерея в браузере", "gallery html", "globe", win.open_gallery),
        ("Промпты", "prompts генерация", "clipboard", win.open_prompts),
        ("Найти дубли", "одинаковые повторы", "magnifying-glass", win.dupes),
        ("Доктор библиотеки", "проверка проблемы битые", "first-aid-kit", win.doctor),
        ("Чего нет в наборах", "палитры недостающие", "checklist", win.missing),
        ("Вес разделов", "размер место диск", "zip-archive", win.show_weight),
        ("Папка генератора", "слежка генератор", "eye", win.pick_gen),
        ("Вставить из буфера", "ctrl+v paste", "clipboard", win.paste),
        ("Палитра из картинки", "цвета перекрасить", "color-palette", lambda: lib.palette_from()),
        ("Сравнить две картинки", "сравнение разница ssim", "magnifying-glass", lambda: lib.compare()),
        ("Векторизация в SVG", "svg vtracer вектор", "drawing_pen", lambda: lib.vectorize()),
        ("Сжать выбранные", "сжатие конвертировать webp", "zip-archive", lib.compress),
        ("Выгрузить выбранные в проект", "экспорт export", "upload-arrow", lib.export),
        ("Редактировать выбранную", "правка редактор", "paint-brush", lib.edit),
        ("Скачать ассеты Unreal", "poly haven ambientcg загрузить", "download", lambda: (tab(2), ue.download())),
        ("Каталог Poly Haven", "каталог ассеты", "globe", lambda: (tab(2), ue.catalog())),
    ]


class CommandPalette(QDialog):
    def __init__(self, win):
        super().__init__(win, Qt.WindowType.Popup)
        self.win = win
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.q = QLineEdit(placeholderText="Команда, раздел, картинка или ассет Unreal...", objectName="search")
        self.q.addAction(lib_icon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self.list = QListWidget()
        self.list.setIconSize(QSize(28, 28))
        self.list.itemActivated.connect(self.run)
        self.hint = QLabel("Enter - выполнить, стрелки - выбор, Esc - закрыть", objectName="faint")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 10)
        v.addWidget(self.q)
        v.addWidget(self.list, 1)
        v.addWidget(self.hint)
        self.cmds = commands(win)
        self.files = None  # картинки - один обход при первом вводе
        self.folders = None
        self.q.textChanged.connect(self.fill)
        self.q.returnPressed.connect(lambda: self.run(self.list.currentItem()))
        self.q.installEventFilter(self)
        w = min(720, win.width() - 80)
        self.resize(w, 460)
        g = win.geometry()
        self.move(g.x() + (g.width() - w) // 2, g.y() + 90)
        self.fill("")

    def eventFilter(self, obj, e):
        if obj is self.q and e.type() == e.Type.KeyPress and e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.list.currentRow() + (1 if e.key() == Qt.Key.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return True
        return super().eventFilter(obj, e)

    def add(self, text, sub, icon, act):
        icon = QIcon(icon) if isinstance(icon, QPixmap) else icon
        it = QListWidgetItem(icon, f"{text}    {sub}" if sub else text)
        it.setData(ACT, act)
        self.list.addItem(it)

    def section(self, text):
        it = QListWidgetItem(text)
        it.setFlags(Qt.ItemFlag.NoItemFlags)
        it.setForeground(self.palette().placeholderText())
        self.list.addItem(it)

    def fill(self, text):
        words = text.lower().split()
        self.list.clear()

        def hit(*hay):
            s = " ".join(hay).lower()
            return all(w in s for w in words)

        cmds = [c for c in self.cmds if hit(c[0], c[1])]
        if cmds:
            self.section("КОМАНДЫ")
            for title, _k, icon, fn in cmds[: 8 if words else 30]:
                self.add(title, "", lib_icon(icon), fn)
        if words:
            if self.files is None:
                self.files = [p for p in K.images_in(LIB)]
                self.folders = sorted({os.path.dirname(p) for p in self.files} - {LIB})
            dirs = [d for d in self.folders if hit(os.path.relpath(d, LIB))][:6]
            if dirs:
                self.section("РАЗДЕЛЫ")
                for d in dirs:
                    self.add(
                        os.path.relpath(d, LIB).replace(os.sep, " / "),
                        "",
                        lib_icon("folder"),
                        lambda d=d: self.win.lib.go_to(d),
                    )
            pics = [p for p in self.files if hit(os.path.relpath(p, LIB))][:8]
            sem = self.win.sem
            if not pics and len(text.strip()) >= 3 and getattr(sem, "ok", False):  # «кит» найдёт whale.webp
                try:
                    pics = sem.search(text, 8)
                except Exception:
                    pics = []
            if pics:
                self.section("КАРТИНКИ")
                for p in pics:
                    rel = os.path.relpath(os.path.dirname(p), LIB).replace(os.sep, " / ")
                    self.add(
                        os.path.splitext(os.path.basename(p))[0],
                        rel,
                        thumb(p, 56),
                        lambda p=p: self.win.lib.go_to(os.path.dirname(p), p),
                    )
            ue = self.win.unreal
            assets = [a for a in ue.items if hit(a.get("name", ""), a.get("theme", ""), " ".join(a.get("tags", [])))][
                :6
            ]
            if assets:
                self.section("АССЕТЫ UNREAL")
                for a in assets:
                    prev = os.path.join(a["dir"], "preview.webp")
                    icon = thumb(prev, 56) if os.path.exists(prev) else lib_icon("game-cartridge")
                    self.add(a.get("name", ""), a.get("theme", ""), icon, lambda a=a: ue.go_to(a))
        if not self.list.count():
            self.section("Ничего не нашлось")
        for i in range(self.list.count()):  # первая выполнимая строка - выбрана
            if self.list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled:
                self.list.setCurrentRow(i)
                break

    def run(self, it):
        act = it.data(ACT) if it else None
        if act:
            self.close()
            act()
