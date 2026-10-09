"""Окно «Подборка по описанию»: «уютная спальня в скандинавском стиле» -> вещи по разделам, пол, стены,
небо. У каждой строки - «Другой вариант»; результат - подборка, комната или импорт в Unreal.
Сам подбор - library/scene_plan.py."""

import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from library import scene_plan as P
from library import unreal as U
from ui.common import bg, log_error
from ui.thumbnails import lib_icon, thumb

EXAMPLES = (
    "уютная спальня в скандинавском стиле",
    "старинный кабинет с тёмным деревом",
    "белая современная ванная",
    "low-poly кухня",
)


class Row(QWidget):
    """Строка плана: превью, раздел, имя, «Другой вариант», галочка «брать»."""

    def __init__(self, dlg, label, choices):
        super().__init__()
        self.dlg, self.label, self.choices, self.i = dlg, label, choices, 0
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 4, 6, 4)
        self.on = QCheckBox()
        self.on.setChecked(True)
        self.on.setToolTip("Брать в подборку")
        self.pic = QLabel()
        self.pic.setFixedSize(56, 56)
        self.sec = QLabel(label, objectName="faint")
        self.sec.setFixedWidth(150)
        self.name = QLabel()
        self.other = QPushButton(lib_icon("dice"), "Другой вариант")
        self.other.setToolTip("Следующий подходящий из того же раздела")
        self.other.clicked.connect(self.next)
        self.other.setEnabled(len(choices) > 1)
        for w in (self.on, self.pic, self.sec):
            h.addWidget(w)
        h.addWidget(self.name, 1)
        h.addWidget(self.other)
        self.show_cur()

    def cur(self):
        return self.choices[self.i] if self.on.isChecked() else None

    def next(self):
        self.i = (self.i + 1) % len(self.choices)
        self.show_cur()

    def show_cur(self):
        a = self.choices[self.i]
        prev = os.path.join(a["dir"], "preview.webp")
        self.pic.setPixmap(thumb(prev, 56) if os.path.exists(prev) else lib_icon("dice_3D").pixmap(40, 40))
        src = a.get("source", "")
        self.name.setText(f"{a.get('name', '')}   <span style='color:gray'>{src}</span>")
        self.name.setToolTip(a["dir"])


