# -*- coding: utf-8 -*-
"""探测：哪种 Chromium flags 组合能让内嵌页面正常加载。"""

import os
import sys
import tempfile

flags = sys.argv[1] if len(sys.argv) > 1 else ""
if flags:
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="probe_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QUrl, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import ConfigManager  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

PAGE = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_login.html"))
out = []

app = QApplication(sys.argv[:1])
cfg = ConfigManager()
cfg.settings.auto_connect_on_launch = False
win = MainWindow(cfg, auto_launch=False)
win._closing = True
win._set_watchdog(False)

win.view.loadFinished.connect(lambda ok: (out.append(ok), app.quit()))
win.view.load(QUrl.fromLocalFile(PAGE))
QTimer.singleShot(12000, app.quit)
app.exec()
print(f"FLAGS=[{flags}] -> loadFinished={out}")
