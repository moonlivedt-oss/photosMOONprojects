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
from ui import db
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
from ui.inbox_tab import InboxTab
from ui.library_tab import LibTab
from ui.missing import MissingDialog
from ui.semantic import SemIndex
from ui.signatures import SigIndex
from ui.tagging import Tagger
from ui.theme import QSS, ui_files
from ui.thumbnails import forget_pixmaps, lib_icon, trim_thumbs
from ui.weight import WeightDialog
from ui.widgets import fill_tree, forget_counts, key

HELP = """<b>Горячие клавиши</b><table cellspacing=4>
<tr><td>Ctrl+S</td><td>сохранить отмеченные куски в раздел</td></tr>
<tr><td>Ctrl+Z / Ctrl+Y</td><td>отменить последнее действие / вернуть отменённое; «История» внизу - отменить несколько сразу</td></tr>
<tr><td>Рамки на листе</td><td>во входящих: тяните край рамки - поправить кусок, Shift + протяжка - новая рамка;
«Склеить» / «Разрезать» над кусками; «Правка кусков» - рецепт из редактора к каждому куску</td></tr>
<tr><td>Метки и заметка</td><td>под цветами справа; поиск находит по ним («#космос»), метки - в дереве слева</td></tr>
<tr><td>Наборы</td><td>в дереве: каждый набор одной обложкой с его палитрами</td></tr>
<tr><td>Плитку на раздел</td><td>перетащите плитки на раздел в дереве - перенос (Ctrl+Z вернёт)</td></tr>
<tr><td>Доктор</td><td>кнопка вверху: пустые, обрезанные, с остатками фона, с каймой, с кусками соседа</td></tr>
<tr><td>Чего нет</td><td>кнопка вверху: наборы из промптов по палитрам; промпт, имя файла, перекраска из готовой палитры</td></tr>
<tr><td>Просмотр</td><td>колесо - увеличить, 1 или двойной щелчок - пиксель в пиксель, 0 - целиком</td></tr>
<tr><td>Ctrl+V</td><td>вставить картинку или файлы из буфера во входящие</td></tr>
<tr><td>Ctrl+1 / Ctrl+2</td><td>вкладки Входящие / Библиотека</td></tr>
<tr><td>Ctrl+F</td><td>поиск по библиотеке; «кот -png» - слово с минусом исключает</td></tr>
<tr><td>Ctrl+M</td><td>поиск по смыслу (кнопка-шар у поиска): «кот в космосе», «уютная ночная улица» - по-русски и по-английски, без слов в имени файла</td></tr>
<tr><td>Метки во входящих</td><td>под полем «Метки» - подсказки по смыслу кусков (CLIP); щелчок добавляет, метки получат все сохранённые куски. Галка «Ставить подсказанные метки» - то же для «Разобрать все» и автораскладки</td></tr>
<tr><td>Метки в библиотеке</td><td>под полем меток справа - подсказки для выбранной картинки (или нескольких), щелчок ставит</td></tr>
<tr><td>Поиск по картинке</td><td>бросьте картинку (файл из проводника или плитку) в строку поиска - похожие по смыслу</td></tr>
<tr><td>Умные папки</td><td>кнопка-закладка у поиска сохраняет поиск (слова, цвет, смысл) в дерево слева - папка сама пополняется</td></tr>
<tr><td>Esc</td><td>в библиотеке - очистить поиск, выйти из «Похожих»</td></tr>
<tr><td>Ctrl+A</td><td>в библиотеке - выделить все плитки</td></tr>
<tr><td>Alt+← / кнопка мыши «назад»</td><td>в библиотеке - к прошлому разделу</td></tr>
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
<tr><td>Ctrl+R</td><td>редактировать: поворот, кадрирование, цвет, перекраска в палитру, убрать фон и кайму, кисть,
обводка, квадрат, тень, свечение, скругление, размер, рецепты;
несколько выбранных - одна правка на все; оригинал уходит в «_sources», Ctrl+Z возвращает</td></tr>
<tr><td>Ctrl+K</td><td>сжать и конвертировать: шторка до/после, «самый лёгкий» формат, лимит в КБ, сравнение форматов</td></tr>
<tr><td>Ctrl+E</td><td>выгрузить выбранное в папку проекта (формат, размер, @2x/@3x, лимит в КБ, svg)</td></tr>
<tr><td>Ctrl+I</td><td>вес разделов: где тяжелее всего, сколько сэкономлено, сжать тяжёлые</td></tr>
<tr><td>Меню плитки</td><td>«Сделать копию в формате» - в фоне, по всем ядрам, Ctrl+Z убирает копии</td></tr>
<tr><td>F9</td><td>живой фон окна: плывёт / застыл (застывший не тратит процессор)</td></tr>
</table><p>Картинки из библиотеки можно перетаскивать мышью прямо в другие программы.</p>
<p>Если что-то пошло не так, окно не закрывается, а пишет ошибку в «_tools/_errors.log».</p>"""


