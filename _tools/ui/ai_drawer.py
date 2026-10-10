"""ИИ-помощники в шапке: кнопка с живой точкой статуса и выезжающая справа лента их действий с «Отменить».

Точка: пульсирует зелёным - помощник что-то сделал только что (2 мин), горит ровно - недавно (30 мин),
серая - тихо, янтарная - помощникам разрешено только смотреть («Только чтение»)."""

import html
import time

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from library import journal
from ui.theme import C
from ui.thumbnails import lib_icon
from ui.widgets import key, panel_head

ACTIVE, RECENT = 120, 1800  # секунд: «только что» и «недавно»


def ago(t):
    d = max(0, time.time() - t)
    if d < 60:
        return "только что"
    if d < 3600:
        return f"{int(d // 60)} мин назад"
    if d < 86400:
        return f"{int(d // 3600)} ч назад"
    return time.strftime("%d.%m %H:%M", time.localtime(t))


def agent_entries(limit=40):
    """Действия помощников (не окна), свежие сначала."""
    return [e for e in journal.entries(limit * 3) if e["who"] != journal.WINDOW][:limit]


class AiStatusButton(QPushButton):
    """Кнопка «ИИ-помощники» с точкой статуса в углу значка."""

    def __init__(self):
        super().__init__(lib_icon("sparkles"), "ИИ-помощники", objectName="ghost")
        self.state = "idle"
        self.phase = 0.0
        self.pulse = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1400, loopCount=-1)
        self.pulse.valueChanged.connect(self._tick)

    def _tick(self, v):
        self.phase = float(v)
        self.update()

    def set_state(self, state, tip):
        self.setToolTip(tip)
        if state == self.state:
            return
        self.state = state
        (self.pulse.start if state == "active" else self.pulse.stop)()
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        col = {
            "active": "#5fe39a",
            "recent": "#5fe39a",
            "readonly": "#f0b45e",
        }.get(self.state, C["faint"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(col)
        icon = self.iconSize().width()  # значок с подписью стоят по центру кнопки - точка на его правом верхнем углу
        content = icon + 6 + self.fontMetrics().horizontalAdvance(self.text())
        x0 = (self.width() - content) / 2
        x, y, r = x0 + icon - 1, self.height() / 2 - icon / 2 + 1, 3.6
        if self.state == "active":  # расходящееся кольцо
            ring = QColor(c)
            ring.setAlphaF(0.55 * (1 - self.phase))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ring)
            rr = r + 6 * self.phase
            p.drawEllipse(QRectF(x - rr, y - rr, 2 * rr, 2 * rr))
        p.setPen(QColor(C["bg0"]))
        p.setBrush(c)
        p.drawEllipse(QRectF(x - r, y - r, 2 * r, 2 * r))
        p.end()


class AiDrawer(QFrame):
    """Лента действий помощников: выезжает справа поверх окна, закрывается той же кнопкой или Esc."""

    W = 380

    def __init__(self, win):
        super().__init__(win, objectName="panel")
        self.win = win
        self.setFixedWidth(self.W)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        top.addWidget(panel_head("ИИ-ПОМОЩНИКИ"))
        top.addStretch(1)
        close = QPushButton(lib_icon("cross"), "", objectName="tool")
        close.setToolTip("Закрыть (Esc)")
        close.clicked.connect(self.toggle)
        top.addWidget(close)
        v.addLayout(top)
        self.status = QLabel(objectName="dim", wordWrap=True)
        v.addWidget(self.status)
        self.ro = QCheckBox("Только чтение")
        self.ro.setToolTip("Помощники ищут и смотрят, но ничего не меняют в библиотеке")
        self.ro.toggled.connect(self.set_read_only)
        v.addWidget(self.ro)
        v.addWidget(QLabel("ЧТО ОНИ СДЕЛАЛИ", objectName="faint"))
        self.box = QWidget()
        self.rows = QVBoxLayout(self.box)
        self.rows.setContentsMargins(0, 0, 4, 0)
        self.rows.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidget(self.box)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        v.addWidget(scroll, 1)
        more = QPushButton(lib_icon("sparkles"), "Подключить помощников...")
        more.setToolTip("Claude Code, Cursor, VS Code и другие: подключить к библиотеке")
        more.clicked.connect(win.agents)
        v.addWidget(more)
        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.setDuration(260)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(lambda: self.isVisible() and not self.opening and self.hide())
        self.opening = False
        key("Escape", self, lambda: self.isVisible() and self.toggle())
        win.installEventFilter(self)
        self.hide()

    # ------------------------------------------------------------
    def place(self, shown):
        top = 48
        self.setFixedHeight(max(300, self.win.height() - top - 36))
        x = self.win.width() - self.W - 12 if shown else self.win.width() + 8
        return QPoint(x, top)

    def toggle(self):
        self.opening = not self.isVisible() or not self.opening
        if self.opening:
            self.refresh()
            self.move(self.place(False))
            self.show()
            self.raise_()
        self.anim.stop()
        self.anim.setStartValue(self.pos())
        self.anim.setEndValue(self.place(self.opening))
        self.anim.start()

    def eventFilter(self, obj, e):
        if obj is self.win and e.type() == QEvent.Type.Resize and self.isVisible():
            self.move(self.place(self.opening))
        return False

    def set_read_only(self, on):
        self.win.cfg["ai_write"] = not on
        self.win.update_ai_status()

    def refresh(self):
        if not self.isVisible() and not self.opening:
            return
        self.ro.blockSignals(True)
        self.ro.setChecked(not self.win.cfg.get("ai_write", True))
        self.ro.blockSignals(False)
        self.status.setText(self.win.ai_tip)
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        try:
            items = agent_entries()
        except Exception:
            items = []
        if not items:
            self.rows.addWidget(
                QLabel(
                    "Помощники пока ничего не меняли. Подключите их кнопкой ниже - их действия появятся здесь, "
                    "и любое можно отменить.",
                    objectName="dim",
                    wordWrap=True,
                )
            )
        for e in items:
            self.rows.addWidget(self.row(e))
        self.rows.addStretch(1)

    def row(self, e):
        w = QFrame(objectName="card")
        w.setStyleSheet(f"QFrame#card{{background:{C['bg2']};border:1px solid {C['line']};border-radius:10px}}")
        h = QHBoxLayout(w)
        h.setContentsMargins(10, 8, 8, 8)
        txt = QLabel(
            f"<b>{html.escape(e['who'])}</b> <span style='color:{C['dim']}'>{ago(e['t'])}</span>"
            f"<br>{html.escape(e['text'])}",
            wordWrap=True,
        )
        txt.setTextFormat(Qt.TextFormat.RichText)
        h.addWidget(txt, 1)
        if e["undone"]:
            lbl = QLabel("отменено", objectName="faint")
            h.addWidget(lbl)
        else:
            b = QPushButton("Отменить", objectName="ghost")
            b.clicked.connect(lambda _c=False, i=e["id"]: (self.win.undo(ids={i}), self.refresh()))
            h.addWidget(b)
        return w
