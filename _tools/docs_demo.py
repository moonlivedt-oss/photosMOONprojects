#!/usr/bin/env python3
"""Анимация для README: py -3.14 _tools/docs_demo.py [--out папка].

Настоящее окно: лист во входящих режется по сетке (повторы помечены «уже есть»), поиск по смыслу находит
картинки без этих слов в именах, во вкладке «Unreal» модель вращается в 3D. Кадры снимаются grab() окна
и собираются в анимированный webp (_docs/screenshots/demo.webp). Входящие - временная папка с копией листа
из _sources, настройки - временная копия: библиотека и settings.json не меняются."""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from library import common as C  # noqa: E402

SHEET = os.path.join(C.LIB, "_sources", "2026-10", "Код и VS Code [ic default].png")
QUERY = "ночной город"
MODEL = dict(kind="model", style="real", theme="::sec:Дом|Стулья и кресла", pick="Mid Century Lounge Chair")
SIZE = (1280, 780)  # окно
WIDTH = 880  # ширина анимации
FPS = 8


def main():
    out = os.path.join(C.LIB, "_docs", "screenshots")
    if "--out" in sys.argv:
        out = os.path.abspath(sys.argv[sys.argv.index("--out") + 1])
    tmp = tempfile.mkdtemp(prefix="demo-")
    inbox = os.path.join(tmp, "inbox")
    os.makedirs(inbox)
    shutil.copy(SHEET, inbox)
    # настройки - копией: окно пишет в них (последний визит Unreal, размеры), а здесь - без автораскладки
    cfg_path = os.path.join(tmp, "settings.json")
    if os.path.exists(C.CFG):
        shutil.copy(C.CFG, cfg_path)
    C.CFG = cfg_path
    cfg = C.load_cfg()
    cfg.update(auto_route=False, gen_dir="", semantic=True, ue_live=True)
    C.save_cfg(cfg)

    from PIL import Image
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from ui import main_window as M
    from ui import theme

    for mod in list(sys.modules.values()):  # входящие - во временную папку во всех модулях окна
        if getattr(mod, "INBOX", None) == C.INBOX and mod is not C:
            mod.INBOX = inbox
    C.INBOX = inbox
    theme.apply(cfg.get("theme", "dark"), cfg.get("accent", "lavender"))
    app.setStyleSheet(theme.stylesheet())
    w = M.Window()
    w.resize(*SIZE)
    w.show()

    from ui.render_previews import to_pil

    clip = []  # [(кадр, мс)]

    def snap():
        pic = to_pil(w.grab().toImage()).convert("RGB")
        return pic.resize((WIDTH, round(pic.height * WIDTH / pic.width)), Image.Resampling.LANCZOS)

    def add(pic, ms):
        if clip and clip[-1][0].size == pic.size:  # плавный переход от прошлой сцены
            prev = clip[-1][0]
            for k in range(1, 6):
                clip.append((Image.blend(prev, pic, k / 6), 50))
        clip.append((pic, ms))

    def still(ms):
        return lambda: add(snap(), ms)

    live = {"on": False, "t": 0.0, "first": True}

    def live_frame():
        if not live["on"]:
            return
        now = time.time()
        pic = snap()
        if live["first"]:
            add(pic, 100)
            live["first"] = False
        else:
            clip[-1] = (clip[-1][0], max(60, round((now - live["t"]) * 1000)))  # настоящая скорость вращения
            clip.append((pic, 100))
        live["t"] = now

    clock = QTimer(interval=1000 // FPS)
    clock.timeout.connect(live_frame)

    def inbox_tab():
        w.tabs.setCurrentIndex(0)
        w.inbox.reload()
        if w.inbox.files.count():
            w.inbox.files.setCurrentRow(0)

    def lib_tab():
        w.tabs.setCurrentIndex(1)
        w.lib.sem.setChecked(True)
        w.lib.q.setText(QUERY)

    def lib_pick():
        lst = w.lib.list
        names = [lst.item(i).text() for i in range(lst.count())]
        row = next((i for i, n in enumerate(names) if "lantern-market" in n or "rainy" in n), 0)
        lst.setCurrentRow(row)
        lst.scrollToItem(lst.item(row))

    def unreal_tab():
        tab = w.unreal
        w.tabs.setCurrentWidget(tab)
        if not tab.loaded:
            tab.refresh()

    def unreal_pick():
        from ui.unreal_tiles import ASSET

        tab = w.unreal
        nav = tab.nav
        nav.kind, nav.theme = MODEL["kind"], MODEL["theme"]
        nav.style.cur = MODEL["style"]
        nav.set_items(tab.items, tab.favs())
        tab.show_assets()
        for i in range(tab.list.count()):
            if tab.list.item(i).data(ASSET).get("name") == MODEL["pick"]:
                tab.list.setCurrentRow(i)
                tab.list.scrollToItem(tab.list.item(i))
                return
        print("нет модели", MODEL["pick"], tab.list.count())

    def live_on():
        live.update(on=True, t=time.time())
        clock.start()

    def save():
        live["on"] = False
        clock.stop()
        path = os.path.join(out, "demo.webp")
        frames = [f for f, _ms in clip]
        durations = [ms for _f, ms in clip]
        durations[-1] = 1500  # пауза перед повтором
        frames[0].save(
            path, "WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=0, quality=74, method=6
        )
        print(
            f"анимация: {path}, кадров {len(frames)}, {sum(durations) / 1000:.1f} с, {os.path.getsize(path) // 1024} КБ"
        )
        shutil.rmtree(tmp, ignore_errors=True)
        os._exit(0)

    steps = [
        (9000, lambda: None),
        (3000, inbox_tab),
        (200, still(2800)),
        (6000, lib_tab),
        (200, still(2400)),
        (3000, lib_pick),
        (200, still(2600)),
        (9000, unreal_tab),
        (7000, unreal_pick),
        (200, still(1200)),
        (4000, live_on),
        (200, save),
    ]
    t0 = time.time()

    def run():
        if not steps:
            return
        delay, fn = steps.pop(0)
        try:
            fn()
        except Exception:
            import traceback

            traceback.print_exc()
        QTimer.singleShot(delay, run)

    QTimer.singleShot(100, run)
    QTimer.singleShot(120000, lambda: (print("время вышло", time.time() - t0), os._exit(1)))
    app.exec()


if __name__ == "__main__":
    main()
