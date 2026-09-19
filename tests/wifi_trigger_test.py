# -*- coding: utf-8 -*-
"""验证「连上指定 WiFi 就自动认证」这条链路。

做法：本地起一个模拟 portal，把读取 SSID 的函数换成可控的假函数，
然后依次模拟「没连无线 → 连上 CampusWiFi」的过程，看程序会不会自己触发认证。
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

TMP = tempfile.mkdtemp(prefix="campus_wifi_")
os.environ["APPDATA"] = TMP
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "QTWEBENGINE_CHROMIUM_FLAGS", "") + " --no-sandbox --disable-gpu"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import ui.main_window as mw  # noqa: E402
from core.config import ConfigManager  # noqa: E402

LOGIN = """<!doctype html><html><head><meta charset="utf-8"><title>认证</title></head><body>
<form onsubmit="return false">
  <input id="username" name="username" type="text">
  <input id="password" name="password" type="password">
  <button type="button" class="btn-login" id="login-account">登录</button>
</form><div id="result">pending</div>
<script>
document.getElementById('login-account').addEventListener('click', function(){
  var u=document.getElementById('username').value, p=document.getElementById('password').value;
  try{ localStorage.setItem('submitted','user='+u+'|pwd='+p); }catch(e){}
  fetch('/__login').then(function(){ location.href='/srun_portal_success?ac_id=1'; });
});
</script></body></html>"""

SUCCESS = """<!doctype html><html><head><meta charset="utf-8"><title>认证</title></head><body>
<p>已用流量 1.2 GB</p><button class="btn-logout" id="logout">注销</button>
</body></html>"""

STATE = {"logged_in": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8"):
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/__login":
            STATE["logged_in"] = True
            self._send("ok", "text/plain")
            return
        if "success" in path or path == "/":
            if STATE["logged_in"]:
                self._send(SUCCESS)
                return
            self._redirect("/login")
            return
        self._send(LOGIN)


def main():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"模拟 portal: http://127.0.0.1:{port}")

    app = QApplication(sys.argv[:1])
    cfg = ConfigManager()
    cfg.settings.auto_connect_on_launch = False
    cfg.settings.skip_if_online = False
    cfg.settings.retry_times = 0
    cfg.settings.post_submit_wait = 1
    cfg.settings.probe_url = f"http://127.0.0.1:{port}/nope"
    cfg.settings.probe_keyword = "不可能匹配的字符串"
    cfg.settings.probe_timeout = 2
    cfg.settings.username = "20250001"
    cfg.settings.set_password("pw123456")
    cfg.settings.url = f"http://127.0.0.1:{port}/"
    cfg.settings.wifi_trigger_enabled = True
    cfg.settings.wifi_ssid = "CampusWiFi"
    cfg.settings.wifi_wait = 0

    # —— 用可控的假 SSID 替换真实读取 ——
    fake = {"ssid": ""}
    mw.wifi.current_ssid = lambda: fake["ssid"]
    mw.wifi.signal_quality = lambda: 88

    win = mw.MainWindow(cfg, auto_launch=False)
    win._closing = True

    logs = []
    win.engine.log.connect(lambda line: logs.append(str(line)))
    win.engine.log.connect(lambda line: print("   |", line))

    triggers = {"n": 0}
    net_probe_triggered = {"v": False}
    online_not_triggered = {"v": False}
    reconnect_triggered = {"v": False}
    cooldown_ok = {"v": False}
    orig_trigger = win._wifi_trigger

    def spy(ssid):
        triggers["n"] += 1
        print(f"   >> 触发自动认证（SSID={ssid}）")
        orig_trigger(ssid)

    # 触发是"排进队列"的（QTimer.singleShot），所以看 _last_trigger_time 判断有没有排队
    def queued() -> bool:
        return win._last_trigger_time > 0

    win._wifi_trigger = spy

    steps = []

    def finish():
        joined = "\n".join(logs)
        checks = [
            ("未连无线时不触发", steps and steps[0]),
            ("连上 CampusWiFi 后自动触发认证", triggers["n"] >= 1),
            ("认证流程完整跑起来", "识别到表单" in joined),
            ("最终判定为成功", any("成功" in l for l in logs)),
            ("网络名不变但没网时会触发", net_probe_triggered["v"]),
            ("网络名不变且有网时不触发", online_not_triggered["v"]),
            ("断开重连能被捕捉", reconnect_triggered["v"]),
            ("冷却期内不重复触发", cooldown_ok["v"]),
        ]
        print("\n—— 断言 ——")
        allok = True
        for name, ok in checks:
            print(("  PASS  " if ok else "  FAIL  ") + name)
            allok = allok and ok
        print(f"\n结论：{'通过' if allok else '有未通过项'}（触发次数={triggers['n']}）")
        win._closing = True
        app.quit()

    def s1():
        print("\n[1] 模拟：还没连上无线网络")
        fake["ssid"] = ""
        win._wifi_tick()
        steps.append(triggers["n"] == 0)
        print(f"    触发次数 = {triggers['n']}（期望 0）")
        QTimer.singleShot(600, s2)

    def s2():
        print("\n[2] 模拟：刚连上无线网络 CampusWiFi")
        fake["ssid"] = "CampusWiFi"
        win._wifi_tick()
        print(f"    触发次数 = {triggers['n']}（期望 1）")
        QTimer.singleShot(12000, s3)

    def s3():
        print("\n[3] 模拟：网络名没变 + 网络是通的 → 不该触发")
        before = triggers["n"]
        win._last_trigger_time = 0
        win._on_wifi_probe(True, "HTTP 204", "CampusWiFi")
        online_not_triggered["v"] = not queued()
        print(f"    是否排队触发 = {queued()}（期望 False）")
        QTimer.singleShot(400, s4)

    def s4():
        print("\n[4] 模拟：网络名没变，但其实上不了网 → 应当触发（这正是用户遇到的场景）")
        before = triggers["n"]
        win._last_trigger_time = 0          # 清掉冷却时间
        win._on_wifi_probe(False, "HTTP 302 · 被劫持到认证页", "CampusWiFi")
        net_probe_triggered["v"] = queued()
        print(f"    是否排队触发 = {queued()}（期望 True）")
        QTimer.singleShot(9000, s5)

    def s5():
        print("\n[5] 模拟：刚断开又连上（SSID 序列 CampusWiFi → '' → CampusWiFi）")
        before = triggers["n"]
        win._last_trigger_time = 0
        fake["ssid"] = ""
        win._wifi_tick()
        fake["ssid"] = "CampusWiFi"
        win._wifi_tick()
        reconnect_triggered["v"] = queued()
        print(f"    是否排队触发 = {queued()}（期望 True）")
        QTimer.singleShot(9000, s6)

    def s6():
        print("\n[6] 模拟：30 秒冷却期内反复触发 → 只算一次")
        before = triggers["n"]
        first = win._last_trigger_time
        win._on_wifi_probe(False, "还是不通", "CampusWiFi")
        win._on_wifi_probe(False, "还是不通", "CampusWiFi")
        cooldown_ok["v"] = win._last_trigger_time == first
        print(f"    冷却时间内触发时间戳是否被刷新 = {win._last_trigger_time != first}（期望 False）")
        QTimer.singleShot(400, finish)

    QTimer.singleShot(800, s1)
    QTimer.singleShot(60000, lambda: (print("超时"), app.quit()))
    app.exec()
    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