# ---------------------------------------------------------------- окно
class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        self.history = []                   # для Ctrl+Z: [(подпись, [("new", путь) | ("move", было, стало)])]
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
        self.inbox.reload()
        self.setCentralWidget(self.tabs)
        PageFade(self.tabs)

        corner = QWidget()
        ch = QHBoxLayout(corner)
        ch.setContentsMargins(0, 0, 8, 4)
        for text, icon, fn, tip in (("Галерея", "Компас", self.open_gallery, "Вся библиотека в браузере"),
                                    ("Промпты", "Заметка", self.open_prompts, ""),
                                    ("Найти дубли", "Лупа", self.dupes, "Одинаковые картинки уедут в «_duplicates»"),
                                    ("Доктор", "first-aid-kit", self.doctor,
                                     "Проверить библиотеку: пустые, обрезанные, с остатками фона и каймой"),
                                    ("Чего нет", "checklist", self.missing,
                                     "Наборы из Prompts.html: каких палитр и картинок не хватает")):
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
        self.undo_btn.clicked.connect(lambda: self.undo())
        self.undo_btn.hide()
        self.redo = []                      # отменённое: [(подпись, шаги, сделанные переносы)] - для Ctrl+Y
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
        self.saved_cfg = cfg_text(self.cfg)                         # настройки пишутся сами, если поменялись:
        self.autosave = QTimer(self, interval=5000)                 # избранное не теряется, если окно упадёт
        self.autosave.timeout.connect(self.save_settings)
        self.autosave.start()
        self.gal = QTimer(self, singleShot=True, interval=1500)     # галерею и отпечатки пересобираем один раз на пачку правок
        self.gal.timeout.connect(self.rebuild)
        self.sizes = {}                                             # размеры файлов генератора на прошлом опросе
        self.poll = QTimer(self, interval=2000)
        self.poll.timeout.connect(self.check_gen)
        self.poll.start()

        for keys, fn in (("Ctrl+Z", lambda: self.undo()), ("Ctrl+Y", self.redo_last),
                         ("Ctrl+Shift+Z", self.redo_last), ("Ctrl+V", self.paste), ("F1", self.show_help),
                         ("Ctrl+1", lambda: self.tabs.setCurrentIndex(0)),
                         ("Ctrl+2", lambda: self.tabs.setCurrentIndex(1)), ("F9", self.toggle_live),
                         ("Ctrl+I", self.show_weight)):
            key(keys, self, fn, local=False)

        self.show_gen()
        self.update_stats()
        self.sigs.refresh()
        self.sem.refresh()
        bg(trim_thumbs, lambda _n: None)
        self.tabs.setCurrentIndex(self.cfg.get("tab", 0) if inbox_files() == [] else 0)
        if self.cfg.get("max"):
            self.setWindowState(Qt.WindowState.WindowMaximized)

    def show_sem_progress(self, prog):
        if prog is None:
            self.sem_lbl.hide()
            if self.lib.sem.isChecked() and self.lib.q.text().strip():
                self.lib.show_files()
            return
        self.sem_lbl.setText(f"Поиск по смыслу: учу картинки {prog[0]} из {prog[1]}")
        self.sem_lbl.show()

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
        self.history = (self.history + [(text, steps)])[-20:]
        self.drop_redo()                    # новое действие - вернуть отменённое уже нельзя
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
        for i, (text, _s) in enumerate(reversed(self.history)):
            m.addAction(("Отменить: " if i == 0 else "Отменить до: ") + text, lambda n=i + 1: self.undo(n))
        if not self.history and not self.redo:
            m.addAction("Действий пока нет").setEnabled(False)

    def undo(self, count=1):
        if not self.history:
            self.say("Отменять нечего")
            return
        texts, bad = [], 0
        for _k in range(min(count, len(self.history))):
            text, steps = self.history.pop()
            done, b = self.undo_steps(steps)
            bad += b
            self.redo.append((text, steps, done))
            texts.append(text)
        self.after_change()
        self.say("Отменено: " + "; ".join(texts) + ("  (не получилось: %d)" % bad if bad else "")
                 + "   Ctrl+Y - вернуть")

    def undo_steps(self, steps):
        """Откатить шаги. Новые файлы уезжают в _sources/_undone (а не в корзину), чтобы Ctrl+Y
        мог их вернуть. -> ([(откуда, куда)] - сделанные переносы, ошибок)."""
        forget_counts()
        done, bad = [], 0
        for step in reversed(steps):
            try:
                if step[0] == "new":
                    if os.path.exists(step[1]):
                        park = unique(os.path.join(PARK, os.path.basename(step[1])))
                        os.makedirs(PARK, exist_ok=True)
                        shutil.move(step[1], park)
                        done.append((step[1], park))
                elif os.path.exists(step[2]):
                    back = step[1] if not os.path.exists(step[1]) else unique(step[1])
                    os.makedirs(os.path.dirname(back), exist_ok=True)
                    shutil.move(step[2], back)
                    self.moved(step[2], back)
                    done.append((step[2], back))
                    if os.path.dirname(back) == INBOX:
                        self.inbox.no_auto.add(back)
            except Exception:
                bad += 1
        return done, bad

    def redo_last(self):
        """Ctrl+Y: вернуть последнее отменённое - переносы в обратную сторону."""
        if not self.redo:
            self.say("Возвращать нечего")
            return
        text, steps, done = self.redo.pop()
        forget_counts()
        bad = 0
        for a, b in reversed(done):
            try:
                if not os.path.exists(b) or os.path.exists(a):
                    bad += 1
                    continue
                os.makedirs(os.path.dirname(a), exist_ok=True)
                shutil.move(b, a)
                self.moved(b, a)
            except Exception:
                bad += 1
        self.history = (self.history + [(text, steps)])[-20:]
        self.after_change()
        self.say("Возвращено: " + text + ("  (не получилось: %d)" % bad if bad else ""))

    def drop_redo(self):
        """Отменённое, что уже не вернуть, - из _sources/_undone в корзину."""
        for _t, _s, done in self.redo:
            for _a, b in done:
                if os.path.dirname(b) == PARK and os.path.exists(b):
                    QFile.moveToTrash(b)
        self.redo = []

    def after_change(self):
        self.update_undo()
        self.inbox.reload()
        if self.tabs.currentIndex() == 1:
            self.lib.refresh()
        self.library_changed()

    def moved(self, src, dst):
        """Избранное, метки и заметка едут вместе с файлом."""
        fav = self.cfg.get("fav", [])
        try:
            a, b = os.path.relpath(src, LIB), os.path.relpath(dst, LIB)
        except ValueError:                  # путь на другом диске - в избранном его быть не может
            return
        if a in fav:
            fav[fav.index(a)] = b
        try:
            db.moved(a, b)
        except Exception as e:
            log_error(f"метки не переехали: {e}")

    # --- приём файлов
    def take(self, files):
        n, bad = 0, []
        for f in files:
            if os.path.isfile(f) and is_image(os.path.basename(f)) and os.path.dirname(os.path.abspath(f)) != INBOX:
                try:
                    shutil.copy2(f, unique(os.path.join(INBOX, os.path.basename(f))))
                    n += 1
                except OSError as e:            # файл занят генератором или нет прав - остальные всё равно берём
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
        self.gen_btn.setToolTip((f"Слежу за папкой: {d}\nНовые картинки сами попадают во входящие.\n"
                                 "Щелчок - выбрать другую или отключить") if d else
                                "Выберите папку, куда генератор сохраняет картинки - новые будут сами попадать во входящие")
        self.inbox.gen_hint.setText((f"Слежу за папкой генератора: {d}") if d else
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
        since, newest, ready, seen = self.cfg.get("gen_since", time.time()), 0, [], {}
        try:
            names = os.listdir(d)
        except OSError:                             # сетевая папка отвалилась - попробуем в следующий раз
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
            if self.sizes.get(p) == st.st_size and st.st_size:      # размер не растёт - файл дописан
                ready.append(p)
                newest = max(newest, st.st_mtime)
            seen[p] = st.st_size
        self.sizes = seen                           # старые записи не копятся
        if ready:
            self.cfg["gen_since"] = newest
            if self.take(ready):
                QApplication.alert(self)            # мигнуть на панели задач, если окно в фоне

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

    def show_help(self):
        QMessageBox.information(self, f"Горячие клавиши - Библиотека картинок {VERSION}", HELP)

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
        self.drop_redo()                    # после закрытия вернуть отменённое нельзя
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
    db.close()
    forget_pixmaps()                # затем картинки и окно, и только потом приложение
    sip.delete(w)
    del w
    sys.exit(code)


if __name__ == "__main__":
    main()
