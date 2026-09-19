# -*- coding: utf-8 -*-
"""风格放大预览：把各控件 2 倍渲染出来，用于校准阴影参数。"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QPixmap, QColor  # noqa: E402
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,  # noqa: E402
                               QLabel, QGridLayout)

from ui import neumorphism as neu  # noqa: E402
from ui.neumorphism import (NeuButton, NeuLineEdit, NeuPanel, NeuCheckBox,  # noqa: E402
                            NeuRadioButton, NeuSlider, NeuSpinBox, NeuComboBox, NeuDot)

SHOTS = os.path.join(ROOT, "_shots")


class Preview(QWidget):
    def __init__(self, mode="light"):
        super().__init__()
        neu.set_palette(mode)
        p = neu.palette()
        self.setStyleSheet(
            f"QWidget{{background:{p['bg']};color:{p['text']};"
            f"font-family:'Microsoft YaHei UI';font-size:13px;}}"
            f"QLineEdit{{background:transparent;border:none;padding:5px 10px;color:{p['text']};}}")
        self.setFixedSize(700, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 24)
        root.setSpacing(22)

        # 按钮
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(18)
        b1 = NeuButton("标准按钮")
        b2 = NeuButton("主按钮", accent=True)
        b3 = NeuButton("禁用", compact=True)
        b3.setEnabled(False)
        b4 = NeuButton("已按下")
        b4.setDown(True)
        for b in (b1, b2, b3, b4):
            h.addWidget(b)
        h.addStretch(1)
        root.addWidget(row)

        # 输入框
        e1 = NeuLineEdit()
        e1.setPlaceholderText("请输入学号")
        e2 = NeuLineEdit(password=True)
        e2.setText("password123")
        row2 = QWidget()
        h2 = QHBoxLayout(row2)
        h2.setContentsMargins(0, 0, 0, 0)
        h2.setSpacing(18)
        h2.addWidget(e1, 1)
        h2.addWidget(e2, 1)
        root.addWidget(row2)

        # 组合控件
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(16)
        grid.addWidget(NeuCheckBox("记住我"), 0, 0)
        cb2 = NeuCheckBox("已勾选")
        cb2.setChecked(True)
        grid.addWidget(cb2, 0, 1)
        grid.addWidget(NeuRadioButton("浅色"), 0, 2)
        rb2 = NeuRadioButton("深色")
        rb2.setChecked(True)
        grid.addWidget(rb2, 0, 3)
        root.addLayout(grid)

        row3 = QWidget()
        h3 = QHBoxLayout(row3)
        h3.setContentsMargins(0, 0, 0, 0)
        h3.setSpacing(18)
        sl = NeuSlider()
        sl.setValue(45)
        h3.addWidget(sl, 1)
        sp = NeuSpinBox()
        sp.setValue(60)
        sp.setSuffix(" 秒")
        h3.addWidget(sp)
        cbo = NeuComboBox()
        cbo.addItems(["铺满（cover）", "适应（contain）"])
        h3.addWidget(cbo)
        h3.addWidget(NeuDot(color_key="success"))
        root.addWidget(row3)

        # 卡片
        card = NeuPanel()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        t = QLabel("这是卡片容器")
        t.setStyleSheet("background:transparent;font-size:15px;font-weight:bold;")
        cl.addWidget(t)
        s = QLabel("同色系表面，靠双光源阴影与背景区分层次")
        s.setStyleSheet("background:transparent;color:#6b7280;font-size:12px;")
        cl.addWidget(s)
        root.addWidget(card, 1)

    def shoot(self, name):
        os.makedirs(SHOTS, exist_ok=True)
        pm = self.grab()
        pm.scaled(pm.width() * 2, pm.height() * 2, Qt.KeepAspectRatio,
                  Qt.SmoothTransformation).save(os.path.join(SHOTS, name))
        print("saved", name)


def main():
    app = QApplication(sys.argv)
    state = {"w": None}

    def stage(mode, nxt):
        w = Preview(mode)
        state["w"] = w
        w.show()
        QTimer.singleShot(450, lambda: (w.shoot(f"preview_{mode}.png"), w.close(), nxt()))

    def done():
        app.quit()

    stage("light", lambda: stage("dark", done))
    QTimer.singleShot(4000, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
