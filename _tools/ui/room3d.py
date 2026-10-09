"""Комната из подборки или выделения: пол и стены - из скачанных текстур, мебель - модели в настоящем
масштабе (сантиметры), свет - HDRI. Черновик интерьера перед Unreal; «Импорт в Unreal» берёт всё разом."""

import os
import random

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QIcon
from PyQt6.QtQuickWidgets import QQuickWidget
from PyQt6.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from library import unreal as U
from ui.common import log_error
from ui.theme import C
from ui.thumbnails import lib_icon, thumb
from ui.viewer3d import materials, studio_probe, url

QML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "room3d.qml")

# размер по умолчанию (самая большая сторона, см), когда у модели нет настоящих размеров
DEFAULT_CM = {
    "Кровати": 210,
    "Диваны": 210,
    "Стулья и кресла": 90,
    "Столы": 130,
    "Шкафы и полки": 180,
    "Кухня и посуда": 90,
    "Ванная": 150,
    "Свет": 150,
    "Техника": 70,
    "Декор": 50,
    "Растения": 90,
    "Стены, двери, окна": 220,
    "Мелочи": 45,
}


def size_cm(a):
    dims = a.get("dimensions_mm")
    if dims and max(dims) > 0:
        return max(10.0, max(dims) / 10)
    return DEFAULT_CM.get(a.get("section") or U.home_section(a), 80)


def footprint(a, s):
    """Сколько места модель занимает на полу (см): у Poly Haven - настоящие ширина и глубина
    (dimensions_mm: x, y - пол, z - высота), у простых моделей - самая большая сторона, с запасом."""
    dims = a.get("dimensions_mm")
    if dims and len(dims) == 3 and max(dims[:2]) > 0:
        return max(20.0, max(dims[0], dims[1]) / 10)
    return s


def layout(models, seed=None):
    """Расстановка рядами от задней стены. -> (items, ширина, глубина) в см."""
    order = list(models)
    if seed is not None:
        random.Random(seed).shuffle(order)
    if seed is None:  # по умолчанию крупное - к задней стене
        order.sort(key=lambda a: -size_cm(a))
    sizes = [size_cm(a) for a in order]
    area = sum((footprint(a, s) + 50) ** 2 for a, s in zip(order, sizes))
    w = max(380.0, min(1400.0, (area**0.5) * 1.15))
    items, x, z, row = [], -w / 2 + 30, None, 0.0
    for a, s in zip(order, sizes):
        fp = footprint(a, s)
        if z is None:
            z = 0.0
        if x + fp > w / 2 - 30 and x > -w / 2 + 30:  # ряд кончился
            z += row + 50
            x, row = -w / 2 + 30, 0.0
        items.append({"a": a, "x": x + fp / 2, "z": z + fp / 2, "size": s})
        x += fp + 50
        row = max(row, fp)
    d = max(380.0, z + row + 120)
    for it in items:  # z считался от задней стены
        it["z"] = -d / 2 + 20 + it["z"]
    return items, w, d


