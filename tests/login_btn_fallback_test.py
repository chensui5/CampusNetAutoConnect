# -*- coding: utf-8 -*-
"""验证「登录按钮不可见也能点」。

现象：开机时程序缩在托盘/窗口隐藏，CSS 入场动画不跑，登录按钮卡在
opacity:0（甚至 display:none），被 visible() 判成不可见而跳过，导致
"找不到登录按钮，请手动点击"。用户一打开窗口、动画跑完，按钮才"出现"。

修法：账号密码已填好时，按 id 直接程序化点击按钮 —— .click() 对隐藏元素同样有效。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QUrl, QTimer                   # noqa: E402
from PySide6.QtWidgets import QApplication                # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView     # noqa: E402

from core.autofill import build_autofill_js, parse_result # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))


TMPL = """<!DOCTYPE html><html><body>
<input type="text" id="username" placeholder="学号">
<input type="password" id="password">
<button type="button" id="login-account" {style}>登录</button>
<script>
document.getElementById('login-account').onclick = function () {{
  window.__clicked = true;
}};
</script>
</body></html>"""


def run_case(app, html: str) -> dict:
    view = QWebEngineView()
    view.resize(400, 300)
    loaded = {"ok": None}
    view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
    view.setHtml(html)
    dl = time.time() + 20
    while loaded["ok"] is None and time.time() < dl:
        app.processEvents()
    got = {"v": None}
    js = build_autofill_js(username="20250001", password="x", auto_submit=True)
    view.page().runJavaScript(js, lambda r: got.update(v=parse_result(r)))
    dl = time.time() + 10
    while got["v"] is None and time.time() < dl:
        app.processEvents()
    view.deleteLater()
    return got["v"] or {}


def main() -> int:
    app = QApplication(sys.argv[:1])

    print("[1] 按钮 opacity:0（CSS 动画没跑完的典型）")
    r = run_case(app, TMPL.format(style='style="opacity:0"'))
    check("识别到表单", bool(r.get("found")))
    check("账号密码已填", bool(r.get("filled")))
    check("仍然点到了按钮（submitted）", bool(r.get("submitted")),
          f"btnSel={r.get('btnSel')!r} looseBtn={r.get('looseBtn')}")

    print("\n[2] 按钮 display:none（彻底隐藏）")
    r2 = run_case(app, TMPL.format(style='style="display:none"'))
    check("识别到表单", bool(r2.get("found")))
    check("账号密码已填", bool(r2.get("filled")))
    check("强制点击兜底生效（forcedBtn）", bool(r2.get("forcedBtn")),
          f"btnSel={r2.get('btnSel')!r}")
    check("仍然点到了按钮（submitted）", bool(r2.get("submitted")),
          f"submitted={r2.get('submitted')}")

    print("\n[3] 正常可见按钮（回归，不该走兜底）")
    r3 = run_case(app, TMPL.format(style=""))
    check("正常点击（submitted）", bool(r3.get("submitted")), f"btnSel={r3.get('btnSel')!r}")
    check("没有误判成强制点击", not r3.get("forcedBtn") and not r3.get("looseBtn"),
          f"looseBtn={r3.get('looseBtn')} forcedBtn={r3.get('forcedBtn')}")

    print("\n[4] 页面上根本没有登录按钮（不该瞎点）")
    html = TMPL.replace('<button type="button" id="login-account" {style}>登录</button>', '')
    r4 = run_case(app, html)
    check("没按钮时不提交", not r4.get("submitted") and not r4.get("forcedBtn"),
          f"submitted={r4.get('submitted')} forcedBtn={r4.get('forcedBtn')}")

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
