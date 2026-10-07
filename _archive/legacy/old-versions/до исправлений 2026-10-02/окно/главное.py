"""Главное окно: вкладки, строка состояния, отмена (Ctrl+Z), приём файлов, папка генератора."""
import os
import shutil
import sys
import time

import картинки as K
from PyQt6 import sip
from PyQt6.QtCore import QFile, QFileSystemWatcher, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QWidget,
)

from окно.анимации import (
    Aurora,
    DropOverlay,
    Motion,
    PageFade,
    TabBar,
    Toast,
    fade_in_window,
)
from окно.вес import WeightDialog
from окно.виджеты import fill_tree, key
from окно.вкладка_библиотеки import LibTab
from окно.входящие import InboxTab
from окно.дубли import DupesDialog
from окно.миниатюры import forget_pixmaps, lib_icon
from окно.общее import (
    HEAVY,
    HEAVY_KB,
    INBOX,
    LIB,
    bg,
    finish_bg,
    human,
    inbox_files,
    is_image,
    load_cfg,
    relay,
    save_cfg,
    unique,
)
from окно.отпечатки import SigIndex
from окно.оформление import QSS, ui_files

HELP = """<b>Горячие клавиши</b><table cellspacing=4>
<tr><td>Ctrl+S</td><td>сохранить отмеченные куски в раздел</td></tr>
<tr><td>Ctrl+Z</td><td>отменить последнее сохранение, переименование или перенос</td></tr>
<tr><td>Ctrl+V</td><td>вставить картинку или файлы из буфера во входящие</td></tr>
<tr><td>Ctrl+1 / Ctrl+2</td><td>вкладки Входящие / Библиотека</td></tr>
<tr><td>Ctrl+F</td><td>поиск по библиотеке</td></tr>
<tr><td>Пробел</td><td>во входящих - отметить / снять выделенные куски</td></tr>
<tr><td>Щелчок по рамке на листе</td><td>отметить / снять этот кусок</td></tr>
<tr><td>Двойной щелчок по куску</td><td>переименовать</td></tr>
<tr><td>F2 / Del / Ctrl+C</td><td>переименовать / в корзину / копировать путь</td></tr>
<tr><td>Ctrl+Shift+C</td><td>копировать саму картинку</td></tr>
<tr><td>Ctrl+колесо</td><td>размер плиток в библиотеке</td></tr>
<tr><td>Пробел</td><td>в библиотеке - просмотр на всё окно (стрелки листают, B - подложка)</td></tr>
<tr><td>B</td><td>в библиотеке - подложка плиток: шахматка / светлая / тёмная</td></tr>
<tr><td>Цвета под просмотром</td><td>главные цвета картинки, щелчок копирует код (#rrggbb)</td></tr>
<tr><td>Ctrl+D</td><td>в избранное / убрать</td></tr>
<tr><td>Метка в имени</td><td>«Космос [ic tokyo]» (кнопка «Имена» в промптах) - окно само выберет нарезку и папку</td></tr>
<tr><td>Ctrl+K</td><td>сжать и конвертировать: шторка до/после, «самый лёгкий» формат, лимит в КБ, сравнение форматов</td></tr>
<tr><td>Ctrl+E</td><td>выгрузить выбранное в папку проекта (формат, размер, @2x/@3x, лимит в КБ, svg)</td></tr>
<tr><td>Ctrl+I</td><td>вес разделов: где тяжелее всего, сколько сэкономлено, сжать тяжёлые</td></tr>
<tr><td>Меню плитки</td><td>«Сделать копию в формате» - в фоне, по всем ядрам, Ctrl+Z убирает копии</td></tr>
<tr><td>F9</td><td>живой фон окна: плывёт / застыл (застывший не тратит процессор)</td></tr>
</table><p>Картинки из библиотеки можно перетаскивать мышью прямо в другие программы.</p>"""