class RoomDialog(QDialog):
    def __init__(self, tab, assets, title="Комната"):
        super().__init__(tab, Qt.WindowType.Window)
        self.tab, self.cfg = tab, tab.cfg
        self.models = [a for a in assets if a.get("kind") == "model"]
        self.extra = [a for a in assets if a.get("kind") == "tex"]
        self.seed = None
        self.setWindowTitle(f"{title} - черновик интерьера")
        self.setWindowIcon(lib_icon("house"))
        self.resize(1280, 820)

        self.quick = QQuickWidget()
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.quick.setSource(QUrl.fromLocalFile(QML))
        self.root = self.quick.rootObject()
        if self.root is None:
            log_error("room3d.qml: " + "; ".join(e.toString() for e in self.quick.errors()))
        else:
            self.root.setProperty("back", C["bg0"])

        self.floor = self.tex_combo("Дом - полы")
        self.wall = self.tex_combo("Дом - стены")
        self.floor.currentIndexChanged.connect(self.apply_textures)
        self.wall.currentIndexChanged.connect(self.apply_textures)
        self.light = QComboBox()
        self.light.addItem(lib_icon("sun"), "Простой свет", "")
        for a in sorted(
            (x for x in tab.items if x.get("kind") == "hdri"),
            key=lambda x: (x.get("theme") != "Интерьер", x.get("name", "")),
        ):
            self.light.addItem(a.get("name", ""), os.path.join(a["dir"], a["main"][0]))
        probe = studio_probe(tab.items, self.cfg)
        self.light.setCurrentIndex(max(0, self.light.findData(probe)))
        self.light.currentIndexChanged.connect(lambda: self.set("probe", url(self.light.currentData() or "")))
        again = QPushButton(lib_icon("dice"), "Расставить иначе")
        again.setToolTip("Другой порядок мебели")
        again.clicked.connect(self.shuffle)
        reset = QPushButton(lib_icon("arrow_counterclockwise"), "Вид заново")
        reset.clicked.connect(lambda: self.root and self.root.resetView())
        shot = QPushButton(lib_icon("camera"), "Снимок")
        shot.clicked.connect(self.screenshot)
        imp = QPushButton(lib_icon("export"), "Импорт в Unreal...", objectName="primary")
        imp.setToolTip("Модели, пол и стены - одним скриптом, с материалами")
        imp.clicked.connect(self.import_ue)
        self.info = QLabel(objectName="dim")

        bar = QHBoxLayout()
        for w in (QLabel("Пол:"), self.floor, QLabel("Стены:"), self.wall, QLabel("Свет:"), self.light):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (again, reset, shot, imp):
            bar.addWidget(w)
        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addWidget(self.quick, 1)
        h = QHBoxLayout()
        h.addWidget(self.info, 1)
        h.addWidget(QLabel("Тянуть - вращать, колесо - ближе, правая кнопка - сдвиг", objectName="faint"))
        v.addLayout(h)
        if self.root is not None:
            self.set("probe", url(self.light.currentData() or ""))
            self.apply_textures()
            self.place()

    def set(self, k, v):
        if self.root is not None:
            self.root.setProperty(k, v)

    def tex_combo(self, theme):
        """Текстуры темы (сперва те, что в подборке) - для пола или стен."""
        cb = QComboBox()
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(12)
        cb.addItem("Без текстуры", None)
        mine = [a for a in self.extra if a.get("theme") == theme]
        rest = [a for a in self.tab.items if a.get("kind") == "tex" and a.get("theme") == theme and a not in mine]
        for a in mine + sorted(rest, key=lambda x: x.get("name", "")):
            prev = os.path.join(a["dir"], "preview.webp")
            cb.addItem(QIcon(thumb(prev, 48)) if os.path.exists(prev) else QIcon(), a.get("name", ""), a)
        cb.setCurrentIndex(1 if cb.count() > 1 else 0)
        return cb

    def apply_textures(self):
        for cb, pre in ((self.floor, "floor"), (self.wall, "wall")):
            a = cb.currentData()
            m = materials(a) if a else {}
            self.set(pre + "Base", url(m.get("baseMap", "")))
            self.set(pre + "Normal", url(m.get("normalMap", "")))
            self.set(pre + "Rough", url(m.get("roughMap", "")))
            self.set(pre + "RoughCh", m.get("roughChannel", 0))

    def place(self):
        items, w, d = layout(self.models, self.seed)
        data = []
        for it in items:
            a = it["a"]
            fbx = next(
                (
                    os.path.join(a["dir"], *m.split("/"))
                    for m in a.get("main", [])
                    if m.lower().endswith((".fbx", ".gltf", ".glb", ".obj"))
                ),
                "",
            )
            data.append(
                {
                    "src": QUrl.fromLocalFile(fbx).toString(),
                    "x": it["x"],
                    "z": it["z"],
                    "rot": 0,
                    "size": it["size"],
                    "linear": a.get("source") == "Quaternius",
                }
            )
        self.set("roomW", w)
        self.set("roomD", d)
        self.set("items", [])
        self.set("items", data)
        self.root.resetView()
        self.info.setText(
            f"Мебели: {len(data)}, комната {w / 100:.1f} x {d / 100:.1f} м, "
            "размеры - настоящие у Poly Haven, примерные у простых моделей"
        )

    def shuffle(self):
        self.seed = random.randrange(1 << 30)
        self.place()

    def screenshot(self):
        start = os.path.join(self.cfg.get("ue_shots", os.path.expanduser("~/Pictures")), "Комната.png")
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить снимок комнаты", start, "PNG (*.png)")
        if path:
            self.cfg["ue_shots"] = os.path.dirname(path)
            self.quick.grabFramebuffer().save(path, "PNG")
            self.tab.win.say(f"Снимок сохранён: {os.path.basename(path)}")

    def import_ue(self):
        picked = [cb.currentData() for cb in (self.floor, self.wall) if cb.currentData()]
        self.tab.import_assets(self.models + picked)
