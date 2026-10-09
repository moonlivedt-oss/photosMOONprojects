"""Каталог Poly Haven прямо в окне: миниатюры с сайта, вид, категория, поиск; отметить нужное и скачать.
Уже скачанное помечено «уже есть». Тема для папки подбирается сама по категориям и меткам (или выбирается)."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from library import unreal as U
from ui.common import CLOSING, HERE, PIX, ROLE, THUMB, bg, in_main, log_error
from ui.thumbnails import lib_icon, remember, thumb_key, tile_image
from ui.unreal_nav import THEME_ICON, theme_label
from ui.unreal_tiles import ASSET, CARD, CardList, card_of

THUMBS = os.path.join(HERE, "_thumbs", "ue_catalog")
KINDS = (("model", "3D-модели"), ("tex", "Текстуры"), ("hdri", "Небо и фоны HDRI"))


def fetch_thumb(c):
    """Миниатюра с сайта в кэш (один раз). -> путь или ''."""
    dst = os.path.join(THUMBS, c["id"] + ".webp")
    if not os.path.exists(dst):
        try:
            os.makedirs(THUMBS, exist_ok=True)
            data = U.get(c["thumb"], timeout=30)
            with open(dst + ".part", "wb") as fh:
                fh.write(data)
            os.replace(dst + ".part", dst)
        except Exception:
            return ""
    return dst


class CatalogDialog(QDialog):
    downloaded = pyqtSignal()

    def __init__(self, tab):
        super().__init__(tab, Qt.WindowType.Window)
        self.tab, self.cfg = tab, tab.cfg
        self.setWindowTitle("Каталог Poly Haven - выбрать и скачать")
        self.setWindowIcon(lib_icon("globe"))
        self.resize(1240, 820)
        self.all, self.shown, self.gen = [], [], 0
        self.have = {a.get("id") for a in tab.items}
        self.stop, self.busy = threading.Event(), False

        self.kind = QComboBox()
        for k, t in KINDS:
            self.kind.addItem(lib_icon({"model": "dice_3D", "tex": "paint-roller", "hdri": "cloud"}[k]), t, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(self.cfg.get("ue_cat_kind", "model"))))
        self.kind.currentIndexChanged.connect(self.load)
        self.cat = QComboBox()
        self.cat.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.cat.currentIndexChanged.connect(self.filter)
        self.q = QLineEdit(placeholderText="Поиск: chair, lamp, brick, sunset...", objectName="search")
        self.q.setClearButtonEnabled(True)
        self.q.addAction(lib_icon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self.qt = QTimer(self, singleShot=True, interval=220)
        self.qt.timeout.connect(self.filter)
        self.q.textChanged.connect(lambda *_: self.qt.start())
        self.new_only = QCheckBox("Только новые")
        self.new_only.setToolTip("Спрятать то, что уже скачано")
        self.new_only.toggled.connect(self.filter)
        self.sort = QComboBox()
        for t, v in (("Популярные", "pop"), ("Новые на сайте", "date"), ("По имени", "name")):
            self.sort.addItem(t, v)
        self.sort.currentIndexChanged.connect(self.filter)

        self.list = CardList(150)
        self.list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.list.itemSelectionChanged.connect(self.update_sel)
        self.list.itemDoubleClicked.connect(
            lambda it: QDesktopServices.openUrl(QUrl(f"https://polyhaven.com/a/{it.data(ASSET)['id']}"))
        )
        self.list.verticalScrollBar().valueChanged.connect(lambda *_: self.more.start())
        self.more = QTimer(self, singleShot=True, interval=120)  # миниатюры видимых - первыми
        self.more.timeout.connect(self.load_visible)
        self.count = QLabel(objectName="dim")

        self.theme = QComboBox()
        self.theme.addItem(lib_icon("sparkles"), "Тему подобрать само", "")
        for th in list(U.THEMES) + ["Разное"]:
            self.theme.addItem(
                lib_icon(THEME_ICON.get(th, "folder")),
                ("Дом: " if th.startswith("Дом - ") else "") + theme_label(th),
                th,
            )
        self.res = QComboBox()
        for r in U.RES:
            self.res.addItem(r.upper(), r)
        self.res.setCurrentIndex(max(0, self.res.findData(self.cfg.get("ue_res", "2k"))))
        self.res.currentIndexChanged.connect(lambda *_: self.update_sel())
        self.sel_lbl = QLabel(objectName="dim")
        self.go = QPushButton(lib_icon("download"), "Скачать отмеченные", objectName="primary")
        self.go.clicked.connect(self.start)
        clear = QPushButton("Снять отметки")
        clear.clicked.connect(self.list.clearSelection)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.status = QLabel(objectName="dim")

        top = QHBoxLayout()
        top.addWidget(self.kind)
        top.addWidget(self.cat)
        top.addWidget(self.q, 1)
        top.addWidget(self.sort)
        top.addWidget(self.new_only)
        bottom = QHBoxLayout()
        bottom.addWidget(self.sel_lbl, 1)
        bottom.addWidget(QLabel("Куда:"))
        bottom.addWidget(self.theme)
        bottom.addWidget(self.res)
        bottom.addWidget(clear)
        bottom.addWidget(self.go)
        hint = QLabel(
            "Щелчок - отметить, ещё щелчок - снять, двойной щелчок - страница на сайте, всё CC0", objectName="faint"
        )
        v = QVBoxLayout(self)
        v.addLayout(top)
        h = QHBoxLayout()
        h.addWidget(self.count, 1)
        h.addWidget(hint)
        v.addLayout(h)
        v.addWidget(self.list, 1)
        v.addWidget(self.bar)
        v.addWidget(self.status)
        v.addLayout(bottom)
        self.update_sel()
        QTimer.singleShot(0, self.load)

    # ------------------------------------------------------------ данные
    def load(self):
        kind = self.kind.currentData()
        self.cfg["ue_cat_kind"] = kind
        self.count.setText("Загружаю каталог...")

        def done(res):
            if isinstance(res, Exception):
                self.count.setText(f"Каталог не открылся: {res}")
                return
            self.all = res
            cats = {}
            for c in res:
                for x in c["info"].get("categories", []):
                    if not x.startswith("collection"):
                        cats[x] = cats.get(x, 0) + 1
            self.cat.blockSignals(True)
            self.cat.clear()
            self.cat.addItem(f"Все категории ({len(res)})", "")
            for x, n in sorted(cats.items(), key=lambda kv: -kv[1]):
                self.cat.addItem(f"{x} ({n})", x)
            self.cat.blockSignals(False)
            self.filter()

        bg(lambda: U.browse(kind), done)

    def filter(self):
        cat, words = self.cat.currentData(), self.q.text().lower().split()
        out = []
        for c in self.all:
            info = c["info"]
            if cat and cat not in info.get("categories", []):
                continue
            if self.new_only.isChecked() and c["id"] in self.have:
                continue
            hay = " ".join([c["name"], c["id"], *info.get("tags", []), *info.get("categories", [])]).lower()
            if words and not all(w in hay for w in words):
                continue
            out.append(c)
        how = self.sort.currentData()
        if how == "date":
            out.sort(key=lambda c: -c["info"].get("date_published", 0))
        elif how == "name":
            out.sort(key=lambda c: c["name"].lower())
        self.shown = out
        kind = self.kind.currentData()
        self.list.clear()
        self.list.reset_anim()
        for c in out:
            info = c["info"]
            sub = ", ".join(info.get("categories", [])[:2])
            if info.get("polycount"):
                sub += f", {info['polycount'] // 1000}k полиг."
            it = QListWidgetItem(c["name"])
            it.setData(ASSET, c)
            it.setData(ROLE, "")
            it.setData(CARD, card_of(kind, c["name"], sub, have=c["id"] in self.have, pickable=True))
            it.setToolTip(", ".join(info.get("tags", [])[:12]))
            self.list.addItem(it)
        n_have = sum(1 for c in out if c["id"] in self.have)
        self.count.setText(f"Показано: {len(out)}, уже скачано из них: {n_have}")
        self.gen += 1
        self.update_sel()
        QTimer.singleShot(50, self.load_visible)

    def load_visible(self):
        """Миниатюры видимых плиток и чуть ниже - с сайта в кэш, потом в плитки."""
        gen = self.gen
        vp = self.list.viewport().rect()
        rows = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(PIX) is not None or it.data(ROLE) == "loading":
                continue
            rect = self.list.visualItemRect(it)
            if rect.bottom() < vp.top() - 50 or rect.top() > vp.bottom() + vp.height():
                continue
            it.setData(ROLE, "loading")
            rows.append((i, it.data(ASSET)))
        if not rows:
            return

        def work():
            out = []
            with ThreadPoolExecutor(8) as ex:
                for (i, _c), path in zip(rows, ex.map(lambda rc: fetch_thumb(rc[1]), rows)):
                    if CLOSING.is_set():
                        break
                    try:
                        out.append((i, path, tile_image(path, THUMB, None) if path else None))
                    except Exception:
                        out.append((i, path, None))
            return out

        def done(res):
            if gen != self.gen or isinstance(res, Exception):
                return
            for i, path, img in res:
                it = self.list.item(i)
                if it is None:
                    continue
                if img is None:
                    it.setData(PIX, QPixmap())
                    continue
                key = thumb_key(path, THUMB, None)
                pm = QPixmap.fromImage(img)
                it.setData(PIX, remember(key, pm) if key else pm)
                self.list.loaded(i)
            self.more.start()

        bg(work, done)

    # ------------------------------------------------------------ скачать
    def chosen(self):
        return [it.data(ASSET) for it in self.list.selectedItems() if it.data(ASSET)["id"] not in self.have]

    def update_sel(self):
        sel = self.chosen()
        kind = self.kind.currentData()
        mb = U.estimate(kind, self.res.currentData()) * len(sel)
        self.sel_lbl.setText(
            f"Отмечено новых: {len(sel)}" + (f", примерно {mb:.0f} МБ" if sel else " - щёлкайте по карточкам")
        )
        self.go.setEnabled(bool(sel) and not self.busy)

    def start(self):
        sel, kind, res = self.chosen(), self.kind.currentData(), self.res.currentData()
        forced = self.theme.currentData()
        self.busy = True
        self.stop.clear()
        self.go.setEnabled(False)
        self.bar.show()
        self.bar.setValue(0)
        errs, got = [], []

        def work():
            for i, c in enumerate(sel):
                if self.stop.is_set():
                    break
                th = forced or U.guess_theme(kind, c["info"])

                def prog(f, t, i=i, c=c):
                    in_main(self.show_prog, ((i + f) / len(sel), f"{c['name']}: {t}"))

                try:
                    U.fetch(c, kind, th, res, prog, self.stop)
                    got.append(c["id"])
                except InterruptedError:
                    break
                except Exception as e:
                    errs.append(f"{c['name']}: {e}")
                    log_error("unreal catalog: %r" % e)
            return got

        def done(res):
            self.busy = False
            if isinstance(res, Exception):  # сбой вне отдельного ассета (каталог, папка) - в итог и журнал
                errs.append(str(res))
                log_error("unreal catalog: %r" % res)
            self.tab.set_progress(None)
            self.have |= set(got)
            self.bar.setValue(1000)
            self.status.setText(f"Скачано: {len(got)}" + (f", не вышло: {'; '.join(errs[:3])}" if errs else ""))
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(ASSET)["id"] in self.have:
                    d = dict(it.data(CARD))
                    d["have"] = True
                    it.setData(CARD, d)
            self.list.clearSelection()
            self.update_sel()
            if not self.isVisible():
                self.tab.win.say(f"Каталог: скачано {len(got)}" + (f", не вышло: {len(errs)}" if errs else ""))
            self.downloaded.emit()

        bg(work, done)

    def show_prog(self, v):
        self.tab.set_progress(f"каталог {int(v[0] * 100)}% - {v[1]}" if not self.isVisible() else None)
        if self.isVisible():
            self.bar.setValue(int(v[0] * 1000))
            self.status.setText(v[1])

    def reject(self):
        """Закрывается всегда; загрузка, если идёт, продолжается в фоне (окно держит вкладка)."""
        self.hide()

    def closeEvent(self, e):
        e.ignore()
        self.hide()
