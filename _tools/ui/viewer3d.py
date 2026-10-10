"""Окно 3D-просмотра ассетов Unreal на Qt Quick 3D (сцена - viewer3d.qml).
Слева лента ассетов текущего раздела вкладки (стрелки - соседний), в середине сцена, справа - вид, свет,
карты текстуры и сведения. Модель - FBX через assimp, текстура - PBR-материал на шаре, кубе или плоскости,
HDRI - панорама изнутри. Мышь: тянуть - вращать, колесо - ближе/дальше (у HDRI - угол обзора), правая - сдвиг."""

import hashlib
import os
from html import escape as esc  # сведения - rich text: имена и метки с сайта не должны стать разметкой

from PIL import Image
from PyQt6.QtCore import QObject, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QPixmap, QQuaternion
from PyQt6.QtQml import QQmlProperty
from PyQt6.QtQuickWidgets import QQuickWidget
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from ui.animations import MOTION
from ui.common import HERE, log_error
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


def checker():
    """Шахматка для проверки развёртки: клетки 8x8 разных оттенков по строкам и подписи A1..H8 -
    видно растяжение, швы и перевёрнутые куски UV."""
    dst = os.path.join(CACHE, "uv_checker_v1.png")
    if os.path.exists(dst):
        return dst
    from PIL import ImageDraw, ImageFont

    n, cell = 8, 128
    im = Image.new("RGB", (n * cell, n * cell))
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=34)
    hues = ["#e5484d", "#f08c3a", "#f2c94c", "#4cb782", "#3fb6c9", "#5b7cff", "#9b6bff", "#e05fb0"]
    for y in range(n):
        base = Image.new("RGB", (1, 1), hues[y]).getpixel((0, 0))
        for x in range(n):
            k = 1.0 if (x + y) % 2 else 0.55
            col = tuple(int(c * k) for c in base)
            d.rectangle([x * cell, y * cell, (x + 1) * cell - 1, (y + 1) * cell - 1], fill=col)
            d.text((x * cell + 12, y * cell + 10), f"{'ABCDEFGH'[x]}{y + 1}", fill=(255, 255, 255), font=font)
            d.line([x * cell + 12, y * cell + 54, x * cell + 60, y * cell + 54], fill=(255, 255, 255), width=4)
    os.makedirs(CACHE, exist_ok=True)
    im.save(dst + ".tmp.png")
    os.replace(dst + ".tmp.png", dst)
    return dst


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


def set_speed(root, k):
    """Скорость анимаций (1 - как в файле): длительность каждой - от исходной, запомненной при первом вызове."""
    for _n, _tl, an in animations(root):
        base = an.property("libDuration")
        if not base:
            base = an.property("duration")
            an.setProperty("libDuration", base)
        running = an.property("running")
        if running:
            an.setProperty("running", False)
        an.setProperty("duration", max(1, int(base / max(0.05, k))))
        if running:
            an.setProperty("running", True)


def refit(root):
    """Подогнать модель под кадр заново, когда она точно загружена: при смене модели первая подгонка
    могла взять рамку прошлой (статус загрузчика ещё «готово») - модель выходила мелкой."""
    if root.property("mode") == "model":
        root.setProperty("fitted", False)
        root.fit()


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
        self.root.setProperty("smooth", MOTION["on"])

    def show_asset(self, a, probe):
        if self.root is None:
            return False
        if self.shown != a["dir"]:
            self.shown = a["dir"]
            load_scene(self.root, a, probe)
            # в панели модель не дёргается; подгонка - по позе покоя
            when_loaded(self.root, lambda: (set_animation(self.root), refit(self.root)))
        return True

    def pause(self, on):
        """Спрятанная панель не крутит модель зря."""
        if self.root is not None:
            self.root.setProperty("spin", not on)


