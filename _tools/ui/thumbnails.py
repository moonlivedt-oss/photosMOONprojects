"""Картинки -> Qt: подложки, плитки, кэш миниатюр (память + диск), значки из библиотеки."""

import hashlib
import os
import time
from collections import OrderedDict

import numpy as np
from PIL import Image
from PyQt6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QIconEngine,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOption

import imaging as K
from ui.common import DUPE, EXT, HERE, LIB, PIX, ROLE, STAR, SUB, TINT
from ui.theme import CURRENT, C


# ---------------------------------------------------------------- картинки -> Qt
def backdrop(w, h, mode):
    """Подложка под превью: шахматка (видно прозрачность), белая или чёрная."""
    if mode == "light":
        return Image.new("RGBA", (w, h), (244, 242, 250, 255))
    if mode == "dark":
        return Image.new("RGBA", (w, h), (0, 0, 0, 255))
    y, x = np.mgrid[0:h, 0:w]
    odd = ((x // 8 + y // 8) % 2)[..., None] == 1
    # шахматка - в тон теме: в светлой тёмные квадраты под каждой картинкой выглядят дырами
    c1, c2 = (
        ([236, 234, 243, 255], [225, 222, 233, 255])
        if CURRENT["theme"] == "light"
        else ([36, 36, 49, 255], [27, 27, 38, 255])
    )
    a = np.where(odd, np.uint8(c1), np.uint8(c2)).astype(np.uint8)
    return Image.fromarray(a).copy()


def to_qimage(im):
    im = im.convert("RGBA")
    q = QImage(im.tobytes("raw", "RGBA"), im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888)
    return q.copy()  # copy: буфер PIL не переживёт выход из функции


def to_pix(im):
    return QPixmap.fromImage(to_qimage(im))


def tile(im, side, mode=None):
    """Квадратная плитка side x side: картинка по центру, под ней подложка (mode=None - прозрачно)."""
    im = im.convert("RGBA")
    im.thumbnail((side, side), Image.LANCZOS)
    bg_ = backdrop(side, side, mode) if mode else Image.new("RGBA", (side, side), (0, 0, 0, 0))
    bg_.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return to_pix(bg_)


def swatch(color, side=14):
    pm = QPixmap(side, side)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#4a4860"), 1))
    p.setBrush(QColor(color))
    p.drawEllipse(1, 1, side - 2, side - 2)
    p.end()
    return QIcon(pm)


_thumbs = OrderedDict()  # плитки в памяти, самые давние выбрасываются
THUMBS_MAX = 2500
THUMBS_DIR = os.path.join(HERE, "_thumbs")


def raw_thumb(path, side):
    """Уменьшенная копия с прозрачностью. Маленькие хранятся на диске: большой раздел открывается сразу.
    Можно звать из фонового потока (только PIL)."""
    st = os.stat(path)
    cache = None
    if side <= 256:
        key = hashlib.sha1(("v2|%s|%d|%d|%d" % (path, st.st_mtime_ns, st.st_size, side)).encode("utf-8")).hexdigest()
        cache = os.path.join(THUMBS_DIR, key[:2], key + ".webp")
        if os.path.exists(cache):
            try:
                with Image.open(cache) as im:
                    im.load()
                    im = im.convert("RGBA")
                if time.time() - os.path.getmtime(cache) > 3 * 86400:
                    os.utime(cache)  # нужная миниатюра «свежеет» - чистка её не тронет
                return im
            except Exception:
                pass
    with Image.open(path) as im:
        im.draft("RGB", (side * 2, side * 2))  # jpg открывается сразу уменьшенным
        im = K.upright(im).convert("RGBA")
    im.thumbnail((side, side), Image.LANCZOS)
    if cache:
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            im.save(cache, "WEBP", quality=88, method=2)
        except OSError:
            pass
    return im


THUMBS_LIMIT, THUMBS_KEEP = 400 * 1048576, 300 * 1048576


def trim_thumbs():
    """В фоне при запуске: кэш миниатюр на диске не растёт бесконечно - после переименований,
    сжатия и смены подложки старые копии больше никогда не читаются. Сверх 400 МБ удаляются
    давно не нужные, пока не останется 300 МБ. Возвращает, сколько удалено."""
    files = []
    for d, _dirs, names in os.walk(THUMBS_DIR):
        for f in names:
            p = os.path.join(d, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
    total = sum(s for _t, s, _p in files)
    if total <= THUMBS_LIMIT:
        return 0
    gone = 0
    for _t, s, p in sorted(files):
        if total <= THUMBS_KEEP:
            break
        try:
            os.remove(p)
            total -= s
            gone += 1
        except OSError:
            pass
    return gone


def tile_image(path, side, mode):
    """Миниатюра как QImage в своих пропорциях, подложка - только под самой картинкой.
    Можно строить в фоне."""
    im = raw_thumb(path, side)
    if mode:
        back = backdrop(im.width, im.height, mode)
        back.alpha_composite(im)
        im = back
    return to_qimage(im)


def remember(key, pm):
    _thumbs[key] = pm
    _thumbs.move_to_end(key)
    while len(_thumbs) > THUMBS_MAX:
        _thumbs.popitem(last=False)
    return pm


def thumb_key(path, side, mode):
    try:
        themed = CURRENT["theme"] if mode and mode not in ("light", "dark") else None  # шахматка зависит от темы
        return (path, os.path.getmtime(path), side, mode, themed)
    except OSError:
        return None


def thumb(path, side, mode=None):
    key = thumb_key(path, side, mode)
    if key is None:
        return QPixmap()
    if key in _thumbs:
        _thumbs.move_to_end(key)
    else:
        try:
            if path.lower().endswith(".svg"):
                src = QIcon(path).pixmap(side, side)
                pm = to_pix(backdrop(side, side, mode)) if mode else QPixmap(side, side)
                if not mode:
                    pm.fill(QColor(0, 0, 0, 0))
                p = QPainter(pm)
                p.drawPixmap((side - src.width()) // 2, (side - src.height()) // 2, src)
                p.end()
            else:
                pm = QPixmap.fromImage(tile_image(path, side, mode))
        except Exception:
            pm = QPixmap()
        remember(key, pm)
    return _thumbs[key]


_icons = None


def forget_pixmaps():
    """Перед выходом: картинки Qt должны умереть раньше самого приложения, иначе Python
    добивает этот кэш уже после него, и процесс падает при закрытии."""
    _thumbs.clear()


MASCOTS = os.path.join(LIB, "03 Маскоты", "Из проектов")  # маскот пустых экранов: «mascot:Сон»


def lib_pix(name, side=48):
    """Значок из "04 Иконки" библиотеки по имени файла без расширения; «mascot:Имя» - маскот."""
    if name.startswith("mascot:"):
        for ext in (".webp", ".png"):
            p = os.path.join(MASCOTS, name[7:] + ext)
            if os.path.exists(p):
                return thumb(p, side)
        return QPixmap()
    global _icons
    if _icons is None:
        _icons = {}
        for p in K.images_in(os.path.join(LIB, "04 Иконки")):  # иконки лежат по подпапкам
            _icons.setdefault(os.path.splitext(os.path.basename(p))[0], p)
    p = _icons.get(name)
    if not p:
        return QPixmap()
    pm = thumb(p, side)
    if CURRENT["theme"] == "light" and is_white(p):  # белые значки Kenney на светлом фоне не видны
        key = (p, side, C["text"])
        if key not in _tinted:
            _tinted[key] = tinted(pm, C["text"])
        return _tinted[key]
    return pm


_white, _tinted = {}, {}


def is_white(path):
    """Значок почти целиком белый (одноцветные значки Kenney) - в светлой теме его надо перекрасить."""
    if path not in _white:
        try:
            a = np.asarray(K.load(path).convert("RGBA").resize((32, 32))).astype(np.float32) / 255
            px = a[..., :3][a[..., 3] > 0.5]
            _white[path] = bool(len(px)) and float((px @ np.float32([0.299, 0.587, 0.114])).mean()) > 0.9
        except Exception:
            _white[path] = False
    return _white[path]


def tinted(pm, color):
    """Тот же значок цветом color: форма и прозрачность остаются."""
    out = QPixmap(pm)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return out


# Значки кнопок, меню и дерева - одним стилем: одноцветные значки Kenney там, где есть подходящий,
# остальное (папки, вкладки) - силуэтом той же картинки; всё цветом текста темы. Карточки и плитки - цветные.
CHROME = {
    "bookmark": "flag",
    "camera": "card_add",
    "checklist": "notepad_write",
    "clipboard": "notepad",
    "color-palette": "toolFill",
    "cross-circle": "cross",
    "crystal-ball-stand": "target",
    "drawing_pen": "toolPencil",
    "eye": "look_b",
    "first-aid-kit": "information",
    "globe": "share1",
    "house": "home",
    "image-file": "card",
    "magnifier-text-lines": "zoom",
    "magnifying-glass": "zoom",
    "Лупа": "zoom",
    "paint-brush": "toolBrush",
    "plug-socket": "share2",
    "plus-circle": "plus",
    "question-mark-bubble": "question",
    "quill-pen": "toolPencil",
    "toolbox": "wrench",
    "trash-bin": "trashcan",
    "upload-arrow": "upload",
    "download-arrow": "download",
    "zip-archive": "smaller",
    "game-cartridge": "gamepad",
}
_chrome = {}


def chrome_pix(name, side=48):
    """Значок для кнопки: одноцветный, цветом текста темы. Яркость картинки -> непрозрачность:
    белое становится цветом, тёмная обводка наклеек - прозрачной (выходит силуэт)."""
    lib_pix(CHROME.get(name, name), side)  # заполняет _icons
    path = _icons.get(CHROME.get(name, name))
    if not path:
        return QPixmap()
    color = QColor(C["text"]) if CURRENT["theme"] == "dark" else QColor(C["dim"])  # в светлой - мягче
    key = (path, side, color.name())
    if key not in _chrome:
        try:
            im = raw_thumb(path, side) if side <= 256 else K.load(path).convert("RGBA")
            im = im.convert("RGBA")
            im.thumbnail((side, side), Image.LANCZOS)
            a = np.asarray(im).astype(np.float32) / 255
            lum = a[..., :3] @ np.float32([0.299, 0.587, 0.114])
            out = np.zeros_like(a)
            out[..., :3] = np.float32(color.getRgb()[:3]) / 255
            out[..., 3] = a[..., 3] * np.clip((lum - 0.12) / 0.6, 0, 1)
            _chrome[key] = to_pix(Image.fromarray((out * 255).astype(np.uint8), "RGBA"))
        except Exception:
            _chrome[key] = QPixmap()
    return _chrome[key]


class LibIconEngine(QIconEngine):
    """Значок библиотеки, который берёт картинку в момент отрисовки: при смене темы на лету
    значки перекрашиваются без пересоздания кнопок."""

    def __init__(self, name):
        super().__init__()
        self.name = name

    def pixmap(self, size, mode, state):
        side = max(16, size.width(), size.height())
        pm = chrome_pix(self.name, 48 if side <= 48 else side)
        if pm.isNull():
            return QPixmap()
        pm = pm.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if mode == QIcon.Mode.Disabled:
            opt = QStyleOption()
            pm = QApplication.style().generatedIconPixmap(mode, pm, opt)
        return pm

    def paint(self, painter, rect, mode, state):
        pm = self.pixmap(rect.size(), mode, state)
        x = rect.x() + (rect.width() - pm.width()) // 2
        y = rect.y() + (rect.height() - pm.height()) // 2
        painter.drawPixmap(x, y, pm)

    def clone(self):
        return LibIconEngine(self.name)


def lib_icon(name):
    if chrome_pix(name).isNull():
        return QIcon()
    return QIcon(LibIconEngine(name))


# ---------------------------------------------------------------- плитки библиотеки
class TileDelegate(QStyledItemDelegate):
    """Рисует плитку-карточку: картинка в своих пропорциях, имя и подпись (папка, формат).
    Наведение (view.hover_amount) поднимает карточку: тень, подсветка, картинка чуть приближается;
    только что загруженная картинка проявляется (view.fade_amount).
    Размер плитки не зависит от того, загрузилась ли картинка: Qt меряет все плитки по первой,
    и пустая первая (ещё грузится в фоне) раньше сплющивала все картинки в полоску."""

    PAD = 9  # поля внутри карточки

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.f1 = QFont("Segoe UI", 9)
        self.f1.setWeight(QFont.Weight.DemiBold)
        self.f2 = QFont("Segoe UI", 8)
        self.f3 = QFont("Segoe UI", 7)
        self.f3.setWeight(QFont.Weight.Bold)

    def sizeHint(self, _option, _index):
        g = self.view.gridSize()
        return g if g.isValid() else QSize(160, 200)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        row = index.row()
        h = self.view.hover_amount(row)
        fade = self.view.fade_amount(row)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        r = QRectF(option.rect).adjusted(5, 5 - 2 * h, -5, -5 - 2 * h)  # наведённая чуть всплывает

        tint = index.data(TINT)
        acc = QColor(tint or C["acc"])  # цвет раздела (как цвет вида у ассетов Unreal)
        if h > 0.01 or sel:  # мягкая тень под карточкой
            k = max(h, 0.6 if sel else 0)
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(1, 7):
                p.setBrush(QColor(0, 0, 0, int(22 * k * (1 - i / 7))))
                p.drawRoundedRect(r.adjusted(-i, -i + 4, i, i + 4), 14 + i, 14 + i)
            glow = QColor(acc)
            glow.setAlpha(int(45 * k))
            p.setBrush(glow)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 16, 16)

        base = QColor(C["bg2"])
        fg = QLinearGradient(r.topLeft(), r.bottomLeft())  # сверху - лёгкий отсвет цвета раздела
        fg.setColorAt(0, mix(base, acc, 0.07 + 0.10 * h + (0.14 if sel else 0)))
        fg.setColorAt(1, mix(base, QColor(C["bg1"]), 0.5))
        p.setBrush(QBrush(fg))
        if sel:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, acc)
            g.setColorAt(1, mix(acc, QColor(C["acc2"]), 0.5))
            p.setPen(QPen(QBrush(g), 2))
        else:
            p.setPen(QPen(mix(QColor(C["line"]), acc, 0.15 + h * 0.6), 1))
        p.drawRoundedRect(r, 14, 14)
        if tint:  # цветная черта сверху - какого вида ассет
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(tint))
            p.drawRoundedRect(QRectF(r.x() + 18, r.y() + 1.5, r.width() - 36, 3.5), 1.75, 1.75)

        side = r.width() - 2 * self.PAD
        box = QRectF(r.x() + self.PAD, r.y() + self.PAD, side, side)
        pm = index.data(PIX)
        if isinstance(pm, QPixmap) and not pm.isNull():
            k = min(box.width() / pm.width(), box.height() / pm.height())
            w, hh = pm.width() * k, pm.height() * k
            img = QRectF(box.x() + (box.width() - w) / 2, box.y() + (box.height() - hh) / 2, w, hh)
            clip = QPainterPath()
            clip.addRoundedRect(img, 10, 10)
            p.setClipPath(clip)
            z = 1 + 0.045 * h  # приближение внутри своей рамки
            src = QRectF(img.center().x() - w * z / 2, img.center().y() - hh * z / 2, w * z, hh * z)
            p.setOpacity(fade)
            p.drawPixmap(src, pm, QRectF(pm.rect()))
            p.setOpacity(1)
            p.setClipping(False)
        else:  # ещё грузится - заглушка с бегущим переливом
            ph = (time.monotonic() * 0.9 + (r.x() + r.y()) / 1600) % 1.4 - 0.2
            g = QLinearGradient(box.topLeft(), box.bottomRight())
            g.setColorAt(0, QColor(C["bg3"]))
            g.setColorAt(max(0.0, min(1.0, ph - 0.15)), QColor(C["bg3"]))
            g.setColorAt(max(0.0, min(1.0, ph)), mix(QColor(C["bg3"]), QColor(C["acc"]), 0.22))
            g.setColorAt(max(0.0, min(1.0, ph + 0.15)), QColor(C["bg2"]))
            g.setColorAt(1, QColor(C["bg2"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawRoundedRect(box.adjusted(side * 0.08, side * 0.08, -side * 0.08, -side * 0.08), 12, 12)
            if hasattr(self.view, "shimmer"):
                self.view.shimmer = True
                if not self.view.anim.isActive():
                    self.view.anim.start()

        if index.data(STAR):  # в избранном - звезда на тёмном кружке
            c = QRectF(box.x() + 5, box.y() + 5, 24, 24)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(13, 13, 19, 200))
            p.drawEllipse(c)
            star = lib_pix("star", 44)
            if not star.isNull():
                p.drawPixmap(c.adjusted(4, 4, -4, -4), star, QRectF(star.rect()))

        ext = index.data(EXT)
        if ext:  # формат - всегда, бледно; при наведении ярче и с весом
            label = ext
            if h > 0.05:
                path = index.data(ROLE)
                try:
                    kb = os.path.getsize(path) / 1024 if path else 0
                    label = f"{ext}  {kb / 1024:.1f} МБ" if kb >= 1024 else f"{ext}  {max(1, round(kb))} КБ"
                except OSError:
                    pass
            p.setFont(self.f3)
            tw = p.fontMetrics().horizontalAdvance(label) + 12
            pill = QRectF(box.right() - tw - 5, box.y() + 5, tw, 18)
            p.setOpacity(0.55 + 0.45 * h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(13, 13, 19, 210))
            p.drawRoundedRect(pill, 9, 9)
            p.setPen(acc if h > 0.05 else QColor("#eceaf6"))  # плашка всегда тёмная - текст светлый в любой теме
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)
            p.setOpacity(1)

        text = QRect(int(r.x()) + 10, int(box.bottom()) + 7, int(r.width()) - 20, 18)
        p.setFont(self.f1)
        p.setPen(QColor(C["selt"] if sel else C["text"]))
        name = p.fontMetrics().elidedText(
            index.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideMiddle, text.width()
        )
        p.drawText(text, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, name)
        p.setFont(self.f2)
        p.setPen(QColor(C["dim"]))
        sub = p.fontMetrics().elidedText(index.data(SUB) or "", Qt.TextElideMode.ElideMiddle, text.width())
        p.drawText(text.translated(0, 17), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, sub)
        p.restore()


def mix(a, b, t):
    """Цвет между a и b (t от 0 до 1)."""
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def palette(path, n=6):
    return K.main_colors(path, n)


class PieceDelegate(QStyledItemDelegate):
    """Кусок нарезанного листа: карточка с номером, круглой галочкой (щелчок - отметить/снять),
    плашкой «уже есть» и именем (двойной щелчок - переименовать). Снятые - притушены."""

    PAD = 8

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.f1 = QFont("Segoe UI", 9)
        self.f1.setWeight(QFont.Weight.DemiBold)
        self.f3 = QFont("Segoe UI", 7)
        self.f3.setWeight(QFont.Weight.Bold)

    def sizeHint(self, _option, _index):
        g = self.view.gridSize()
        return g if g.isValid() else QSize(150, 180)

    def card(self, option):
        return QRectF(option.rect).adjusted(5, 5, -5, -5)

    def check_rect(self, option):
        r = self.card(option)
        return QRectF(r.x() + self.PAD + 5, r.y() + self.PAD + 5, 24, 24)

    def name_rect(self, option):
        r = self.card(option)
        return QRect(int(r.x()) + 8, int(r.bottom()) - 30, int(r.width()) - 16, 24)

    def editorEvent(self, event, model, option, index):
        """Щелчок по кружку - отметить или снять кусок, не трогая выделение."""
        if (
            event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)
            and event.button() == Qt.MouseButton.LeftButton
            and self.check_rect(option).adjusted(-4, -4, 4, 4).contains(event.position())
        ):
            if event.type() == QEvent.Type.MouseButtonRelease:
                on = index.data(Qt.ItemDataRole.CheckStateRole) in (Qt.CheckState.Checked, 2)
                model.setData(
                    index,
                    (Qt.CheckState.Unchecked if on else Qt.CheckState.Checked).value,
                    Qt.ItemDataRole.CheckStateRole,
                )
            return True
        return super().editorEvent(event, model, option, index)

    def updateEditorGeometry(self, editor, option, _index):
        editor.setGeometry(self.name_rect(option))

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        on = index.data(Qt.ItemDataRole.CheckStateRole) in (Qt.CheckState.Checked, 2)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        r = self.card(option)
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0, QColor(C["acc"]))
        grad.setColorAt(1, QColor(C["acc2"]))

        p.setBrush(QColor(C["accd"] if sel else C["bg3"] if hover else C["bg2"]))
        p.setPen(QPen(QBrush(grad), 2) if sel else QPen(QColor(C["line2"] if hover else C["line"]), 1))
        p.drawRoundedRect(r, 14, 14)

        side = r.width() - 2 * self.PAD
        box = QRectF(r.x() + self.PAD, r.y() + self.PAD, side, min(side, r.height() - 2 * self.PAD - 30))
        pm = index.data(PIX)
        if isinstance(pm, QPixmap) and not pm.isNull():
            k = min(box.width() / pm.width(), box.height() / pm.height())
            w, h = pm.width() * k, pm.height() * k
            img = QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)
            clip = QPainterPath()
            clip.addRoundedRect(img, 9, 9)
            p.setClipPath(clip)
            p.setOpacity(1.0 if on else 0.32)
            p.drawPixmap(img, pm, QRectF(pm.rect()))
            p.setOpacity(1)
            p.setClipping(False)

        c = self.check_rect(option)  # галочка: полный градиентный кружок или пустое кольцо
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawEllipse(c)
            pen = QPen(QColor(C["ink"]), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            path = QPainterPath(QPointF(c.x() + 7, c.y() + 12.5))
            path.lineTo(c.x() + 10.5, c.y() + 16)
            path.lineTo(c.x() + 17.5, c.y() + 8.5)
            p.drawPath(path)
        else:
            p.setBrush(QColor(13, 13, 19, 190))
            p.setPen(QPen(QColor(C["dim"]), 1.6))
            p.drawEllipse(c.adjusted(1, 1, -1, -1))

        p.setFont(self.f3)
        num = str(index.row() + 1)  # номер - как у рамки на листе
        tw = p.fontMetrics().horizontalAdvance(num) + 12
        pill = QRectF(box.right() - tw - 4, box.y() + 4, tw, 18)
        dupe = index.data(DUPE)
        if dupe:
            text = "уже есть"
            tw2 = p.fontMetrics().horizontalAdvance(text) + 14
            pill = QRectF(box.right() - tw2 - 4, box.y() + 4, tw2, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f0b44c"))
            p.drawRoundedRect(pill, 9, 9)
            p.setPen(QColor(C["ink"]))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(13, 13, 19, 190))
            p.drawRoundedRect(pill, 9, 9)
            p.setPen(QColor(C["dim"]))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, num)

        p.setFont(self.f1)
        p.setPen(QColor(C["selt"] if sel else C["text"] if on else C["faint"]))
        nr = self.name_rect(option)
        name = p.fontMetrics().elidedText(
            index.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideMiddle, nr.width()
        )
        p.drawText(nr, Qt.AlignmentFlag.AlignCenter, name)
        p.restore()
