# -*- coding: utf-8 -*-
"""Neumorphism（新拟物派）风格引擎。

把 Web 端的 Tailwind 规则翻译成 Qt 的绘制规则：

    凸起（Default）   : 右下暗影 + 左上高光
    悬停（Hover）     : 阴影缩小（手指靠近遮光），不位移
    按下（Active）    : 转为 inset 凹陷，不位移
    输入框（Default） : 深 inset，聚焦时 inset 变浅（通道打开）

光源方向恒定：-X/-Y = 白高光，#+X/+Y = 暗影。
由于 QSS 不支持 box-shadow，这里用 QPainter 多层叠加近似高斯弥散，
并把结果缓存成 QPixmap，避免重复绘制。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QSize, QPointF
from PySide6.QtGui import (QPainter, QColor, QPainterPath, QPixmap, QPolygonF)
from PySide6.QtWidgets import (
    QPushButton, QLineEdit, QTextEdit, QCheckBox, QRadioButton, QSlider,
    QFrame, QTabBar, QSpinBox, QComboBox, QSizePolicy, QWidget,
)

# ---------------------------------------------------------------- 调色板

PALETTES = {
    # 浅色新拟物：单色系 + 双重光源
    "light": {
        "bg":          "#e0e5ec",
        "surface":     "#e0e5ec",
        "surface2":    "#f0f0f3",
        "shadow_dark": "#b8bcc2",
        "shadow_light": "#ffffff",
        "accent":      "#6d5dfc",
        "accent_text": "#ffffff",
        "text":        "#333333",
        "text2":       "#6b7280",
        "text3":       "#9aa2b1",
        "success":     "#2f9e79",
        "warn":        "#b8860b",
        "danger":      "#d9534f",
        "hover":       "#d8dde4",
        "is_light":    True,
    },
    # 深色新拟物：同色系深灰 + 双光源（非纯黑，光源方向不变）
    "dark": {
        "bg":          "#262a31",
        "surface":     "#262a31",
        "surface2":    "#2c313a",
        "shadow_dark": "#1b1e24",
        "shadow_light": "#343b45",
        "accent":      "#7d6dff",
        "accent_text": "#ffffff",
        "text":        "#e6e9ef",
        "text2":       "#9aa2b1",
        "text3":       "#6c7480",
        "success":     "#3ecf8e",
        "warn":        "#ffb020",
        "danger":      "#ff6b6b",
        "hover":       "#2f353e",
        "is_light":    False,
    },
}

_current = dict(PALETTES["light"])


def set_palette(mode: str) -> dict:
    global _current
    _current = dict(PALETTES.get(mode, PALETTES["light"]))
    _CACHE.clear()
    return _current


def palette() -> dict:
    return _current


def c(key: str, alpha: int | None = None) -> QColor:
    col = QColor(_current.get(key, "#808080"))
    if alpha is not None:
        col.setAlpha(alpha)
    return col


# ---------------------------------------------------------------- 绘制原语

_STEPS = 16          # 弥散层数，越大越柔和
_CACHE: dict = {}


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _falloff(i: int, steps: int = _STEPS) -> float:
    """离元素边缘越远越淡（i=1 紧贴边缘，最浓）。"""
    return (1.0 - (i - 1) / steps) ** 1.35


def paint_raised(p: QPainter, rect: QRectF, radius: float,
                 size: float = 10.0, strength: float = 1.0,
                 fill_key: str = "surface") -> None:
    """凸起：右下暗影 + 左上高光 + 同色本体。

    用同心环带逐层扩散，避免实心叠加在内侧饱和成硬边。
    """
    dark = c("shadow_dark")
    light = c("shadow_light")
    band = size / _STEPS
    p.save()
    p.setPen(Qt.NoPen)

    for i in range(1, _STEPS + 1):            # 右下暗影
        off = size * i / _STEPS
        a = int(185 * _falloff(i) * strength)
        if a < 1:
            continue
        col = QColor(dark)
        col.setAlpha(a)
        outer = rounded_path(rect.translated(off, off), radius)
        inner = rounded_path(rect.translated(off - band, off - band), radius)
        p.fillPath(outer.subtracted(inner), col)

    for i in range(1, _STEPS + 1):            # 左上高光
        off = size * i / _STEPS
        a = int(215 * _falloff(i) * strength)
        if a < 1:
            continue
        col = QColor(light)
        col.setAlpha(a)
        outer = rounded_path(rect.translated(-off, -off), radius)
        inner = rounded_path(rect.translated(-off + band, -off + band), radius)
        p.fillPath(outer.subtracted(inner), col)

    p.setBrush(c(fill_key))
    p.drawRoundedRect(rect, radius, radius)
    p.restore()


def paint_inset(p: QPainter, rect: QRectF, radius: float,
                size: float = 7.0, strength: float = 1.0,
                fill_key: str = "surface") -> None:
    """凹陷：内部左上暗影 + 右下高光（光源方向与凸起一致）。"""
    outer = rounded_path(rect, radius)
    dark = c("shadow_dark")
    light = c("shadow_light")
    p.save()
    p.setClipPath(outer)
    p.fillPath(outer, c(fill_key))
    p.setPen(Qt.NoPen)
    for i in range(1, _STEPS + 1):            # 左上内侧暗影
        off = size * i / _STEPS
        a = int(160 * _falloff(i) * strength)
        if a < 1:
            continue
        col = QColor(dark)
        col.setAlpha(a)
        inner = rounded_path(rect.adjusted(off, off, off, off), radius)
        p.fillPath(outer.subtracted(inner), col)
    for i in range(1, _STEPS + 1):            # 右下内侧高光
        off = size * i / _STEPS
        a = int(185 * _falloff(i) * strength)
        if a < 1:
            continue
        col = QColor(light)
        col.setAlpha(a)
        inner = rounded_path(rect.adjusted(-off, -off, -off, -off), radius)
        p.fillPath(outer.subtracted(inner), col)
    p.restore()


def paint_flat(p: QPainter, rect: QRectF, radius: float, fill_key: str = "surface",
               alpha: int | None = None) -> None:
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(c(fill_key, alpha))
    p.drawRoundedRect(rect, radius, radius)
    p.restore()


def _shadow_pixmap(owner, key, size: QSize, dpr: float, draw) -> QPixmap:
    """把阴影绘制结果缓存成位图（挂在控件实例上），避免每帧重画几十层圆角矩形。"""
    cache = owner.__dict__.setdefault("_neu_cache", {})
    hit = cache.get(key)
    if hit is not None:
        return hit
    pm = QPixmap(max(1, int(size.width() * dpr)), max(1, int(size.height() * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    draw(p)
    p.end()
    if len(cache) > 60:
        cache.clear()
    cache[key] = pm
    return pm


# ---------------------------------------------------------------- 基类

class NeuMixin:
    """自绘背景的公共逻辑。"""

    _pad = 10          # 给阴影留出的边距
    _radius = 12

    def _dpr(self) -> float:
        try:
            return float(self.devicePixelRatioF())
        except Exception:
            return 1.0

    def _state_key(self) -> tuple:
        return (id(palette()), )

    def _bg(self, w: int, h: int, kind: str, hover: bool = False,
            strength: float = 1.0, fill_key: str = "surface") -> QPixmap:
        dpr = self._dpr()
        key = (w, h, kind, hover, round(strength, 2), self._radius,
               palette()["bg"], dpr, fill_key)

        def draw(p: QPainter):
            r = QRectF(self._pad, self._pad, w - self._pad * 2, h - self._pad * 2)
            if kind == "raised":
                paint_raised(p, r, self._radius,
                             size=4.0 if hover else 8.0, strength=strength,
                             fill_key=fill_key)
            elif kind == "inset":
                paint_inset(p, r, self._radius,
                            size=4.5 if hover else 8.0, strength=strength,
                            fill_key=fill_key)
            elif kind == "deep":
                paint_inset(p, r, self._radius, size=9.0, strength=strength,
                            fill_key=fill_key)
            else:
                paint_flat(p, r, self._radius)

        return _shadow_pixmap(self, key, QSize(w, h), dpr, draw)

    def _content_rect(self) -> QRectF:
        return QRectF(self._pad, self._pad,
                      self.width() - self._pad * 2, self.height() - self._pad * 2)


# ---------------------------------------------------------------- 控件

class NeuButton(QPushButton, NeuMixin):
    """凸起按钮：hover 收阴影，press 转凹陷，全程不位移。"""

    def __init__(self, text="", parent=None, accent=False, danger=False, compact=False):
        super().__init__(text, parent)
        self._accent = accent
        self._danger = danger
        self._compact = compact
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self._radius = 12
        self._pad = 9
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def setAccent(self, on: bool):
        self._accent = on
        self.update()

    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        return QSize(base.width() + self._pad * 2 + (10 if self._compact else 20),
                     base.height() + self._pad * 2 + (2 if self._compact else 8))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pressed = self.isDown() or (self.isCheckable() and self.isChecked())
        w, h = self.width(), self.height()
        strength = 1.0 if self.isEnabled() else 0.4
        fill = "accent" if self._accent else "surface"
        if pressed:
            p.drawPixmap(0, 0, self._bg(w, h, "inset", hover=False,
                                        strength=strength, fill_key=fill))
        else:
            p.drawPixmap(0, 0, self._bg(w, h, "raised", hover=self._hover,
                                        strength=strength, fill_key=fill))

        r = self._content_rect().toRect()
        if self._accent:
            pen_col = c("accent_text")
        else:
            pen_col = c("danger") if self._danger else c("text")
        if not self.isEnabled():
            pen_col = c("text3")

        font = self.font()
        if self._accent:
            font.setBold(True)
        p.setFont(font)
        p.setPen(pen_col)
        p.drawText(r, Qt.AlignCenter, self.text())
        p.end()


class NeuLineEdit(QLineEdit, NeuMixin):
    """输入框：默认深凹陷，聚焦时凹陷变浅（惰性收缩）。"""

    def __init__(self, parent=None, password=False):
        super().__init__(parent)
        self._radius = 12
        self._pad = 9
        self._focus = False
        if password:
            self.setEchoMode(QLineEdit.Password)
        self.setAttribute(Qt.WA_MacShowFocusRect, False)

    def sizeHint(self) -> QSize:
        b = super().sizeHint()
        return QSize(b.width() + self._pad * 2, b.height() + self._pad * 2 + 4)

    def minimumSizeHint(self) -> QSize:
        return QSize(80, self.sizeHint().height())

    def focusInEvent(self, e):
        self._focus = True
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._focus = False
        self.update()
        super().focusOutEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawPixmap(0, 0, self._bg(self.width(), self.height(),
                                    "raised" if self._focus else "deep"))
        p.end()
        # 文本交给原生实现，QSS 已把背景/边框设为透明
        super().paintEvent(e)


class NeuTextEdit(QTextEdit, NeuMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._radius = 12
        self._pad = 10

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawPixmap(0, 0, self._bg(self.width(), self.height(), "deep"))
        p.end()
        super().paintEvent(e)


class NeuPanel(QFrame):
    """同色系卡片/分组容器，靠凸起阴影与背景区分。"""

    def __init__(self, parent=None, radius=16, pad=16, inset=False):
        super().__init__(parent)
        self._radius = radius
        self._pad = pad
        self._inset = inset
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setContentsMargins(pad, pad, pad, pad)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = 9.0 if self._inset else 10.0
        r = QRectF(11, 11, self.width() - 22, self.height() - 22)
        if self._inset:
            paint_inset(p, r, self._radius, size=s)
        else:
            paint_raised(p, r, self._radius, size=s)
        p.end()


class NeuCheckBox(QCheckBox):
    """自绘复选框：未选中凸起，选中凹陷 + 强调色对勾。"""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._hover = False
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(39 + 10 + fm.horizontalAdvance(self.text()) + 8,
                     max(34, fm.height() + 16))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        box = QRectF(9, (self.height() - 21) / 2, 21, 21)
        if self.isChecked():
            paint_inset(p, box, 8, size=6.0)
            p.setPen(Qt.NoPen)
            p.setBrush(c("accent"))
            p.drawRoundedRect(box.adjusted(5, 5, -5, -5), 4, 4)
        else:
            paint_raised(p, box, 8, size=4.0 if self._hover else 6.0)
        p.setPen(c("text") if self.isEnabled() else c("text3"))
        p.setFont(self.font())
        p.drawText(QRectF(39, 0, self.width() - 39, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class NeuRadioButton(QRadioButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._hover = False
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(39 + 10 + fm.horizontalAdvance(self.text()) + 8,
                     max(34, fm.height() + 16))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        box = QRectF(9, (self.height() - 21) / 2, 21, 21)
        if self.isChecked():
            paint_inset(p, box, 11, size=6.0)
            p.setPen(Qt.NoPen)
            p.setBrush(c("accent"))
            p.drawEllipse(box.center(), 6, 6)
        else:
            paint_raised(p, box, 11, size=4.0 if self._hover else 6.0)
        p.setPen(c("text") if self.isEnabled() else c("text3"))
        p.setFont(self.font())
        p.drawText(QRectF(39, 0, self.width() - 39, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class NeuSlider(QSlider):
    """凹槽轨道 + 凸起滑块，交互不位移。"""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._hover = False
        self._pad = 6
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(180, 44)

    def minimumSizeHint(self) -> QSize:
        return QSize(120, 44)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def _handle_center(self) -> QPointF:
        span = self.maximum() - self.minimum()
        t = 0.0 if span <= 0 else (self.value() - self.minimum()) / span
        d = 24.0
        x = 6 + d / 2 + t * (self.width() - 12 - d)
        return QPointF(x, self.height() / 2)

    def _value_from_x(self, x: float) -> int:
        d = 24.0
        usable = max(1.0, self.width() - 12 - d)
        t = (x - 6 - d / 2) / usable
        t = min(1.0, max(0.0, t))
        span = self.maximum() - self.minimum()
        return int(round(self.minimum() + t * span))

    def mousePressEvent(self, e):
        self.setValue(self._value_from_x(e.position().x()))
        e.accept()

    def mouseMoveEvent(self, e):
        self.setValue(self._value_from_x(e.position().x()))
        e.accept()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        track = QRectF(6, self.height() / 2 - 6, self.width() - 12, 12)
        paint_inset(p, track, 6, size=6.0)
        center = self._handle_center()
        # 已选进度：强调色薄层
        p.setPen(Qt.NoPen)
        p.setBrush(c("accent", 90))
        prog = QRectF(track.left() + 4, track.top() + 4,
                      max(0.0, center.x() - track.left() - 4), track.height() - 8)
        p.drawRoundedRect(prog, 3, 3)
        handle = QRectF(center.x() - 12, center.y() - 12, 24, 24)
        paint_raised(p, handle, 12, size=4.0 if self._hover else 6.0)
        p.setPen(Qt.NoPen)
        p.setBrush(c("accent"))
        p.drawEllipse(center, 5, 5)
        p.end()


class NeuSpinBox(QSpinBox):
    """凹陷数值框 + 自绘上下箭头。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._radius = 12
        self._pad = 9
        self.setButtonSymbols(QSpinBox.NoButtons)
        self.setFrame(False)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def sizeHint(self) -> QSize:
        b = super().sizeHint()
        return QSize(max(b.width() + self._pad * 2 + 26, 110), b.height() + self._pad * 2 + 4)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        h = self.height()
        r = QRectF(self._pad, self._pad, self.width() - self._pad * 2, h - self._pad * 2)
        paint_inset(p, r, self._radius, size=8.0)
        p.end()
        # 上下箭头（不调 super，避免默认边框和按钮残留）
        p2 = QPainter(self)
        p2.setRenderHint(QPainter.Antialiasing, True)
        cx = self.width() - self._pad - 13
        up = self._hover_up = QRectF(cx - 8, h / 2 - 16, 16, 14)
        dn = QRectF(cx - 8, h / 2 + 2, 16, 14)
        p2.setPen(Qt.NoPen)
        p2.setBrush(c("text2"))
        p2.drawPolygon(QPolygonF([QPointF(up.center().x(), up.top() + 2),
                                  QPointF(up.left() + 3, up.bottom() - 2),
                                  QPointF(up.right() - 3, up.bottom() - 2)]))
        p2.drawPolygon(QPolygonF([QPointF(dn.center().x(), dn.bottom() - 2),
                                  QPointF(dn.left() + 3, dn.top() + 2),
                                  QPointF(dn.right() - 3, dn.top() + 2)]))
        p2.end()

    def mousePressEvent(self, e):
        h = self.height()
        cx = self.width() - self._pad - 13
        if e.position().x() >= cx - 10:
            if e.position().y() < h / 2:
                self.stepUp()
            else:
                self.stepDown()
            e.accept()
            return
        super().mousePressEvent(e)


