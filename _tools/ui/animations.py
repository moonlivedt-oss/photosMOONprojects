"""Движение в окне: живой фон, вкладки с бегущей таблеткой, переходы страниц, свечение и рябь
на кнопках, всплывающие сообщения, оверлей перетаскивания, парящий значок пустых страниц.
Всё рисуется само и само останавливается, когда двигать нечего."""

import math
import time

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QRegion,
)
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QComboBox,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabBar,
    QWidget,
)

from ui.theme import C
from ui.thumbnails import lib_pix

OUT = QEasingCurve.Type.OutCubic


def anim(owner, ms, cb, start=0.0, end=1.0, curve=OUT, done=None):
    """Значение от start до end за ms, cb(v) на каждом кадре. Живёт, пока жив owner."""
    a = QVariantAnimation(owner)
    a.setDuration(ms)
    a.setStartValue(float(start))
    a.setEndValue(float(end))
    a.setEasingCurve(curve)
    a.valueChanged.connect(cb)
    if done:
        a.finished.connect(done)
    a.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return a


def stop(a):
    """Остановить анимацию, если она ещё жива (законченные удаляются сами)."""
    try:
        if a is not None:
            a.stop()
    except RuntimeError:
        pass


def rgba(name, alpha):
    c = QColor(C[name])
    c.setAlpha(int(alpha))
    return c


# ---------------------------------------------------------------- живой фон
class Aurora(QObject):
    """Медленно плывущие пятна цвета за панелями окна. Рисуется в маленькую картинку и растягивается,
    а перерисовывается только то, что не закрыто сплошными панелями (щели, полоса вкладок, низ),
    так что списки с тысячами плиток из-за фона не перерисовываются.
    Пятна огромные и размытые, им хватает 12 кадров в секунду; кадр собирается один раз на тик,
    а окно в фоне (не в фокусе или свёрнуто) фон не двигает вовсе."""

    FPS = 10
    BLOBS = (  # цвет, сила, радиус (доля диагонали), скорость, фаза
        ("acc", 120, 0.42, 0.050, 0.0),
        ("acc2", 95, 0.36, 0.037, 2.1),
        ("teal", 70, 0.34, 0.043, 4.2),
        ("acc", 60, 0.30, 0.061, 5.3),
    )

    def __init__(self, win):
        super().__init__(win)
        self.win, self.t0, self.solid, self.solid_at = win, time.monotonic(), [], 0.0
        self.full_at, self.cache, self.live = 0.0, None, True
        self.timer = QTimer(self, interval=1000 // self.FPS)
        self.timer.timeout.connect(self.tick)
        win.installEventFilter(self)

    def eventFilter(self, obj, e):
        t = e.type()
        if t in (QEvent.Type.Show, QEvent.Type.WindowActivate, QEvent.Type.WindowStateChange):
            if self.live and obj.isActiveWindow() and not obj.isMinimized():
                self.timer.start()
        elif t in (QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
            self.timer.stop()
        elif t in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self.solid_at = 0
            self.cache = None
        return False

    def set_live(self, on):
        """Выключенный фон остаётся красивым, но застывшим - ноль работы."""
        self.live = on
        if on and self.win.isActiveWindow():
            self.timer.start()
        else:
            self.timer.stop()

    def solids(self):
        """Сплошные панели окна - под ними фон не обновляем. Список освежается раз в секунду."""
        now = time.monotonic()
        if now - self.solid_at > 1.0:
            self.solid_at = now
            self.solid = [
                w
                for w in self.win.findChildren(QWidget)
                if isinstance(w, (QAbstractScrollArea, QGroupBox, QLineEdit, QComboBox, QAbstractSpinBox))
                or w.objectName() in ("panel", "drop")
            ]
        return self.solid

    def tick(self):
        now = time.monotonic()
        self.cache = None  # новый кадр соберётся при первой отрисовке
        if now - self.full_at > 6.0:  # изредка целиком: подтянуть уголки скруглённых панелей
            self.full_at = now
            self.win.update()
            return
        reg = QRegion(self.win.rect())
        for w in self.solids():
            try:
                if not w.isVisible():
                    continue
                r = QRect(w.mapTo(self.win, QPoint(0, 0)), w.size())
            except RuntimeError:  # панель уже удалена
                self.solid_at = 0
                continue
            # целиком, с уголками: иначе Qt перерисовывал бы весь список ради уголка;
            # уголки подтягивает редкое полное обновление, пятна за 6 секунд почти не сдвигаются
            reg -= QRegion(r)
        self.win.update(reg)

    def frame(self, w, h):
        """Кадр фона в 1/12 размера - пятна размытые, мелкая картинка их не портит."""
        sw, sh = max(8, w // 12), max(8, h // 12)
        img = QImage(sw, sh, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(C["bg0"]))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = time.monotonic() - self.t0
        diag = math.hypot(sw, sh)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for name, power, rad, speed, ph in self.BLOBS:
            x = sw * (0.5 + 0.45 * math.sin(t * speed * 2.3 + ph))
            y = sh * (0.5 + 0.42 * math.cos(t * speed * 1.7 + ph * 1.3))
            r = diag * rad * (1 + 0.12 * math.sin(t * speed * 3 + ph))
            g = QRadialGradient(QPointF(x, y), r)
            g.setColorAt(0, rgba(name, power * 0.9))
            g.setColorAt(0.5, rgba(name, power * 0.3))
            g.setColorAt(1, rgba(name, 0))
            p.fillRect(QRectF(0, 0, sw, sh), QBrush(g))
        p.end()
        return img

    def paint(self, p, rect):
        if self.cache is None or self.cache.size() != rect.size():
            self.cache = self.bake(rect)
        p.drawPixmap(rect.topLeft(), self.cache)

    def bake(self, rect):
        pm = QPixmap(rect.size())
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, rect.width(), rect.height()), self.frame(rect.width(), rect.height()))
        # тонкий световой край сверху и затемнение к низу - глубина
        g = QLinearGradient(0, 0, 0, rect.height())
        g.setColorAt(0, QColor(255, 255, 255, 10))
        g.setColorAt(0.08, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 70))
        p.fillRect(QRectF(0, 0, rect.width(), rect.height()), QBrush(g))
        p.end()
        return pm