def section(text):
    return QLabel(text, objectName="sect")


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
            self.root.setProperty("smooth", MOTION["on"])
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

        # --- верх: соседние и счёт; имя и раздел - крупно поверх сцены (viewer3d.qml)
        self.prev_b = QPushButton(lib_icon("arrowLeft"), "", objectName="tool")
        self.prev_b.setToolTip("Предыдущий (стрелка влево)")
        self.prev_b.clicked.connect(lambda: self.step(-1))
        self.next_b = QPushButton(lib_icon("arrowRight"), "", objectName="tool")
        self.next_b.setToolTip("Следующий (стрелка вправо)")
        self.next_b.clicked.connect(lambda: self.step(1))
        self.counter = QLabel(objectName="dim")
        hint = QLabel(
            "Тянуть - вращать, колесо - ближе, правая кнопка - сдвиг, стрелки - соседний ассет",
            objectName="faint",
        )
        top = QHBoxLayout()
        top.addWidget(self.prev_b)
        top.addWidget(self.next_b)
        top.addSpacing(6)
        top.addWidget(self.counter)
        top.addStretch(1)
        top.addWidget(hint)

        # --- плавающая панель поверх сцены: вид, вращение, каркас, пол, человек, снимок
        self.hud = QFrame(self.quick, objectName="hud")
        hl = QHBoxLayout(self.hud)
        hl.setContentsMargins(8, 6, 8, 6)
        hl.setSpacing(4)

        def hud_btn(icon, tip, checkable=False):
            b = QPushButton(lib_icon(icon), "", objectName="hudb", checkable=checkable)
            b.setToolTip(tip)
            b.setIconSize(QSize(20, 20))
            hl.addWidget(b)
            return b

        self.reset_b = hud_btn("arrow_counterclockwise", "Вид заново (F)")
        self.reset_b.clicked.connect(self.reset_view)
        self.spin = hud_btn("rotate_horizontal_up", "Вращать, как на подставке (Пробел)", True)
        self.spin.toggled.connect(lambda v: self.set("spin", v))
        self.wire = hud_btn("menuGrid", "Каркас - сетка полигонов (W)", True)
        self.wire.toggled.connect(lambda v: self.set("wire", v))
        self.floor = hud_btn("card", "Подиум, тень и сетка (G)", True)
        self.floor.setChecked(self.cfg.get("ue_floor", True))
        self.floor.toggled.connect(self.toggle_floor)
        self.set("floor", self.floor.isChecked())
        self.human = hud_btn("user-silhouette", "Человек 180 см рядом - сравнить размер (H)", True)
        self.human.setChecked(self.cfg.get("ue_human", False))
        self.human.toggled.connect(self.toggle_human)
        sep = QFrame(objectName="vline")
        sep.setFixedWidth(1)
        hl.addWidget(sep)
        self.shot_b = hud_btn("camera", "Снимок того, что видно сейчас")
        self.shot_b.clicked.connect(self.screenshot)
        self.quick.installEventFilter(self)

        # --- шкала анимации под сценой
        self.tl = None  # (Timeline, TimelineAnimation) играющей анимации
        self.play_b = QPushButton(objectName="tool")
        self.play_b.setToolTip("Пауза / играть")
        self.play_b.clicked.connect(self.toggle_play)
        self.frame_s = QSlider(Qt.Orientation.Horizontal)
        self.frame_s.setToolTip("Кадр анимации - тянуть, чтобы посмотреть по кадрам")
        self.frame_s.sliderMoved.connect(self.scrub)
        self.frame_lbl = QLabel(objectName="dim")
        self.frame_lbl.setMinimumWidth(70)
        self.speed_c = QComboBox()
        for t, v in (("x0.25", 0.25), ("x0.5", 0.5), ("x1", 1.0), ("x1.5", 1.5), ("x2", 2.0)):
            self.speed_c.addItem(t, v)
        self.speed_c.setCurrentIndex(2)
        self.speed_c.setToolTip("Скорость анимации")
        self.speed_c.currentIndexChanged.connect(lambda _i: self.anim_speed())
        self.timeline = QFrame(objectName="spec")
        tlay = QHBoxLayout(self.timeline)
        tlay.setContentsMargins(8, 4, 10, 4)
        self.tl_name = QLabel(objectName="statk")
        for w in (self.play_b, self.tl_name):
            tlay.addWidget(w)
        tlay.addWidget(self.frame_s, 1)
        tlay.addWidget(self.frame_lbl)
        tlay.addWidget(self.speed_c)
        self.timeline.hide()
        self.tick = QTimer(self, interval=40)
        self.tick.timeout.connect(self.follow_frame)

        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addLayout(top)
        mv.addWidget(self.quick, 1)
        mv.addWidget(self.timeline)

        # --- панель справа
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
        from ui.unreal_panel import AssetCard

        self.info = AssetCard(compact=True)
        self.info.anim_clicked.connect(self.pick_anim)
        self.info.tag_clicked.connect(lambda t: (self.tab.q.setText(t), self.tab.win.raise_()))
        self.info.said.connect(lambda s: self.tab.win.say(s))
        self.how = QLabel(objectName="dim", wordWrap=True)
        self.how.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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

        block(
            "tex",
            section("ФИГУРА"),
            (self.shape, self.tiling),
            ("Рельеф", self.height_s),
            section("КАРТЫ - ПОСМОТРЕТЬ ОТДЕЛЬНО"),
            self.maps,
        )
        block("hdri", section("ПАНОРАМА"), self.balls, self.unwrap)
        self.build_tryon()
        block(
            "try",
            section("ПРИМЕРИТЬ ТЕКСТУРУ"),
            self.try_find,
            self.try_chips,
            self.tryon,
            self.parts_lbl,
            self.parts,
            (self.try_tile, self.try_rot),
            (self.try_tint, self.try_cmp),
            ("Блеск", self.try_gloss),
        )
        self.anim = QComboBox()
        self.anim.setToolTip("Анимации из файла модели: по умолчанию модель стоит спокойно")
        self.anim.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.anim.setMinimumContentsLength(14)
        self.anim.currentIndexChanged.connect(self.play_anim)
        self.want_anim = None  # анимация, которую просили сыграть сразу после загрузки (щелчок в панели)
        block("anim", section("АНИМАЦИЯ"), self.anim)
        block("light", section("СВЕТ"), self.env, self.sky)
        block("expo", ("Яркость", self.expo), ("Поворот неба", self.rot))
        block("info", section("СВЕДЕНИЯ"), self.info, self.how)
        pv.addStretch(1)
        btns = QHBoxLayout()
        for b in (files, proj):
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
            ("H", self.human.toggle),
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

    def toggle_human(self, v):
        self.cfg["ue_human"] = v
        self.set("showHuman", v)

    def human_height(self, a):
        """Рост человека 180 см в единицах сцены: модель вписана в 200 по большей стороне, а её размер
        в см известен (dims_cm из FBX или размеры с сайта). Нет размера - 0 (кнопка неактивна)."""
        from ui.unreal_panel import HUMAN_CM, dims_cm

        d = dims_cm(a) if a.get("kind") == "model" else None
        return HUMAN_CM * 200 / max(d) if d and max(d) > 0 else 0.0

    def eventFilter(self, obj, e):
        if obj is self.quick and e.type() == e.Type.Resize:
            self.place_hud()
        parts = getattr(self, "parts", None)  # фильтр ставится раньше, чем создан список деталей
        if parts is not None and obj is parts.viewport() and e.type() == e.Type.Leave:  # мышь ушла со списка
            self.set("flashPart", -1)
        return super().eventFilter(obj, e)

    def place_hud(self):
        """Плавающая панель - по центру внизу сцены."""
        self.hud.adjustSize()
        self.hud.move((self.quick.width() - self.hud.width()) // 2, self.quick.height() - self.hud.height() - 14)
        self.hud.raise_()

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
        self.strip_lbl.setText(f"ТАКИЕ ЖЕ, КАК ВО ВКЛАДКЕ: {len(lst)}")

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
    # ------------------------------------------------------------ примерка текстуры
    TRY_KINDS = (
        ("fit", "Подходит", ""),
        ("all", "Все", ""),
        (
            "fabric",
            "Ткани",
            "fabric leather carpet linen wool velvet cloth jacquard denim cotton knit fleece corduroy rug",
        ),
        ("wood", "Дерево", "wood wooden plank planks parquet oak bark laminate timber"),
        ("stone", "Камень", "stone rock marble tile tiles brick bricks concrete granite cobblestone plaster terrazzo"),
        ("metal", "Металл", "metal rust rusty iron steel corrugated aluminium copper brass"),
    )

    def build_tryon(self):
        """Примерка: поиск, фильтр по материалу, сетка превью, детали модели, повтор, поворот, оттенок, блеск."""
        from ui.widgets import Flow

        self.try_find = QLineEdit(placeholderText="Найти текстуру: дуб, бархат, мрамор...")
        self.try_find.setClearButtonEnabled(True)
        self.try_find.textChanged.connect(self.filter_tryon)
        self.try_chips = QWidget()
        flow = Flow(self.try_chips, 4)
        self.try_kind = QButtonGroup(self)
        self.try_kind.setExclusive(True)
        for kind, text, _w in self.TRY_KINDS:
            b = QPushButton(text, objectName="chip", checkable=True)
            b.setProperty("key", kind)
            self.try_kind.addButton(b)
            flow.addWidget(b)
        self.try_kind.buttons()[1].setChecked(True)
        self.try_kind.buttonClicked.connect(lambda _b: self.filter_tryon())
        self.tryon = QListWidget()
        self.tryon.setViewMode(QListWidget.ViewMode.IconMode)
        self.tryon.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.tryon.setMovement(QListWidget.Movement.Static)
        self.tryon.setIconSize(QSize(52, 52))
        self.tryon.setGridSize(QSize(80, 96))
        self.tryon.setWordWrap(True)
        self.tryon.setUniformItemSizes(True)
        self.tryon.setFixedHeight(214)
        self.tryon.setToolTip("Щелчок - надеть на модель; сначала - подходящие ей по смыслу")
        self.tryon.currentItemChanged.connect(lambda *_: self.apply_tryon())
        self.parts_lbl = QLabel("Детали: на что надеть", objectName="dim")
        self.parts = QListWidget()
        self.parts.setMaximumHeight(124)
        self.parts.setMouseTracking(True)
        self.parts.setToolTip("Снимите галочку - деталь останется в родном материале; наведение - подсветка детали")
        self.parts.itemChanged.connect(lambda _it: self.apply_mask())
        self.parts.itemEntered.connect(lambda it: self.set("flashPart", self.parts.row(it)))
        self.parts.viewport().installEventFilter(self)
        self.try_tile = QDoubleSpinBox(minimum=0.25, maximum=16, value=2, singleStep=0.25, prefix="Повтор x")
        self.try_tile.setDecimals(2)
        self.try_tile.setToolTip("Сколько раз рисунок повторяется на детали")
        self.try_tile.valueChanged.connect(lambda v: (self.set("tiling", float(v)), self.save_tryon()))
        self.try_rot = QSpinBox(minimum=0, maximum=345, singleStep=15, suffix="°", wrapping=True)
        self.try_rot.setToolTip("Повернуть рисунок: доски вдоль, а не поперёк")
        self.try_rot.valueChanged.connect(lambda v: (self.set("uvRotation", float(v)), self.save_tryon()))
        self.try_tint = QPushButton(lib_icon("color-palette"), "Оттенок")
        self.try_tint.setToolTip("Подкрасить текстуру; правый щелчок - без оттенка")
        self.try_tint.clicked.connect(self.pick_tint)
        self.try_tint.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.try_tint.customContextMenuRequested.connect(lambda _p: self.set_tint("#ffffff"))
        self.try_cmp = QPushButton(lib_icon("eye"), "Было")
        self.try_cmp.setToolTip("Держите - родные материалы, отпустите - примерка")
        self.try_cmp.pressed.connect(lambda: self.set("tryOn", False))
        self.try_cmp.released.connect(lambda: self.set("tryOn", self.tryon_data() is not None))
        self.try_gloss = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=90, value=0)
        self.try_gloss.setToolTip("Глянец: 0 - как в карте шероховатости, дальше - глаже и с бликами")
        self.try_gloss.valueChanged.connect(lambda v: (self.set("roughAmount", 1 - v / 100), self.save_tryon()))
        self.tint = "#ffffff"
        self.try_restoring = False

    def tryon_data(self):
        it = self.tryon.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def fill_tryon(self):
        """Сетка для примерки: родные, шахматка, подходящие этой модели по смыслу, потом все текстуры."""
        model = self.asset or {}
        if self.tryon.count() and self.tryon.property("for") == model.get("dir"):
            return
        self.tryon.setProperty("for", model.get("dir"))
        self.tryon.blockSignals(True)
        self.tryon.clear()
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
        self.try_fit = {a["dir"] for a in fit}

        def add(icon, text, data, tip=""):
            it = QListWidgetItem(icon, text)
            it.setData(Qt.ItemDataRole.UserRole, data)
            it.setToolTip(tip or text)
            it.setSizeHint(QSize(80, 96))
            self.tryon.addItem(it)

        add(lib_icon("dice_3D"), "Родные", None, "Родные материалы модели")
        add(lib_icon("menuGrid"), "Шахматка", "checker", "Шахматка - проверить развёртку UV")
        for a in fit + [x for x in tex if x["dir"] not in self.try_fit]:
            prev = os.path.join(a["dir"], "preview.webp")
            icon = QIcon(thumb(prev, 52)) if os.path.exists(prev) else QIcon()
            tip = a.get("name", "") + ("  - подходит этой модели" if a["dir"] in self.try_fit else "")
            add(icon, a.get("name", ""), a, tip)
        self.tryon.setCurrentRow(0)
        self.tryon.blockSignals(False)
        self.filter_tryon()

    def filter_tryon(self):
        """Поиск и фильтр по материалу; «Родные» и «Шахматка» видны всегда."""
        q = self.try_find.text().strip().lower().replace("ё", "е")
        b = self.try_kind.checkedButton()
        key = b.property("key") if b else "all"
        words = set(dict((k, w) for k, _t, w in self.TRY_KINDS).get(key, "").split())
        fit = getattr(self, "try_fit", set())
        for i in range(self.tryon.count()):
            it = self.tryon.item(i)
            a = it.data(Qt.ItemDataRole.UserRole)
            if not isinstance(a, dict):
                it.setHidden(False)
                continue
            hay = " ".join([a.get("name", ""), a.get("theme", ""), *a.get("tags", [])]).lower()
            ok = (not q or q in hay) and (
                key == "all" or (key == "fit" and a["dir"] in fit) or bool(words & set(hay.replace(",", " ").split()))
            )
            it.setHidden(not ok)

    def apply_tryon(self):
        t = self.tryon_data()
        for w in (self.try_tile, self.try_rot, self.try_tint, self.try_cmp, self.try_gloss, self.parts):
            w.setEnabled(t is not None)
        if t is None or not self.asset or self.asset.get("kind") != "model":
            self.set("tryOn", False)
            self.save_tryon()
            return
        if t == "checker":
            mats = {k: "" for k in ("normalMap", "roughMap", "metalMap", "aoMap", "heightMap")}
            mats["baseMap"] = checker()
        else:
            mats = materials(t)
        for k, v in mats.items():
            self.set(k, url(v) if k.endswith("Map") else v)
        self.set("tiling", float(self.try_tile.value()))
        self.set("uvRotation", float(self.try_rot.value()))
        self.set("roughAmount", 1 - self.try_gloss.value() / 100)
        self.set("tint", QColor(self.tint))
        self.set("heightAmount", 0.0)
        self.set("tryOn", False)  # заново - чтобы подхватить новые карты
        self.set("tryOn", True)
        self.save_tryon()

    # --- детали модели (разные материалы): галочки - на что надеть
    def fill_parts(self):
        parts = self.root.property("parts") if self.root is not None else None
        if hasattr(parts, "toVariant"):
            parts = parts.toVariant()
        parts = list(parts or [])
        self.parts.blockSignals(True)
        self.parts.clear()
        for p in parts:
            name = str(p.get("name", "")) if isinstance(p, dict) else str(p)
            n = int(p.get("count", 1)) if isinstance(p, dict) else 1
            it = QListWidgetItem(name + (f"  ({n} шт.)" if n > 1 else ""))
            it.setData(Qt.ItemDataRole.UserRole, name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.parts.addItem(it)
        self.parts.blockSignals(False)
        many = len(parts) > 1
        self.parts.setVisible(many)
        self.parts_lbl.setVisible(many)
        saved = self.cfg.get("ue_tryon", {}).get((self.asset or {}).get("dir", ""), {})
        if many and saved.get("off"):
            self.parts.blockSignals(True)
            for i in range(self.parts.count()):
                if self.parts.item(i).data(Qt.ItemDataRole.UserRole) in saved["off"]:
                    self.parts.item(i).setCheckState(Qt.CheckState.Unchecked)
            self.parts.blockSignals(False)
        self.apply_mask()

    def apply_mask(self):
        on = [i for i in range(self.parts.count()) if self.parts.item(i).checkState() == Qt.CheckState.Checked]
        all_on = len(on) == self.parts.count()
        self.set("tryMask", [] if all_on else (on or [-1]))  # ни одной - не надевать никуда
        self.save_tryon()

    def pick_tint(self):
        from PyQt6.QtWidgets import QColorDialog

        c = QColorDialog.getColor(QColor(self.tint), self, "Оттенок текстуры")
        if c.isValid():
            self.set_tint(c.name())

    def set_tint(self, color):
        self.tint = color
        pm = QPixmap(14, 14)
        pm.fill(QColor(color))
        self.try_tint.setIcon(QIcon(pm) if color.lower() != "#ffffff" else lib_icon("color-palette"))
        self.set("tint", QColor(color))
        self.save_tryon()

    def save_tryon(self):
        """Примерка запоминается для каждой модели: открыли снова - та же текстура, детали и настройки."""
        if self.try_restoring or not self.asset or self.asset.get("kind") != "model":
            return
        store = self.cfg.setdefault("ue_tryon", {})
        t = self.tryon_data()
        if t is None:
            store.pop(self.asset["dir"], None)
            return
        off = [
            self.parts.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.parts.count())
            if self.parts.item(i).checkState() != Qt.CheckState.Checked
        ]
        store[self.asset["dir"]] = {
            "tex": "checker" if t == "checker" else t["dir"],
            "off": off,
            "tiling": self.try_tile.value(),
            "rot": self.try_rot.value(),
            "tint": self.tint,
            "gloss": self.try_gloss.value(),
        }

    def restore_tryon(self):
        """Прошлая примерка этой модели (до загрузки - текстура и настройки, детали - после)."""
        saved = self.cfg.get("ue_tryon", {}).get(self.asset["dir"])
        self.try_restoring = True
        try:
            self.try_tile.setValue(saved.get("tiling", 2) if saved else 2)
            self.try_rot.setValue(saved.get("rot", 0) if saved else 0)
            self.try_gloss.setValue(saved.get("gloss", 0) if saved else 0)
            self.set_tint(saved.get("tint", "#ffffff") if saved else "#ffffff")
            row = 0
            if saved:
                for i in range(self.tryon.count()):
                    d = self.tryon.item(i).data(Qt.ItemDataRole.UserRole)
                    if d == saved["tex"] or (isinstance(d, dict) and d["dir"] == saved["tex"]):
                        row = i
                        break
            self.tryon.blockSignals(True)
            self.tryon.setCurrentRow(row)
            self.tryon.blockSignals(False)
        finally:
            self.try_restoring = False

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
    def show_asset(self, a, from_strip=False, anim=None):
        if self.root is None:
            return False
        if anim and self.asset is not None and self.asset["dir"] == a["dir"] and self.anim.count() > 1:
            self.pick_anim(anim)  # модель уже открыта - только включить анимацию
            self.show()
            self.raise_()
            self.activateWindow()
            return True
        self.asset = a
        kind = a.get("kind")
        if not from_strip:
            self.fill_strip(a)
            for i, x in enumerate(self.assets):
                if x["dir"] == a["dir"]:
                    self.strip.blockSignals(True)
                    self.strip.setCurrentRow(i)
                    self.strip.blockSignals(False)
        self.set("title", a.get("name", ""))
        self.set("subtitle", "  /  ".join(b for b in (U.KINDS.get(kind, ("", ""))[1], a.get("theme", "")) if b))
        row = next((i for i, x in enumerate(self.assets) if x["dir"] == a["dir"]), -1)
        self.counter.setText(f"{row + 1} из {len(self.assets)}" if row >= 0 else "")
        hh = self.human_height(a)
        self.set("humanHeight", hh)
        self.human.setEnabled(hh > 0)
        self.human.setToolTip(
            "Человек 180 см рядом - сравнить размер (H)" if hh > 0 else "Размер модели в сантиметрах неизвестен"
        )
        self.set("showHuman", self.human.isChecked() and hh > 0)
        for b in (self.spin, self.wire, self.floor, self.human):
            b.setVisible(kind != "hdri")
        self.place_hud()
        self.stop_timeline()
        vis = {
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
            for k, v in (("tint", QColor("#ffffff")), ("uvRotation", 0.0), ("roughAmount", 1.0), ("tryMask", [])):
                self.set(k, v)  # у текстуры на шаре - без настроек примерки
        if kind == "model":
            self.set("tryMask", [])
            self.set("flashPart", -1)
            self.fill_tryon()
            self.restore_tryon()
            self.apply_tryon()
            when_loaded(self.root, self.fill_parts)
            self.want_anim = anim
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
        refit(self.root)
        self.anim.blockSignals(True)
        self.anim.clear()
        self.anim.addItem("Без анимации (поза покоя)", None)
        for n in names:
            self.anim.addItem(n, n)
        self.anim.blockSignals(False)
        self.blocks["anim"].setVisible(bool(names))
        want, self.want_anim = self.want_anim, None
        if want and self.anim.findData(want) > 0:
            self.anim.setCurrentIndex(self.anim.findData(want))

    def pick_anim(self, name):
        """Щелчок по анимации в сведениях: выбрать её в списке (там же она и заиграет)."""
        i = self.anim.findData(name)
        if i > 0:
            self.anim.setCurrentIndex(i)

    def play_anim(self, _i=0):
        name = self.anim.currentData()
        set_animation(self.root, name)
        self.anim_speed()
        self.stop_timeline()
        pick = next(((tl, an) for n, tl, an in animations(self.root) if n == name), None) if name else None
        if pick is None:
            return
        self.tl = pick
        tl = pick[0]
        lo, hi = int(tl.property("startFrame") or 0), int(tl.property("endFrame") or 0)
        self.frame_s.setRange(lo, max(lo + 1, hi))
        self.tl_name.setText(name.upper())
        self.timeline.show()
        self.play_icons(True)
        self.tick.start()

    def stop_timeline(self):
        self.tick.stop()
        self.tl = None
        self.timeline.hide()

    def play_icons(self, playing):
        from ui.unreal_panel import play_icon

        self.play_b.setIcon(lib_icon("pause") if playing else play_icon(C["acc"]))

    def toggle_play(self):
        if self.tl is None:
            return
        an = self.tl[1]
        paused = bool(an.property("paused")) or not an.property("running")
        if not an.property("running"):
            an.setProperty("running", True)
        an.setProperty("paused", not paused)
        self.play_icons(paused)

    def scrub(self, frame):
        """Тянут шкалу: анимация на паузе, кадр - с ползунка."""
        if self.tl is None:
            return
        tl, an = self.tl
        if not an.property("paused"):
            an.setProperty("paused", True)
            self.play_icons(False)
        tl.setProperty("currentFrame", float(frame))
        self.frame_lbl.setText(f"кадр {frame}")

    def follow_frame(self):
        if self.tl is None or self.frame_s.isSliderDown():
            return
        f = self.tl[0].property("currentFrame") or 0
        self.frame_s.setValue(int(f))
        self.frame_lbl.setText(f"кадр {int(f)}")

    def anim_speed(self):
        if self.root is not None:
            set_speed(self.root, self.speed_c.currentData() or 1.0)

    def update_info(self):
        a = self.asset
        if not a:
            return
        size = self.root.property("sizeText") if self.root is not None else ""
        self.info.show_asset(a, size_text=size or "")
        # имя файла без пробелов не переносится и раздвигает панель - по одному в строку, длинные с многоточием
        names = [os.path.basename(m) for m in a.get("main", [])]
        rows = ["<b>Файлы</b><br>" + "<br>".join(esc(n if len(n) <= 34 else n[:16] + "..." + n[-15:]) for n in names)]
        how = U.howto(a)
        if how:
            rows.append(f"<b>Как в Unreal.</b> {esc(how)}")
        self.how.setText("<br><br>".join(rows))

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
