# -*- coding: utf-8 -*-
"""验证「改设置能不能自动落盘」。

为什么要有这个测试：
用户反馈「勾上『启动后自动连接校园网』，重启后又变回没勾」。
根因是 save_from_ui()（把界面状态收进配置）只被【保存配置】按钮调用，
而自动保存走的是 _dirty() → 定时器 → _do_save() → cfg.save()，
_do_save 直接把内存里那份**旧**配置写盘，从不回头读界面。

所以这个测试只做一件事：改界面 → 等自动保存 → 读文件，看值有没有进去。
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="campusp_test_")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from core.config import ConfigManager                  # noqa: E402
from ui.main_window import MainWindow                  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))


def read_cfg(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    app = QApplication(sys.argv[:1])

    cfg = ConfigManager()
    cfg.settings.auto_connect_on_launch = False     # 模拟"当前是关的"
    cfg.settings.start_delay = 8
    cfg.settings.wifi_ssid = "OldWiFi"
    cfg.save()

    win = MainWindow(cfg, auto_launch=False)
    win._closing = True
    win._set_watchdog(False)
    win.show()
    app.processEvents()

    print(f"  配置文件: {cfg.path}")
    print()

    # ---------- 1) 界面初始状态应与文件一致 ----------
    print("[1] 初始同步")
    check("复选框读到了文件里的值（False）",
          win.cb_auto_connect.isChecked() is False,
          f"isChecked={win.cb_auto_connect.isChecked()}")
    check("无线网络名读到了文件里的值",
          win.ed_ssid.text() == "OldWiFi",
          win.ed_ssid.text())

    # ---------- 2) 改界面，等自动保存 ----------
    print("\n[2] 改界面 → 等自动保存（不点【保存配置】）")
    win.cb_auto_connect.setChecked(True)
    win.sp_delay.setValue(20)
    win.ed_ssid.setText("NewWiFi")
    print("  已改动：勾选自动连接 / 延迟 20 秒 / 网络名 NewWiFi")
    print("  等待 1.5 秒让自动保存触发…")

    done = {"v": False}

    def after_wait():
        done["v"] = True

    QTimer.singleShot(1500, after_wait)
    while not done["v"]:
        app.processEvents()

    data = read_cfg(cfg.path)
    print(f"\n  落盘内容：auto_connect_on_launch={data.get('auto_connect_on_launch')!r}"
          f"  start_delay={data.get('start_delay')!r}  wifi_ssid={data.get('wifi_ssid')!r}")

    check("「启动后自动连接」改动已落盘",
          data.get("auto_connect_on_launch") is True,
          f"实际={data.get('auto_connect_on_launch')!r}")
    check("「启动后延迟」改动已落盘",
          data.get("start_delay") == 20,
          f"实际={data.get('start_delay')!r}")
    check("「无线网络名」改动已落盘",
          data.get("wifi_ssid") == "NewWiFi",
          f"实际={data.get('wifi_ssid')!r}")

    # ---------- 3) 反过来：取消勾选也要落盘 ----------
    print("\n[3] 反向验证：取消勾选也要落盘")
    win.cb_auto_connect.setChecked(False)
    done["v"] = False
    QTimer.singleShot(1500, after_wait)
    while not done["v"]:
        app.processEvents()
    data = read_cfg(cfg.path)
    check("取消勾选已落盘",
          data.get("auto_connect_on_launch") is False,
          f"实际={data.get('auto_connect_on_launch')!r}")

    # ---------- 4) 模拟重启：新窗口应读回改动后的值 ----------
    print("\n[4] 模拟重启：重新读配置")
    win.cb_auto_connect.setChecked(True)
    done["v"] = False
    QTimer.singleShot(1500, after_wait)
    while not done["v"]:
        app.processEvents()

    win.close()
    cfg2 = ConfigManager()
    check("重启后配置里仍是勾选状态",
          cfg2.settings.auto_connect_on_launch is True,
          f"实际={cfg2.settings.auto_connect_on_launch!r}")

    win2 = MainWindow(cfg2, auto_launch=False)
    win2._closing = True
    win2._set_watchdog(False)
    app.processEvents()
    check("重启后界面复选框是勾上的（这就是用户抱怨的那一项）",
          win2.cb_auto_connect.isChecked() is True,
          f"isChecked={win2.cb_auto_connect.isChecked()}")
    win2.close()

    # ---------- 汇总 ----------
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print()
    for name, ok, _ in results:
        if not ok:
            print(f"   未通过：{name}")
    print(f"\n结论：{passed}/{total} 通过")
    if passed != total:
        print("→ 说明「改设置不落盘」的 bug 仍然存在")
    else:
        print("→ 改动能自动落盘了")

    app.quit()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
