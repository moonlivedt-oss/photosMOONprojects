"""Сравнить в 3D: 2-4 модели на одном подиуме в одном масштабе (настоящем, если у всех известен размер) или
2-4 текстуры на одинаковых шарах - под одним светом, вращаются вместе. Вкладка «Unreal», правый щелчок по
выбранным -> «Сравнить в 3D». Сцена - compare3d.qml."""

import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtQuickWidgets import QQuickWidget
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ui.common import log_error
from ui.theme import C
from ui.thumbnails import lib_icon
from ui.viewer3d import materials, studio_probe, url

QML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compare3d.qml")


def real_cm(a):
    """Самая большая сторона в см (с сайта или из FBX) или None."""
    if a.get("dimensions_mm"):
        return max(a["dimensions_mm"]) / 10
    d = a.get("dims_cm")
    return max(d) if d else None


def model_file(a):
    return next(
        (
            os.path.join(a["dir"], *m.split("/"))
            for m in a.get("main", [])
            if m.lower().endswith((".fbx", ".gltf", ".glb", ".obj"))
        ),
        "",
    )


class CompareDialog(QDialog):
    def __init__(self, tab, assets):
        super().__init__(tab, Qt.WindowType.Window)
        self.tab, self.cfg = tab, tab.cfg
        kind = assets[0].get("kind")
        self.assets = [a for a in assets if a.get("kind") == kind][:4]
        self.kind = kind
        self.setWindowTitle("Сравнение: " + ", ".join(a.get("name", "") for a in self.assets))
        self.setWindowIcon(lib_icon("dice_3D"))
        self.resize(1280, 760)
        self.quick = QQuickWidget()
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.quick.setSource(QUrl.fromLocalFile(QML))
        self.root = self.quick.rootObject()
        if self.root is None:
            log_error("compare3d.qml: " + "; ".join(e.toString() for e in self.quick.errors()))
        else:
            self.root.setProperty("back", C["bg0"])
            self.root.setProperty("accent", C["acc"])
        sizes = [real_cm(a) for a in self.assets]
        self.can_real = kind == "model" and all(sizes)
        self.real = QCheckBox("Настоящий размер")
        self.real.setToolTip(
            "Модели - в своих сантиметрах: видно, что стол выше стула"
            if self.can_real
            else "Размер известен не у всех - все вписаны в одинаковую высоту"
        )
        self.real.setChecked(self.can_real)
        self.real.setEnabled(self.can_real)
        self.real.toggled.connect(self.place)
        self.spin = QCheckBox("Вращать вместе")
        self.spin.toggled.connect(lambda v: self.set("spin", v))
        self.light = QComboBox()
        self.light.addItem(lib_icon("sun"), "Простой свет", "")
        for a in sorted(
            (x for x in tab.items if x.get("kind") == "hdri" and x.get("main")),
            key=lambda x: (x.get("theme") != "Студия", x.get("name", "")),
        ):
            self.light.addItem(a.get("name", ""), os.path.join(a["dir"], a["main"][0]))
        self.light.setCurrentIndex(max(0, self.light.findData(studio_probe(tab.items, self.cfg))))
        self.light.currentIndexChanged.connect(lambda: self.set("probe", url(self.light.currentData() or "")))
        reset = QPushButton(lib_icon("arrow_counterclockwise"), "Вид заново")
        reset.clicked.connect(lambda: self.root and self.root.resetView())
        bar = QHBoxLayout()
        for w in (self.real, self.spin, QLabel("Свет:"), self.light):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(reset)
        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addWidget(self.quick, 1)
        v.addWidget(QLabel("Тянуть - вращать, колесо - ближе, правая кнопка - сдвиг", objectName="faint"))
        if self.root is not None:
            self.set("probe", url(self.light.currentData() or ""))
            self.place()

    def set(self, k, v):
        if self.root is not None:
            self.root.setProperty(k, v)

    def sub(self, a):
        bits = []
        if a.get("kind") == "model":
            cm = real_cm(a)
            if cm:
                bits.append(f"{round(cm)} см")
            if a.get("polycount"):
                p = a["polycount"]
                bits.append(f"{p / 1000:.1f}k полиг." if p >= 1000 else f"{p} полиг.")
        if a.get("res"):
            bits.append(str(a["res"]).upper())
        bits.append(a.get("source", ""))
        return ", ".join(b for b in bits if b)

    def place(self):
        real = self.real.isChecked() and self.can_real
        items, sizes = [], []
        for a in self.assets:
            d = {"kind": self.kind, "name": a.get("name", ""), "sub": self.sub(a)}
            if self.kind == "model":
                d["src"] = QUrl.fromLocalFile(model_file(a)).toString()
                d["size"] = real_cm(a) if real else 200
                sizes.append(d["size"])
            else:
                m = materials(a)
                d.update(
                    base=QUrl.fromLocalFile(m["baseMap"]).toString() if m.get("baseMap") else "",
                    normal=QUrl.fromLocalFile(m["normalMap"]).toString() if m.get("normalMap") else "",
                    rough=QUrl.fromLocalFile(m["roughMap"]).toString() if m.get("roughMap") else "",
                    roughCh=m.get("roughChannel", 0),
                    size=170,
                )
                sizes.append(170)
            items.append(d)
        if real:  # самая большая - 200 единиц сцены, остальные - в той же пропорции (см)
            k = 200 / max(sizes)
            for d in items:
                d["size"] = d["size"] * k
        self.set("slot", max(230.0, max(d["size"] for d in items) * 1.15))
        self.set("items", [])
        self.set("items", items)
        self.root.resetView()


def can_compare(sel):
    """Сравнивать можно 2-4 одного вида: модели (открываются в 3D) или текстуры."""
    from ui.viewer3d import viewable

    if not 2 <= len(sel) <= 4 or len({a.get("kind") for a in sel}) != 1:
        return False
    k = sel[0].get("kind")
    return k == "tex" or (k == "model" and all(viewable(a) for a in sel) and all(model_file(a) for a in sel))
