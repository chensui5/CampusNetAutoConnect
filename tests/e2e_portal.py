# -*- coding: utf-8 -*-
"""端到端演练：完整模拟深澜 portal 的行为。

本地 HTTP 服务：
    /srun_portal_success?...  → 已登录页（没有表单，有"注销"按钮）
    /srun_portal_pc?...       → 登录页（有账号/密码/登录按钮）
    /                         → 302 跳到登录页

登录页点"登录"后会像真实 portal 一样跳到 xxx_success。
验证三件事：
    1. 地址填成"认证成功页"时，能自动找到真正的登录页
    2. 表单能填对、按钮能点到
    3. 靠"页面跳到 success"判定登录成功（不再只靠网络探测）
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

TMP = tempfile.mkdtemp(prefix="campus_e2e_")
os.environ["APPDATA"] = TMP
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "QTWEBENGINE_CHROMIUM_FLAGS", "") + " --no-sandbox --disable-gpu"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.config import ConfigManager  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

SUCCESS_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>网络准入认证</title></head><body>
<h3>网络准入认证</h3>
<p>用户账号 20250001</p><p>已用流量 838.01 GB</p><p>已用时长 556小时</p>
<button type="button" class="btn-logout" id="logout">注销</button>
<div id="result">pending</div>
</body></html>"""

LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>网络准入认证</title></head><body>
<div class="panel panel-login">
  <div class="panel-row"><input id="username" name="username" type="text" placeholder="请输入学号"></div>
  <div class="panel-row"><input id="password" name="password" type="password" placeholder="请输入密码"></div>
  <div class="panel-row"><label><input type="checkbox" id="remember"> 记住密码</label></div>
  <div class="panel-row"><button type="button" class="btn-login" id="login-account">登录</button></div>
</div>
<div id="result">pending</div>
<script>
function doLogin() {
  var u = document.getElementById('username').value;
  var p = document.getElementById('password').value;
  var r = document.getElementById('remember').checked;
  try {
    sessionStorage.setItem('submitted', 'LOGIN_OK|user=' + u + '|pwd=' + p + '|remember=' + r);
    localStorage.setItem('submitted', 'LOGIN_OK|user=' + u + '|pwd=' + p + '|remember=' + r);
  } catch (e) {}
  document.getElementById('result').innerText =
    'LOGIN_OK|user=' + u + '|pwd=' + p + '|remember=' + r;
  // 真实 portal 的行为：先告诉网关"我认证了"，再跳转到 success 页
  fetch('/__login').then(function () {}, function () {}).then(function () {
    location.href = '/srun_portal_success?ac_id=1';
  });
  return false;
}
document.getElementById('login-account').addEventListener('click', function (e) {
  e.preventDefault();
  doLogin();
});
</script></body></html>"""


STATE = {"logged_in": False}


class Handler(BaseHTTPRequestHandler):
    """模拟真实 portal：未登录时任何页面都把你送回登录页。"""

    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype="text/html; charset=utf-8"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str):
        self.send_response(302)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/__login":                     # 登录页点按钮后标记已登录
            STATE["logged_in"] = True
            self._send(b"ok", "text/plain")
            return
        if path == "/srun_portal_pc":
            # 登录页本身永远可以直接打开（否则会无限重定向）
            self._send(LOGIN_PAGE.encode("utf-8"))
            return
        if not STATE["logged_in"]:
            # 未登录：success 页、根路径统统送回登录页
            self._redirect("/srun_portal_pc?ac_id=1&theme=pro")
            return
        if "success" in path or path == "/":
            self._send(SUCCESS_PAGE.encode("utf-8"))
            return
        self._send(LOGIN_PAGE.encode("utf-8"))


def main():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"模拟 portal 已启动：http://127.0.0.1:{port}")

    app = QApplication(sys.argv[:1])
    cfg = ConfigManager()
    cfg.settings.auto_connect_on_launch = False
    cfg.settings.skip_if_online = False
    cfg.settings.retry_times = 0
    cfg.settings.post_submit_wait = 1
    cfg.settings.page_load_timeout = 12
    # 探测点永远不匹配 → 强制程序认为"离线"，从而跑完整流程
    cfg.settings.probe_url = f"http://127.0.0.1:{port}/srun_portal_success"
    cfg.settings.probe_keyword = "绝对不会出现的字符串"
    cfg.settings.probe_timeout = 2
    cfg.settings.username = "20250001"
    cfg.settings.set_password("mypassword888")
    cfg.settings.url = f"http://127.0.0.1:{port}/srun_portal_success?ac_id=1&theme=pro"

    win = MainWindow(cfg, auto_launch=False)
    win._closing = True
    win._set_watchdog(False)

    logs = []
    result = {"ok": None, "msg": ""}

    def on_log(line):
        logs.append(str(line))
        print("   |", line)

    def on_finished(ok, msg):
        result["ok"] = ok
        result["msg"] = msg
        print(f"\n===== 引擎判定：{'成功' if ok else '失败'} —— {msg} =====")
        QTimer.singleShot(400, check_page)

    def check_page():
        def cb(v):
            t = str(v or "")
            print("   登录页记录下来的内容：", t)
            finish(("LOGIN_OK" in t and "20250001" in t and "mypassword888" in t), t)
        win.view.page().runJavaScript(
            "(function(){try{return localStorage.getItem('submitted')||"
            "sessionStorage.getItem('submitted')||'none';}catch(e){return 'err';}})()", cb)

    def finish(page_ok, note):
        joined = "\n".join(logs)
        checks = [
            ("成功识别到登录表单", "识别到表单" in joined),
            ("识别到的是 #login-account 按钮", "#login-account" in joined),
            ("点击了登录按钮", "已点击登录按钮" in joined),
            ("靠页面跳转判定成功", result["ok"] is True and "已登录" in result["msg"]),
            ("账号密码填写正确", page_ok),
        ]
        print("\n—— 过程断言 ——")
        allok = True
        for name, ok in checks:
            print(("  PASS  " if ok else "  FAIL  ") + name)
            allok = allok and ok
        print(f"\n结论：{'全部通过' if allok else '有未通过项'}（{note[:60]}）")
        win._closing = True
        app.quit()

    win.engine.log.connect(on_log)
    win.engine.finished.connect(on_finished)
    QTimer.singleShot(600, lambda: win.engine.start("端到端测试"))
    QTimer.singleShot(50000, lambda: (print("超时"), app.quit()))

    app.exec()
    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
