# -*- coding: utf-8 -*-
"""冒烟测试：自动填表 / 页面诊断 / 背景注入 / 主题切换 / 配置加密。

不改动真实配置（APPDATA 指向临时目录），并把各页面截图输出到 _shots/。
"""

from __future__ import annotations

import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="campus_smoke_")
os.environ["APPDATA"] = TMP
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = os.environ.get(
    "QTWEBENGINE_CHROMIUM_FLAGS", "") + " --no-sandbox --disable-gpu"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.autofill import (build_autofill_js, build_background_js,  # noqa: E402
                           build_inspect_js, parse_result)
from core.config import ConfigManager  # noqa: E402
from core.netcheck import check_online  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

PAGE = os.path.join(ROOT, "tests", "test_login.html")
SHOTS = os.path.join(ROOT, "_shots")
IMG = os.path.join(TMP, "bg.png")

results = []


def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"  -> {extra}" if extra else ""))


def make_image():
    os.makedirs(SHOTS, exist_ok=True)
    img = QImage(1600, 1000, QImage.Format_RGB32)
    p = QPainter(img)
    p.fillRect(img.rect(), QColor("#20304a"))
    p.setPen(QColor("#7fd1ff"))
    for i in range(0, 1600, 60):
        p.drawArc(i, 200, 400, 400, 30 * 16, 120 * 16)
    p.setPen(QColor("#ffd166"))
    p.drawEllipse(600, 380, 420, 300)
    p.end()
    img.save(IMG)
    return IMG


def shot(win, name):
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, name)
    win.grab().save(path)
    print(f"  截图 -> {path}")


def main():
    print("BOOT smoke test")
    app = QApplication(sys.argv)
    cfg = ConfigManager()
    cfg.settings.auto_connect_on_launch = False
    cfg.settings.url = PAGE
    cfg.settings.username = "20210001"
    cfg.settings.set_password("p@ssw0rd-测试")

    win = MainWindow(cfg, auto_launch=False)
    win._closing = True
    win._set_watchdog(False)
    win.resize(1120, 860)
    win.show()

    page = win.view.page()

    # ---------- 1 自动填表 ----------
    def step1(_ok=None):
        print("\n[1] 自动识别并填写登录表单")
        js = build_autofill_js(cfg.settings.username, cfg.settings.get_password())
        page.runJavaScript(js, step1_cb)

    def step1_cb(res):
        res = parse_result(res)
        check("识别到密码框", bool(res.get("found")), str(res.get("pwdSel")))
        check("识别到账号框", bool(res.get("userSel")), str(res.get("userSel")))
        check("识别到登录按钮", bool(res.get("btnSel")), str(res.get("btnSel")))
        check("已点击提交", bool(res.get("submitted")))
        QTimer.singleShot(300, step2)

    def step2():
        print("\n[2] 页面是否收到账号密码")
        page.runJavaScript("document.getElementById('result').innerText", step2_cb)

    def step2_cb(text):
        t = str(text)
        check("提交结果正确", "LOGIN_OK" in t and "user=20210001" in t and "p@ssw0rd-测试" in t, t)
        check("复选框已勾选", "remember=true" in t, t)
        step3()

    # ---------- 3 诊断 ----------
    def step3():
        print("\n[3] 页面结构诊断")
        page.runJavaScript(build_inspect_js(), step3_cb)

    def step3_cb(res):
        res = parse_result(res)
        check("诊断出 form", len(res.get("forms", [])) >= 1, str(len(res.get("forms", []))))
        check("诊断出密码框", len(res.get("password", [])) >= 1)
        check("诊断出按钮", len(res.get("buttons", [])) >= 1)
        step4()

    # ---------- 4 背景 ----------
    def step4():
        print("\n[4] 自定义背景注入")
        uri = MainWindow._image_to_data_uri(make_image())
        check("图片转 data URI", uri.startswith("data:image/jpeg;base64,") and len(uri) > 1000,
              f"{len(uri)} 字符")
        js = build_background_js(uri=uri, enabled=True, dim=35, blur=0,
                                 fit="cover", light=False, hollow=True)
        page.runJavaScript(js, step4_cb)

    def step4_cb(res):
        res = parse_result(res)
        check("背景已应用", bool(res.get("ok")), str(res.get("msg")))
        page.runJavaScript(
            "!!document.getElementById('__campus_bg') && !!document.getElementById('__campus_dim')"
            " && getComputedStyle(document.getElementById('__campus_bg')).backgroundImage.length > 20",
            step4_check)

    def step4_check(v):
        check("背景节点生效", v is True, str(v))
        step5()

    # ---------- 5 主题与截图 ----------
    def step5():
        print("\n[5] 明暗主题与界面截图")
        cfg.settings.theme = "light"
        win._apply_theme_to_ui()
        win.tabs.setCurrentIndex(0)
        QTimer.singleShot(500, lambda: (shot(win, "01_light_connect.png"), step5b()))

    def step5b():
        win.tabs.setCurrentIndex(1)
        QTimer.singleShot(600, lambda: (shot(win, "02_light_preview.png"), step5c()))

    def step5c():
        win.tabs.setCurrentIndex(3)
        QTimer.singleShot(400, lambda: (shot(win, "03_light_advanced.png"), step5d()))

    def step5d():
        win.tabs.setCurrentIndex(2)
        QTimer.singleShot(400, lambda: (shot(win, "04_light_appearance.png"), step5e()))

    def step5e():
        cfg.settings.theme = "dark"
        win._apply_theme_to_ui()
        win.tabs.setCurrentIndex(0)
        QTimer.singleShot(500, lambda: (shot(win, "05_dark_connect.png"), step5f()))

    def step5f():
        win.tabs.setCurrentIndex(1)
        QTimer.singleShot(600, lambda: (shot(win, "06_dark_preview.png"), step5g()))

    def step5g():
        win.tabs.setCurrentIndex(3)
        QTimer.singleShot(400, lambda: (shot(win, "07_dark_advanced.png"), step6()))

    # ---------- 6 网络探测 ----------
    def step6():
        print("\n[6] 网络探测")
        ok, detail = check_online()
        check("探测函数可运行", True, f"online={ok} · {detail}")
        step7()

    # ---------- 7 配置加密 ----------
    def step7():
        print("\n[7] 配置加密存储")
        cfg.settings.username = "20210001"
        cfg.settings.set_password("p@ssw0rd-测试")
        cfg.save()
        cfg2 = ConfigManager()
        check("密码可解密还原", cfg2.settings.get_password() == "p@ssw0rd-测试")
        check("账号已持久化", cfg2.settings.username == "20210001")
        check("密码未明文落盘", "p@ssw0rd" not in open(cfg.path, encoding="utf-8").read())
        finish()

    def finish():
        passed = sum(1 for _, ok, _ in results if ok)
        print(f"\n===== 冒烟测试完成：{passed}/{len(results)} 通过 =====")
        win._closing = True
        app.quit()

    win.view.loadFinished.connect(
        lambda ok: (print("PAGE loaded", ok), QTimer.singleShot(400, step1) if ok else None))
    win.view.load(QUrl.fromLocalFile(PAGE))
    QTimer.singleShot(60000, app.quit)
    return_code = app.exec()
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
