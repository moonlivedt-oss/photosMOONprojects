"""Карточки ассетов Unreal (вкладка и каталог): у каждого вида свой цвет и своя подача.
Модель и текстура - на «студийном» пятне света с тенью под ними, HDRI и IES - картинкой во всю карточку,
панорама HDRI медленно едет при наведении. Ярлык вида, разрешение, вес, звезда, «уже скачано»."""

import math
import time

from PyQt6.QtCore import QMimeData, QRectF, QSize, Qt, QUrl
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate

from ui.common import PIX
from ui.theme import C
from ui.thumbnails import lib_pix, mix
from ui.widgets import LibList

CARD = Qt.ItemDataRole.UserRole + 12  # словарь подписи карточки (см. card_of)
ASSET = Qt.ItemDataRole.UserRole + 10  # asset.json у плитки вкладки / кандидат у плитки каталога
LOOK = {  # вид -> (ярлык, значок, цвет)
    "tex": ("Текстура", "paint-roller", "#f0a35e"),
    "hdri": ("HDRI", "cloud", "#6cb8ff"),
    "model": ("Модель", "dice_3D", "#a897ff"),
    "ies": ("IES", "lightning-bolt", "#ffd166"),
}
WIDE = ("hdri", "ies")  # картинка во всю карточку, а не предмет на пятне света


def card_of(kind, name, sub="", res="", size="", fav=False, have=False, pickable=False):
    """pickable - карточка каталога: отметка галочкой в кружке справа сверху."""
    return {
        "kind": kind,
        "name": name,
        "sub": sub,
        "res": res,
        "size": size,
        "fav": fav,
        "have": have,
        "pickable": pickable,
    }


def pill(p, rect, text, fg, bg, font, icon=None):
    p.setFont(font)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    x = rect.x() + 7
    if icon is not None and not icon.isNull():
        s = rect.height() - 6
        p.drawPixmap(QRectF(x, rect.y() + 3, s, s), icon, QRectF(icon.rect()))
        x += s + 4
    p.setPen(fg)
    p.drawText(
        QRectF(x, rect.y(), rect.right() - x - 6, rect.height()),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        text,
    )


def pill_width(p, text, font, icon=False, h=20):
    p.setFont(font)
    return p.fontMetrics().horizontalAdvance(text) + 14 + (h - 2 if icon else 0)


