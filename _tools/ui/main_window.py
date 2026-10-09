"""Главное окно: вкладки, строка состояния, отмена (Ctrl+Z), приём файлов, папка генератора."""

import os
import shutil
import sys
import time
import traceback

from PyQt6 import sip
from PyQt6.QtCore import QFile, QFileSystemWatcher, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QWidget,
)

import imaging as K
from library import db, journal
from library.tagging import Tagger
from ui.agents import AgentsDialog
from ui.animations import (
    Aurora,
    DropOverlay,
    Motion,
    PageFade,
    TabBar,
    Toast,
    fade_in_window,
)
from ui.common import (
    HEAVY,
    HEAVY_KB,
    INBOX,
    LIB,
    PARK,
    VERSION,
    bg,
    cfg_text,
    finish_bg,
    human,
    inbox_files,
    is_image,
    load_cfg,
    log_error,
    relay,
    save_cfg,
    unique,
)
from ui.doctor import DoctorDialog
from ui.dupes import DupesDialog
from ui.help import NEW, HelpDialog
from ui.inbox_tab import InboxTab
from ui.library_tab import LibTab
from ui.missing import MissingDialog
from ui.semantic import SemIndex
from ui.signatures import SigIndex
from ui.thumbnails import forget_pixmaps, lib_icon, trim_thumbs
from ui.unreal_tab import UnrealTab
from ui.weight import WeightDialog
from ui.widgets import fill_tree, forget_counts, key


