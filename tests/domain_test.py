# -*- coding: utf-8 -*-
"""验证「运营商选择」：多运营商的 portal 能不能选对。

模拟一个有三个运营商的深澜 portal（默认停在联通），配置成"电信"，
看程序提交时用的是不是 @telecom。
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

TMP = tempfile.mkdtemp(prefix="campus_domain_")
os.environ["APPDATA"] = TMP
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "QTWEBENGINE_CHROMIUM_FLAGS", "") + " --no-sandbox --disable-gpu"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import ConfigManager  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>网络准入认证</title></head><body>
<div class="panel panel-login">
  <div class="panel-row">
    <select id="domain" name="domain">
      <option value="@unicom">联通</option>
      <option value="@telecom">电信</option>
      <option value="@cmcc">移动</option>
    </select>
  </div>
  <div class="panel-row"><input id="username" name="username" type="text"></div>
  <div class="panel-row"><input id="password" name="password" type="password"></div>
  <div class="panel-row">
    <button type="button" class="btn-login" id="login-account">登录</button>
  </div>
</div>
<script>
document.getElementById('login-account').addEventListener('click', function () {
  var d = document.getElementById('domain').value;
  var u = document.getElementById('username').value;
  var p = document.getElementById('password').value;
  try { localStorage.setItem('sent', 'domain=' + d + '|user=' + u + '|pwd=' + p); } catch (e) {}
  fetch('/__login').then(function () {}, function () {}).then(function () {
    location.href = '/srun_portal_success?ac_id=1';
  });
});
</script></body></html>"""

SUCCESS_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>认证</title></head><body>
<p>已用流量 1.2 GB</p><button class="btn-logout" id="logout">注销</button></body></html>"""

STATE = {"logged_in": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: str):
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/__login":
            STATE["logged_in"] = True
            self._send("ok")
            return
        if "success" in path and STATE["logged_in"]:
            self._send(SUCCESS_PAGE)
            return
        self._send(LOGIN_PAGE)


def main():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    app = QApplication(sys.argv[:1])
    cfg = ConfigManager()
    cfg.settings.auto_connect_on_launch = False
    cfg.settings.skip_if_online = False
    cfg.settings.retry_times = 0
    cfg.settings.post_submit_wait = 1
    cfg.settings.probe_url = f"http://127.0.0.1:{port}/"
    cfg.settings.probe_keyword = "不可能匹配"
    cfg.settings.probe_timeout = 2
    cfg.settings.username = "20250001"
    cfg.settings.set_password("pw123456")
    cfg.settings.url = f"http://127.0.0.1:{port}/login"
    cfg.settings.domain = "电信"          # ← 关键：指定运营商

    win = MainWindow(cfg, auto_launch=False)
    win._closing = True
    win._set_watchdog(False)

    logs = []
    win.engine.log.connect(lambda l: (logs.append(str(l)), print("   |", l)))

    result = {"ok": None}

    def on_finished(ok, msg):
        result["ok"] = ok
        print(f"\n===== 引擎判定：{'成功' if ok else '失败'} —— {msg} =====")
        QTimer.singleShot(500, check)

    def check():
        def cb(v):
            finish(str(v or ""))
        win.view.page().runJavaScript(
            "(function(){try{return localStorage.getItem('sent')||'none';}catch(e){return 'err';}})()", cb)

    def finish(sent):
        joined = "\n".join(logs)
        checks = [
            ("日志里确认了运营商选择", "已选择运营商" in joined),
            ("提交时用的是电信 @telecom", "domain=@telecom" in sent),
            ("没被页面的默认值（联通）带走", "domain=@unicom" not in sent),
            ("账号密码同时正确", "user=20250001" in sent and "pwd=pw123456" in sent),
            ("引擎判定成功", result["ok"] is True),
        ]
        print(f"\n   页面最终提交的内容：{sent}")
        print("\n—— 断言 ——")
        allok = True
        for name, ok in checks:
            print(("  PASS  " if ok else "  FAIL  ") + name)
            allok = allok and ok
        print(f"\n结论：{'通过' if allok else '有未通过项'}")
        win._closing = True
        app.quit()

    win.engine.finished.connect(on_finished)
    QTimer.singleShot(600, lambda: win.engine.start("运营商测试"))
    QTimer.singleShot(50000, lambda: (print("超时"), app.quit()))
    app.exec()
    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
