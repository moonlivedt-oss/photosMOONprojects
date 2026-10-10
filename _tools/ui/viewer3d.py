"""Окно 3D-просмотра ассетов Unreal на Qt Quick 3D (сцена - viewer3d.qml).
Слева лента ассетов текущего раздела вкладки (стрелки - соседний), в середине сцена, справа - вид, свет,
карты текстуры и сведения. Модель - FBX через assimp, текстура - PBR-материал на шаре, кубе или плоскости,
HDRI - панорама изнутри. Мышь: тянуть - вращать, колесо - ближе/дальше (у HDRI - угол обзора), правая - сдвиг."""

import hashlib
import os
from html import escape as esc  # сведения - rich text: имена и метки с сайта не должны стать разметкой

from PIL import Image
from PyQt6.QtCore import QObject, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QQuaternion
from PyQt6.QtQml import QQmlProperty
from PyQt6.QtQuickWidgets import QQuickWidget
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from library import unreal as U
from ui.common import HERE, human, log_error
from ui.theme import C
from ui.thumbnails import lib_icon, thumb
from ui.widgets import key

QML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer3d.qml")
CACHE = os.path.join(HERE, "_thumbs", "ue3d")  # нормали, перевёрнутые для Qt (OpenGL), и каналы ARM
CAN_VIEW = ("tex", "hdri", "model")


def viewable(a):
    """Можно ли открыть ассет в 3D окна: модели с сотнями морфов (лицо MetaHuman) роняют Qt Quick 3D -
    у них флаг no_qt3d (в asset.json или из library/fbx_meta), вместо 3D - картинка превью. Если есть
    просмотровая копия без морфов (view в asset.json, library/blender_preview.make_view_model) - открывается она."""
    return a.get("kind") in CAN_VIEW and (not a.get("no_qt3d") or bool(a.get("view")))


SHORT = {"tex": "Текстура", "hdri": "HDRI", "model": "Модель"}


def url(path):
    return QUrl.fromLocalFile(path) if path else QUrl()


def find(files, *keys):
    """Первый файл, в имени которого есть один из ключей (без учёта регистра)."""
    for k in keys:
        for f in files:
            if k in os.path.basename(f).lower():
                return f
    return ""


def cached(path, tag, fn):
    """Производная картинка (fn(Image) -> Image) в кэше: считается один раз на файл."""
    if not path:
        return ""
    st = os.stat(path)
    key_ = hashlib.md5(f"{path}|{st.st_mtime}|{st.st_size}|{tag}".encode()).hexdigest()
    dst = os.path.join(CACHE, key_ + ".png")
    if not os.path.exists(dst):
        os.makedirs(CACHE, exist_ok=True)
        with Image.open(path) as im:
            out = fn(im.convert("RGB"))
        out.save(dst + ".tmp.png")
        os.replace(dst + ".tmp.png", dst)
    return dst


def gl_normal(path):
    """Unreal ждёт нормаль DirectX, Qt Quick 3D - OpenGL: зелёный канал перевёрнут."""

    def flip(im):
        r, g, b = im.split()
        return Image.merge("RGB", (r, g.point(lambda v: 255 - v), b))

    return cached(path, "gl", flip)


def channel(path, i):
    """Один канал упакованной карты (ARM) серым - чтобы посмотреть его отдельно."""
    return cached(path, f"ch{i}", lambda im: im.split()[i])


def texture_files(a):
    d = a["dir"]
    return [
        os.path.join(d, f)
        for f in sorted(os.listdir(d))
        if f.lower().endswith((".jpg", ".jpeg", ".png")) and not f.startswith("preview")
    ]


def materials(a):
    """Карты PBR-текстуры -> свойства сцены (с каналами для упакованной ARM)."""
    files = texture_files(a)
    arm = find(files, "_arm_")
    out = {
        "baseMap": find(files, "_diff_", "_color", "albedo", "basecolor"),
        "normalMap": "",
        "roughMap": "",
        "metalMap": "",
        "aoMap": "",
        "heightMap": find(files, "_disp_", "displacement", "height"),
        "roughChannel": 0,
        "metalChannel": 0,
        "aoChannel": 0,
    }
    nd = find(files, "_nor_dx_", "normaldx")
    ngl = find(files, "_nor_gl_", "normalgl")
    try:
        out["normalMap"] = ngl or gl_normal(nd)
    except Exception as e:  # без нормали материал всё равно покажется
        log_error("viewer3d normal: %r" % e)
    if arm:
        out.update(roughMap=arm, roughChannel=1, metalMap=arm, metalChannel=2, aoMap=arm, aoChannel=0)
    else:
        out.update(
            roughMap=find(files, "_rough", "roughness"),
            metalMap=find(files, "metalness", "_metal"),
            aoMap=find(files, "ambientocclusion", "_ao_"),
        )
    return out


