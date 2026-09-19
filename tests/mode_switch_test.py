# -*- coding: utf-8 -*-
"""复现用户遇到的场景：页面刚打开时停在「单点登录」模式，账号登录按钮还没渲染出来。

程序以前会退而求其次去点「单点登录」那个 span（那其实是模式切换按钮，点了等于白点）。
现在应该：等页面切到账号登录模式，再点真正的 #login-account。
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

TMP = tempfile.mkdtemp(prefix="campus_mode_")
os.environ["APPDATA"] = TMP
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "QTWEBENGINE_CHROMIUM_FLAGS", "") + " --no-sandbox --disable-gpu"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import ConfigManager  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

# 关键：一开始只有「单点登录」可见，#login-account 是隐藏的；
# 2 秒后才切成账号登录模式（真实深澜 portal 就是这个行为）
LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>网络准入认证</title></head><body>
<div class="panel panel-login">
  <div class="panel-row login-mode mode-sso" id="ssoRow">
    <span class="login-mode mode-sso" id="ssoEntry">单点登录</span>
  </div>
  <div class="panel-row"><input id="username" name="username" type="text"></div>
  <div class="panel-row"><input id="password" name="password" type="password"></div>
  <div class="panel-row">
    <button type="button" class="btn-login" id="login-account"
            style="display:none">登录</button>
  </div>
</div>
<script>
document.getElementById('ssoEntry').addEventListener('click', function () {
  try { localStorage.setItem('wrong_click', '点了单点登录'); } catch (e) {}
});
setTimeout(function () {
  document.getElementById('login-account').style.display = '';
  document.getElementById('ssoRow').style.display = 'none';
}, 2000);
document.getElementById('login-account').addEventListener('click', function () {
  var u = document.getElementById('username').value;
  var p = document.getElementById('password').value;
  try { localStorage.setItem('submitted', 'user=' + u + '|pwd=' + p); } catch (e) {}
  fetch('/__login').then(function () {}, function () {}).then(function () {
    location.href = '/srun_portal_success?ac_id=1';
  });
});
</script></body></html>"""

SUCCESS_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>网络准入认证</title></head><body>
<p>用户账号 20250001</p><p>已用流量 838.01 GB</p>
<button class="btn-logout" id="logout">注销</button></body></html>"""

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
        if path == "/nope":
            self._send("<html>blocked</html>")
            return
        self._send(LOGIN_PAGE)


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
    cfg.settings.page_load_timeout = 15
    cfg.settings.probe_url = f"http://127.0.0.1:{port}/nope"
    cfg.settings.probe_keyword = "不可能匹配"
    cfg.settings.probe_timeout = 2
    cfg.settings.username = "20250001"
    cfg.settings.set_password("mypassword888")
    cfg.settings.url = f"http://127.0.0.1:{port}/login"

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
            print("\n   localStorage:", v)
            finish(str(v or ""))

        win.view.page().runJavaScript(
            "(function(){try{var s=localStorage.getItem('submitted')||'none';"
            "var w=localStorage.getItem('wrong_click')?'点了单点登录':'没点';"
            "return s+' || '+w;}catch(e){return 'err';}})()", cb)

    def finish(store):
        joined = "\n".join(logs)
        checks = [
            ("识别到「单点登录」是模式切换按钮，没去点它", "点了单点登录" not in store),
            ("等页面切到账号登录模式（有重试日志）",
             "单点登录" in joined and "稍后再试" in joined),
            ("最终点到的是 #login-account", "按钮=#login-account" in joined),
            ("账号密码填对了", "user=20250001" in store and "pwd=mypassword888" in store),
            ("引擎判定成功", result["ok"] is True),
        ]
        print("\n—— 断言 ——")
        allok = True
        for name, ok in checks:
            print(("  PASS  " if ok else "  FAIL  ") + name)
            allok = allok and ok
        print(f"\n结论：{'通过' if allok else '有未通过项'}")
        win._closing = True
        app.quit()

    win.engine.finished.connect(on_finished)
    QTimer.singleShot(600, lambda: win.engine.start("模式切换测试"))
    QTimer.singleShot(60000, lambda: (print("超时"), app.quit()))
    app.exec()
    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