class NeuComboBox(QComboBox):
    """凹陷选择框 + 自绘箭头。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._radius = 12
        self._pad = 9
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        b = super().sizeHint()
        return QSize(max(b.width() + self._pad * 2 + 24, 130), b.height() + self._pad * 2 + 4)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        h = self.height()
        r = QRectF(self._pad, self._pad, self.width() - self._pad * 2, h - self._pad * 2)
        paint_inset(p, r, self._radius, size=8.0)
        p.setPen(c("text"))
        p.setFont(self.font())
        text_rect = r.adjusted(14, 0, -30, 0)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                   self.fontMetrics().elidedText(self.currentText(),
                                                 Qt.ElideRight, int(text_rect.width())))
        cx = self.width() - self._pad - 16
        cy = h / 2
        p.setPen(Qt.NoPen)
        p.setBrush(c("text2"))
        p.drawPolygon(QPolygonF([QPointF(cx - 5, cy - 2),
                                 QPointF(cx + 5, cy - 2),
                                 QPointF(cx, cy + 4)]))
        p.end()


class NeuTabBar(QTabBar):
    """选中凸起、未选中平铺的标签条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_index = -1

    def tabSizeHint(self, index: int) -> QSize:
        s = super().tabSizeHint(index)
        return QSize(s.width() + 34, max(44, s.height() + 14))

    def enterEvent(self, e):
        self._hover_index = self.tabAt(e.position().toPoint())
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover_index = -1
        self.update()
        super().leaveEvent(e)

    def mouseMoveEvent(self, e):
        idx = self.tabAt(e.position().toPoint())
        if idx != self._hover_index:
            self._hover_index = idx
            self.update()
        super().mouseMoveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cur = self.currentIndex()
        for i in range(self.count()):
            r = QRectF(self.tabRect(i)).adjusted(4, 5, -4, -5)
            if i == cur:
                paint_raised(p, r, 12, size=6.0)
            else:
                paint_flat(p, r, 12, fill_key="surface")
                if i == self._hover_index:
                    p.setPen(Qt.NoPen)
                    p.setBrush(c("hover"))
                    p.drawRoundedRect(r, 12, 12)
            p.setPen(c("accent") if i == cur else c("text2"))
            f = self.font()
            f.setBold(i == cur)
            p.setFont(f)
            p.drawText(r, Qt.AlignCenter, self.tabText(i))
        p.end()


class NeuDot(QWidget):
    """状态指示灯：凹槽 + 发光圆点。"""

    def __init__(self, parent=None, color_key="text3"):
        super().__init__(parent)
        self._key = color_key
        self.setFixedSize(34, 34)

    def set_color(self, key: str):
        self._key = key
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(7, 7, 20, 20)
        paint_inset(p, r, 10, size=6.0)
        p.setPen(Qt.NoPen)
        col = c(self._key)
        glow = QColor(col)
        glow.setAlpha(70)
        p.setBrush(glow)
        p.drawEllipse(r.center(), 9, 9)
        p.setBrush(col)
        p.drawEllipse(r.center(), 5.5, 5.5)
        p.end()