# ---------------------------------------------------------------- вкладки
class TabBar(QTabBar):
    """Вкладки-таблетки: подсветка выбранной переезжает к новой, под ней тлеет градиентная черта."""

    def __init__(self):
        super().__init__()
        self.pill, self.glow = QRectF(), 0.0
        self.move_anim = None
        self.setMouseTracking(True)
        self.setDrawBase(False)
        self.currentChanged.connect(self.slide)

    def target(self, i):
        return QRectF(self.tabRect(i)).adjusted(3, 8, -3, -6) if i >= 0 else QRectF()

    def slide(self, i):
        start, end = QRectF(self.pill), self.target(i)
        if start.isNull() or not self.isVisible():
            self.pill = end
            self.update()
            return
        stop(self.move_anim)

        def step(v):
            # левый и правый край едут с разной скоростью - таблетка «тянется», как жидкая
            a, b = min(1, v * 1.25), max(0, v * 1.25 - 0.25)
            lead, tail = (a, b) if end.x() > start.x() else (b, a)
            left = start.left() + (end.left() - start.left()) * tail
            right = start.right() + (end.right() - start.right()) * lead
            self.pill = QRectF(left, end.top(), right - left, end.height())
            self.update()

        self.move_anim = anim(self, 420, step, curve=QEasingCurve.Type.OutQuint)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.pill = self.target(self.currentIndex())

    def showEvent(self, e):
        super().showEvent(e)
        self.pill = self.target(self.currentIndex())

    def paintEvent(self, e):
        if self.pill.isNull():
            self.pill = self.target(self.currentIndex())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.pill
        if not r.isNull():
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, rgba("acc", 85))
            g.setColorAt(1, rgba("acc2", 45))
            p.setPen(QPen(rgba("acc", 110), 1))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(r, 10, 10)
            line = QLinearGradient(r.left(), 0, r.right(), 0)
            line.setColorAt(0, rgba("acc", 0))
            line.setColorAt(0.5, rgba("acc2", 255))
            line.setColorAt(1, rgba("acc", 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(line))
            p.drawRoundedRect(QRectF(r.left() + 12, r.bottom() + 2, r.width() - 24, 2), 1, 1)
        p.end()
        super().paintEvent(e)


class PageFade(QObject):
    """Смена вкладки: старая страница уезжает и тает, новая выезжает навстречу."""

    def __init__(self, tabs):
        super().__init__(tabs)
        self.tabs, self.prev = tabs, tabs.currentIndex()
        tabs.currentChanged.connect(self.go)

    def go(self, i):
        old = self.tabs.widget(self.prev) if self.prev >= 0 else None
        d = 1 if i > self.prev else -1
        self.prev = i
        new = self.tabs.widget(i)
        if old is None or new is None or not self.tabs.isVisible():
            return
        shot = old.grab()
        ghost = QLabel(self.tabs)
        ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        ghost.setPixmap(shot)
        geo = QRect(new.mapTo(self.tabs, QPoint(0, 0)), QWidget.size(new))  # у вкладок свои size и move
        ghost.setGeometry(geo)
        ghost.show()
        ghost.raise_()
        fx = QGraphicsOpacityEffect(ghost)
        ghost.setGraphicsEffect(fx)
        fx_new = QGraphicsOpacityEffect(new)  # на время перехода; свой эффект у вкладок не бывает
        fx_new.setOpacity(0)
        new.setGraphicsEffect(fx_new)
        home = QWidget.pos(new)

        def step(v):
            out = min(1.0, v / 0.55)  # старая уходит быстрее, чем приходит новая
            inn = max(0.0, (v - 0.2) / 0.8)
            fx.setOpacity(1 - out)
            fx_new.setOpacity(inn)
            ghost.move(geo.x() - int(d * 36 * out), geo.y())
            QWidget.move(new, home.x() + int(d * 36 * (1 - inn)), home.y())  # у вкладки библиотеки свой move()

        def done():
            QWidget.move(new, home)
            new.setGraphicsEffect(None)
            ghost.deleteLater()

        anim(self, 340, step, done=done)


# ---------------------------------------------------------------- кнопки и поля
class Ripple(QWidget):
    """Круг от точки нажатия внутри кнопки."""

    def __init__(self, btn, pos):
        super().__init__(btn)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(btn.rect())
        self.c, self.v = QPointF(pos), 0.0
        self.light = btn.objectName() == "primary"
        self.show()
        anim(self, 520, self.step, done=self.deleteLater)

    def step(self, v):
        self.v = v
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.setClipPath(clip)
        far = math.hypot(self.width(), self.height())
        c = QColor(255, 255, 255) if self.light else QColor(C["acc"])
        c.setAlpha(int((110 if self.light else 90) * (1 - self.v)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(self.c, far * self.v, far * self.v)
        p.end()


class Shine(QWidget):
    """Блик, что раз в несколько секунд пробегает по главной кнопке."""

    def __init__(self, btn):
        super().__init__(btn)
        self.btn, self.x = btn, -1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.every = QTimer(self, interval=4200)
        self.every.timeout.connect(self.run)
        self.every.start()

    def run(self):
        if not self.btn.isVisible() or not self.btn.isEnabled():
            return
        self.setGeometry(self.btn.rect())
        self.raise_()
        self.show()
        anim(self, 900, self.step, curve=QEasingCurve.Type.InOutSine, done=self.hide)

    def step(self, v):
        self.x = v
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.setClipPath(clip)
        w = self.width()
        cx = -w * 0.3 + self.x * w * 1.6
        g = QLinearGradient(cx - 40, 0, cx + 40, self.height())
        g.setColorAt(0, QColor(255, 255, 255, 0))
        g.setColorAt(0.5, QColor(255, 255, 255, 90))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(self.rect(), QBrush(g))
        p.end()


class Motion(QObject):
    """Фильтр на всё приложение: свечение кнопок и полей при наведении/фокусе, рябь при нажатии,
    блик на главных кнопках. Чужие эффекты (если у виджета свой QGraphicsEffect) не трогаем."""

    def __init__(self, app):
        super().__init__(app)
        self.anims = {}
        app.installEventFilter(self)

    def glow(self, w, on, color, strength):
        fx = w.graphicsEffect()
        if fx is not None and not isinstance(fx, QGraphicsDropShadowEffect):
            return
        if fx is None:
            if not on:
                return
            fx = QGraphicsDropShadowEffect(w)
            fx.setOffset(0, 0)
            fx.setBlurRadius(0)
            w.setGraphicsEffect(fx)
        old = self.anims.pop(id(w), None)
        stop(old)
        c = QColor(color)

        def step(v):
            try:
                fx.setBlurRadius(4 + 22 * v)
                c.setAlpha(int(strength * v))
                fx.setColor(c)
            except RuntimeError:
                pass

        def done():
            self.anims.pop(id(w), None)
            if not on:
                try:
                    if w.graphicsEffect() is fx:
                        w.setGraphicsEffect(None)
                except RuntimeError:
                    pass

        start = fx.color().alpha() / strength if strength else 0
        self.anims[id(w)] = anim(w, 260 if on else 380, step, start, 1.0 if on else 0.0, done=done)

    def eventFilter(self, obj, e):
        t = e.type()
        if t not in (
            QEvent.Type.Enter,
            QEvent.Type.Leave,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.FocusIn,
            QEvent.Type.FocusOut,
            QEvent.Type.Show,
        ):
            return False
        if isinstance(obj, QPushButton):
            primary = obj.objectName() == "primary"
            if t == QEvent.Type.Show and primary and not obj.property("shine"):
                obj.setProperty("shine", True)
                Shine(obj)
            elif t == QEvent.Type.Enter and obj.isEnabled():
                self.glow(obj, True, C["acc2"] if primary else C["acc"], 200 if primary else 120)
            elif t == QEvent.Type.Leave:
                self.glow(obj, False, C["acc"], 200 if primary else 120)
            elif t == QEvent.Type.MouseButtonPress and obj.isEnabled() and e.button() == Qt.MouseButton.LeftButton:
                Ripple(obj, e.position())
        elif (
            isinstance(obj, QLineEdit)
            and t in (QEvent.Type.FocusIn, QEvent.Type.FocusOut)
            and not isinstance(obj.parent(), (QAbstractSpinBox, QComboBox))
        ):  # не поле внутри счётчика
            self.glow(obj, t == QEvent.Type.FocusIn, C["acc"], 150)
        return False


# ---------------------------------------------------------------- сообщения
class Toast(QWidget):
    """Сообщение, что всплывает внизу окна и само уходит. Новое сообщение подменяет текст на месте.
    action = (подпись, функция) - кнопка справа («Отменить»); пока над пузырём мышь, он не уходит."""

    def __init__(self, win):
        super().__init__(win)
        self.win, self.text, self.v, self.bump, self.bumped = win, "", 0.0, 0.0, 0.0
        self.action, self.hot = None, False
        self.setMouseTracking(True)
        self.hide_timer = QTimer(self, singleShot=True)
        self.hide_timer.timeout.connect(self.leave_later)
        self.cur = None
        self.hide()

    def btn_rect(self):
        if not self.action:
            return QRectF()
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self.action[0]) + 26
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        return QRectF(r.right() - w - 7, r.top() + 7, w, r.height() - 14)

    def leave_later(self):
        if self.underMouse():
            self.hide_timer.start(1200)  # читают или тянутся к кнопке - не убегать
        else:
            self.fade(False)

    def mouseMoveEvent(self, e):
        hot = self.btn_rect().contains(e.position())
        if hot != self.hot:
            self.hot = hot
            self.setCursor(Qt.CursorShape.PointingHandCursor if hot else Qt.CursorShape.ArrowCursor)
            self.update()

    def mousePressEvent(self, e):
        if self.action and self.btn_rect().contains(e.position()):
            fn, self.action = self.action[1], None
            self.fade(False)
            fn()

    def say(self, text, ms=3200, action=None):
        self.text, self.action, self.hot = text, action, False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not action)
        fm = self.fontMetrics()
        extra = fm.horizontalAdvance(action[0]) + 44 if action else 0
        w = min(self.win.width() - 80, fm.horizontalAdvance(text) + 64 + extra)
        h = 42
        bottom = self.win.height() - (self.win.statusBar().height() if self.win.statusBar() else 0)
        self.base = QRect((self.win.width() - w) // 2, bottom - h - 22, w, h)
        self.setGeometry(self.base)
        if self.isVisible() and self.v > 0.5:
            if time.monotonic() - self.bumped > 0.6:  # частые «Режу 3 из 10» не дёргают пузырь
                self.bumped = time.monotonic()
                anim(self, 380, self.set_bump, 1.0, 0.0, curve=QEasingCurve.Type.OutElastic)
        else:
            self.show()
            self.raise_()
            self.fade(True)
        self.raise_()
        self.hide_timer.start(ms)
        self.update()

    def set_bump(self, v):
        self.bump = v
        self.update()

    def fade(self, on):
        stop(self.cur)

        def step(v):
            self.v = v
            self.move(self.base.x(), self.base.y() + int(18 * (1 - v)))
            self.update()

        self.cur = anim(
            self,
            340 if on else 420,
            step,
            self.v,
            1.0 if on else 0.0,
            curve=QEasingCurve.Type.OutBack if on else QEasingCurve.Type.InCubic,
            done=None if on else self.hide,
        )

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self.v)))
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(8, 8, 14, 235))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, QColor(C["acc"]))
        g.setColorAt(1, QColor(C["acc2"]))
        p.setPen(QPen(QBrush(g), 1.4 + 1.6 * self.bump))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        dot = QRectF(r.left() + 16, r.center().y() - 4, 8, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(dot.adjusted(-self.bump * 2, -self.bump * 2, self.bump * 2, self.bump * 2))
        p.setPen(QColor(C["text"]))
        fm = self.fontMetrics()
        b = self.btn_rect()
        room = r.width() - 50 - (b.width() + 12 if self.action else 0)
        p.drawText(
            QRectF(dot.right() + 10, r.top(), room, r.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            fm.elidedText(self.text, Qt.TextElideMode.ElideMiddle, int(room)),
        )
        if self.action:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g) if self.hot else QColor(C["accd"]))
            p.drawRoundedRect(b, b.height() / 2, b.height() / 2)
            p.setPen(QColor("#15131f" if self.hot else C["text"]))
            p.drawText(b, Qt.AlignmentFlag.AlignCenter, self.action[0])
        p.end()


