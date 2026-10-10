#!/usr/bin/env python3
"""Снимки окна для README: py -3.14 _tools/docs_screenshots.py [снимок ...] [--out папка].

Открывает настоящее окно (на экране, иначе нет шрифтов), выставляет вкладки, модели и ракурсы и сохраняет
снимки в _docs/screenshots (webp). settings.json окно по ходу меняет - копия возвращается в конце.
Снимки: hero, unreal, viewer-model, viewer-texture, scene, room; без имён - все."""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PIL import Image  # noqa: E402
from PyQt6.QtCore import QObject, QTimer  # noqa: E402
from PyQt6.QtGui import QVector3D  # noqa: E402
from PyQt6.QtWidgets import QAbstractItemView, QApplication, QSplitter  # noqa: E402

from library.common import LIB  # noqa: E402

CFG = os.path.join(HERE, "settings.json")
OUT = os.path.join(LIB, "_docs", "screenshots")

# что показывать: подобрано по превью - самые выразительные из скачанного
HERO = ("02 Наклейки/Сказочные существа/Фиолетовая ночь", "baby-dragon")
UNREAL = dict(kind="model", style="real", theme="::sec:Дом|Декор", pick="Bronze Whale Statue")
MODEL = dict(kind="model", style="real", theme="::sec:Дом|Стулья и кресла", pick="Mid Century Lounge Chair")
MODEL_VIEW = dict(angle=(-14, 34), env="Photo Studio Loft Hall", exposure=135)
TEXTURE = dict(kind="tex", style="all", theme=None, pick="Coast Sand Rocks 02")
TEXTURE_VIEW = dict(angle=(-18, 30), env="Photo Studio Loft Hall", exposure=120)
SCENE = "уютная гостиная в винтажном стиле"
# комната - отобранные вещи (подборка по описанию может взять ящик для рассады или раму без стены)
ROOM = (
    "Sofa 03",
    "Mid Century Lounge Chair",
    "Rockingchair 01",
    "Coffee Table 01",
    "Vintage Cabinet 01",
    "Wooden Display Shelves",
    "Classic Console 01",
    "Ornate Mirror 01",
    "Potted Plant 02",
    "Potted Plant 04",
    "Chandelier 01",
)


def to_webp(pm, name):
    tmp = os.path.join(OUT, name + ".tmp.png")
    pm.save(tmp, "PNG")
    with Image.open(tmp) as im:
        im.convert("RGB").save(os.path.join(OUT, name + ".webp"), "WEBP", quality=90, method=6)
    os.remove(tmp)
    print("снимок:", name)