# ---------------------------------------------------------------- окно
class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        self.history = []                   # для Ctrl+Z: [(подпись, [("new", путь) | ("move", было, стало)])]
        self.sigs = SigIndex()
        self.setWindowTitle("Библиотека картинок")
        self.setWindowIcon(lib_icon("Звезда"))
        self.resize(*self.cfg.get("size", [1280, 800]))
        self.setAcceptDrops(True)
        os.makedirs(INBOX, exist_ok=True)

        self.aurora = Aurora(self)
        self.aurora.set_live(self.cfg.get("live_bg", True))
        self.tabs = QTabWidget()
        self.tabs.setTabBar(TabBar())
        self.tabs.setIconSize(QSize(20, 20))
        self.inbox = InboxTab(self)
        self.lib = LibTab(self)
        self.tabs.addTab(self.inbox, lib_icon("Задачи"), "Входящие")
        self.tabs.addTab(self.lib, lib_icon("Книга"), "Библиотека")
        self.inbox.reload()
        self.setCentralWidget(self.tabs)
        PageFade(self.tabs)

        corner = QWidget()
        ch = QHBoxLayout(corner)
        ch.setContentsMargins(0, 0, 8, 4)
        for text, icon, fn, tip in (("Галерея", "Компас", self.open_gallery, "Вся библиотека в браузере"),
                                    ("Промпты", "Заметка", self.open_prompts, ""),
                                    ("Найти дубли", "Лупа", self.dupes, "Одинаковые картинки уедут в «_дубли»")):
            b = QPushButton(lib_icon(icon), text, objectName="ghost")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            ch.addWidget(b)
        self.gen_btn = QPushButton(lib_icon("eye"), "", objectName="ghost")
        self.gen_btn.clicked.connect(self.pick_gen)
        ch.addWidget(self.gen_btn)
        helpb = QPushButton(lib_icon("question-mark-bubble"), "", objectName="ghost")
        helpb.setToolTip("Горячие клавиши (F1)")
        helpb.clicked.connect(self.show_help)
        ch.addWidget(helpb)
        self.tabs.setCornerWidget(corner)

        self.undo_btn = QPushButton("Отменить", objectName="undo")
        self.undo_btn.clicked.connect(self.undo)
        self.undo_btn.hide()
        self.stats = QLabel()
        self.heavy_btn = QPushButton(objectName="flat")
        self.heavy_btn.setToolTip("Показать файлы тяжелее %d КБ - их можно сжать (Ctrl+K)" % HEAVY_KB)
        self.heavy_btn.clicked.connect(lambda: (self.tabs.setCurrentIndex(1), self.lib.show_section(HEAVY)))
        self.weight_btn = QPushButton("Вес разделов", objectName="flat")
        self.weight_btn.setToolTip("Где библиотека тяжелее всего и сколько уже сэкономлено (Ctrl+I)")
        self.weight_btn.clicked.connect(self.show_weight)
        self.statusBar().addPermanentWidget(self.weight_btn)
        self.statusBar().addPermanentWidget(self.heavy_btn)
        self.statusBar().addPermanentWidget(self.undo_btn)
        self.statusBar().addPermanentWidget(self.stats)

        self.overlay = DropOverlay(self, "Отпустите - картинки попадут во входящие")
        self.toast = Toast(self)

        self.inbox.changed.connect(self.library_changed)
        self.lib.changed.connect(self.library_changed)
        self.tabs.currentChanged.connect(self.tab_changed)

        self.watch = QFileSystemWatcher([INBOX], self)
        self.watch.directoryChanged.connect(lambda _p: self.inbox.reload())
        self.gal = QTimer(self, singleShot=True, interval=1500)     # галерею и отпечатки пересобираем один раз на пачку правок
        self.gal.timeout.connect(self.rebuild)
        self.sizes = {}                                             # размеры файлов генератора на прошлом опросе
        self.poll = QTimer(self, interval=2000)
        self.poll.timeout.connect(self.check_gen)
        self.poll.start()

        for keys, fn in (("Ctrl+Z", self.undo), ("Ctrl+V", self.paste), ("F1", self.show_help),
                         ("Ctrl+1", lambda: self.tabs.setCurrentIndex(0)),
                         ("Ctrl+2", lambda: self.tabs.setCurrentIndex(1)), ("F9", self.toggle_live),
                         ("Ctrl+I", self.show_weight)):
            key(keys, self, fn, local=False)

        self.show_gen()
        self.update_stats()
        self.sigs.refresh()
        self.tabs.setCurrentIndex(self.cfg.get("tab", 0) if inbox_files() == [] else 0)
        if self.cfg.get("max"):
            self.setWindowState(Qt.WindowState.WindowMaximized)

    def say(self, text):
        if self.isVisible():
            self.toast.say(text)                # пузырь внизу; строка состояния - пока окно не показано
        else:
            self.statusBar().showMessage(text, 8000)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setClipRegion(e.region())
        self.aurora.paint(p, self.rect())
        p.end()

    def tab_changed(self, i):
        if i == 1:
            self.lib.refresh()
        else:
            self.inbox.reload()

    def library_changed(self):
        fill_tree(self.inbox.tree)
        self.inbox.update_save()
        self.update_stats()
        self.gal.start()

    def rebuild(self):
        """Галерея пересобирается в фоне: она открывает все картинки библиотеки, и в главном потоке
        окно замирало на пару секунд (Windows успевала показать белое «Не отвечает»)."""
        if getattr(self, "gal_busy", False):
            self.gal.start()                    # прошлая сборка ещё идёт - попробуем позже
        else:
            self.gal_busy = True
            bg(K.cmd_gallery, lambda _r: setattr(self, "gal_busy", False))
        self.sigs.refresh()

    def update_stats(self):
        files = K.images_in(LIB)
        size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
        self.stats.setText("В библиотеке: %d картинок, %s" % (len(files), human(size)))
        heavy = [f for f in files if os.path.exists(f) and os.path.getsize(f) > HEAVY_KB * 1024]
        self.heavy_btn.setText("Тяжёлых: %d (%s) - сжать?" % (len(heavy), human(sum(map(os.path.getsize, heavy)))))
        self.heavy_btn.setVisible(bool(heavy))

    # --- отмена
    def push(self, text, steps):
        if not steps:
            return
        self.history = (self.history + [(text, steps)])[-20:]
        self.undo_btn.setToolTip("Ctrl+Z: " + text)
        self.undo_btn.show()

    def undo(self):
        if not self.history:
            self.say("Отменять нечего")
            return
        text, steps = self.history.pop()
        bad = 0
        for step in reversed(steps):
            try:
                if step[0] == "new":
                    if os.path.exists(step[1]) and not QFile.moveToTrash(step[1]):
                        bad += 1
                elif os.path.exists(step[2]):
                    back = step[1] if not os.path.exists(step[1]) else unique(step[1])
                    os.makedirs(os.path.dirname(back), exist_ok=True)
                    shutil.move(step[2], back)
                    self.moved(step[2], back)
                    if os.path.dirname(back) == INBOX:
                        self.inbox.no_auto.add(back)
            except Exception:
                bad += 1
        if self.history:
            self.undo_btn.setToolTip("Ctrl+Z: " + self.history[-1][0])
        else:
            self.undo_btn.hide()
        self.inbox.reload()
        if self.tabs.currentIndex() == 1:
            self.lib.refresh()
        self.library_changed()
        self.say("Отменено: " + text + ("  (не получилось: %d)" % bad if bad else ""))

    def moved(self, src, dst):
        """Избранное едет вместе с файлом."""
        fav = self.cfg.get("fav", [])
        a, b = os.path.relpath(src, LIB), os.path.relpath(dst, LIB)
        if a in fav:
            fav[fav.index(a)] = b

    # --- приём файлов
    def take(self, files):
        n = 0
        for f in files:
            if os.path.isfile(f) and is_image(os.path.basename(f)) and os.path.dirname(os.path.abspath(f)) != INBOX:
                shutil.copy2(f, unique(os.path.join(INBOX, os.path.basename(f))))
                n += 1
        if n:
            self.tabs.setCurrentIndex(0)
            self.inbox.reload()
            self.say("Во входящие добавлено: %d" % n)
        return n

    def paste(self):
        cb = QApplication.clipboard()
        md = cb.mimeData()
        if md.hasUrls() and self.take([u.toLocalFile() for u in md.urls() if u.isLocalFile()]):
            return
        if md.hasImage():
            img = cb.image()
            if not img.isNull():
                p = unique(os.path.join(INBOX, "Вставка %s.png" % time.strftime("%Y-%m-%d %H-%M-%S")))
                img.save(p, "PNG")
                self.tabs.setCurrentIndex(0)
                self.inbox.reload()
                self.say("Картинка из буфера во входящих: " + os.path.basename(p))
                return
        self.say("В буфере нет картинки")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is None:      # свои плитки обратно во входящие не принимаем
            e.acceptProposedAction()
            self.overlay.appear(True)

    def dragLeaveEvent(self, _e):
        self.overlay.appear(False)

    def dropEvent(self, e):
        self.overlay.appear(False)
        self.take([u.toLocalFile() for u in e.mimeData().urls()])

    # --- папка генератора: новые картинки сами копируются во входящие
    def show_gen(self):
        d = self.cfg.get("gen_dir")
        self.gen_btn.setText("Генератор: слежу" if d else "Папка генератора...")
        self.gen_btn.setToolTip(("Слежу за папкой: %s\nНовые картинки сами попадают во входящие.\n"
                                 "Щелчок - выбрать другую или отключить" % d) if d else
                                "Выберите папку, куда генератор сохраняет картинки - новые будут сами попадать во входящие")
        self.inbox.gen_hint.setText(("Слежу за папкой генератора: %s" % d) if d else
                                    "Можно указать папку генератора (кнопка вверху) - новые картинки будут приходить сами")
        self.say("Слежу за папкой генератора: " + d if d else "Папка генератора не задана")

    def pick_gen(self):
        d = QFileDialog.getExistingDirectory(self, "Папка, куда генератор сохраняет картинки (Отмена - не следить)",
                                             self.cfg.get("gen_dir", ""))
        self.cfg["gen_dir"] = os.path.normpath(d) if d else ""
        self.cfg["gen_since"] = time.time()         # берём только то, что появится после выбора
        self.sizes = {}
        self.show_gen()

    def check_gen(self):
        d = self.cfg.get("gen_dir")
        if not d or not os.path.isdir(d):
            return
        since, newest, ready = self.cfg.get("gen_since", time.time()), 0, []
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if not is_image(f) or not os.path.isfile(p):
                continue
            st = os.stat(p)
            if st.st_mtime <= since:
                continue
            if self.sizes.get(p) == st.st_size and st.st_size:      # размер не растёт - файл дописан
                ready.append(p)
                newest = max(newest, st.st_mtime)
            self.sizes[p] = st.st_size
        if ready:
            self.cfg["gen_since"] = newest
            if self.take(ready):
                QApplication.alert(self)            # мигнуть на панели задач, если окно в фоне

    # --- прочее
    def show_weight(self):
        WeightDialog(self).exec()

    def toggle_live(self):
        self.cfg["live_bg"] = not self.cfg.get("live_bg", True)
        self.aurora.set_live(self.cfg["live_bg"])
        self.say("Живой фон: " + ("плывёт" if self.cfg["live_bg"] else "застыл (F9 - включить)"))

    def show_help(self):
        QMessageBox.information(self, "Горячие клавиши", HELP)

    def open_gallery(self):
        self.gal.stop()
        K.cmd_gallery()
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(LIB, "Галерея.html")))

    def open_prompts(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(LIB, "Промпты.html")))

    def dupes(self):
        if self.sigs.busy:
            self.say("Отпечатки библиотеки ещё считаются - попробуйте через пару секунд")
            return
        groups = self.sigs.groups()
        if not groups:
            QMessageBox.information(self, "Дубли", "Одинаковых картинок нет.")
            return
        DupesDialog(self, groups).exec()

    def closeEvent(self, e):
        self.cfg["max"] = self.isMaximized()
        if not self.isMaximized():
            self.cfg["size"] = [self.width(), self.height()]
        self.cfg["tab"] = self.tabs.currentIndex()
        self.cfg["split_in"] = self.inbox.split.sizes()
        self.cfg["split_mid"] = self.inbox.mid.sizes()
        self.cfg["split_lib"] = self.lib.split.sizes()
        self.cfg["archive"] = self.inbox.keep.isChecked()
        save_cfg(self.cfg)
        if self.gal.isActive():
            K.cmd_gallery()
        e.accept()


def main():
    app = QApplication(sys.argv)
    relay()
    app.setStyleSheet(QSS.replace("@UI", ui_files()))
    for fx in (Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu, Qt.UIEffect.UI_AnimateCombo,
               Qt.UIEffect.UI_AnimateTooltip, Qt.UIEffect.UI_FadeTooltip):
        app.setEffectEnabled(fx, True)
    Motion(app)
    w = Window()
    fade_in_window(w)
    w.show()
    code = app.exec()
    finish_bg()                     # фоновые потоки - доделать или бросить
    forget_pixmaps()                # затем картинки и окно, и только потом приложение
    sip.delete(w)
    del w
    sys.exit(code)


if __name__ == "__main__":
    main()
