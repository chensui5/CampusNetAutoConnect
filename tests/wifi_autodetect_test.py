# -*- coding: utf-8 -*-
"""验证「自动识别校园网名」这套逻辑。

用户诉求：
    不想手动填无线网络名，希望程序自己认出哪个网络是校园网，
    连上之后自动连接、自动认证。

设计：
    - 程序在"连上了但被拦到认证页"或"认证成功"时，把该无线网络名记下来
    - 之后只在认识的那些网络上动手；一个都没记住时，任何无线网络都试
      （反正判断依据是"能不能上网"，认错的代价只是白试一次）
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="campusp_auto_")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from core.config import ConfigManager                  # noqa: E402
from ui.main_window import MainWindow                  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))


def pump(app, ms: int) -> None:
    """跑事件循环 ms 毫秒（让定时器和信号处理完）。"""
    done = {"v": False}
    QTimer.singleShot(ms, lambda: done.update(v=True))
    while not done["v"]:
        app.processEvents()


def main() -> int:
    app = QApplication(sys.argv[:1])

    cfg = ConfigManager()
    cfg.settings.wifi_ssid = ""            # 故意不填，考察自动识别
    cfg.settings.wifi_auto_detect = True
    cfg.settings.wifi_known_ssids = []
    cfg.settings.wifi_trigger_enabled = True
    cfg.save()

    win = MainWindow(cfg, auto_launch=False)
    win._closing = True
    win._set_watchdog(False)
    win.show()
    app.processEvents()

    print("[1] 初始状态：还没识别到任何校园网")
    check("识别记录是空的", win.s.wifi_known_ssids == [],
          str(win.s.wifi_known_ssids))
    check("此时任何无线网络都接受（先都试试）",
          win._accept_ssid("CampusWiFi") and win._accept_ssid("HomeWiFi"))
    check("界面提示了尚未识别",
          "尚未识别" in win.lbl_known.text(), win.lbl_known.text())

    print("\n[2] 连上 CampusWiFi，但被拦到认证页 → 应当被记住")
    win._on_wifi_probe(False, "HTTP 302 · 未匹配期望内容（可能被劫持到认证页）", "CampusWiFi")
    pump(app, 300)
    check("已记住 CampusWiFi", "CampusWiFi" in win.s.wifi_known_ssids,
          str(win.s.wifi_known_ssids))
    check("界面已显示出来", "CampusWiFi" in win.lbl_known.text(), win.lbl_known.text())

    print("\n[3] 只认认识的网络了")
    check("CampusWiFi 仍然接受", win._accept_ssid("CampusWiFi"))
    check("HomeWiFi 不再乱试", not win._accept_ssid("HomeWiFi"))

    print("\n[4] 单纯的断网（不是认证页劫持）不该被误记")
    win._on_wifi_probe(False, "连接超时（timeout）", "NeighborWiFi")
    pump(app, 200)
    check("NeighborWiFi 没被记进去",
          "NeighborWiFi" not in win.s.wifi_known_ssids,
          str(win.s.wifi_known_ssids))

    print("\n[5] 认证成功也会记名")
    win._trigger_ssid = "LibraryWiFi"
    win.on_finished(True, "连接成功，网络已通")
    pump(app, 300)
    check("LibraryWiFi 已被记住", "LibraryWiFi" in win.s.wifi_known_ssids,
          str(win.s.wifi_known_ssids))

    print("\n[6] 识别记录会落盘（重启后还在）")
    pump(app, 1200)                      # 等自动保存
    if os.path.exists(cfg.path):
        data = json.load(io.open(cfg.path, encoding="utf-8"))
        check("配置文件里有识别记录",
              "CampusWiFi" in (data.get("wifi_known_ssids") or []),
              str(data.get("wifi_known_ssids")))
        check("wifi_auto_detect 已落盘",
              data.get("wifi_auto_detect") is True,
              str(data.get("wifi_auto_detect")))
    else:
        check("配置文件存在", False, cfg.path)

    cfg2 = ConfigManager()
    check("重新读配置仍有记录",
          "CampusWiFi" in (cfg2.settings.wifi_known_ssids or []),
          str(cfg2.settings.wifi_known_ssids))

    print("\n[7] 手动填的网络名和识别记录会取并集")
    win.ed_ssid.setText("ManualWiFi")
    pump(app, 100)
    check("手填的 ManualWiFi 也接受", win._accept_ssid("ManualWiFi"))
    check("识别出的 CampusWiFi 仍接受", win._accept_ssid("CampusWiFi"))
    check("HomeWiFi 依然不接受", not win._accept_ssid("HomeWiFi"))

    print("\n[8] 清空识别记录")
    win._clear_known_ssids()
    pump(app, 300)
    check("识别记录已清空", win.s.wifi_known_ssids == [],
          str(win.s.wifi_known_ssids))
    check("清空后只剩手填的目标",
          win._accept_ssid("ManualWiFi") and not win._accept_ssid("CampusWiFi"),
          f"ManualWiFi={win._accept_ssid('ManualWiFi')} "
          f"CampusWiFi={win._accept_ssid('CampusWiFi')}")

    print("\n[9] 关掉自动识别后，不记名也不用记录")
    win.ed_ssid.setText("")
    win.cb_wifi_auto.setChecked(False)
    pump(app, 300)
    win._on_wifi_probe(False, "HTTP 302 · 被劫持到认证页", "NewCampus")
    pump(app, 300)
    check("关闭后不再记名",
          "NewCampus" not in (win.s.wifi_known_ssids or []),
          str(win.s.wifi_known_ssids))
    check("关闭后也不拿记录去匹配",
          win._accept_ssid("CampusWiFi"),
          "都关且都不填时回退成『任何网络都试』")
    check("界面上标注了自动识别已关闭",
          "关闭" in win.lbl_known.text(), win.lbl_known.text())

    win.close()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print()
    for name, ok, _ in results:
        if not ok:
            print(f"   未通过：{name}")
    print(f"\n结论：{passed}/{total} 通过")
    app.quit()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
