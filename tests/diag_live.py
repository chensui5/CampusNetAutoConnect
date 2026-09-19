# -*- coding: utf-8 -*-
"""真机诊断：打开真实认证页，把渲染后的 DOM 结构打印出来（只读，不提交）。"""

from __future__ import annotations

import os
import sys
import json

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "QTWEBENGINE_CHROMIUM_FLAGS", "") + " --no-sandbox --disable-gpu"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QUrl, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineProfile  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "http://10.10.10.1/srun_portal_pc?ac_id=1&theme=pro"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

DUMP_JS = r"""
(function () {
  function info(el) {
    if (!el) return null;
    var r = el.getBoundingClientRect();
    var s = getComputedStyle(el);
    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || '',
      cls: (typeof el.className === 'string' ? el.className : ''),
      type: el.type || '',
      name: el.name || '',
      text: ((el.innerText || el.value || '') + '').replace(/\s+/g, ' ').trim().slice(0, 24),
      visible: !!(r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'),
      rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
      display: s.display
    };
  }
  function all(sel) {
    return Array.prototype.map.call(document.querySelectorAll(sel), info);
  }
  return JSON.stringify({
    url: location.href,
    title: document.title,
    ready: document.readyState,
    viewport: [window.innerWidth, window.innerHeight],
    scrollHeight: document.documentElement.scrollHeight,
    forms: Array.prototype.map.call(document.querySelectorAll('form'), function (f) {
      return { id: f.id, action: f.getAttribute('action'), method: f.getAttribute('method'),
               inputs: f.querySelectorAll('input').length, html: f.outerHTML.slice(0, 260) };
    }),
    inputs: all('input'),
    buttons: all('button, a[class*=btn], a[id*=login], input[type=submit], input[type=button], [id*=login-]'),
    loginAccount: info(document.getElementById('login-account')),
    captchaInput: info(document.getElementById('captcha')),
    captchaImg: info(document.getElementById('captchaImg')),
    bodyText: ((document.body.innerText || '') + '').replace(/\s+/g, ' ').slice(0, 500)
  });
})()
"""


def main():
    app = QApplication(sys.argv[:1])
    view = QWebEngineView()
    view.resize(1200, 900)
    view.show()
    try:
        view.page().profile().setHttpUserAgent(UA)
    except Exception:
        pass

    state = {"done": False}

    def dump(tag=""):
        view.page().runJavaScript(DUMP_JS, lambda res: report(res, tag))

    def report(res, tag):
        if state["done"]:
            return
        state["done"] = True
        if isinstance(res, str):
            try:
                data = json.loads(res)
            except Exception as e:
                print("解析失败", e, res[:500])
                app.quit()
                return
        elif isinstance(res, dict):
            data = res
        else:
            print("拿不到结果：", repr(res)[:300])
            app.quit()
            return

        print("=" * 70)
        print("URL      :", data.get("url"))
        print("标题     :", data.get("title"), "| readyState:", data.get("ready"))
        print("视口     :", data.get("viewport"), "| 页面总高:", data.get("scrollHeight"))
        print("\n【表单 form】")
        for f in data.get("forms") or []:
            print("  ", f)
        print("\n【所有 input】")
        for i in data.get("inputs") or []:
            print(f"   {i['tag']}#{i['id']} name={i['name']} type={i['type']} "
                  f"可见={i['visible']} rect={i['rect']} text={i['text']!r}")
        print("\n【按钮/链接】")
        for b in data.get("buttons") or []:
            print(f"   {b['tag']}#{b['id']}.{b['cls'][:26]} 可见={b['visible']} "
                  f"rect={b['rect']} text={b['text']!r}")
        print("\n【登录按钮 login-account】:", data.get("loginAccount"))
        print("【验证码输入框】:", data.get("captchaInput"))
        print("【验证码图片】:", data.get("captchaImg"))
        print("\n【页面可见文字】")
        print("  ", data.get("bodyText"))
        app.quit()

    def loaded(ok):
        print("loadFinished:", ok)
        QTimer.singleShot(4000, lambda: dump("after4s"))

    view.loadFinished.connect(loaded)
    view.load(QUrl(URL))
    QTimer.singleShot(25000, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
