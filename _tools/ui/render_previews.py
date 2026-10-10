"""Превью для моделей без картинки (Quaternius отдаёт только FBX): модель рисуется той же сценой, что и
3D-просмотр (viewer3d.qml), без фона и пола, под студийным HDRI, снимок обрезается по краям -> preview.webp.

Окно не нужно: cli.py unreal previews; вкладка «Unreal» досчитывает недостающие сама, по одной, в фоне."""

import os

from PIL import Image
from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtQuickWidgets import QQuickWidget

from ui.common import log_error
from ui.viewer3d import QML, load_scene

SIDE = 512


def needs_preview(a):
    if a.get("kind") != "model" or a.get("_np"):  # _np - уже не вышло (preview.none), не пробовать снова
        return False
    if "_pt" in a:  # из обхода assets()
        return not a["_pt"]
    d = a["dir"]
    return not os.path.exists(os.path.join(d, "preview.webp")) and not os.path.exists(os.path.join(d, NONE))


NONE = "preview.none"  # метка «превью не рисуется» (плоская стена в профиль, пустой FBX)


def give_up(a):
    try:
        open(os.path.join(a["dir"], NONE), "w").close()
    except OSError:
        pass


def touches_edge(img: QImage, pad=3):
    """Непрозрачное у края кадра - значит, модель обрезана."""
    im = to_pil(img)
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    return bool(box) and (box[0] <= pad or box[1] <= pad or box[2] >= im.width - pad or box[3] >= im.height - pad)


def to_pil(img: QImage):
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return Image.frombuffer(
        "RGBA", (img.width(), img.height()), bytes(ptr), "raw", "RGBA", img.bytesPerLine(), 1
    ).copy()


def save_preview(img: QImage, dst):
    """Снимок -> обрезка по непрозрачному с полями -> квадрат SIDE с прозрачным фоном."""
    im = to_pil(img)
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        raise ValueError("пустой кадр")
    im = im.crop(box)
    k = SIDE * 0.86 / max(im.size)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 0))
    out.alpha_composite(im, ((SIDE - im.width) // 2, (SIDE - im.height) // 2))
    out.save(os.path.join(dst, "preview.webp"), quality=90)


class PreviewRenderer(QObject):
    """Рисует превью по очереди: run(assets, probe). Сигналы: one(ассет, ок), done(сколько вышло)."""

    one = pyqtSignal(object, bool)
    done = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QQuickWidget()
        self.view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.view.setClearColor(Qt.GlobalColor.transparent)
        self.view.resize(900, 900)
        self.view.setSource(QUrl.fromLocalFile(QML))
        self.root = self.view.rootObject()
        if self.root is not None:
            for k, v in (("plain", True), ("floor", False), ("spin", False), ("exposure", 1.5)):
                self.root.setProperty(k, v)
        self.queue, self.ok, self.probe, self.wait = [], 0, "", 0
        self.timer = QTimer(self, interval=100)
        self.timer.timeout.connect(self.poll)

    def run(self, assets, probe=""):
        if self.root is None:
            log_error("render_previews: сцена не открылась")
            self.done.emit(0)
            return
        self.queue, self.ok, self.probe = list(assets), 0, probe
        self.view.show()
        self.next()

    def next(self):
        if not self.queue:
            self.timer.stop()
            self.view.hide()
            self.done.emit(self.ok)
            return
        self.cur = self.queue.pop(0)
        self.wait, self.tries = 0, 0
        self.root.setProperty("camScale", 1.35)
        load_scene(self.root, self.cur, self.probe)
        # взгляд чуть сверху и сбоку - как на карточках Kenney
        self.timer.start()

    def poll(self):
        self.wait += 1
        status = self.root.property("status") or ""
        if status or self.wait > 120:  # не открылась или 12 с без ответа
            log_error(f"render_previews: {self.cur.get('name')}: {status or 'нет ответа'}")
            give_up(self.cur)
            self.one.emit(self.cur, False)
            self.timer.stop()
            QTimer.singleShot(0, self.next)
            return
        if not self.root.property("fitted") or self.wait < 4:  # пара кадров после подгонки
            return
        img = self.view.grabFramebuffer()
        if touches_edge(img) and self.tries < 4:  # модель вылезла за кадр - отъехать и снять заново
            self.tries += 1
            self.root.setProperty("camScale", 1.35 * 1.5**self.tries)
            self.root.resetView()
            self.wait = 0
            return
        self.timer.stop()
        try:
            save_preview(img, self.cur["dir"])
            self.ok += 1
            self.one.emit(self.cur, True)
        except Exception as e:
            log_error(f"render_previews: {self.cur.get('name')}: {e!r}")
            give_up(self.cur)
            self.one.emit(self.cur, False)
        QTimer.singleShot(0, self.next)


def render_all(assets, probe=""):
    """Из командной строки: своё QApplication, ждать конца. -> сколько вышло."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    r = PreviewRenderer()
    res = {}
    r.one.connect(lambda a, ok: print(("  + " if ok else "  ! ") + a.get("name", "")))
    r.done.connect(lambda n: (res.setdefault("n", n), app.quit()))
    QTimer.singleShot(0, lambda: r.run(assets, probe))
    app.exec()
    return res.get("n", 0)