class SceneDialog(QDialog):
    def __init__(self, tab):
        super().__init__(tab, Qt.WindowType.Window)
        self.tab = tab
        self.setWindowTitle("Подборка по описанию")
        self.setWindowIcon(lib_icon("sparkles"))
        self.resize(860, 760)
        self.q = QLineEdit(placeholderText="Опишите комнату: " + EXAMPLES[0], objectName="search")
        self.q.returnPressed.connect(self.build)
        self.style = QComboBox()
        for t, v in (("Стиль: по описанию", None), ("Реалистичные модели", False), ("Low-poly", True)):
            self.style.addItem(t, v)
        go = QPushButton(lib_icon("sparkles"), "Собрать", objectName="primary")
        go.clicked.connect(self.build)
        top = QHBoxLayout()
        top.addWidget(self.q, 1)
        top.addWidget(self.style)
        top.addWidget(go)
        ex = QHBoxLayout()
        ex.addWidget(QLabel("Например:", objectName="faint"))
        for e in EXAMPLES:
            b = QPushButton(e, objectName="chip")
            b.clicked.connect(lambda _c=False, t=e: (self.q.setText(t), self.build()))
            ex.addWidget(b)
        ex.addStretch(1)
        self.info = QLabel(
            "ИИ подберёт вещи по разделам «Дома», пол, стены и небо из скачанных ассетов - по смыслу описания.",
            objectName="dim",
            wordWrap=True,
        )
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.save_btn = QPushButton(lib_icon("bookmark"), "Сохранить подборку")
        self.save_btn.clicked.connect(self.save)
        self.room_btn = QPushButton(lib_icon("house"), "Комната")
        self.room_btn.setToolTip("Расставить в 3D-комнате: пол и стены - из подборки")
        self.room_btn.clicked.connect(self.room)
        self.imp_btn = QPushButton(lib_icon("export"), "Импорт в Unreal...")
        self.imp_btn.clicked.connect(lambda: self.tab.import_assets(self.picked()))
        self.blend_btn = QPushButton(lib_icon("dice_3D"), "В Blender")
        self.blend_btn.setToolTip(
            "Собрать комнату в Blender: модели в масштабе, пол, стены, свет HDRI; сохранить .blend"
        )
        self.blend_btn.clicked.connect(self.blender)
        self.pack_btn = QPushButton(lib_icon("zip-archive"), "Пакет...")
        self.pack_btn.setToolTip("Файлы, скрипт импорта, авторы и лицензии - одной папкой или zip")
        self.pack_btn.clicked.connect(lambda: self.tab.pack_assets(self.picked(), self.q.text().strip()[:60]))
        foot = QHBoxLayout()
        foot.addStretch(1)
        for b in (self.save_btn, self.room_btn, self.blend_btn, self.imp_btn, self.pack_btn):
            b.setEnabled(False)
            foot.addWidget(b)
        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addLayout(ex)
        v.addWidget(self.info)
        v.addWidget(self.list, 1)
        v.addLayout(foot)
        self.rows = []

    def build(self):
        text = self.q.text().strip()
        if not text:
            self.q.setFocus()
            return
        sem = self.tab.sem
        if sem is None:
            self.info.setText("Нужна модель поиска по смыслу: py -3.14 _tools/get_models.py clip")
            return
        items, style = list(self.tab.items), self.style.currentData()
        self.info.setText("Подбираю...")

        def section_of(a):
            return a.get("section") or U.home_section(a)

        def done(p):
            if isinstance(p, Exception):
                log_error("scene plan: %r" % p)
                self.info.setText(f"Не вышло: {p}")
                return
            self.show_plan(p)

        bg(lambda: P.plan(sem, items, text, section_of, low_poly=style), done)

    def show_plan(self, p):
        self.list.clear()
        self.rows = []
        rows = [(s["section"], s["choices"]) for s in p["slots"]]
        rows += [(t, p[k]) for t, k in (("Пол", "floor"), ("Стены", "wall"), ("Небо HDRI", "hdri")) if p[k]]
        for label, choices in rows:
            w = Row(self, label, choices)
            it = QListWidgetItem()
            it.setSizeHint(QSize(0, 66))
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            self.rows.append(w)
        mixed = {a.get("source") in P.LOW_POLY_SOURCES for _l, ch in rows[: len(p["slots"])] for a in ch[:1]}
        self.info.setText(
            f"Комната: {p['room']}, стиль: {'low-poly' if p['low_poly'] else 'реалистичный'}. "
            f"Вещей: {len(p['slots'])}"
            + (". Где своего стиля почти нет, взяты модели другого" if len(mixed) > 1 else "")
            + ". «Другой вариант» - следующий подходящий."
        )
        if not p["slots"]:
            self.info.setText("Для этой комнаты нет скачанных моделей - «Скачать ещё...», темы «Дом - ...»")
        for b in (self.save_btn, self.room_btn, self.blend_btn, self.imp_btn, self.pack_btn):
            b.setEnabled(bool(self.rows))

    def picked(self):
        return [a for a in (r.cur() for r in self.rows) if a]

    def save(self):
        name = self.q.text().strip()[:60] or "Подборка"
        self.tab.add_to_set(name, self.picked())
        self.tab.nav.pick_kind("::sets")

    def blender(self):
        """Пол, стены и небо - из своих строк плана, остальное - вещи комнаты."""
        by = {r.label: r.cur() for r in self.rows}
        special = {"Пол", "Стены", "Небо HDRI"}
        models = [r.cur() for r in self.rows if r.label not in special and r.cur()]
        self.tab.open_blender(
            models,
            self.q.text().strip()[:40] or "Комната",
            room=True,
            floor=by.get("Пол"),
            wall=by.get("Стены"),
            hdri=by.get("Небо HDRI"),
        )

    def room(self):
        self.tab.room(self.picked(), self.q.text().strip()[:40] or "Комната")