# ---------------------------------------------------------------- окно
class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        take_old_favs(self.cfg)
        # Ctrl+Z: [(подпись, шаги, id в журнале)]. Журнал общий с ИИ-помощником и переживает перезапуск.
        last = list(reversed(journal.entries(20, undone=False)))
        self.history = [(e["text"], e["steps"], e["id"]) for e in last]
        self.who = {e["id"]: e["who"] for e in last if e["who"] != journal.WINDOW}  # id -> кто сделал, если не окно
        self.jseen = journal.last_id()  # действия помощника новее этого - ещё не показаны
        self.sigs = SigIndex()
        self.sem = SemIndex()
        self.tagger = Tagger(self.sem)
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
        self.unreal = UnrealTab(self)
        self.unreal.items_loaded.connect(self.lib.update_ue_strip)
        self.tabs.addTab(self.unreal, lib_icon("game-cartridge"), "Unreal")
        self.inbox.reload()
        self.setCentralWidget(self.tabs)
        PageFade(self.tabs)

        corner = QWidget()
        ch = QHBoxLayout(corner)
        ch.setContentsMargins(0, 0, 8, 4)
        for text, icon, fn, tip in (
            ("Галерея", "Компас", self.open_gallery, "Вся библиотека в браузере"),
            ("Промпты", "Заметка", self.open_prompts, "Промпты для генерации листов"),
        ):
            b = QPushButton(lib_icon(icon), text, objectName="ghost")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            ch.addWidget(b)
        # редкие проверки - одной кнопкой с меню, чтобы верхняя строка не была забита
        tools = QPushButton(lib_icon("toolbox"), "Инструменты", objectName="ghost")
        tm = QMenu(self)
        for text, icon, fn in (
            ("Найти дубли", "Лупа", self.dupes),
            ("Доктор библиотеки", "first-aid-kit", self.doctor),
            ("Чего нет в наборах", "checklist", self.missing),
            ("Вес разделов (Ctrl+I)", "zip-archive", self.show_weight),
        ):
            tm.addAction(lib_icon(icon), text, fn)
        tm.addSeparator()
        tm.addAction(lib_icon("color-palette"), "Палитра из картинки...", lambda: self.lib.palette_from())
        tm.addAction(lib_icon("magnifying-glass"), "Сравнить две картинки...", lambda: self.lib.compare())
        tm.addAction(lib_icon("drawing_pen"), "Векторизация в SVG...", lambda: self.lib.vectorize())
        tm.addSeparator()
        tm.addAction(lib_icon("sparkles"), "Оформление: тема и акцент...", self.theme_dialog)
        tm.addAction(lib_icon("eye"), "Папка генератора...", self.pick_gen)
        tools.setMenu(tm)
        tools.setToolTip("Дубли, доктор, чего нет, вес разделов, папка генератора")
        ch.addWidget(tools)
        ai = QPushButton(lib_icon("sparkles"), "ИИ-помощники", objectName="ghost")
        ai.setToolTip("Claude, Cursor и другие помощники: подключить, что им можно, что они сделали")
        ai.clicked.connect(self.agents)
        ch.addWidget(ai)
        self.gen_btn = QPushButton(lib_icon("eye"), "", objectName="ghost")
        self.gen_btn.clicked.connect(self.pick_gen)
        ch.addWidget(self.gen_btn)
        helpb = QPushButton(lib_icon("question-mark-bubble"), "", objectName="ghost")
        helpb.setToolTip("Справка: что умеет окно, горячие клавиши, что нового (F1)")
        helpb.clicked.connect(self.show_help)
        ch.addWidget(helpb)
        self.tabs.setCornerWidget(corner)

        self.undo_btn = QPushButton("Отменить", objectName="undo")
        self.undo_btn.clicked.connect(lambda: self.undo())
        self.undo_btn.hide()
        self.redo = []  # отменённое: [(подпись, шаги, сделанные переносы)] - для Ctrl+Y
        self.hist_btn = QPushButton("История", objectName="flat")
        self.hist_menu = QMenu(self)
        self.hist_menu.aboutToShow.connect(self.history_menu)
        self.hist_btn.setMenu(self.hist_menu)
        self.hist_btn.hide()
        self.stats = QLabel()
        self.heavy_btn = QPushButton(objectName="flat")
        self.heavy_btn.setToolTip("Показать файлы тяжелее %d КБ - их можно сжать (Ctrl+K)" % HEAVY_KB)
        self.heavy_btn.clicked.connect(lambda: (self.tabs.setCurrentIndex(1), self.lib.show_section(HEAVY)))
        self.weight_btn = QPushButton("Вес разделов", objectName="flat")
        self.weight_btn.setToolTip("Где библиотека тяжелее всего и сколько уже сэкономлено (Ctrl+I)")
        self.weight_btn.clicked.connect(self.show_weight)
        self.sem_lbl = QLabel(objectName="dim")
        self.sem_lbl.hide()
        self.sem.on_progress = self.show_sem_progress
        self.statusBar().addPermanentWidget(self.sem_lbl)
        self.statusBar().addPermanentWidget(self.weight_btn)
        self.statusBar().addPermanentWidget(self.heavy_btn)
        self.statusBar().addPermanentWidget(self.hist_btn)
        self.statusBar().addPermanentWidget(self.undo_btn)
        self.statusBar().addPermanentWidget(self.stats)

        self.overlay = DropOverlay(self, "Отпустите - картинки попадут во входящие")
        self.toast = Toast(self)

        self.inbox.changed.connect(self.library_changed)
        self.lib.changed.connect(self.library_changed)
        self.tabs.currentChanged.connect(self.tab_changed)

        # копирование пачки файлов дёргает слежение десятки раз - перечитываем один раз, когда утихнет
        self.inbox_timer = QTimer(self, singleShot=True, interval=400)
        self.inbox_timer.timeout.connect(self.inbox.reload)
        self.watch = QFileSystemWatcher([INBOX], self)
        self.watch.directoryChanged.connect(lambda _p: self.inbox_timer.start())
        self.saved_cfg = cfg_text(self.cfg)  # настройки пишутся сами, если поменялись:
        self.autosave = QTimer(self, interval=5000)  # избранное не теряется, если окно упадёт
        self.autosave.timeout.connect(self.save_settings)
        self.autosave.start()
        self.gal = QTimer(
            self, singleShot=True, interval=1500
        )  # галерею и отпечатки пересобираем один раз на пачку правок
        self.gal.timeout.connect(self.rebuild)
        self.sizes = {}  # размеры файлов генератора на прошлом опросе
        self.poll = QTimer(self, interval=2000)
        self.poll.timeout.connect(self.check_gen)
        self.poll.timeout.connect(self.check_journal)
        self.poll.start()

        for keys, fn in (
            ("Ctrl+Z", lambda: self.undo()),
            ("Ctrl+Y", self.redo_last),
            ("Ctrl+Shift+Z", self.redo_last),
            ("Ctrl+V", self.paste),
            ("F1", self.show_help),
            ("Ctrl+1", lambda: self.tabs.setCurrentIndex(0)),
            ("Ctrl+2", lambda: self.tabs.setCurrentIndex(1)),
            ("Ctrl+3", lambda: self.tabs.setCurrentIndex(2)),
            ("F9", self.toggle_live),
            ("Ctrl+I", self.show_weight),
        ):
            key(keys, self, fn, local=False)

        self.show_gen()
        self.update_stats()
        self.sigs.refresh()
        self.sem.refresh()
        bg(trim_thumbs, lambda _n: None)
        self.tabs.setCurrentIndex(self.cfg.get("tab", 0) if inbox_files() == [] else 0)
        if self.cfg.get("max"):
            self.setWindowState(Qt.WindowState.WindowMaximized)
        QTimer.singleShot(900, self.greet)

    def show_sem_progress(self, prog):
        if prog is None:
            self.sem_lbl.hide()
            if self.lib.sem.isChecked() and self.lib.q.text().strip():
                self.lib.show_files()
            return
        self.sem_lbl.setText(f"Поиск по смыслу: учу картинки {prog[0]} из {prog[1]}")
        self.sem_lbl.show()

    def say(self, text, undo=False):
        """undo - в пузыре кнопка «Отменить»: только что записанное действие (не старше пары секунд -
        если это действие ничего не записало, чужое не подвернётся)."""
        if self.isVisible():
            jid, t = getattr(self, "last_push", (None, 0))
            self.last_push = (None, 0)
            fresh = undo and jid and time.monotonic() - t < 3 and self.history and self.history[-1][2] == jid
            jid = jid if fresh else None
            act = ("Отменить", lambda: self.undo(ids={jid})) if jid else None
            self.toast.say(text, 6000 if act else 3200, act)  # пузырь внизу; строка состояния - пока окно не показано
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
        elif i == 2:
            self.unreal.refresh()
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
            self.gal.start()  # прошлая сборка ещё идёт - попробуем позже
        else:
            self.gal_busy = True
            bg(K.build_gallery, lambda _r: setattr(self, "gal_busy", False))
        self.sigs.refresh()
        self.sem.refresh()

    def update_stats(self):
        """Число и вес картинок - в фоне: обход 4000+ файлов в главном потоке подвешивал окно
        после каждого сохранения."""

        def work():
            n = size = hn = hsize = 0
            for f in K.images_in(LIB):
                try:
                    b = os.path.getsize(f)
                except OSError:
                    continue
                n, size = n + 1, size + b
                if b > HEAVY_KB * 1024:
                    hn, hsize = hn + 1, hsize + b
            return n, size, hn, hsize

        def done(res):
            if isinstance(res, Exception):
                return
            n, size, hn, hsize = res
            self.stats.setText("В библиотеке: %d картинок, %s" % (n, human(size)))
            self.heavy_btn.setText("Тяжёлых: %d (%s) - сжать?" % (hn, human(hsize)))
            self.heavy_btn.setVisible(bool(hn))

        bg(work, done)

    def save_settings(self):
        text = cfg_text(self.cfg)
        if text != self.saved_cfg:
            try:
                save_cfg(self.cfg)
                self.saved_cfg = text
            except OSError as e:
                log_error(f"настройки не записались: {e}")

    # --- отмена
    def push(self, text, steps):
        forget_counts()
        if not steps:
            return
        jid = journal.record(journal.WINDOW, text, steps)
        self.jseen = max(self.jseen, jid or 0)
        self.last_push = (jid, time.monotonic())
        self.history = (self.history + [(text, steps, jid)])[-20:]
        self.drop_redo()  # новое действие - вернуть отменённое уже нельзя
        self.update_undo()

    def update_undo(self):
        self.undo_btn.setVisible(bool(self.history))
        self.hist_btn.setVisible(bool(self.history or self.redo))
        if self.history:
            self.undo_btn.setToolTip("Ctrl+Z: " + self.history[-1][0])
        self.hist_btn.setToolTip("Последние действия: отменить несколько сразу или вернуть отменённое (Ctrl+Y)")

    def history_menu(self):
        """Список последних действий: щелчок отменяет всё до этого места включительно."""
        m = self.hist_menu
        m.clear()
        if self.redo:
            m.addAction(f"Вернуть: {self.redo[-1][0]}\tCtrl+Y", self.redo_last)
            m.addSeparator()
        for i, (text, _s, jid) in enumerate(reversed(self.history)):
            who = self.who.get(jid)
            m.addAction(
                ("Отменить: " if i == 0 else "Отменить до: ") + (f"[{who}] " if who else "") + text,
                lambda n=i + 1: self.undo(n),
            )
        if not self.history and not self.redo:
            m.addAction("Действий пока нет").setEnabled(False)

    def undo(self, count=1, ids=None):
        """Отменить count последних действий или именно эти (ids - из журнала, свежие отменяются первыми)."""
        if not self.history:
            self.say("Отменять нечего")
            return
        if ids is not None:
            pick = [h for h in self.history if h[2] in ids]
            if not pick:
                self.say("Уже отменено")
                return
            self.history = [h for h in self.history if h[2] not in ids] + pick
            count = len(pick)
        texts, bad = [], 0
        for _k in range(min(count, len(self.history))):
            text, steps, jid = self.history.pop()
            done, b = self.undo_steps(steps)
            journal.mark(jid)
            bad += b
            self.redo.append((text, steps, done, jid))
            texts.append(text)
        self.after_change()
        self.say(
            "Отменено: " + "; ".join(texts) + ("  (не получилось: %d)" % bad if bad else "") + "   Ctrl+Y - вернуть"
        )

    def undo_steps(self, steps):
        """Откатить шаги. Новые файлы уезжают в _sources/_undone (а не в корзину), чтобы Ctrl+Y
        мог их вернуть. -> (сделанное для Ctrl+Y, ошибок)."""
        forget_counts()

        def back_in_inbox(_src, dst):
            if os.path.dirname(dst) == INBOX:
                self.inbox.no_auto.add(dst)  # вернулся во входящие - сам не раскладывать

        return journal.undo_steps(steps, LIB, PARK, back_in_inbox)

    def redo_last(self):
        """Ctrl+Y: вернуть последнее отменённое - переносы в обратную сторону, метки как были."""
        if not self.redo:
            self.say("Возвращать нечего")
            return
        text, steps, done, jid = self.redo.pop()
        forget_counts()
        bad = journal.redo_steps(done, LIB)
        journal.mark(jid, False)
        self.history = (self.history + [(text, steps, jid)])[-20:]
        self.after_change()
        self.say("Возвращено: " + text + ("  (не получилось: %d)" % bad if bad else ""))

    def drop_redo(self):
        """Отменённое, что уже не вернуть, - из _sources/_undone в корзину."""
        for _t, _s, done, _j in self.redo:
            for d in done:
                if d[0] == "mv" and os.path.dirname(d[2]) == PARK and os.path.exists(d[2]):
                    QFile.moveToTrash(d[2])
        self.redo = []

    def after_change(self):
        self.update_undo()
        self.inbox.reload()
        if self.tabs.currentIndex() == 1:
            self.lib.refresh()
        self.library_changed()

    def moved(self, src, dst):
        """Избранное, метки и заметка едут вместе с файлом."""
        try:
            db.moved(os.path.relpath(src, LIB), os.path.relpath(dst, LIB))
        except ValueError:  # путь на другом диске - в базе его быть не может
            pass
        except Exception as e:
            log_error(f"метки не переехали: {e}")

    # --- действия ИИ-помощника: появляются в истории (Ctrl+Z отменяет) и всплывают пузырём
    def check_journal(self):
        try:
            new = journal.entries(50, since=self.jseen)
            gone = journal.undone_among([j for _t, _s, j in self.history])
        except Exception as e:
            log_error(f"журнал: {e}")
            return
        if gone:  # помощник сам отменил своё - из истории окна убрать
            self.history = [h for h in self.history if h[2] not in gone]
        theirs = [e for e in reversed(new) if e["who"] != journal.WINDOW and not e["undone"]]
        if new:
            self.jseen = max(e["id"] for e in new)
        for e in theirs:
            self.who[e["id"]] = e["who"]
            self.history = (self.history + [(e["text"], e["steps"], e["id"])])[-20:]
        if theirs or gone:
            self.update_undo()
            self.after_change()
        if theirs:
            last = theirs[-1]
            more = "  (и ещё %d)" % (len(theirs) - 1) if len(theirs) > 1 else ""
            self.toast.say(
                f"{last['who']}: {last['text']}{more}",
                6000,
                ("Отменить", lambda ids={e["id"] for e in theirs}: self.undo(ids=ids)),
            )

    # --- приём файлов
    def take(self, files):
        n, bad = 0, []
        for f in files:
            if os.path.isfile(f) and is_image(os.path.basename(f)) and os.path.dirname(os.path.abspath(f)) != INBOX:
                try:
                    shutil.copy2(f, unique(os.path.join(INBOX, os.path.basename(f))))
                    n += 1
                except OSError as e:  # файл занят генератором или нет прав - остальные всё равно берём
                    bad.append(f"{os.path.basename(f)}: {e.strerror or e}")
        if n:
            self.tabs.setCurrentIndex(0)
            self.inbox.reload()
        if n or bad:
            self.say("Во входящие добавлено: %d" % n + ("   не получилось: {}".format("; ".join(bad)) if bad else ""))
        return n

    def paste(self):
        cb = QApplication.clipboard()
        md = cb.mimeData()
        if md.hasUrls() and self.take([u.toLocalFile() for u in md.urls() if u.isLocalFile()]):
            return
        if md.hasImage():
            img = cb.image()
            if not img.isNull():
                p = unique(os.path.join(INBOX, "Вставка {}.png".format(time.strftime("%Y-%m-%d %H-%M-%S"))))
                img.save(p, "PNG")
                self.tabs.setCurrentIndex(0)
                self.inbox.reload()
                self.say("Картинка из буфера во входящих: " + os.path.basename(p))
                return
        self.say("В буфере нет картинки")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.source() is None:  # свои плитки обратно во входящие не принимаем
            e.acceptProposedAction()
            self.overlay.appear(True)

    def dragLeaveEvent(self, _e):
        self.overlay.appear(False)

    def dropEvent(self, e):
        self.overlay.appear(False)
        self.take([u.toLocalFile() for u in e.mimeData().urls()])

    # --- папка генератора: новые картинки сами копируются во входящие
    def theme_dialog(self):
        from ui.tools_dialogs import ThemeDialog

        ThemeDialog(self).exec()

    def apply_theme(self):
        """Сменить тему на лету: цвета C меняются на месте, стили пересобираются, фон и плитки перерисовываются."""
        from ui import theme

        theme.apply(self.cfg.get("theme", "dark"), self.cfg.get("accent", "lavender"))
        QApplication.instance().setStyleSheet(theme.stylesheet())
        self.aurora.cache = None
        fill_tree(self.inbox.tree)
        self.lib.refresh()
        self.unreal.nav.fill_themes()
        for w in QApplication.instance().allWidgets():
            w.update()

    def show_gen(self):
        d = self.cfg.get("gen_dir")
        self.gen_btn.setVisible(bool(d))  # кнопка видна, только когда слежка включена; выбрать - в «Инструментах»
        self.gen_btn.setText("Генератор: слежу" if d else "Папка генератора...")
        self.gen_btn.setToolTip(
            (f"Слежу за папкой: {d}\nНовые картинки сами попадают во входящие.\nЩелчок - выбрать другую или отключить")
            if d
            else "Выберите папку, куда генератор сохраняет картинки - новые будут сами попадать во входящие"
        )
        self.inbox.gen_hint.setText(
            (f"Слежу за папкой генератора: {d}")
            if d
            else "Можно указать папку генератора (кнопка вверху) - новые картинки будут приходить сами"
        )
        self.say("Слежу за папкой генератора: " + d if d else "Папка генератора не задана")

    def pick_gen(self):
        d = QFileDialog.getExistingDirectory(
            self, "Папка, куда генератор сохраняет картинки (Отмена - не следить)", self.cfg.get("gen_dir", "")
        )
        self.cfg["gen_dir"] = os.path.normpath(d) if d else ""
        self.cfg["gen_since"] = time.time()  # берём только то, что появится после выбора
        self.sizes = {}
        self.show_gen()

    def check_gen(self):
        d = self.cfg.get("gen_dir")
        if not d or not os.path.isdir(d):
            return
        since, newest, ready, seen = self.cfg.get("gen_since", time.time()), 0, [], {}
        try:
            names = os.listdir(d)
        except OSError:  # сетевая папка отвалилась - попробуем в следующий раз
            return
        for f in names:
            p = os.path.join(d, f)
            if not is_image(f):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_mtime <= since or not os.path.isfile(p):
                continue
            if self.sizes.get(p) == st.st_size and st.st_size:  # размер не растёт - файл дописан
                ready.append(p)
                newest = max(newest, st.st_mtime)
            seen[p] = st.st_size
        self.sizes = seen  # старые записи не копятся
        if ready:
            self.cfg["gen_since"] = newest
            if self.take(ready):
                QApplication.alert(self)  # мигнуть на панели задач, если окно в фоне

    # --- прочее
    def doctor(self):
        DoctorDialog(self).exec()

    def missing(self):
        MissingDialog(self).exec()

    def show_weight(self):
        WeightDialog(self).exec()

    def toggle_live(self):
        self.cfg["live_bg"] = not self.cfg.get("live_bg", True)
        self.aurora.set_live(self.cfg["live_bg"])
        self.say("Живой фон: " + ("плывёт" if self.cfg["live_bg"] else "застыл (F9 - включить)"))

    def show_help(self, topic=None):
        HelpDialog(self, topic).show()

    def agents(self):
        AgentsDialog(self).exec()

    def greet(self):
        """После обновления - «Что нового», при самом первом запуске - «С чего начать»."""
        seen = self.cfg.get("seen_version")
        self.cfg["seen_version"] = VERSION
        if seen != VERSION:
            self.show_help(NEW if seen or self.cfg.get("size") else "С чего начать")

    def open_gallery(self):
        self.gal.stop()
        K.build_gallery()
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(LIB, "Gallery.html")))

    def open_prompts(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(LIB, "Prompts.html")))

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
        self.lib.remember_section()
        self.drop_redo()  # после закрытия вернуть отменённое нельзя
        try:
            save_cfg(self.cfg)
        except OSError as ex:
            log_error(f"настройки не записались: {ex}")
        if self.gal.isActive():
            try:
                K.build_gallery()
            except Exception as ex:
                log_error(f"галерея не собралась: {ex}")
        e.accept()