# ---------------------------------------------------------------- перетаскивание в окно
class DropOverlay(QWidget):
    """Затемнение с бегущей пунктирной рамкой и парящей стрелкой, пока над окном несут файлы."""

    def __init__(self, win, text):
        super().__init__(win)
        self.text, self.v, self.t0 = text, 0.0, time.monotonic()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self.update)
        self.cur = None
        self.icon = lib_pix("download-arrow", 128)
        self.hide()

    def appear(self, on):
        stop(self.cur)
        if on:
            self.setGeometry(self.parent().rect())
            self.raise_()
            self.show()
            self.timer.start()

        def step(v):
            self.v = v
            self.update()

        def done():
            if not on:
                self.timer.stop()
                self.hide()

        self.cur = anim(self, 220, step, self.v, 1.0 if on else 0.0, done=done)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        t = time.monotonic() - self.t0
        p.setOpacity(self.v)
        p.fillRect(self.rect(), QColor(6, 6, 12, 200))
        r = QRectF(self.rect()).adjusted(28, 28, -28, -28)
        k = 1 - 0.02 * (1 - self.v)
        r = QRectF(
            r.center().x() - r.width() * k / 2, r.center().y() - r.height() * k / 2, r.width() * k, r.height() * k
        )
        glow = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.5)
        glow.setColorAt(0, rgba("acc", 60 + 25 * math.sin(t * 3)))
        glow.setColorAt(1, rgba("acc", 0))
        p.fillRect(r, QBrush(glow))
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(C["acc"]))
        g.setColorAt(1, QColor(C["acc2"]))
        pen = QPen(QBrush(g), 3)
        pen.setDashPattern([6, 5])
        pen.setDashOffset(-t * 14)  # «бегущие муравьи»
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 24, 24)
        y = r.center().y() - 70 + 10 * math.sin(t * 3.2)
        if not self.icon.isNull():
            p.drawPixmap(QRectF(r.center().x() - 48, y, 96, 96), self.icon, QRectF(self.icon.rect()))
        f = p.font()
        f.setPointSize(17)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(C["text"]))
        p.drawText(QRectF(r.x(), r.center().y() + 46, r.width(), 40), Qt.AlignmentFlag.AlignCenter, self.text)
        p.end()


