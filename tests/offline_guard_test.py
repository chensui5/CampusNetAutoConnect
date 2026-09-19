# -*- coding: utf-8 -*-
"""验证针对用户反馈做的四项改动。

1. 没连无线网络时，自动触发不能瞎跑（前置检查）
2. 掉线时能把校园网连回来（可开关）
3. 预览页可以关掉（浏览器转后台，不再上屏渲染）
4. 页面打不开时立刻换地址、以及「连账号密码框都没有」时不空转 9 轮

全部用替身（monkey-patch）驱动，不会真的动用户的网络。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

# 与 main.py 保持一致：反节流参数是"后台也能填表"的前提
_FLAGS = ("--no-sandbox --disable-gpu "
          "--disable-background-timer-throttling "
          "--disable-backgrounding-occluded-windows "
          "--disable-renderer-backgrounding "
          "--disable-features=CalculateNativeWinOcclusion")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _FLAGS
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="campusp_guard_")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

from core import wifi                                   # noqa: E402
from core.config import ConfigManager                   # noqa: E402
from ui.main_window import MainWindow                   # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))


def pump(app, ms: int) -> None:
    done = {"v": False}
    QTimer.singleShot(ms, lambda: done.update(v=True))
    while not done["v"]:
        app.processEvents()


def main() -> int:
    app = QApplication(sys.argv[:1])

    # ---- 无线状态换成可控替身 ----
    # 界面模块引用的是同一个模块对象，替换模块属性即可生效
    fake = {"ssid": "EZU"}
    connects: list[str] = []

    def fake_ssid():
        return fake["ssid"]

    def fake_connect(ssid):
        connects.append(ssid)
        return True, f"已发起连接到「{ssid}」"

    real_ssid, real_connect = wifi.current_ssid, wifi.connect
    wifi.current_ssid = fake_ssid
    wifi.connect = fake_connect

    cfg = ConfigManager()
    cfg.settings.wifi_ssid = "EZU"
    cfg.settings.wifi_known_ssids = ["EZU"]
    cfg.settings.wifi_auto_detect = True
    cfg.settings.wifi_auto_connect = True
    cfg.settings.preview_enabled = True
    cfg.settings.wifi_trigger_enabled = True
    cfg.save()

    win = MainWindow(cfg, auto_launch=False)
    win._closing = True
    win._set_watchdog(False)
    win._has_wifi = True                # 假装有无线网卡
    win.show()
    app.processEvents()

    # ---------- 1) 预览页开关 ----------
    # 注意：预览页不是当前标签页，所以用 isHidden()（显式隐藏状态）判断，
    # 而不是 isVisible()（要求所有祖先都可见）。
    print("[1] 预览页开关")
    check("默认显示预览（复选框是勾的）", win.cb_preview.isChecked())
    check("网页控件处于显示状态", not win.view.isHidden(),
          f"isHidden={win.view.isHidden()}")

    win.cb_preview.setChecked(False)
    pump(app, 250)
    check("关掉后网页不再显示", win.view.isHidden(),
          f"isHidden={win.view.isHidden()}")
    check("关掉后仍挂在窗口里（Chromium 才能继续跑）",
          win.view.parent() is not None, str(type(win.view.parent()).__name__))
    check("关掉后显示说明文字", not win.preview_tip.isHidden())

    win.cb_preview.setChecked(True)
    pump(app, 250)
    check("重新勾上后网页恢复显示", not win.view.isHidden())

    # ---------- 2) 前置检查 ----------
    print("\n[2] 自动认证前置检查")
    fake["ssid"] = ""
    connects.clear()
    win._last_wifi_connect_at = 0.0
    check("没连无线网络时，前置检查不放行",
          win._wifi_preflight("后台自动重连") is False)
    check("并且顺手尝试把校园网连回来", connects == ["EZU"], str(connects))

    fake["ssid"] = "HomeWiFi"
    check("连的不是校园网时，不放行",
          win._wifi_preflight("后台自动重连") is False)

    fake["ssid"] = "EZU"
    check("连的是校园网时，放行",
          win._wifi_preflight("后台自动重连") is True)

    # ---------- 3) 自动连接校园网 ----------
    print("\n[3] 掉线时自动连接校园网")
    fake["ssid"] = ""
    connects.clear()
    win._last_wifi_connect_at = 0.0
    win._wifi_tick()
    check("掉线时发起了连接", connects == ["EZU"], str(connects))

    connects.clear()
    win._wifi_tick()
    win._wifi_tick()
    check("30 秒冷却内不会反复连", connects == [], str(connects))

    win.cb_wifi_connect.setChecked(False)
    pump(app, 150)
    fake["ssid"] = ""
    connects.clear()
    win._last_wifi_connect_at = 0.0
    win._wifi_tick()
    check("关掉开关后不再自动连接", connects == [], str(connects))

    # ---------- 4) 页面打不开 / 没有表单，都不该空转 ----------
    print("\n[4] 换地址要快，不空转")
    fake["ssid"] = "EZU"
    cfg.settings.url = "http://127.0.0.1:1/"     # 必然连不上
    cfg.settings.skip_if_online = False
    cfg.settings.retry_times = 0
    cfg.save()

    logs: list[str] = []
    win.engine.log.connect(lambda t: logs.append(t))
    t0 = time.time()
    win.engine.start("手动")
    done = {"v": False}
    win.engine.finished.connect(lambda *_: done.update(v=True))
    deadline = time.time() + 90
    while not done["v"] and time.time() < deadline:
        app.processEvents()
    cost = time.time() - t0
    joined = "\n".join(logs)
    print(f"    耗时 {cost:.1f}s")

    check("流程正常结束", done["v"])
    check("页面打不开时立刻换地址",
          "页面打不开，不等渲染了" in joined,
          [l for l in logs if "打不开" in l][:1].__str__()[:70])
    check("「没有账号密码框」不再死等 9 轮",
          "（9/9）" not in joined,
          f"出现 9/9 = {'（9/9）' in joined}")
    check("每页最多试 4 轮（MAX_NOFORM_ROUND）",
          joined.count("这一轮还没看到账号密码框") <= 12,
          f"出现 {joined.count('这一轮还没看到账号密码框')} 次")
    # 挂钟时间只做个宽松兜底：这个用例是"在线环境"下的最坏情况 ——
    # 候选里的探测地址全都能加载，每个都要走完识别轮次（受机器负载影响较大）。
    # 真正的离线场景里它们全部加载失败，整轮约 3 秒。
    # 判定"有没有变快"靠上面两条结构性断言，不靠这个秒数。
    check("总耗时没有失控（< 35s）", cost < 35, f"{cost:.1f}s")

    # ---------- 4.5) 刚成功就不该被自动触发重复跑 ----------
    # 实测见过"开机自动"和"WiFi 触发"同一秒各跑一遍，第二次空转 12 秒
    print("\n[4.5] 认证成功后的静默期")
    # 浏览器"未就绪"时 _ensure_browser 会把动作延后执行，这里直接标记就绪，
    # 好让断言能立刻看到结果
    win._browser_ready = True
    fake["ssid"] = "EZU"
    win._last_success_at = time.time()
    started: list[str] = []
    orig_start = win.engine.start
    win.engine.start = lambda reason, submit=True: started.append(reason)
    win._last_trigger_time = 0.0

    win._start_engine("WiFi 触发（EZU）", auto=True)
    check("刚成功 25 秒内，自动触发被挡掉", started == [], str(started))

    fake["ssid"] = ""
    win._last_success_at = time.time() - 60      # 静默期已过
    win._last_trigger_time = 0.0
    win._start_engine("后台自动重连", auto=True)
    check("静默期过了仍然会被前置检查挡住（没连网）", started == [], str(started))

    fake["ssid"] = "EZU"
    win._start_engine("后台自动重连", auto=True)
    check("静默期过了、也连着校园网，正常放行",
          started == ["后台自动重连"], str(started))

    win._start_engine("手动", auto=False)
    check("手动点击不受静默期影响", started[-1] == "手动", str(started))
    win.engine.start = orig_start

    # ---------- 5) 页面隐藏时，表单照样能识别并提交 ----------
    # 这条最关键：用户反馈"缩在托盘里时账号密码填进去了、但登录按钮点不到，
    # 把窗口一打开就好了"。根因是 Chromium 对不可见页面做了渲染/定时器节流。
    print("\n[5] 预览关闭（页面隐藏）时仍能识别并提交")
    from PySide6.QtCore import QUrl
    from core.autofill import build_autofill_js, parse_result

    page_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "test_login.html")
    win.cb_preview.setChecked(False)
    pump(app, 250)
    check("页面当前是隐藏的", win.view.isHidden())

    loaded = {"ok": None}

    def on_loaded(ok):
        loaded["ok"] = ok

    win.view.loadFinished.connect(on_loaded)
    win.view.load(QUrl.fromLocalFile(page_path))
    deadline = time.time() + 30
    while loaded["ok"] is None and time.time() < deadline:
        app.processEvents()
    check("隐藏状态下页面能加载", loaded["ok"] is True, str(loaded["ok"]))

    got = {"v": None}
    js = build_autofill_js(username="20250001", password="testpass",
                           auto_submit=True, remember_checkbox=True)
    win.view.page().runJavaScript(js, lambda r: got.update(v=parse_result(r)))
    deadline = time.time() + 20
    while got["v"] is None and time.time() < deadline:
        app.processEvents()
    res = got["v"] or {}
    check("隐藏状态下仍能识别到表单", bool(res.get("found")),
          f"found={res.get('found')}")
    check("隐藏状态下仍能填上账号密码", bool(res.get("userSel")) and bool(res.get("pwdSel")),
          f"账号={res.get('userSel')} 密码={res.get('pwdSel')}")
    check("隐藏状态下仍能点到登录按钮", bool(res.get("submitted")),
          f"按钮={res.get('btnSel')} submitted={res.get('submitted')}")

    win.close()
    wifi.current_ssid, wifi.connect = real_ssid, real_connect

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