class Shots:
    def __init__(self, names):
        from ui import main_window as M
        from ui import theme

        cfg = M.load_cfg()
        theme.apply(cfg.get("theme", "dark"), cfg.get("accent", "lavender"))
        QApplication.instance().setStyleSheet(theme.stylesheet())
        self.w = M.Window()
        self.w.show()
        self.steps = []
        for n in names:
            getattr(self, "shot_" + n.replace("-", "_"))()

    # --------------------------------------------------------- шаги
    def add(self, delay, fn):
        self.steps.append((delay, fn))

    def run(self):
        if not self.steps:
            finish(0)
            return
        delay, fn = self.steps.pop(0)

        def go():
            try:
                fn()
            except Exception:
                import traceback

                traceback.print_exc()
                finish(1)
                return
            self.run()

        QTimer.singleShot(delay, go)

    # --------------------------------------------------------- помощники
    def ue_open(self, kind, style, theme, pick):
        """Вкладка Unreal: вид, стиль, раздел дерева и выбранная плитка."""
        from ui.unreal_tiles import ASSET

        w = self.w
        tab = w.unreal
        w.tabs.setCurrentWidget(tab)
        nav = tab.nav
        nav.kind, nav.theme = kind, theme
        nav.style.cur = style
        nav.set_items(tab.items, tab.favs())
        tab.show_assets()
        for i in range(tab.list.count()):
            if tab.list.item(i).data(ASSET).get("name") == pick:
                tab.list.setCurrentRow(i)
                tab.list.scrollToItem(tab.list.item(i), QAbstractItemView.ScrollHint.PositionAtCenter)
                return tab.list.item(i).data(ASSET)
        raise RuntimeError(f"нет «{pick}» в {theme}")

    def ue_ready(self):
        tab = self.w.unreal
        self.w.tabs.setCurrentWidget(tab)
        if not tab.loaded:
            tab.refresh()

    def view(self, spec, look, name, size=(1100, 680)):
        def open3d():
            tab = self.w.unreal
            tab.view3d(self.ue_open(**spec))
            tab.viewer.resize(*size)

        def light():
            v = self.w.unreal.viewer
            for i in range(v.env.count()):
                if v.env.itemText(i).startswith(look["env"]):
                    v.env.setCurrentIndex(i)
                    break
            v.expo.setValue(look["exposure"])

        def angle():
            v = self.w.unreal.viewer
            pitch, yaw = look["angle"]
            v.root.findChild(QObject, "orbit").setProperty("eulerRotation", QVector3D(pitch, yaw, 0))

        self.add(300, self.ue_ready)
        self.add(4000, open3d)
        self.add(5000, light)
        self.add(2500, angle)
        self.add(1500, lambda: to_webp(self.w.unreal.viewer.grab(), name))
        self.add(200, lambda: self.w.unreal.viewer.hide())

    # --------------------------------------------------------- снимки
    def shot_hero(self):
        def setup():
            w = self.w
            w.resize(1536, 941)
            w.tabs.setCurrentWidget(w.lib)
            w.lib.split.setSizes([290, 880, 340])  # дереву - место под имена разделов
            w.lib.show_section(os.path.join(LIB, *HERO[0].split("/")))

        def pick():
            lst = self.w.lib.list
            for i in range(lst.count()):
                if lst.item(i).text() == HERO[1]:
                    lst.setCurrentRow(i)

        self.add(500, setup)
        self.add(2500, pick)
        self.add(2500, lambda: to_webp(self.w.grab(), "hero"))

    def shot_unreal(self):
        def wide():  # после того как окно сменило размер, иначе раскладка вернёт старые доли
            tab = self.w.unreal
            split = next(sp for sp in tab.findChildren(QSplitter) if sp.widget(0) is tab.nav)
            split.setSizes([290, 880, 340])

        self.add(300, self.ue_ready)
        self.add(4000, lambda: (self.w.resize(1536, 941), self.ue_open(**UNREAL)))
        self.add(1500, wide)
        self.add(6000, lambda: to_webp(self.w.grab(), "unreal"))

    def shot_viewer_model(self):
        self.view(MODEL, MODEL_VIEW, "viewer-model")

    def shot_viewer_texture(self):
        self.view(TEXTURE, TEXTURE_VIEW, "viewer-texture")

    def shot_scene(self):
        def setup():
            tab = self.w.unreal
            tab.scene()
            d = tab.scene_dlg
            d.resize(860, 760)
            d.q.setText(SCENE)
            d.build()

        self.add(300, self.ue_ready)
        self.add(4000, setup)
        self.add(9000, lambda: to_webp(self.w.unreal.scene_dlg.grab(), "scene"))

    def shot_room(self):
        def setup():
            tab = self.w.unreal
            by = {a.get("name"): a for a in tab.items if a.get("kind") == "model"}
            tab.room([by[n] for n in ROOM if n in by], "Гостиная")
            d = tab.room_dlg
            d.resize(1100, 700)
            for cb, want in ((d.floor, "Wooden Floor"), (d.light, "Photo Studio")):
                i = next((i for i in range(cb.count()) if cb.itemText(i).startswith(want)), -1)
                if i >= 0:
                    cb.setCurrentIndex(i)

        def closer():  # комната крупнее и чуть сверху - мебель видно, пустого пола меньше
            root = self.w.unreal.room_dlg.root
            cam = root.findChild(QObject, "cam")
            cam.setProperty("position", QVector3D(0, 0, cam.property("position").z() * 0.74))
            root.findChild(QObject, "orbit").setProperty("eulerRotation", QVector3D(-30, 18, 0))

        self.add(300, self.ue_ready)
        self.add(4000, setup)
        self.add(9000, closer)
        self.add(2000, lambda: to_webp(self.w.unreal.room_dlg.grab(), "room"))


def finish(code):
    if os.path.exists(CFG + ".shotbak"):
        shutil.copy(CFG + ".shotbak", CFG)
        os.remove(CFG + ".shotbak")
    os._exit(code)


def main():
    global OUT
    args = sys.argv[1:]
    if "--out" in args:
        i = args.index("--out")
        OUT = os.path.abspath(args[i + 1])
        del args[i : i + 2]
    os.makedirs(OUT, exist_ok=True)
    names = args or ["hero", "unreal", "viewer-model", "viewer-texture", "scene", "room"]
    shutil.copy(CFG, CFG + ".shotbak")
    app = QApplication(sys.argv[:1])
    s = Shots(names)
    QTimer.singleShot(1500, s.run)
    QTimer.singleShot(300000, lambda: finish(2))
    app.exec()


if __name__ == "__main__":
    main()
