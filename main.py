# -*- coding: utf-8 -*-
"""校园网自动连接 —— 程序入口。

作者：尘遂
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if not getattr(sys, "frozen", False) and _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core.config import ConfigManager, APP_TITLE  # noqa: E402

# Chromium 的启动参数必须在 QApplication 之前设置。
_cfg = ConfigManager()
if _cfg.settings.browser_compat_mode:
    _extra = "--no-sandbox --disable-gpu"
    _old = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--no-sandbox" not in _old:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (_old + " " + _extra).strip()

# 让内嵌浏览器也跟随系统缩放，避免高分屏下字体发虚
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402

from ui.main_window import MainWindow, make_app_icon  # noqa: E402

SERVER_NAME = "CampusNetAutoConnect-SingleInstance"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("CampusNetAutoConnect")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_app_icon())

    # —— 单实例：已在运行则唤起已有窗口 ——
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show\n")
        sock.flush()
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    auto_launch = "--auto" in sys.argv
    win = MainWindow(_cfg, auto_launch=auto_launch)

    def on_new_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def handle():
            try:
                conn.readAll()
            except Exception:
                pass
            win.show_normal()
            conn.close()

        conn.readyRead.connect(handle)

    server.newConnection.connect(on_new_connection)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