def map_list(a):
    """Карты текстуры для кнопок «посмотреть отдельно»: [(подпись, путь к файлу, канал или None)]."""
    files = texture_files(a)
    arm = find(files, "_arm_")
    out = [
        ("Цвет", find(files, "_diff_", "_color", "albedo", "basecolor"), None),
        ("Нормаль", find(files, "_nor_dx_", "normaldx", "_nor_gl_"), None),
    ]
    if arm:
        out += [("Шероховатость", arm, 1), ("Металл", arm, 2), ("AO", arm, 0), ("ARM целиком", arm, None)]
    else:
        out += [
            ("Шероховатость", find(files, "_rough", "roughness"), None),
            ("Металл", find(files, "metalness", "_metal"), None),
            ("AO", find(files, "ambientocclusion", "_ao_"), None),
        ]
    out.append(("Высота", find(files, "_disp_", "displacement", "height"), None))
    return [m for m in out if m[1]]


# ---------------------------------------------------------------- анимации модели
# Qt Quick 3D (6.11) сам делает из анимаций FBX по Timeline на каждую и запускает их по кругу: у персонажей
# Kenney их 30 штук - модель дёргалась. Окно останавливает все и включает одну, выбранную в просмотре 3D.
def animations(root):
    """[(имя, Timeline, TimelineAnimation)] загруженной модели; пустые (длина 0) не считаются."""
    out = []
    for o in root.findChildren(QObject):
        if o.metaObject().className() != "QQuickTimelineAnimation" or o.parent() is None:
            continue
        if (o.property("duration") or 0) <= 0:
            continue
        out.append((o.objectName() or f"анимация {len(out) + 1}", o.parent(), o))
    return out


def _dot(a, b):
    return a.scalar() * b.scalar() + a.x() * b.x() + a.y() * b.y() + a.z() * b.z()


def fix_keyframes(timeline):
    """Ключи поворота, которые Qt испортил при чтении FBX: одиночный ключ «в никуда» между двумя похожими
    соседями - на одну рамку кость выворачивало (у персонажей Kenney - второй ключ каждой анимации).
    Такой ключ заменяется серединой соседей; знаки выравниваются - поворот идёт коротким путём.
    Один раз на таймлайн (отметка - динамическое свойство libFixed)."""
    if timeline.property("libFixed"):
        return 0
    timeline.setProperty("libFixed", True)
    fixed = 0
    for g in timeline.findChildren(QObject):
        if g.metaObject().className() != "QQuickKeyframeGroup" or g.property("property") != "rotation":
            continue
        kfs = [k for k in g.findChildren(QObject) if k.metaObject().className() == "QQuickKeyframe"]
        kfs.sort(key=lambda k: k.property("frame") or 0)
        qs = [k.property("value") for k in kfs]
        if len(qs) < 3 or not all(isinstance(q, QQuaternion) for q in qs):
            continue
        for i in range(1, len(qs)):  # q и -q - один поворот; соседи одного знака - интерполяция без кувырка
            if _dot(qs[i], qs[i - 1]) < 0:
                qs[i] = -qs[i]
                kfs[i].setProperty("value", qs[i])
        for i in range(1, len(qs) - 1):
            a, q, b = qs[i - 1], qs[i], qs[i + 1]
            if abs(_dot(a, b)) > 0.95 and abs(_dot(q, a)) < 0.9 and abs(_dot(q, b)) < 0.9:
                qs[i] = QQuaternion.nlerp(a, b, 0.5)
                kfs[i].setProperty("value", qs[i])
                fixed += 1
    return fixed