def take_old_favs(cfg):
    """Избранное до 2.2 жило в settings.json - переносим в базу (её видит и ИИ-помощник)."""
    old = cfg.pop("fav", None)
    if old:
        try:
            db.set_fav(old)
        except Exception as e:
            cfg["fav"] = old
            log_error(f"избранное не перенеслось в базу: {e}")


def install_guard(app):
    """Без sys.excepthook PyQt6 роняет процесс на исключении в слоте - пишем в журнал и пузырём."""

    def hook(kind, err, tb):
        log_error("".join(traceback.format_exception(kind, err, tb)))
        try:
            for w in app.topLevelWidgets():
                if isinstance(w, Window) and w.isVisible():
                    w.say("Ошибка: %s  (подробности в _errors.log)" % (err or kind.__name__))
                    break
        except Exception:
            pass

    sys.excepthook = hook


def main():
    app = QApplication(sys.argv)
    install_guard(app)
    relay()
    from ui import theme

    cfg = load_cfg()  # тема и акцент - до первой отрисовки
    theme.apply(cfg.get("theme", "dark"), cfg.get("accent", "lavender"))
    app.setStyleSheet(theme.stylesheet())
    for fx in (
        Qt.UIEffect.UI_AnimateMenu,
        Qt.UIEffect.UI_FadeMenu,
        Qt.UIEffect.UI_AnimateCombo,
        Qt.UIEffect.UI_AnimateTooltip,
        Qt.UIEffect.UI_FadeTooltip,
    ):
        app.setEffectEnabled(fx, True)
    Motion(app)
    w = Window()
    fade_in_window(w)
    w.show()
    code = app.exec()
    finish_bg()  # фоновые потоки - доделать или бросить
    db.close()
    forget_pixmaps()  # затем картинки и окно, и только потом приложение
    sip.delete(w)
    del w
    sys.exit(code)


if __name__ == "__main__":
    main()
