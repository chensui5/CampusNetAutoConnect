# -*- coding: utf-8 -*-
"""打包为 Windows 可执行程序。

用法：
    python build.py            # 生成图标 + 打包
    python build.py --icon     # 只生成图标
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(ROOT, "assets", "app.ico")
APP_NAME = "CampusNetAutoConnect"
ACCENT = "#6d5dfc"


def make_icon(path: str = ICON) -> str:
    """用代码画一个 WiFi 图标并写成多尺寸 ICO（内嵌 PNG）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sys.path.insert(0, ROOT)
    from PySide6.QtCore import Qt, QBuffer, QIODevice, QByteArray
    from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pngs = []
    for s in sizes:
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        k = s / 64.0
        pen = QPen(QColor(ACCENT))
        pen.setCapStyle(Qt.RoundCap)
        for i, inset in enumerate((6, 18, 30)):
            pen.setWidth(max(1, round((6 if i == 2 else 5) * k)))
            p.setPen(pen)
            p.drawArc(int(inset * k), int(inset * k),
                      int((64 - inset * 2) * k), int((64 - inset * 2) * k),
                      315 * 16, 270 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawEllipse(int(26 * k), int(26 * k), max(2, round(12 * k)), max(2, round(12 * k)))
        p.end()
        buf = QByteArray()
        b = QBuffer(buf)
        b.open(QIODevice.WriteOnly)
        pm.save(b, "PNG")
        b.close()
        pngs.append(bytes(buf))

    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for s, png in zip(sizes, pngs):
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                               len(png), offset + len(data))
        data += png
    with open(path, "wb") as f:
        f.write(header + entries + data)
    print(f"图标已生成：{path}")
    return path


def build():
    icon = make_icon()
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed", "--onedir",
        "--name", APP_NAME,
        "--icon", icon,
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
    ]
    for mod in ("PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
                "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
                "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
                "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL"):
        cmd += ["--exclude-module", mod]
    cmd.append(os.path.join(ROOT, "main.py"))
    print("开始打包…")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode == 0:
        print(f"完成：{os.path.join(ROOT, 'dist', APP_NAME, APP_NAME + '.exe')}")
    return r.returncode


if __name__ == "__main__":
    if "--icon" in sys.argv:
        make_icon()
    else:
        sys.exit(build())