def set_animation(root, name=None):
    """Играть одну анимацию (по имени) или ни одной: модель замирает в позе первого кадра первой анимации."""
    anims = animations(root)
    for _n, _tl, an in anims:  # всё стоп
        an.setProperty("running", False)
    for _n, tl, _an in anims:
        tl.setProperty("enabled", False)
    pick = next(((tl, an) for n, tl, an in anims if n == name), None)
    if pick is None and anims:  # покой: поза первого кадра (обычно idle - стоит ровно)
        tl = anims[0][1]
        tl.setProperty("enabled", True)
        tl.setProperty("currentFrame", tl.property("startFrame") or 0.0)
        tl.setProperty("enabled", False)
    elif pick is not None:
        tl, an = pick
        fix_keyframes(tl)
        tl.setProperty("enabled", True)
        an.setProperty("running", True)
    return [n for n, _tl, _an in anims]


def when_loaded(root, fn, tries=60):
    """Вызвать fn(), когда модель загрузилась (подогнана под кадр); анимации появляются только тогда."""

    def check(left=tries):
        if root.property("fitted") or root.property("status"):
            fn()
        elif left > 0:
            QTimer.singleShot(150, lambda: check(left - 1))

    QTimer.singleShot(150, check)


def load_scene(root, a, probe="", sky=False):
    """Ассет в сцену viewer3d.qml (её делят большое окно и живой просмотр в панели вкладки).
    probe - HDRI для освещения модели и текстуры; у самого HDRI - он сам."""
    kind = a.get("kind")
    if a.get("no_qt3d") and not a.get("view"):  # страховка: сюда такие не должны попадать (viewable)
        root.setProperty("status", "Эту модель 3D окна не откроет - смотрите в Unreal или Blender")
        return
    root.setProperty("status", "")
    from library.unreal_extra import yaw_of

    root.setProperty("modelYaw", yaw_of(a) if kind == "model" else 0)
    root.setProperty("flat", QUrl())
    root.setProperty("sizeText", "")
    root.setProperty("mode", kind)
    main = [os.path.join(a["dir"], *m.split("/")) for m in a.get("main", [])]
    if kind == "hdri":
        root.setProperty("probe", url(main[0] if main else ""))
        root.setProperty("showSky", True)
    else:
        root.setProperty("probe", url(probe))
        root.setProperty("showSky", sky)
    root.setProperty("linearColors", a.get("source") == "Quaternius")
    if kind == "model":
        fbx = next((p for p in main if p.lower().endswith((".fbx", ".gltf", ".glb", ".obj"))), "")
        if a.get("view"):  # просмотровая копия (MetaHuman: все части одним GLB без морфов) - только для 3D окна
            fbx = os.path.join(a["dir"], a["view"])
        root.setProperty("modelSource", QUrl())  # тот же файл заново - иначе загрузчик не перечитает
        root.setProperty("modelSource", url(fbx))
    if kind == "tex":
        for k, v in materials(a).items():
            root.setProperty(k, url(v) if k.endswith("Map") else v)
    root.resetView()


def studio_probe(items, cfg):
    """HDRI для освещения: выбранный в большом окне или первый студийный."""
    saved = cfg.get("ue_env")
    if saved and os.path.exists(saved):
        return saved
    hd = sorted(
        (a for a in items if a.get("kind") == "hdri" and a.get("main")),
        key=lambda a: (a.get("theme") != "Студия", a.get("name", "")),
    )
    return os.path.join(hd[0]["dir"], hd[0]["main"][0]) if hd else ""


class MiniView(QQuickWidget):
    """Живой 3D в правой панели вкладки: модель на подставке медленно вращается, текстура - на шаре,
    HDRI - панорама. Тянуть мышью можно и здесь."""

    def __init__(self):
        super().__init__()
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setSource(QUrl.fromLocalFile(QML))
        self.setMinimumSize(200, 200)
        self.root = self.rootObject()
        self.shown = None
        if self.root is None:
            log_error("viewer3d.qml (панель): " + "; ".join(e.toString() for e in self.errors()))
            return
        self.root.setProperty("back", C["bg1"])
        self.root.setProperty("floor", True)
        self.root.setProperty("spin", True)

    def show_asset(self, a, probe):
        if self.root is None:
            return False
        if self.shown != a["dir"]:
            self.shown = a["dir"]
            load_scene(self.root, a, probe)
            when_loaded(self.root, lambda: set_animation(self.root))  # в панели модель не дёргается
        return True

    def pause(self, on):
        """Спрятанная панель не крутит модель зря."""
        if self.root is not None:
            self.root.setProperty("spin", not on)