# ---------------------------------------------------------------- парящий значок
class Floaty(QWidget):
    """Значок пустой страницы: покачивается вверх-вниз, под ним дышит цветная тень."""

    def __init__(self, icon, size=96):
        super().__init__()
        self.pm, self.side, self.t0 = lib_pix(icon, size * 2), size, time.monotonic()
        self.setFixedHeight(size + 40)
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self.update)

    def showEvent(self, e):
        super().showEvent(e)
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        t = time.monotonic() - self.t0
        s = math.sin(t * 2.0)
        cx = self.width() / 2
        base = self.height() - 14
        sh = QRadialGradient(QPointF(cx, base), self.side * 0.5)
        sh.setColorAt(0, rgba("acc", 90 - 30 * s))
        sh.setColorAt(1, rgba("acc", 0))
        p.save()
        p.translate(cx, base)
        p.scale(1, 0.22)
        p.translate(-cx, -base)
        k = 0.8 - 0.15 * s
        p.fillRect(QRectF(cx - self.side * k, base - self.side * k, self.side * 2 * k, self.side * 2 * k), QBrush(sh))
        p.restore()
        if not self.pm.isNull():
            y = 8 + 8 * (1 + s)
            p.drawPixmap(QRectF(cx - self.side / 2, y, self.side, self.side), self.pm, QRectF(self.pm.rect()))
        p.end()


def fade_in_window(w, ms=320):
    w.setWindowOpacity(0.0)
    anim(w, ms, w.setWindowOpacity)
