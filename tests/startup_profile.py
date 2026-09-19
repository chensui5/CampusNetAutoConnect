# -*- coding: utf-8 -*-
"""启动耗时剖析：找出打开时卡住的那几秒花在哪。"""

from __future__ import annotations

import os
import sys
import time

os.environ["APPDATA"] = os.environ.get("APPDATA", "")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "QTWEBENGINE_CHROMIUM_FLAGS", "") + " --no-sandbox --disable-gpu"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

T = {"t": time.perf_counter()}


def lap(name):
    now = time.perf_counter()
    print(f"  {name:<34} {now - T['t']:7.3f}s")
    T["t"] = now


print("=== 启动耗时剖析 ===")
lap("import 完成")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
lap("导入 Qt / QtWebEngine")

from core.config import ConfigManager  # noqa: E402
lap("导入 core.config")

import ui.main_window as mw  # noqa: E402
lap("导入 ui.main_window")

app = QApplication(sys.argv[:1])
lap("QApplication 创建")

cfg = ConfigManager()
lap("ConfigManager（读配置+解密密码）")

# 给 MainWindow 的关键步骤打点
for name in ("_build_ui", "_build_tray", "sync_from_cfg",
             "_init_background_uri", "_apply_theme_to_ui",
             "_check_wifi_hardware"):
    if hasattr(mw.MainWindow, name):
        orig = getattr(mw.MainWindow, name)

        def make(orig=orig, name=name):
            def wrapper(self, *a, **k):
                t = time.perf_counter()
                r = orig(self, *a, **k)
                print(f"    · {name:<26} {time.perf_counter() - t:7.3f}s")
                return r
            return wrapper
        setattr(mw.MainWindow, name, make())

t0 = time.perf_counter()
win = mw.MainWindow(cfg, auto_launch=False)
print(f"    · {'MainWindow 构造合计':<26} {time.perf_counter() - t0:7.3f}s")
lap("MainWindow 构造")

win._closing = True
win._set_watchdog(False)

t0 = time.perf_counter()
win.show()
lap("show()")

t0 = time.perf_counter()
app.processEvents()
lap("首次事件处理（布局+绘制）")

# 再画几轮，看阴影缓存是否已经稳定
t0 = time.perf_counter()
for _ in range(3):
    win.repaint()
    app.processEvents()
lap("连续重绘 3 次")

print("\n=== 分项：单个控件首次绘制成本 ===")
from ui.neumorphism import NeuButton, NeuLineEdit, NeuPanel  # noqa: E402
for cls, args in ((NeuButton, ("测试",)), (NeuLineEdit, ()), (NeuPanel, ())):
    w = cls(*args)
    w.resize(200, 44)
    w.show()
    app.processEvents()
    t0 = time.perf_counter()
    w.repaint()
    app.processEvents()
    print(f"  {cls.__name__:<16} 首次 {time.perf_counter() - t0:7.4f}s")
    w.close()

print("\n=== 无线网卡检测 ===")
from core import wifi  # noqa: E402
t0 = time.perf_counter()
wifi.interfaces()
print(f"  wifi.interfaces()      {time.perf_counter() - t0:7.4f}s")
t0 = time.perf_counter()
wifi.current_ssid()
print(f"  wifi.current_ssid()    {time.perf_counter() - t0:7.4f}s")
t0 = time.perf_counter()
wifi.signal_quality()
print(f"  wifi.signal_quality()  {time.perf_counter() - t0:7.4f}s")

print("\n=== 开机自启读取 ===")
from core import autostart  # noqa: E402
t0 = time.perf_counter()
autostart.is_enabled()
print(f"  autostart.is_enabled() {time.perf_counter() - t0:7.4f}s")

print("\n=== 主题应用（QSS 全量重算）===")
from ui.theme import apply_theme  # noqa: E402
t0 = time.perf_counter()
apply_theme(app, "dark")
print(f"  apply_theme(dark)      {time.perf_counter() - t0:7.4f}s")

app.quit()
print("\n完成")
