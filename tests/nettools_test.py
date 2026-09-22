# -*- coding: utf-8 -*-
"""网络工具页自测：连接枚举 + 系统收发计数 + 测速（本地服务）+ 界面。"""

from __future__ import annotations

import http.server
import os
import sys
import tempfile
import threading
import time

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="campusp_net_")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox --disable-gpu"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication  # noqa: E402

from core import netstat  # noqa: E402
from core.speedtest import SpeedTestWorker  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))


class Handler(http.server.BaseHTTPRequestHandler):
    payload = b"x" * (4 * 1024 * 1024)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        # 分块慢发，好让"实时速率"信号有机会触发
        for i in range(0, len(self.payload), 65536):
            self.wfile.write(self.payload[i:i + 65536])
            time.sleep(0.02)

    def log_message(self, *a):
        pass


def main() -> int:
    app = QApplication(sys.argv[:1])

    print("[1] 连接枚举")
    conns = netstat.list_connections()
    check("能枚举到连接", len(conns) > 0, f"{len(conns)} 条")
    if conns:
        check("字段齐全",
              all(k in conns[0] for k in ("pid", "proto", "local", "remote", "state", "proc")),
              str(sorted(conns[0].keys())))
        check("TCP 状态可读", any(c["proto"] == "TCP" and c["state"] for c in conns))
        check("能解出进程名", any(not c["proc"].startswith("PID ") for c in conns))

    print("[2] 系统收发计数")
    a = netstat.io_totals()
    time.sleep(0.4)
    b = netstat.io_totals()
    check("单调不减", b[0] >= a[0] and b[1] >= a[1], f"{a} -> {b}")
    check("数值非零", b[0] > 0 or b[1] > 0, str(b))

    print("[3] 测速（本地服务，不依赖外网）")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/big"

    got: dict = {"v": None}
    err: dict = {"v": None}
    live_vals: list[float] = []
    # 故意把连不上的地址放第一个，验证会自动跳到下一个
    w = SpeedTestWorker(f"http://127.0.0.1:1/dead\n{url}", seconds=3)
    w.done.connect(lambda d: got.update(v=d))
    w.failed.connect(lambda e: err.update(v=e))
    w.live.connect(lambda m: live_vals.append(m))
    w.start()
    deadline = time.time() + 20
    while got["v"] is None and err["v"] is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    w.wait(3000)
    srv.shutdown()

    check("测速没报错", err["v"] is None, err["v"] or "")
    d = got["v"] or {}
    check("多地址：坏的跳过后用好的", d.get("url") == url, str(d.get("url")))
    check("拿到下载速率", d.get("mbps", 0) > 0, f"{d.get('mbps', 0):.1f} Mbps")
    check("测到字节数", d.get("mb", 0) > 0, f"{d.get('mb', 0):.2f} MB / {d.get('sec', 0):.1f}s")
    check("延迟为正值", d.get("latency_ms", -1) > 0, f"{d.get('latency_ms', 0):.1f} ms")
    check("测速过程中报了实时速率", len(live_vals) > 0,
          f"{len(live_vals)} 次，峰值 {max(live_vals or [0]):.1f}")

    print("[4] 界面：网络页")
    from core.config import ConfigManager
    from ui.main_window import MainWindow

    cfg = ConfigManager()
    win = MainWindow(cfg, auto_launch=False)
    win._closing = True
    win._set_watchdog(False)
    win.show()
    app.processEvents()

    names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    check("有「网络」标签页", "网络" in names, str(names))
    check("测速控件就位", hasattr(win, "btn_speed") and hasattr(win, "ed_speed_url"))
    check("地址取自配置",
          win.ed_speed_url.toPlainText().strip() == cfg.settings.speedtest_url.strip(),
          win.ed_speed_url.toPlainText().splitlines()[0][:48])

    win._goto_tab("网络")
    app.processEvents()
    txt = win.txt_conn.toPlainText()
    check("切页即自动刷新连接", txt.strip() != "", f"{len(txt)} 字符")
    check("列表含表头与进程列", "进程" in txt and "连接" in txt)
    check("总览显示连接数", "条连接" in win.lb_netrate.text(), win.lb_netrate.text())

    check("有单位下拉",
          [win.cb_speed_unit.itemText(i) for i in range(win.cb_speed_unit.count())]
          == ["Mbps", "MB/s", "KB/s"], win.cb_speed_unit.currentText())
    win.cb_speed_unit.setCurrentText("MB/s")
    check("切到 MB/s 后格式跟着变", "MB/s" in win._fmt_speed(80), win._fmt_speed(80))
    win.cb_speed_unit.setCurrentText("Mbps")
    check("切回 Mbps", win._fmt_speed(80) == "80.0 Mbps", win._fmt_speed(80))

    check("有释放浏览器开关", hasattr(win, "cb_release"))

    print("[5] 浏览器释放 / 重建")
    win._ensure_browser(lambda: None)
    deadline = time.time() + 25
    while not win._browser_ready and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    check("浏览器已就绪", win._browser_ready)
    check("view 存在", win.view is not None)
    win._release_browser()
    check("释放后 view 置空", win.view is None)
    check("释放后标记未就绪", win._browser_ready is False)
    win._ensure_browser(lambda: None)
    check("再次需要时自动重建 view", win.view is not None)
    deadline = time.time() + 25
    while not win._browser_ready and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    check("重建后能再次就绪", win._browser_ready)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shot = os.path.join(root, "_shots", "08_net_tab.png")
    win.grab().save(shot)
    check("截图已保存", os.path.exists(shot), shot)
    win.close()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print()
    for name, ok, _ in results:
        if not ok:
            print(f"   未通过：{name}")
    print(f"结论：{passed}/{total} 通过")
    app.quit()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