def section(text):
    return QLabel(text, objectName="faint")


class Viewer3D(QDialog):
    def __init__(self, tab):
        super().__init__(tab, Qt.WindowType.Window)
        self.tab, self.cfg = tab, tab.cfg
        self.setWindowTitle("Просмотр 3D")
        self.setWindowIcon(lib_icon("dice_3D"))
        self.resize(*self.cfg.get("ue_view_size", [1360, 820]))
        self.asset, self.assets = None, []

        self.quick = QQuickWidget()
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.quick.setSource(QUrl.fromLocalFile(QML))
        self.quick.setMinimumSize(420, 320)
        self.root = self.quick.rootObject()
        if self.root is None:
            log_error("viewer3d.qml: " + "; ".join(e.toString() for e in self.quick.errors()))
        else:
            self.root.setProperty("back", C["bg0"])
            self.root.setProperty("accent", C["acc"])
            self.size_prop = QQmlProperty(self.root, "sizeText")
            self.size_prop.connectNotifySignal(self.update_info)

        # --- лента слева
        self.strip = QListWidget()
        self.strip.setViewMode(QListWidget.ViewMode.ListMode)
        self.strip.setIconSize(QSize(56, 56))
        self.strip.setSpacing(2)
        self.strip.setMinimumWidth(190)
        self.strip.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strip.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.strip.currentRowChanged.connect(self.strip_pick)
        self.strip_lbl = QLabel(objectName="faint")
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.strip_lbl)
        lv.addWidget(self.strip, 1)

        # --- верх: имя, подпись, соседние
        self.title = QLabel(objectName="head")
        self.sub = QLabel(objectName="dim")
        self.prev_b = QPushButton(lib_icon("arrowLeft"), "", objectName="tool")
        self.prev_b.setToolTip("Предыдущий (стрелка влево)")
        self.prev_b.clicked.connect(lambda: self.step(-1))
        self.next_b = QPushButton(lib_icon("arrowRight"), "", objectName="tool")
        self.next_b.setToolTip("Следующий (стрелка вправо)")
        self.next_b.clicked.connect(lambda: self.step(1))
        top = QHBoxLayout()
        top.addWidget(self.prev_b)
        top.addWidget(self.next_b)
        top.addSpacing(6)
        top.addWidget(self.title)
        top.addWidget(self.sub, 1)
        hint = QLabel(
            "Тянуть - вращать, колесо - ближе, правая кнопка - сдвиг, F - вид заново, "
            "Пробел - вращение, W - каркас, G - пол, стрелки - соседний ассет",
            objectName="faint",
            wordWrap=True,
        )
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addLayout(top)
        mv.addWidget(self.quick, 1)
        mv.addWidget(hint)

        # --- панель справа
        self.reset_b = QPushButton(lib_icon("arrow_counterclockwise"), "Вид заново")
        self.reset_b.setToolTip("Вернуть камеру (F)")
        self.reset_b.clicked.connect(self.reset_view)
        self.spin = QCheckBox("Вращать (Пробел)")
        self.spin.toggled.connect(lambda v: self.set("spin", v))
        self.wire = QCheckBox("Каркас (W)")
        self.wire.setToolTip("Сетка полигонов")
        self.wire.toggled.connect(lambda v: self.set("wire", v))
        self.floor = QCheckBox("Пол, тень и сетка (G)")
        self.floor.setChecked(self.cfg.get("ue_floor", True))
        self.floor.toggled.connect(self.toggle_floor)
        self.set("floor", self.floor.isChecked())
        self.shape = QComboBox()
        for t, v, ic in (("Шар", "sphere", "dot_large"), ("Куб", "cube", "dice_3D"), ("Плоскость", "plane", "card")):
            self.shape.addItem(lib_icon(ic), t, v)
        self.shape.currentIndexChanged.connect(lambda _i: self.set("shape", self.shape.currentData()))
        self.tiling = QSpinBox(minimum=1, maximum=16, value=1, prefix="Повтор x")
        self.tiling.setToolTip("Сколько раз текстура повторяется на фигуре")
        self.tiling.valueChanged.connect(lambda v: self.set("tiling", float(v)))
        self.height_s = self.slider(0, 100, 0, "Рельеф по карте высоты", lambda v: self.set("heightAmount", v / 1000))
        self.maps = QWidget()
        self.maps_l = QGridLayout(self.maps)
        self.maps_l.setContentsMargins(0, 0, 0, 0)
        self.map_group = QButtonGroup(self)
        self.map_group.setExclusive(True)
        self.balls = QCheckBox("Шары-пробники")
        self.balls.setToolTip("Зеркальный и матовый шар: как это небо освещает сцену")
        self.balls.toggled.connect(lambda v: self.set("mirrorBall", v))
        self.unwrap = QCheckBox("Развёртка целиком")
        self.unwrap.setToolTip("Вся панорама плоской картинкой")
        self.unwrap.toggled.connect(self.toggle_unwrap)
        self.env = QComboBox()
        self.env.setToolTip("Каким небом освещать модель или текстуру")
        self.env.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.env.setMinimumContentsLength(14)
        self.env.currentIndexChanged.connect(self.apply_env)
        self.sky = QCheckBox("Небо на фоне")
        self.sky.toggled.connect(lambda v: self.set("showSky", v))
        self.expo = self.slider(10, 400, 100, "Яркость неба", lambda v: self.set("exposure", v / 100))
        self.rot = self.slider(0, 360, 0, "Поворот неба", lambda v: self.set("skyRotation", float(v)))
        self.info = QLabel(objectName="dim", wordWrap=True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info.setOpenExternalLinks(True)
        shot = QPushButton(lib_icon("camera"), "Снимок")
        shot.setToolTip("Сохранить картинку того, что видно сейчас")
        shot.clicked.connect(self.screenshot)
        files = QPushButton(lib_icon("folder"), "Файлы")
        files.clicked.connect(lambda: self.asset and QDesktopServices.openUrl(QUrl.fromLocalFile(self.asset["dir"])))
        proj = QPushButton(lib_icon("export"), "В проект...")
        proj.setToolTip("Скопировать файлы ассета в папку проекта Unreal")
        proj.clicked.connect(self.to_project)

        panel = QWidget(objectName="panel")
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(12, 12, 12, 12)
        self.blocks = {}

        def block(name, *rows):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 8)
            for r in rows:
                if isinstance(r, tuple):
                    h = QHBoxLayout()
                    for x in r:
                        h.addWidget(QLabel(x) if isinstance(x, str) else x)
                    v.addLayout(h)
                else:
                    v.addWidget(r)
            self.blocks[name] = w
            pv.addWidget(w)

        block("view", section("ВИД"), self.reset_b, self.spin, self.wire, self.floor)
        block(
            "tex",
            section("ФИГУРА"),
            (self.shape, self.tiling),
            ("Рельеф", self.height_s),
            section("КАРТЫ - ПОСМОТРЕТЬ ОТДЕЛЬНО"),
            self.maps,
        )
        block("hdri", section("ПАНОРАМА"), self.balls, self.unwrap)
        self.tryon = QComboBox()
        self.tryon.setToolTip("Надеть скачанную текстуру на всю модель: ткань на диван, дерево на стол")
        self.tryon.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.tryon.setMinimumContentsLength(14)
        self.tryon.currentIndexChanged.connect(self.apply_tryon)
        self.try_tile = QSpinBox(minimum=1, maximum=16, value=2, prefix="Повтор x")
        self.try_tile.setToolTip("Сколько раз рисунок повторяется на модели")
        self.try_tile.valueChanged.connect(lambda v: self.set("tiling", float(v)) if self.tryon.currentData() else None)
        block("try", section("ПРИМЕРИТЬ ТЕКСТУРУ"), self.tryon, self.try_tile)
        self.anim = QComboBox()
        self.anim.setToolTip("Анимации из файла модели: по умолчанию модель стоит спокойно")
        self.anim.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.anim.setMinimumContentsLength(14)
        self.anim.currentIndexChanged.connect(lambda _i: set_animation(self.root, self.anim.currentData()))
        block("anim", section("АНИМАЦИЯ"), self.anim)
        block("light", section("СВЕТ"), self.env, self.sky)
        block("expo", ("Яркость", self.expo), ("Поворот неба", self.rot))
        block("info", section("СВЕДЕНИЯ"), self.info)
        pv.addStretch(1)
        btns = QHBoxLayout()
        for b in (shot, files, proj):
            btns.addWidget(b)
        pv.addLayout(btns)
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        # не уже самой панели: иначе правый край (повтор, метки) обрезан - гориз. прокрутки нет
        scroll.setMinimumWidth(
            max(320, panel.minimumSizeHint().width() + scroll.verticalScrollBar().sizeHint().width())
        )
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(mid)
        split.addWidget(scroll)
        split.setStretchFactor(1, 1)
        split.setSizes(self.cfg.get("ue_view_split", [210, 820, 320]))
        split.splitterMoved.connect(lambda *_: self.cfg.__setitem__("ue_view_split", split.sizes()))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.addWidget(split)

        for seq, fn in (
            ("Left", lambda: self.step(-1)),
            ("Right", lambda: self.step(1)),
            ("F", self.reset_view),
            ("Space", self.spin.toggle),
            ("W", self.wire.toggle),
            ("G", self.floor.toggle),
            ("Escape", self.close),
        ):
            key(seq, self, fn)

    # ------------------------------------------------------------ мелочи
    def slider(self, lo, hi, val, tip, fn):
        s = QSlider(Qt.Orientation.Horizontal, minimum=lo, maximum=hi, value=val)
        s.setToolTip(tip)
        s.valueChanged.connect(fn)
        return s

    def set(self, name, value):
        if self.root is not None:
            self.root.setProperty(name, value)

    def reset_view(self):
        if self.root is not None:
            self.root.resetView()

    def toggle_floor(self, v):
        self.cfg["ue_floor"] = v
        self.set("floor", v)

    # ------------------------------------------------------------ лента
    def fill_strip(self, current):
        """Те же ассеты, что сейчас во вкладке (раздел, поиск), только те, что можно посмотреть."""
        lst = [a for a in self.tab.chosen() if viewable(a)]
        if not any(a["dir"] == current["dir"] for a in lst):
            lst = [current] + lst
        if [a["dir"] for a in lst] == [a["dir"] for a in self.assets]:
            return
        self.assets = lst
        self.strip.blockSignals(True)
        self.strip.clear()
        for a in lst:
            it = QListWidgetItem(a.get("name", ""))
            prev = os.path.join(a["dir"], "preview.webp")
            if os.path.exists(prev):
                it.setIcon(QIcon(thumb(prev, 112)))
            it.setToolTip(f"{SHORT.get(a.get('kind'), '')}, {a.get('theme', '')}")
            self.strip.addItem(it)
        self.strip.blockSignals(False)
        self.strip_lbl.setText(f"{len(lst)} шт. - как во вкладке")

    def strip_pick(self, row):
        if 0 <= row < len(self.assets) and self.assets[row] is not self.asset:
            self.show_asset(self.assets[row], from_strip=True)

    def step(self, d):
        if not self.assets:
            return
        row = (self.strip.currentRow() + d) % len(self.assets)
        self.strip.setCurrentRow(row)

    # ------------------------------------------------------------ свет
    def hdris(self):
        """Скачанные HDRI для освещения: студийные первыми."""
        out = [a for a in self.tab.items if a.get("kind") == "hdri" and a.get("main")]
        return sorted(out, key=lambda a: (a.get("theme") != "Студия", a.get("name", "")))

    def fill_env(self):
        if self.env.count():
            return
        self.env.blockSignals(True)
        self.env.addItem(lib_icon("sun"), "Простой свет (без неба)", "")
        for a in self.hdris():
            prev = os.path.join(a["dir"], "preview.webp")
            icon = QIcon(thumb(prev, 48)) if os.path.exists(prev) else QIcon()
            self.env.addItem(icon, f"{a['name']}, {a.get('theme', '')}", os.path.join(a["dir"], a["main"][0]))
        saved = self.cfg.get("ue_env")
        i = self.env.findData(saved) if saved else -1
        self.env.setCurrentIndex(i if i >= 0 else (1 if self.env.count() > 1 else 0))
        self.env.blockSignals(False)

    def apply_env(self):
        if self.asset and self.asset.get("kind") != "hdri":
            path = self.env.currentData() or ""
            self.cfg["ue_env"] = path
            self.set("probe", url(path))

    # ------------------------------------------------------------ примерка текстуры на модель
    def fill_tryon(self):
        """Список для примерки: сначала подходящие этой модели (ткань для дивана, дерево для стола - по смыслу),
        потом все текстуры. Пересобирается для каждой модели."""
        model = self.asset or {}
        if self.tryon.count() and self.tryon.property("for") == model.get("dir"):
            return
        self.tryon.setProperty("for", model.get("dir"))
        self.tryon.blockSignals(True)
        self.tryon.clear()
        self.tryon.addItem(lib_icon("dice_3D"), "Родные материалы", None)
        order = ("Дом - ткани и кожа", "Дом - полы", "Дом - стены", "Дом - плитка и камень")
        tex = [a for a in self.tab.items if a.get("kind") == "tex"]
        tex.sort(key=lambda a: (order.index(a["theme"]) if a.get("theme") in order else 9, a.get("name", "")))
        fit = []
        sem = getattr(self.tab, "sem", None)
        if sem is not None and tex:
            from library import unreal_sem

            try:
                fit = unreal_sem.materials_for(sem, model.get("section") or U.home_section(model), tex)
            except Exception as e:
                log_error("viewer3d tryon: %r" % e)

        def add(a, suffix=""):
            prev = os.path.join(a["dir"], "preview.webp")
            icon = QIcon(thumb(prev, 48)) if os.path.exists(prev) else QIcon()
            self.tryon.addItem(icon, a.get("name", "") + suffix, a)

        for a in fit:
            add(a, "  - подходит")
        if fit:
            self.tryon.insertSeparator(self.tryon.count())
        for a in tex:
            add(a)
        self.tryon.setToolTip(
            "Надеть скачанную текстуру на всю модель. Сначала - подходящие ей по смыслу"
            + (f" ({model.get('section')})" if model.get("section") else "")
        )
        self.tryon.blockSignals(False)

    def apply_tryon(self):
        t = self.tryon.currentData()
        if not t or not self.asset or self.asset.get("kind") != "model":
            self.set("tryOn", False)
            return
        for k, v in materials(t).items():
            self.set(k, url(v) if k.endswith("Map") else v)
        self.set("tiling", float(self.try_tile.value()))
        self.set("heightAmount", 0.0)
        self.set("tryOn", False)  # заново - чтобы подхватить новые карты
        self.set("tryOn", True)

    # ------------------------------------------------------------ карты и развёртка
    def fill_maps(self, a):
        for b in self.map_group.buttons():
            self.map_group.removeButton(b)
            b.deleteLater()
        items = [("3D", "", None)] + map_list(a)
        for i, (label, path, ch) in enumerate(items):
            b = QPushButton(label, objectName="chip", checkable=True)
            b.setToolTip(
                "Материал на фигуре"
                if not path
                else os.path.basename(path) + ("" if ch is None else f" - канал {'RGB'[ch]}")
            )
            b.clicked.connect(lambda _c, lb=label, p=path, c=ch: self.show_map(lb, p, c))
            self.map_group.addButton(b)
            self.maps_l.addWidget(b, i // 2, i % 2)
            if i == 0:
                b.setChecked(True)

    def show_map(self, label, path, ch):
        if not path:
            self.set("flat", QUrl())
            return
        try:
            src = channel(path, ch) if ch is not None else path
        except Exception as e:
            log_error("viewer3d map: %r" % e)
            src = path
        self.set("flatTile", True)
        self.set("flatTitle", f"{label} - {os.path.basename(path)}")
        self.set("flat", url(src))

    def toggle_unwrap(self, v):
        prev = os.path.join(self.asset["dir"], "preview.webp") if self.asset else ""
        if v and os.path.exists(prev):
            self.set("flatTile", False)
            self.set("flatTitle", "Развёртка (превью) - сама панорама в файле .hdr")
            self.set("flat", url(prev))
        else:
            self.set("flat", QUrl())

    # ------------------------------------------------------------ показать
    def show_asset(self, a, from_strip=False):
        if self.root is None:
            return False
        self.asset = a
        kind = a.get("kind")
        if not from_strip:
            self.fill_strip(a)
            for i, x in enumerate(self.assets):
                if x["dir"] == a["dir"]:
                    self.strip.blockSignals(True)
                    self.strip.setCurrentRow(i)
                    self.strip.blockSignals(False)
        self.title.setText(a.get("name", ""))
        self.sub.setText("   " + " / ".join(b for b in (U.KINDS.get(kind, ("", ""))[1], a.get("theme", "")) if b))
        vis = {
            "view": kind != "hdri",
            "tex": kind == "tex",
            "hdri": kind == "hdri",
            "light": kind != "hdri",
            "expo": True,
            "info": True,
            "try": kind == "model",
            "anim": False,  # покажется, когда у загруженной модели найдутся анимации
        }
        for name, w in self.blocks.items():
            w.setVisible(vis[name])
        self.unwrap.blockSignals(True)
        self.unwrap.setChecked(False)
        self.unwrap.blockSignals(False)
        if kind != "hdri":
            self.fill_env()
        load_scene(self.root, a, self.env.currentData() or "", self.sky.isChecked())
        if kind == "tex":
            self.fill_maps(a)
            self.set("tryOn", False)
        if kind == "model":
            self.fill_tryon()
            self.apply_tryon()
            when_loaded(self.root, self.fill_anims)
        self.update_info()
        self.reset_view()
        self.show()
        self.raise_()
        self.activateWindow()
        return True

    def fill_anims(self):
        """Модель загрузилась: все анимации стоп, список - в выбор (если они есть)."""
        names = set_animation(self.root)
        self.anim.blockSignals(True)
        self.anim.clear()
        self.anim.addItem("Без анимации (поза покоя)", None)
        for n in names:
            self.anim.addItem(n, n)
        self.anim.blockSignals(False)
        self.blocks["anim"].setVisible(bool(names))

    def update_info(self):
        a = self.asset
        if not a:
            return
        rows = []
        if a.get("res"):
            rows.append(f"Разрешение: {a['res'].upper()}")
        rows.append(f"Вес: {human(a.get('size', 0))}")
        if a.get("polycount"):
            rows.append("Полигонов: " + f"{a['polycount']:,}".replace(",", " "))
        if a.get("dimensions_mm"):
            rows.append("Размер: " + " x ".join(f"{x / 10:g}" for x in a["dimensions_mm"]) + " см")
        elif self.root is not None and self.root.property("sizeText"):
            rows.append(f"Габариты: {self.root.property('sizeText')} (единицы файла)")
        if a.get("description"):
            rows.append(esc(a["description"]))
        src = a.get("source", "")
        authors = [x for x in a.get("authors", []) if x != src]
        if authors:
            src += ", " + ", ".join(authors)
        src = esc(src)
        if a.get("url"):
            src = f'<a href="{esc(a["url"])}" style="color:{C["acc"]}">{src}</a>'
        rows.append(src)
        rows.append("Лицензия: CC0" if U.is_cc0(a) else "Лицензия: " + esc(a.get("license", "")))
        if a.get("tags"):
            rows.append("Метки: " + esc(", ".join(a["tags"][:12])))
        # имя файла без пробелов не переносится и раздвигает панель - по одному в строку, длинные с многоточием
        names = [os.path.basename(m) for m in a.get("main", [])]
        rows.append("Файлы:<br>" + "<br>".join(esc(n if len(n) <= 34 else n[:16] + "..." + n[-15:]) for n in names))
        how = U.howto(a)
        if how:
            rows.append(f"<br><b>Как в Unreal.</b> {esc(how)}")
        self.info.setText("<br>".join(r for r in rows if r))

    # ------------------------------------------------------------ кнопки
    def screenshot(self):
        if not self.asset:
            return
        start = os.path.join(
            self.cfg.get("ue_shots", os.path.expanduser("~/Pictures")), f"{self.asset.get('name', 'asset')}.png"
        )
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить снимок", start, "PNG (*.png)")
        if not path:
            return
        self.cfg["ue_shots"] = os.path.dirname(path)
        self.quick.grabFramebuffer().save(path, "PNG")
        self.tab.win.say(f"Снимок сохранён: {os.path.basename(path)}")

    def to_project(self):
        if self.asset:
            self.tab.copy_to_project([self.asset])

    def closeEvent(self, e):
        self.cfg["ue_view_size"] = [self.width(), self.height()]
        self.set("spin", False)
        super().closeEvent(e)