class AssetDelegate(QStyledItemDelegate):
    PAD, CAP = 8, 46

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.f1 = QFont("Segoe UI", 9)
        self.f1.setWeight(QFont.Weight.DemiBold)
        self.f2 = QFont("Segoe UI", 8)
        self.f3 = QFont("Segoe UI", 7)
        self.f3.setWeight(QFont.Weight.Bold)

    def sizeHint(self, _o, _i):
        g = self.view.gridSize()
        return g if g.isValid() else QSize(180, 230)

    def paint(self, p, option, index):
        d = index.data(CARD) or {}
        kind = d.get("kind", "model")
        label, icon_name, color = LOOK.get(kind, LOOK["model"])
        col = QColor(color)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        row = index.row()
        h = self.view.hover_amount(row)
        fade = self.view.fade_amount(row)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        r = QRectF(option.rect).adjusted(5, 5 - 3 * h, -5, -5 - 3 * h)

        # тень и свечение цветом вида
        k = max(h, 0.7 if sel else 0)
        if k > 0.01:
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(1, 8):
                p.setBrush(QColor(0, 0, 0, int(26 * k * (1 - i / 8))))
                p.drawRoundedRect(r.adjusted(-i, -i + 5, i, i + 5), 16 + i, 16 + i)
            glow = QColor(col)
            glow.setAlpha(int(55 * k))
            p.setBrush(glow)
            p.drawRoundedRect(r.adjusted(-2.5, -2.5, 2.5, 2.5), 17, 17)

        # карточка
        card = QPainterPath()
        card.addRoundedRect(r, 15, 15)
        base = QColor(C["bg2"])
        top = mix(base, col, 0.10 + 0.10 * h + (0.12 if sel else 0))
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, top)
        g.setColorAt(1, mix(base, QColor(C["bg1"]), 0.5))
        p.fillPath(card, QBrush(g))
        p.setPen(QPen(col if sel else mix(QColor(C["line"]), col, 0.25 + 0.6 * h), 2 if sel else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(card)

        # картинка
        box = QRectF(r.x() + self.PAD, r.y() + self.PAD, r.width() - 2 * self.PAD, r.width() - 2 * self.PAD)
        clip = QPainterPath()
        clip.addRoundedRect(box, 11, 11)
        p.save()
        p.setClipPath(clip)
        pm = index.data(PIX)
        wide = kind in WIDE
        if not wide:  # студийное пятно света под предметом
            rg = QRadialGradient(box.center().x(), box.y() + box.height() * 0.42, box.width() * 0.75)
            spot = QColor(col)
            spot.setAlpha(int(70 + 40 * h))
            rg.setColorAt(0, spot)
            rg.setColorAt(0.55, QColor(col.red(), col.green(), col.blue(), 18))
            rg.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(box, QColor(C["bg0"]))
            p.fillRect(box, QBrush(rg))
            sh = QRadialGradient(box.center().x(), box.bottom() - box.height() * 0.1, box.width() * 0.36)
            sh.setColorAt(0, QColor(0, 0, 0, 120))
            sh.setColorAt(1, QColor(0, 0, 0, 0))
            p.save()
            p.translate(box.center().x(), box.bottom() - box.height() * 0.1)
            p.scale(1, 0.22)
            p.translate(-box.center().x(), -(box.bottom() - box.height() * 0.1))
            p.fillRect(box.adjusted(0, -box.height(), 0, box.height()), QBrush(sh))
            p.restore()
        else:
            p.fillRect(box, QColor(C["bg0"]))
        if isinstance(pm, QPixmap) and not pm.isNull():
            p.setOpacity(fade)
            if wide:  # во всю карточку; панорама едет при наведении
                k2 = max(box.width() / pm.width(), box.height() / pm.height())
                sw, sh2 = box.width() / k2, box.height() / k2
                spare = pm.width() - sw
                t = 0.5
                if kind == "hdri" and h > 0.05 and spare > 1:
                    t = 0.5 + 0.5 * math.sin(time.monotonic() * 0.35 + row)
                src = QRectF(spare * t, (pm.height() - sh2) / 2, sw, sh2)
                z = 1 + 0.04 * h
                dst = QRectF(
                    box.center().x() - box.width() * z / 2,
                    box.center().y() - box.height() * z / 2,
                    box.width() * z,
                    box.height() * z,
                )
                p.drawPixmap(dst, pm, src)
            else:
                m = 0.06 - 0.04 * h  # при наведении предмет чуть крупнее
                inner = box.adjusted(box.width() * m, box.height() * m, -box.width() * m, -box.height() * m)
                kk = min(inner.width() / pm.width(), inner.height() / pm.height())
                w, hh = pm.width() * kk, pm.height() * kk
                p.drawPixmap(
                    QRectF(inner.center().x() - w / 2, inner.center().y() - hh / 2 - 2 * h, w, hh),
                    pm,
                    QRectF(pm.rect()),
                )
            p.setOpacity(1)
        else:  # ещё грузится - перелив
            ph = (time.monotonic() * 0.9 + (r.x() + r.y()) / 1600) % 1.4 - 0.2
            lg = QLinearGradient(box.topLeft(), box.bottomRight())
            lg.setColorAt(0, QColor(C["bg3"]))
            lg.setColorAt(max(0.0, min(1.0, ph)), mix(QColor(C["bg3"]), col, 0.25))
            lg.setColorAt(1, QColor(C["bg2"]))
            p.fillRect(box, QBrush(lg))
            if hasattr(self.view, "shimmer"):
                self.view.shimmer = True
                if not self.view.anim.isActive():
                    self.view.anim.start()
        if wide:  # затемнение снизу, чтобы плашки читались
            vg = QLinearGradient(box.topLeft(), box.bottomLeft())
            vg.setColorAt(0, QColor(0, 0, 0, 70))
            vg.setColorAt(0.3, QColor(0, 0, 0, 0))
            vg.setColorAt(0.75, QColor(0, 0, 0, 0))
            vg.setColorAt(1, QColor(0, 0, 0, 110))
            p.fillRect(box, QBrush(vg))
        p.restore()

        # плашки: вид слева сверху, разрешение справа, вес снизу при наведении
        ph_ = 20
        dark = QColor(13, 13, 19, 205)
        kicon = lib_pix(icon_name, 40)
        kw = pill_width(p, label, self.f3, True, ph_)
        tag_bg = QColor(col)
        tag_bg.setAlpha(225)
        pill(p, QRectF(box.x() + 6, box.y() + 6, kw, ph_), label, QColor("#14121c"), tag_bg, self.f3, kicon)
        x_right = box.right() - 6
        if d.get("res"):
            w = pill_width(p, d["res"], self.f3, False)
            pill(p, QRectF(x_right - w, box.y() + 6, w, ph_), d["res"], QColor(C["text"]), dark, self.f3)
            x_right -= w + 4
        if d.get("fav"):
            c = QRectF(x_right - ph_, box.y() + 6, ph_, ph_)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dark)
            p.drawEllipse(c)
            star = lib_pix("star", 40)
            if not star.isNull():
                p.drawPixmap(c.adjusted(3, 3, -3, -3), star, QRectF(star.rect()))
        if d.get("pickable") and not d.get("have") and (sel or h > 0.05):
            c = QRectF(box.right() - 30, box.y() + 6, 24, 24)
            p.setOpacity(1 if sel else h)
            p.setPen(QPen(QColor("#ffffff"), 1.6))
            p.setBrush(col if sel else dark)
            p.drawEllipse(c)
            if sel:
                ok = lib_pix("checkmark", 40)
                if not ok.isNull():
                    p.drawPixmap(c.adjusted(4, 4, -4, -4), ok, QRectF(ok.rect()))
            p.setOpacity(1)
        if d.get("have"):
            t = "уже есть"
            w = pill_width(p, t, self.f3, False)
            pill(
                p, QRectF(box.x() + 6, box.bottom() - ph_ - 6, w, ph_), t, QColor("#0f1a12"), QColor("#7ee0a0"), self.f3
            )
        if d.get("size") and h > 0.05:
            p.setOpacity(h)
            w = pill_width(p, d["size"], self.f3, False)
            pill(
                p,
                QRectF(box.right() - w - 6, box.bottom() - ph_ - 6, w, ph_),
                d["size"],
                QColor(C["text"]),
                dark,
                self.f3,
            )
            p.setOpacity(1)

        # черта цвета вида под картинкой
        line = QLinearGradient(box.bottomLeft(), box.bottomRight())
        line.setColorAt(0, QColor(col.red(), col.green(), col.blue(), 0))
        line.setColorAt(0.5, col)
        line.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(line))
        p.drawRoundedRect(QRectF(box.x() + 10, box.bottom() + 4, box.width() - 20, 2), 1, 1)

        # подписи
        tr = QRectF(r.x() + 10, box.bottom() + 9, r.width() - 20, 18)
        p.setFont(self.f1)
        p.setPen(QColor(C["selt"] if sel else C["text"]))
        p.drawText(
            tr,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            p.fontMetrics().elidedText(d.get("name", ""), Qt.TextElideMode.ElideRight, int(tr.width())),
        )
        p.setFont(self.f2)
        p.setPen(QColor(C["dim"]))
        p.drawText(
            tr.translated(0, 17),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            p.fontMetrics().elidedText(d.get("sub", ""), Qt.TextElideMode.ElideRight, int(tr.width())),
        )
        p.restore()


class CardList(LibList):
    """Плитки-карточки ассетов; drag_paths(items) - какие файлы отдать при перетаскивании."""

    def __init__(self, side, drag_paths=None):
        super().__init__(side)
        self.drag_paths = drag_paths
        self.setItemDelegate(AssetDelegate(self))

    def relayout(self):
        w = max(1, self.viewport().width() - 8)  # впритык Qt переносит последний столбец на новую строку
        cols = max(1, w // (self.base + 28))
        cell = w // cols
        self.setGridSize(QSize(cell, cell + AssetDelegate.CAP))

    def tick(self):
        super().tick()
        # наведённая панорама HDRI едет - держим перерисовку, пока мышь на ней
        it = self.item(self.hover_row) if self.hover_row >= 0 else None
        if it is not None and (it.data(CARD) or {}).get("kind") == "hdri" and not self.anim.isActive():
            self.anim.start()

    def mimeData(self, items):
        md = QMimeData()
        if self.drag_paths:
            md.setUrls([QUrl.fromLocalFile(p) for p in self.drag_paths(items)])
        return md
