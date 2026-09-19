# -*- coding: utf-8 -*-
"""真机验证：用真实配置、真实认证页跑一遍连接流程（不注销、不改动网络）。

当前如果在已登录状态，应当走「页面预检 → 判定已登录 → 成功」这条路。
"""

from __future__ import annotations

import os
import sys

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "QTWEBENGINE_CHROMIUM_FLAGS", "") + " --no-sandbox --disable-gpu"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import ConfigManager  # noqa: E402
from core.netcheck import check_online_multi, parse_probes  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


def main():
    app = QApplication(sys.argv[:1])
    cfg = ConfigManager()
    print("认证页地址 :", cfg.settings.url)
    print("账号       :", cfg.settings.username)
    print("密码长度   :", len(cfg.settings.get_password()))

    pr = parse_probes(cfg.settings.probe_url, cfg.settings.probe_keyword)
    ok, detail = check_online_multi(pr, cfg.settings.probe_timeout)
    print(f"当前网络   : {'在线' if ok else '离线'}（{detail[:120]}）")
    print("-" * 60)

    cfg.settings.auto_connect_on_launch = False
    cfg.settings.skip_if_online = False      # 强制走一遍流程
    cfg.settings.retry_times = 0

    win = MainWindow(cfg, auto_launch=False)
    win._closing = True
    win._set_watchdog(False)

    done = {"v": False}

    def on_log(line):
        print("   |", line)

    def on_fin(ok, msg):
        if done["v"]:
            return
        done["v"] = True
        print("\n" + "=" * 60)
        print("结果：", "成功" if ok else "失败", "—", msg)
        rep = win.engine.report or {}
        for st in rep.get("steps", []):
            print(f"   · {st['step']}: {'OK' if st['ok'] else 'NG'} ({st['detail']}, {st['t']}s)")
        for w in rep.get("watch", []):
            print("   watch:", {k: v for k, v in w.items() if k != "snippet"})
        if rep.get("page_errors"):
            print("   页面错误:", rep["page_errors"])
        if rep.get("snapshot"):
            print("   截图:", rep["snapshot"])
        win._closing = True
        app.quit()

    win.engine.log.connect(on_log)
    win.engine.finished.connect(on_fin)
    QTimer.singleShot(500, lambda: win.engine.start("真机验证"))
    QTimer.singleShot(60000, lambda: (print("超时"), app.quit()))
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
