# -*- coding: utf-8 -*-
"""主界面 —— Neumorphism（新拟物派）风格。"""

from __future__ import annotations

import html
import os
import time
import shutil
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QUrl, QByteArray, QBuffer, QIODevice, QSize
from PySide6.QtGui import (QIcon, QPixmap, QPainter, QColor, QPen, QFont,
                           QDesktopServices, QImage)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFileDialog, QMessageBox, QSystemTrayIcon, QMenu, QStatusBar,
    QSizePolicy, QApplication, QFrame, QScrollArea,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage

from core.autofill import build_background_js
from core.config import (ConfigManager, APP_TITLE, APP_VERSION, AUTHOR,
                         app_data_dir, logs_dir, backgrounds_dir)
from core.engine import ConnectEngine, ProbeWorker
from core.logger import get_logger
from core import autostart, wifi
from ui.theme import apply_theme
from ui import neumorphism as neu
from ui.neumorphism import (NeuButton, NeuLineEdit, NeuTextEdit, NeuPanel,
                            NeuCheckBox, NeuRadioButton, NeuSlider, NeuSpinBox,
                            NeuComboBox, NeuTabBar, NeuDot)

ACCENT_ICON = "#6d5dfc"

# 认证成功后的一段静默期：这段时间内不再响应自动触发。
# 否则"开机自动"和"WiFi 触发"会几乎同时各跑一遍，第二次纯属白耗
# （实测见过同一秒起了两个流程，第二个空转 12 秒）。
SUCCESS_QUIET_SEC = 25


def make_app_icon(color: str = ACCENT_ICON) -> QIcon:
    """自绘 WiFi 图标。"""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setCapStyle(Qt.RoundCap)
    for i, inset in enumerate((6, 18, 30)):
        pen.setWidth(6 if i == 2 else 5)
        p.setPen(pen)
        p.drawArc(inset, inset, 64 - inset * 2, 64 - inset * 2, 315 * 16, 270 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(26, 26, 12, 12)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, cfg: ConfigManager, auto_launch: bool = False):
        super().__init__()
        self.cfg = cfg
        self.s = cfg.settings
        self.log = get_logger()
        self._bg_uri = ""
        self._watchdog_on = False
        self._closing = False
        self._palette = dict(neu.PALETTES["light"])

        self.setWindowTitle(f"{APP_TITLE} v{APP_VERSION}")
        self.setWindowIcon(make_app_icon())
        self.resize(1140, 900)
        self.setMinimumSize(960, 680)

        # —— 无线监听（定时器先建好，避免信号早触发时报属性不存在）——
        self._last_ssid = None
        self._last_wifi_probe = 0.0
        self._last_trigger_time = 0.0
        self._last_wifi_connect_at = 0.0
        self._last_success_at = 0.0
        self._trigger_ssid = ""
        self._wifi_probe_worker = None
        self.wifi_timer = QTimer(self)
        self.wifi_timer.timeout.connect(self._wifi_tick)

        # —— 内嵌浏览器（此刻只是占个位，真正初始化推迟到窗口出来之后）——
        self._browser_ready = False
        self._browser_starting = False
        self._pending_browser_action = None
        self.view = QWebEngineView()
        self.view.setMinimumHeight(260)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # —— 引擎 ——
        self.engine = ConnectEngine(cfg, self.view, self)
        self.engine.log.connect(self.append_log)
        self.engine.status.connect(self.set_status)
        self.engine.finished.connect(self.on_finished)
        self.engine.need_manual.connect(self.on_need_manual)
        self.view.loadFinished.connect(self._on_page_loaded)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._do_save)

        self._build_ui()
        self._build_tray()
        self.sync_from_cfg()
        # 到这为止界面才算能读；在此之前触发的自动保存不该去收集界面状态
        self._ui_ready = True
        # 程序被移动/改名过的话，把开机自启项修正到当前位置（否则开机没反应）
        try:
            fixed, note = autostart.repair_if_stale()
            if fixed:
                self._blocked = True
                self.cb_autostart.setChecked(True)
                self._blocked = False
                self.append_log(note)
        except Exception:
            pass
        self._apply_theme_to_ui()
        # 背景图要解码 + 缩放 + 重编码，别堵在启动路径上
        QTimer.singleShot(0, self._init_background_uri)

        self.log.qt_handler.record.connect(self.append_log)

        self.watchdog = QTimer(self)
        self.watchdog.timeout.connect(self._watchdog_tick)
        self._worker = None

        # —— 无线网络监听 ——
        self._check_wifi_hardware()
        self._set_watchdog(self.s.reconnect_enabled)

        self.set_status("就绪")
        if self.s.auto_connect_on_launch and self.s.url:
            delay = max(0, int(self.s.start_delay))
            self.append_log(f"将在 {delay} 秒后自动尝试连接…")
            QTimer.singleShot(delay * 1000,
                              lambda: self._start_engine("启动自动", auto=True) if not self._closing else None)
        elif not self.s.url:
            self.append_log("还没配置认证页地址，到【连接】页填好账号密码后点保存即可")

        if auto_launch and self.s.launch_minimized:
            self.hide()
            self.tray.showMessage(APP_TITLE, "已在后台启动，正在守护校园网连接",
                                  QSystemTrayIcon.Information, 3000)
        else:
            self.show()

    # ==================== 通用小部件 ====================
    @staticmethod
    def _label(text: str, role: str = "muted", size: int = 13, bold: bool = False) -> QLabel:
        lab = QLabel(text)
        lab.setProperty("role", role)
        f = lab.font()
        f.setPointSize(max(8, int(size * 0.72)))
        f.setBold(bold)
        lab.setFont(f)
        return lab

    def _card(self, title: str = "", subtitle: str = "") -> tuple[NeuPanel, QVBoxLayout]:
        panel = NeuPanel()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(27, 22, 27, 20)
        lay.setSpacing(10)
        if title:
            head = QWidget()
            hl = QVBoxLayout(head)
            hl.setContentsMargins(2, 0, 2, 0)
            hl.setSpacing(2)
            t = self._label(title, "title", 14, True)
            hl.addWidget(t)
            if subtitle:
                hl.addWidget(self._label(subtitle, "muted", 11))
            lay.addWidget(head)
        return panel, lay

    @staticmethod
    def _field(label: str, widget: QWidget) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(14)
        lab = QLabel(label)
        lab.setFixedWidth(96)
        lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lab.setProperty("role", "muted")
        g.addWidget(lab, 0, 0)
        g.addWidget(widget, 0, 1)
        g.setColumnStretch(1, 1)
        return w

    @staticmethod
    def _wrap_scroll(inner: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(inner)
        inner.setAutoFillBackground(False)
        sa.viewport().setAutoFillBackground(False)
        return sa

    # ==================== 界面搭建 ====================
    def _build_ui(self):
        root = QWidget()
        rv = QVBoxLayout(root)
        rv.setContentsMargins(22, 18, 22, 14)
        rv.setSpacing(14)

        # ---- 头部 ----
        head = NeuPanel(radius=18, pad=18)
        rv.addWidget(head)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(make_app_icon().pixmap(38, 38))
        logo.setProperty("role", "plain")
        hl.addWidget(logo)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title_box.addWidget(self._label(APP_TITLE, "body", 17, True))
        title_box.addWidget(self._label("自动识别表单 · 掉线重连 · 自定义背景", "muted", 11))
        hl.addLayout(title_box)
        hl.addStretch(1)

        self.dot = NeuDot(color_key="accent")
        hl.addWidget(self.dot)
        st_box = QVBoxLayout()
        st_box.setSpacing(1)
        self.lbl_status = self._label("就绪", "body", 14, True)
        self.lbl_last = self._label("上次：—", "muted", 11)
        st_box.addWidget(self.lbl_status)
        st_box.addWidget(self.lbl_last)
        hl.addLayout(st_box)
        hl.addSpacing(10)
        self.btn_themesw = NeuButton("切换主题", compact=True)
        self.btn_themesw.clicked.connect(self._cycle_theme)
        hl.addWidget(self.btn_themesw)

        # ---- 标签页 ----
        self.tabs = QTabWidget()
        self.tabs.setTabBar(NeuTabBar())
        self.tabs.addTab(self._wrap_scroll(self._build_connect_tab()), "连接")
        self.tabs.addTab(self._build_preview_tab(), "预览")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.addTab(self._wrap_scroll(self._build_appearance_tab()), "外观")
        self.tabs.addTab(self._wrap_scroll(self._build_advanced_tab()), "高级")
        self.tabs.addTab(self._build_log_tab(), "日志")
        self.tabs.addTab(self._wrap_scroll(self._build_about_tab()), "关于")
        rv.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

        sb = QStatusBar()
        self.sb_status = self._label("就绪", "muted", 11)
        self.sb_right = self._label(f"v{APP_VERSION} · 作者 {AUTHOR}", "muted", 11)
        sb.addWidget(self.sb_status)
        sb.addPermanentWidget(self.sb_right)
        self.setStatusBar(sb)

    # ---------- 连接页 ----------
    def _build_connect_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(9, 9, 9, 9)
        v.setSpacing(4)

        card, lay = self._card("连接配置", "程序会在下方预览页里自动识别登录表单、填写账号密码并提交")
        cols = QWidget()
        ch = QHBoxLayout(cols)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(34)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(10)
        self.ed_url = NeuLineEdit()
        self.ed_url.setPlaceholderText("http://10.10.10.1")
        self.ed_user = NeuLineEdit()
        self.ed_user.setPlaceholderText("学号 / 账号")
        self.ed_pwd = NeuLineEdit(password=True)
        self.ed_pwd.setPlaceholderText("校园网密码")
        self.cb_show_pwd = NeuCheckBox("显示")
        pwd_row = QWidget()
        ph = QHBoxLayout(pwd_row)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(12)
        ph.addWidget(self.ed_pwd, 1)
        ph.addWidget(self.cb_show_pwd)
        lv.addWidget(self._field("认证页地址", self.ed_url))
        lv.addWidget(self._field("账号", self.ed_user))
        lv.addWidget(self._field("密码", pwd_row))
        lv.addStretch(1)
        ch.addWidget(left, 3)

        right = QWidget()
        rg = QGridLayout(right)
        rg.setContentsMargins(0, 0, 0, 0)
        rg.setHorizontalSpacing(16)
        rg.setVerticalSpacing(14)
        self.btn_connect = NeuButton("立即连接", accent=True)
        self.btn_test = NeuButton("测试连接")
        self.btn_inspect = NeuButton("诊断页面")
        self.btn_watchdog = NeuButton("停止后台")
        self.btn_external = NeuButton("外部浏览器")
        self.btn_shot = NeuButton("页面截图")
        self.btn_save = NeuButton("保存配置", accent=True)
        for i, b in enumerate((self.btn_connect, self.btn_test, self.btn_inspect,
                               self.btn_watchdog, self.btn_external, self.btn_shot)):
            rg.addWidget(b, i // 2, i % 2)
        rg.addWidget(self.btn_save, 3, 0, 1, 2)
        rg.setRowStretch(4, 1)
        rg.setColumnStretch(0, 1)
        rg.setColumnStretch(1, 1)
        ch.addWidget(right, 2)
        lay.addWidget(cols)
        v.addWidget(card)

        tip = self._label("认证页在【预览】页里全屏显示，点【立即连接】会自动切过去", "muted", 11)
        tip.setAlignment(Qt.AlignCenter)
        v.addWidget(tip)
        v.addStretch(1)

        self.btn_save.clicked.connect(self._on_save_clicked)
        self.btn_connect.clicked.connect(lambda: self._connect_now("手动"))
        self.btn_test.clicked.connect(self.run_test)
        self.btn_inspect.clicked.connect(self.run_inspect)
        self.btn_watchdog.clicked.connect(self.toggle_watchdog)
        self.btn_external.clicked.connect(self.open_external)
        self.btn_shot.clicked.connect(self.save_screenshot)
        self.cb_show_pwd.toggled.connect(
            lambda on: self.ed_pwd.setEchoMode(NeuLineEdit.Normal if on else NeuLineEdit.Password))
        self.ed_url.textChanged.connect(self._dirty)
        self.ed_user.textChanged.connect(self._dirty)
        self.ed_pwd.textChanged.connect(self._dirty_password)
        return w

    # ---------- 预览页 ----------
    def _build_preview_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(9, 9, 9, 9)
        v.setSpacing(4)

        card, lay = self._card("认证页预览", "自动填表就发生在这个页面里；窗口拉大，页面也跟着变大")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        bar = QWidget()
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(12)
        self.lbl_url = self._label("浏览器尚未启动 · 点【打开认证页】或【立即连接】时自动准备",
                                   "muted", 11)
        self.btn_go_auth = NeuButton("打开认证页", accent=True)
        self.btn_reload = NeuButton("刷新")
        self.btn_back = NeuButton("后退")
        self.btn_external2 = NeuButton("外部浏览器")
        self.btn_shot2 = NeuButton("截图")
        self.btn_use_url = NeuButton("设为认证页")
        self.cb_preview = NeuCheckBox("启用预览页")
        bh.addWidget(self.lbl_url, 1)
        for b in (self.cb_preview, self.btn_go_auth, self.btn_use_url, self.btn_reload,
                  self.btn_back, self.btn_external2, self.btn_shot2):
            bh.addWidget(b)
        lay.addWidget(bar)

        # 网页放在一个容器里，靠「启用预览页」决定是显示它、还是只留一句说明。
        # 关掉时 view 仍然是容器的子控件（只是隐藏）—— Chromium 照常跑 JS，
        # 我们不需要那些像素，只需要页面把表单渲染出来。
        self.preview_host = QWidget()
        ph = QVBoxLayout(self.preview_host)
        ph.setContentsMargins(0, 0, 0, 0)
        self.preview_tip = self._label(
            "预览已关闭 —— 浏览器在后台安静地跑，不再占用界面渲染\n"
            "连接过程看【日志】页；想看网页就勾上左边的「启用预览页」",
            "muted", 12)
        self.preview_tip.setAlignment(Qt.AlignCenter)
        self.preview_tip.setWordWrap(True)
        lay.addWidget(self.preview_host, 1)
        v.addWidget(card, 1)

        self.btn_go_auth.clicked.connect(self._open_auth_page)
        self.btn_reload.clicked.connect(self.view.reload)
        self.btn_back.clicked.connect(self.view.back)
        self.btn_external2.clicked.connect(self.open_external)
        self.btn_shot2.clicked.connect(self.save_screenshot)
        self.btn_use_url.clicked.connect(self._use_current_url)
        self.cb_preview.toggled.connect(self._on_preview_toggled)
        self._apply_preview_mode()
        self.view.urlChanged.connect(self._on_url_changed)
        return w

    def _on_preview_toggled(self, on: bool):
        self._dirty()
        self._apply_preview_mode()
        self.append_log("预览页已" + ("开启" if on else "关闭（浏览器转入后台，更省资源）"))

    def _apply_preview_mode(self):
        """按开关决定预览区显示网页、还是只留一句说明。"""
        if not hasattr(self, "preview_host"):
            return
        enabled = bool(self.cb_preview.isChecked()) if hasattr(self, "cb_preview") else True
        lay = self.preview_host.layout()
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
        self.view.setParent(self.preview_host)      # 始终挂在容器下，保持存活
        if enabled:
            lay.addWidget(self.view)
            self.view.show()
        else:
            lay.addWidget(self.preview_tip)
            self.preview_tip.show()
        if hasattr(self, "btn_shot2"):
            self.btn_shot2.setEnabled(enabled)

    def _use_current_url(self):
        """在预览页手动翻到真正的登录页后，一键存为认证页地址。"""
        u = self.view.url().toString()
        if not u or u.startswith("about:") or u.startswith("data:"):
            QMessageBox.information(self, "提示", "当前还没有打开任何页面")
            return
        self.ed_url.setText(u)
        self.s.url = u
        self._flush()
        self.append_log(f"已把当前页面设为认证页地址：{u}")
        self.set_status("认证页地址已更新")

    def _on_tab_changed(self, idx):
        if self.tabs.tabText(idx) == "预览" and not getattr(self, "_browser_ready", False):
            self._ensure_browser(lambda: None)

    def _on_url_changed(self, url):
        if hasattr(self, "lbl_url"):
            self.lbl_url.setText(url.toString())

    def _open_auth_page(self):
        self._flush()
        urls = ConnectEngine._build_candidates(self.s.url)
        if not urls:
            QMessageBox.information(self, "提示", "请先填写认证页地址")
            self._goto_tab("连接")
            return
        if len(urls) > 1:
            self.append_log(f"按候选顺序打开，共 {len(urls)} 个候选地址")
        self._ensure_browser(lambda: self.view.load(urls[0]))

    def _goto_tab(self, name: str):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                self.tabs.setCurrentIndex(i)
                return

    # ---------- 外观页 ----------
    def _build_appearance_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(9, 9, 9, 9)
        v.setSpacing(4)

        card, lay = self._card("主题", "明亮环境选浅色，夜间选深色，光源方向始终左上")
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(26)
        self.rb_dark = NeuRadioButton("深色")
        self.rb_light = NeuRadioButton("浅色")
        self.rb_system = NeuRadioButton("跟随系统")
        for rb, val in ((self.rb_dark, "dark"), (self.rb_light, "light"), (self.rb_system, "system")):
            rb.toggled.connect(lambda on, m=val: self._change_theme(m) if on else None)
            rh.addWidget(rb)
        rh.addStretch(1)
        lay.addWidget(row)
        v.addWidget(card)

        card2, lay2 = self._card("网页背景", "把自己的图作为认证页背景，认证功能不受影响")
        self.cb_bg = NeuCheckBox("启用自定义背景")
        pick = QWidget()
        ph = QHBoxLayout(pick)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(12)
        self.btn_pick_bg = NeuButton("选择图片")
        self.btn_clear_bg = NeuButton("清除")
        self.lbl_bg_path = self._label("未选择", "muted", 11)
        ph.addWidget(self.btn_pick_bg)
        ph.addWidget(self.btn_clear_bg)
        ph.addWidget(self.lbl_bg_path, 1)
        self.cb_bg_hollow = NeuCheckBox("淡化页面原有底色（效果更明显）")
        dim_row = QWidget()
        dh = QHBoxLayout(dim_row)
        dh.setContentsMargins(0, 0, 0, 0)
        dh.setSpacing(12)
        self.sl_dim = NeuSlider()
        self.sl_dim.setRange(0, 80)
        self.lbl_dim = self._label("35%", "muted", 12)
        self.lbl_dim.setFixedWidth(46)
        dh.addWidget(self.sl_dim, 1)
        dh.addWidget(self.lbl_dim)
        blur_row = QWidget()
        bh = QHBoxLayout(blur_row)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(12)
        self.sl_blur = NeuSlider()
        self.sl_blur.setRange(0, 20)
        self.lbl_blur = self._label("0px", "muted", 12)
        self.lbl_blur.setFixedWidth(46)
        bh.addWidget(self.sl_blur, 1)
        bh.addWidget(self.lbl_blur)
        self.cb_fit = NeuComboBox()
        self.cb_fit.addItem("铺满（cover）", "cover")
        self.cb_fit.addItem("适应（contain）", "contain")
        self.cb_fit.addItem("拉伸填满", "100% 100%")
        self.cb_fit.addItem("原始大小", "auto")
        self.preview = QLabel("无背景")
        self.preview.setFixedHeight(150)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setProperty("role", "muted")

        lay2.addWidget(self.cb_bg)
        lay2.addWidget(self._field("背景图片", pick))
        lay2.addWidget(self._field("暗化程度", dim_row))
        lay2.addWidget(self._field("背景模糊", blur_row))
        lay2.addWidget(self._field("填充方式", self.cb_fit))
        lay2.addWidget(self.cb_bg_hollow)
        prev_panel = NeuPanel(radius=14, pad=10, inset=True)
        pv = QVBoxLayout(prev_panel)
        pv.setContentsMargins(20, 20, 20, 20)
        pv.addWidget(self.preview)
        lay2.addWidget(prev_panel)
        self.btn_apply_bg = NeuButton("立即应用到页面", accent=True)
        lay2.addWidget(self.btn_apply_bg)
        v.addWidget(card2)
        v.addStretch(1)

        self.btn_pick_bg.clicked.connect(self.pick_background)
        self.btn_clear_bg.clicked.connect(self.clear_background)
        self.btn_apply_bg.clicked.connect(self.apply_background)
        self.cb_bg.toggled.connect(lambda _: (self._dirty(), self.apply_background()))
        self.cb_bg_hollow.toggled.connect(lambda _: (self._dirty(), self.apply_background()))
        self.sl_dim.valueChanged.connect(lambda v: (self.lbl_dim.setText(f"{v}%"),
                                                    self._dirty(), self.apply_background()))
        self.sl_blur.valueChanged.connect(lambda v: (self.lbl_blur.setText(f"{v}px"),
                                                     self._dirty(), self.apply_background()))
        self.cb_fit.currentIndexChanged.connect(lambda _: (self._dirty(), self.apply_background()))
        return w

    # ---------- 高级页 ----------
    def _build_advanced_tab(self):
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(9, 9, 9, 9)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        # 启动行为
        c1, l1 = self._card("启动行为")
        self.cb_autostart = NeuCheckBox("开机自动启动")
        self.cb_auto_connect = NeuCheckBox("启动后自动连接校园网")
        self.cb_minimized = NeuCheckBox("开机启动时最小化到托盘")
        self.cb_tray = NeuCheckBox("关闭窗口时最小化到托盘")
        self.sp_delay = NeuSpinBox()
        self.sp_delay.setRange(0, 120)
        self.sp_delay.setSuffix(" 秒")
        for x in (self.cb_autostart, self.cb_auto_connect, self.cb_minimized, self.cb_tray):
            l1.addWidget(x)
        l1.addWidget(self._field("启动后延迟", self.sp_delay))
        l1.addStretch(1)

        # 后台守护
        c2, l2 = self._card("后台守护")
        self.cb_reconnect = NeuCheckBox("掉线时自动重连")
        self.cb_compat = NeuCheckBox("浏览器兼容模式（推荐开启）")
        self.sp_interval = NeuSpinBox()
        self.sp_interval.setRange(10, 3600)
        self.sp_interval.setSuffix(" 秒")
        self.sp_retry = NeuSpinBox()
        self.sp_retry.setRange(0, 5)
        self.sp_retry.setSuffix(" 次")
        self.sp_retry_delay = NeuSpinBox()
        self.sp_retry_delay.setRange(1, 30)
        self.sp_retry_delay.setSuffix(" 秒")
        self.sp_timeout = NeuSpinBox()
        self.sp_timeout.setRange(5, 120)
        self.sp_timeout.setSuffix(" 秒")
        self.sp_wait = NeuSpinBox()
        self.sp_wait.setRange(1, 30)
        self.sp_wait.setSuffix(" 秒")
        l2.addWidget(self.cb_reconnect)
        l2.addWidget(self.cb_compat)
        l2.addWidget(self._field("检查间隔", self.sp_interval))
        l2.addWidget(self._field("重试次数", self.sp_retry))
        l2.addWidget(self._field("重试间隔", self.sp_retry_delay))
        l2.addWidget(self._field("加载超时", self.sp_timeout))
        l2.addWidget(self._field("提交后等待", self.sp_wait))
        l2.addStretch(1)

        # 联网检测
        c3, l3 = self._card("联网检测")
        self.ed_probe = NeuTextEdit()
        self.ed_probe.setFixedHeight(84)
        self.ed_probe.setPlaceholderText("每行一个探测地址\n地址|期望内容")
        self.ed_keyword = NeuLineEdit()
        self.sp_probe_timeout = NeuSpinBox()
        self.sp_probe_timeout.setRange(1, 20)
        self.sp_probe_timeout.setSuffix(" 秒")
        self.cb_skip = NeuCheckBox("已联网时跳过连接流程")
        l3.addWidget(self._field("探测地址", self.ed_probe))
        l3.addWidget(self._field("期望内容", self.ed_keyword))
        l3.addWidget(self._field("探测超时", self.sp_probe_timeout))
        l3.addWidget(self.cb_skip)
        l3.addStretch(1)

        # 网络触发（连上指定 WiFi 后才认证）
        c5, l5 = self._card("网络触发", "开机时 WiFi 还没连上，认证页打不开——这个功能就是等网络就绪")
        self.cb_wifi = NeuCheckBox("连上指定无线网络后自动认证")
        self.cb_wifi_connect = NeuCheckBox("断线时自动连接校园网（需先在 Windows 里连过）")
        ssid_row = QWidget()
        sr = QHBoxLayout(ssid_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(12)
        self.ed_ssid = NeuLineEdit()
        self.ed_ssid.setPlaceholderText("留空 = 任意无线网络")
        self.btn_ssid_now = NeuButton("用当前", compact=True)
        sr.addWidget(self.ed_ssid, 1)
        sr.addWidget(self.btn_ssid_now)
        self.sp_wifi_interval = NeuSpinBox()
        self.sp_wifi_interval.setRange(1, 60)
        self.sp_wifi_interval.setSuffix(" 秒")
        self.sp_wifi_wait = NeuSpinBox()
        self.sp_wifi_wait.setRange(0, 60)
        self.sp_wifi_wait.setSuffix(" 秒")
        self.lbl_wifi = self._label("检测中…", "muted", 11)

        # 自动识别校园网：不用手填名字，程序自己认
        self.cb_wifi_auto = NeuCheckBox("自动识别校园网（认过一次就记住）")
        known_row = QWidget()
        kr = QHBoxLayout(known_row)
        kr.setContentsMargins(0, 0, 0, 0)
        kr.setSpacing(12)
        self.lbl_known = self._label("尚未识别到，连上一次就会记住", "muted", 11)
        self.btn_clear_known = NeuButton("清空", compact=True)
        kr.addWidget(self.lbl_known, 1)
        kr.addWidget(self.btn_clear_known)

        l5.addWidget(self.cb_wifi)
        l5.addWidget(self.cb_wifi_auto)
        l5.addWidget(self.cb_wifi_connect)
        l5.addWidget(self._field("已识别的校园网", known_row))
        l5.addWidget(self._field("无线网络名", ssid_row))
        l5.addWidget(self._field("检查间隔", self.sp_wifi_interval))
        l5.addWidget(self._field("连上后等待", self.sp_wifi_wait))
        l5.addWidget(self._field("当前", self.lbl_wifi))
        l5.addStretch(1)

        # 表单兜底
        c4, l4 = self._card("表单兜底", "一般不用管；识别不顺、或要选运营商时才填")
        self.ed_sel_user = NeuLineEdit()
        self.ed_sel_pwd = NeuLineEdit()
        self.ed_sel_btn = NeuLineEdit()
        self.ed_sel_user.setPlaceholderText("#username")
        self.ed_sel_pwd.setPlaceholderText("input[type=password]")
        self.ed_sel_btn.setPlaceholderText("#loginBtn")
        self.ed_domain = NeuLineEdit()
        self.ed_domain.setPlaceholderText("如 联通 / 电信 / 移动；留空按页面默认")
        self.cb_submit = NeuCheckBox("填完自动点击登录")
        self.cb_remember = NeuCheckBox("自动勾选“记住我 / 同意协议”")
        self.cb_close_page = NeuCheckBox("连接成功后清空预览页面")
        l4.addWidget(self._field("运营商", self.ed_domain))
        l4.addWidget(self._field("账号框", self.ed_sel_user))
        l4.addWidget(self._field("密码框", self.ed_sel_pwd))
        l4.addWidget(self._field("登录按钮", self.ed_sel_btn))
        l4.addWidget(self.cb_submit)
        l4.addWidget(self.cb_remember)
        l4.addWidget(self.cb_close_page)
        l4.addStretch(1)

        grid.addWidget(c1, 0, 0)   # 启动行为
        grid.addWidget(c5, 0, 1)   # 网络触发
        grid.addWidget(c2, 1, 0)   # 后台守护
        grid.addWidget(c3, 1, 1)   # 联网检测
        grid.addWidget(c4, 2, 0)   # 表单兜底
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.btn_reset = NeuButton("恢复默认设置")
        self.btn_open_cfg = NeuButton("打开配置目录")
        bar = QWidget()
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(24, 0, 24, 4)
        bh.addWidget(self.btn_reset)
        bh.addWidget(self.btn_open_cfg)
        bh.addStretch(1)
        grid.addWidget(bar, 3, 0, 1, 2)

        self.btn_open_cfg.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(app_data_dir())))
        self.btn_reset.clicked.connect(self.reset_settings)
        self.cb_autostart.toggled.connect(self.on_autostart_toggle)

        for x in (self.cb_auto_connect, self.cb_minimized, self.cb_tray, self.cb_reconnect,
                  self.cb_compat, self.cb_skip, self.cb_remember, self.cb_close_page, self.cb_submit):
            x.toggled.connect(lambda _: self._dirty())
        for x in (self.sp_delay, self.sp_interval, self.sp_retry, self.sp_retry_delay,
                  self.sp_timeout, self.sp_wait, self.sp_probe_timeout):
            x.valueChanged.connect(lambda _: self._dirty())
        self.btn_ssid_now.clicked.connect(self._use_current_ssid)
        self.cb_wifi_auto.toggled.connect(
            lambda _: (self._dirty(), self._refresh_known_ssids()))
        self.cb_wifi_connect.toggled.connect(lambda _: self._dirty())
        self.btn_clear_known.clicked.connect(self._clear_known_ssids)
        self.cb_wifi.toggled.connect(lambda _: (self._dirty(), self._apply_wifi_watch()))
        self.sp_wifi_interval.valueChanged.connect(lambda _: (self._dirty(), self._apply_wifi_watch()))
        self.sp_wifi_wait.valueChanged.connect(lambda _: self._dirty())
        self.ed_ssid.textChanged.connect(lambda _: (self._dirty(), setattr(self, "_last_ssid", None)))
        self.ed_probe.textChanged.connect(lambda: self._dirty())
        for x in (self.ed_keyword, self.ed_sel_user, self.ed_sel_pwd,
                  self.ed_sel_btn, self.ed_domain):
            x.textChanged.connect(lambda _: self._dirty())
        return w

    # ---------- 日志页 ----------
    def _build_log_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(9, 9, 9, 9)
        v.setSpacing(4)
        card, lay = self._card("运行日志", "每一步都有记录，排查问题时先看这里")
        self.log_view = NeuTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(NeuTextEdit.NoWrap)
        f = QFont("Consolas")
        f.setPointSize(9)
        self.log_view.setFont(f)
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(12)
        b1 = NeuButton("清空显示")
        b2 = NeuButton("导出日志")
        b3 = NeuButton("打开日志目录")
        b4 = NeuButton("复制全部", accent=True)
        rh.addWidget(b4)
        rh.addWidget(b1)
        rh.addWidget(b2)
        rh.addWidget(b3)
        rh.addStretch(1)
        lay.addWidget(row)
        lay.addWidget(self.log_view, 1)
        v.addWidget(card, 1)
        b1.clicked.connect(self.log_view.clear)
        b2.clicked.connect(self.export_log)
        b3.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(logs_dir())))
        b4.clicked.connect(self.copy_log)
        return w

    def copy_log(self):
        try:
            QApplication.clipboard().setText(self.log_view.toPlainText())
            self.set_status("日志已复制到剪贴板")
            self.append_log("已把当前日志复制到剪贴板")
        except Exception as e:
            self.append_log(f"复制失败：{e}")

    # ---------- 关于页 ----------
    def _build_about_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(9, 9, 9, 9)
        v.setSpacing(4)

        card, lay = self._card()
        logo = QLabel()
        logo.setPixmap(make_app_icon().pixmap(72, 72))
        logo.setAlignment(Qt.AlignCenter)
        logo.setProperty("role", "plain")
        lay.addWidget(logo)
        t = self._label(APP_TITLE, "body", 20, True)
        t.setAlignment(Qt.AlignCenter)
        s = self._label(f"版本 {APP_VERSION} · 作者 {AUTHOR}", "muted", 12)
        s.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        lay.addWidget(s)
        tip = self._label("新拟物派界面 · 双光源柔光 · 明暗双主题", "title", 11)
        tip.setAlignment(Qt.AlignCenter)
        lay.addWidget(tip)

        card2, lay2 = self._card("它能做什么")
        self.about_body = NeuTextEdit()
        self.about_body.setReadOnly(True)
        self.about_body.setMinimumHeight(300)
        lay2.addWidget(self.about_body)
        v.addWidget(card)
        v.addWidget(card2, 1)

        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(12)
        b1 = NeuButton("打开配置目录")
        b2 = NeuButton("打开日志目录")
        b3 = NeuButton("关于作者")
        rh.addWidget(b1)
        rh.addWidget(b2)
        rh.addWidget(b3)
        rh.addStretch(1)
        v.addWidget(row)
        b1.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(app_data_dir())))
        b2.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(logs_dir())))
        b3.clicked.connect(lambda: QMessageBox.information(
            self, "关于", f"作者：{AUTHOR}\n\n{APP_TITLE} v{APP_VERSION}\n"
                          f"遇到问题先看【日志】页，那里有完整的每一步记录。"))
        return w

    # ==================== 托盘 ====================
    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_app_icon(), self)
        self.tray.setToolTip(f"{APP_TITLE} v{APP_VERSION}")
        menu = QMenu()
        a_show = menu.addAction("显示主界面")
        a_conn = menu.addAction("立即连接")
        a_stop = menu.addAction("停止后台")
        menu.addSeparator()
        a_quit = menu.addAction("退出")
        self.tray.setContextMenu(menu)
        a_show.triggered.connect(self.show_normal)
        a_conn.triggered.connect(lambda: self._connect_now("托盘"))
        a_stop.triggered.connect(lambda: self._set_watchdog(False))
        a_quit.triggered.connect(self.exit_app)
        self.tray.activated.connect(
            lambda r: self.show_normal() if r in (QSystemTrayIcon.Trigger,
                                                  QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    def show_normal(self):
        self.show()
        self.raise_()
        self.activateWindow()

    # ==================== 配置同步 ====================
    def sync_from_cfg(self):
        s = self.s
        self._blocked = True
        self.ed_url.setText(s.url)
        self.ed_user.setText(s.username)
        self.ed_pwd.setText(s.get_password())
        self.cb_autostart.setChecked(autostart.is_enabled())
        self.cb_auto_connect.setChecked(s.auto_connect_on_launch)
        self.sp_delay.setValue(s.start_delay)
        self.cb_minimized.setChecked(s.launch_minimized)
        self.cb_tray.setChecked(s.close_to_tray)
        self.cb_reconnect.setChecked(s.reconnect_enabled)
        self.cb_compat.setChecked(s.browser_compat_mode)
        self.sp_interval.setValue(s.reconnect_interval)
        self.sp_retry.setValue(s.retry_times)
        self.sp_retry_delay.setValue(s.retry_delay)
        self.sp_timeout.setValue(s.page_load_timeout)
        self.sp_wait.setValue(s.post_submit_wait)
        self.ed_probe.setPlainText(s.probe_url)
        self.ed_keyword.setText(s.probe_keyword)
        self.sp_probe_timeout.setValue(s.probe_timeout)
        self.cb_skip.setChecked(s.skip_if_online)
        self.cb_wifi.setChecked(s.wifi_trigger_enabled)
        self.cb_wifi_auto.setChecked(s.wifi_auto_detect)
        self.cb_wifi_connect.setChecked(s.wifi_auto_connect)
        self.ed_ssid.setText(s.wifi_ssid)
        self.sp_wifi_interval.setValue(s.wifi_check_interval)
        self.sp_wifi_wait.setValue(s.wifi_wait)
        self.ed_sel_user.setText(s.sel_username)
        self.ed_sel_pwd.setText(s.sel_password)
        self.ed_sel_btn.setText(s.sel_submit)
        self.ed_domain.setText(s.domain)
        self.cb_submit.setChecked(s.auto_submit)
        self.cb_remember.setChecked(s.remember_checkbox)
        self.cb_close_page.setChecked(s.close_page_after_success)
        self.cb_bg.setChecked(s.bg_enabled)
        self.sl_dim.setValue(s.bg_dim)
        self.sl_blur.setValue(s.bg_blur)
        self.lbl_dim.setText(f"{s.bg_dim}%")
        self.lbl_blur.setText(f"{s.bg_blur}px")
        idx = self.cb_fit.findData(s.bg_fit)
        self.cb_fit.setCurrentIndex(max(0, idx))
        self.lbl_bg_path.setText(os.path.basename(s.bg_file) if s.bg_file else "未选择")
        {"dark": self.rb_dark, "light": self.rb_light,
         "system": self.rb_system}.get(s.theme, self.rb_light).setChecked(True)
        self._refresh_known_ssids()
        if hasattr(self, "cb_preview"):
            self.cb_preview.setChecked(s.preview_enabled)
            self._apply_preview_mode()
        self._blocked = False

    def collect_from_ui(self) -> None:
        """把界面上的当前状态收进配置对象（只收集，不落盘、不排定时器）。

        以前只有【保存配置】按钮会收集界面状态，而勾选框/输入框的改动走的是
        自动保存（_dirty → 定时器 → _do_save），_do_save 直接把内存里那份**旧**配置
        写盘 —— 于是出现"勾上『启动后自动连接』，重启后又变回没勾"。
        现在 _do_save 每次落盘前都会先调这里。
        """
        s = self.s
        s.url = self.ed_url.text().strip()
        s.username = self.ed_user.text().strip()
        s.auto_connect_on_launch = self.cb_auto_connect.isChecked()
        s.start_delay = self.sp_delay.value()
        s.launch_minimized = self.cb_minimized.isChecked()
        s.close_to_tray = self.cb_tray.isChecked()
        s.reconnect_enabled = self.cb_reconnect.isChecked()
        s.browser_compat_mode = self.cb_compat.isChecked()
        s.reconnect_interval = self.sp_interval.value()
        s.retry_times = self.sp_retry.value()
        s.retry_delay = self.sp_retry_delay.value()
        s.page_load_timeout = self.sp_timeout.value()
        s.post_submit_wait = self.sp_wait.value()
        s.probe_url = self.ed_probe.toPlainText().strip()
        s.probe_keyword = self.ed_keyword.text().strip()
        s.probe_timeout = self.sp_probe_timeout.value()
        s.skip_if_online = self.cb_skip.isChecked()
        s.wifi_trigger_enabled = self.cb_wifi.isChecked()
        s.wifi_ssid = self.ed_ssid.text().strip()
        s.wifi_auto_detect = self.cb_wifi_auto.isChecked()
        s.wifi_auto_connect = self.cb_wifi_connect.isChecked()
        s.preview_enabled = self.cb_preview.isChecked()
        # 注意：wifi_known_ssids 由 _learn_ssid() 直接维护，界面上没有对应控件
        s.wifi_check_interval = self.sp_wifi_interval.value()
        s.wifi_wait = self.sp_wifi_wait.value()
        s.sel_username = self.ed_sel_user.text().strip()
        s.sel_password = self.ed_sel_pwd.text().strip()
        s.sel_submit = self.ed_sel_btn.text().strip()
        s.domain = self.ed_domain.text().strip()
        s.auto_submit = self.cb_submit.isChecked()
        s.remember_checkbox = self.cb_remember.isChecked()
        s.close_page_after_success = self.cb_close_page.isChecked()
        s.bg_enabled = self.cb_bg.isChecked()
        s.bg_dim = self.sl_dim.value()
        s.bg_blur = self.sl_blur.value()
        s.bg_fit = self.cb_fit.currentData() or "cover"
        s.auto_start = self.cb_autostart.isChecked()
        s.first_run = False

    def save_from_ui(self, force=False):
        self.collect_from_ui()
        if force:
            self._do_save()
        else:
            self._dirty()

    def _on_save_clicked(self):
        self.save_from_ui(True)
        self.append_log("配置已保存")
        self.set_status("配置已保存")

    def _dirty(self):
        if getattr(self, "_blocked", False):
            return
        self._save_timer.start(600)

    def _dirty_password(self):
        self.s.set_password(self.ed_pwd.text())
        self._dirty()

    def _do_save(self):
        # 落盘前先收一遍界面状态 —— 自动保存也必须反映用户刚才的改动
        if getattr(self, "_ui_ready", False):
            try:
                self.collect_from_ui()
            except Exception:
                pass
        if self.cfg.save():
            self.watchdog.setInterval(max(10, self.s.reconnect_interval) * 1000)
            self._apply_wifi_watch()

    def _flush(self):
        self._save_timer.stop()
        self._do_save()

    def reset_settings(self):
        if QMessageBox.question(self, "恢复默认设置",
                                "将清空除账号密码外的所有设置，确定吗？") != QMessageBox.Yes:
            return
        keep_user, keep_pwd, keep_url = self.s.username, self.s.get_password(), self.s.url
        self.cfg.settings = type(self.s)()
        self.cfg.settings.username = keep_user
        self.cfg.settings.set_password(keep_pwd)
        self.cfg.settings.url = keep_url
        self.s = self.cfg.settings
        self.engine.cfg = self.cfg
        self.sync_from_cfg()
        self._flush()
        self.append_log("已恢复默认设置（保留账号与地址）")

    def on_autostart_toggle(self, on):
        if getattr(self, "_blocked", False):
            return
        ok, msg = autostart.set_enabled(on)
        if ok:
            self.append_log(f"开机自启动已{'开启' if on else '关闭'}")
        else:
            self.append_log(f"开机自启动设置失败：{msg}")
            QMessageBox.warning(self, "提示", f"设置开机自启动失败：{msg}")
        self._dirty()

    # ==================== 主题 ====================
    def _cycle_theme(self):
        order = ["light", "dark", "system"]
        cur = self.s.theme if self.s.theme in order else "light"
        nxt = order[(order.index(cur) + 1) % len(order)]
        {"dark": self.rb_dark, "light": self.rb_light,
         "system": self.rb_system}[nxt].setChecked(True)

    def _change_theme(self, mode):
        if getattr(self, "_blocked", False):
            return
        if mode == self.s.theme and getattr(self, "_palette", None):
            return
        self.s.theme = mode
        btn = {"dark": self.rb_dark, "light": self.rb_light,
               "system": self.rb_system}.get(mode)
        if btn is not None and not btn.isChecked():
            self._blocked = True
            btn.setChecked(True)
            self._blocked = False
        self._apply_theme_to_ui()
        self._dirty()

    def _apply_theme_to_ui(self):
        app = QApplication.instance()
        p = apply_theme(app, self.s.theme)
        self._palette = p
        for wdg in self.findChildren(QWidget):
            wdg.update()
        # 注意：这里千万别碰 view.page()——首次访问要启动 Chromium，会卡 1 秒多
        if getattr(self, "_browser_ready", False):
            try:
                self.view.page().setBackgroundColor(QColor(p["bg"]))
            except Exception:
                pass
        self.log_colors = {
            "DEBUG": p["text3"], "INFO": p["text2"],
            "WARNING": p["warn"], "ERROR": p["danger"],
        }
        self._render_about()
        self.set_status(self.lbl_status.text())
        self.apply_background()

    def _render_about(self):
        if not hasattr(self, "about_body"):
            return
        p = self._palette
        body, strong, dim = p["text"], p["text"], p["text2"]
        items = [
            ("基础", ["本地加密保存账号、密码、认证页地址",
                     "开机自启动（可选），启动后自动打开认证页",
                     "自动识别登录表单，填入账号密码并点击登录",
                     "测试连接 / 诊断页面结构",
                     "随时停止后台守护"]),
            ("进阶", ["掉线自动重连的后台守护",
                     "自定义网页背景，把自己的图换到认证页上",
                     "明暗双主题，随环境切换",
                     "完整日志，便于排查"]),
            ("安全", ["密码经 Windows DPAPI 加密，绑定当前 Windows 账户，",
                     "换账户或换机器都无法解密；配置文件仅存于本机。"]),
        ]
        parts = [f'<div style="line-height:1.9; color:{dim};">']
        for title, lines in items:
            parts.append(f'<b style="color:{strong};">{title}</b><br>')
            for ln in lines:
                parts.append(f"· {ln}<br>")
            parts.append("<br>")
        parts.append("</div>")
        self.about_body.setHtml("".join(parts))

    # ==================== 背景 ====================
    def _init_background_uri(self):
        if self.s.bg_file and os.path.exists(self.s.bg_file):
            t0 = time.time()
            self._bg_uri = self._image_to_data_uri(self.s.bg_file)
            self._update_preview(self.s.bg_file)
            cost = time.time() - t0
            if cost > 0.3:
                self.append_log(f"背景图处理完成（{cost:.1f}s）")
            self.apply_background()

    @staticmethod
    def _image_to_data_uri(path: str, max_side: int = 1600) -> str:
        try:
            img = QImage(path)
            if img.isNull():
                return ""
            if img.width() > max_side or img.height() > max_side:
                img = img.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            buf = QByteArray()
            buffer = QBuffer(buf)
            buffer.open(QIODevice.WriteOnly)
            img.save(buffer, "JPG", 82)
            buffer.close()
            return "data:image/jpeg;base64," + bytes(buf.toBase64()).decode("ascii")
        except Exception:
            return ""

    def pick_background(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
        if not path:
            return
        try:
            os.makedirs(backgrounds_dir(), exist_ok=True)
            dst = os.path.join(backgrounds_dir(),
                               f"bg_{int(time.time())}{os.path.splitext(path)[1]}")
            shutil.copy2(path, dst)
            self.s.bg_file = dst
            self.lbl_bg_path.setText(os.path.basename(dst))
            self._bg_uri = self._image_to_data_uri(dst)
            self._update_preview(dst)
            self.s.bg_enabled = True
            self.cb_bg.setChecked(True)
            self.append_log(f"已选择背景图片：{os.path.basename(path)}")
            self.apply_background()
            self._flush()
        except Exception as e:
            self.append_log(f"设置背景失败：{e}")

    def clear_background(self):
        self.s.bg_file = ""
        self.s.bg_enabled = False
        self._bg_uri = ""
        self.cb_bg.setChecked(False)
        self.lbl_bg_path.setText("未选择")
        self.preview.setPixmap(QPixmap())
        self.preview.setText("无背景")
        self.apply_background()
        self._flush()

    def _update_preview(self, path):
        pm = QPixmap(path)
        if pm.isNull():
            return
        self.preview.setPixmap(pm.scaled(max(120, self.preview.width() - 10), 140,
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.preview.setText("")

    def _is_light_theme(self) -> bool:
        if self.s.theme == "light":
            return True
        if self.s.theme == "dark":
            return False
        try:
            return QColor(self._palette.get("bg", "#262a31")).lightness() > 128
        except Exception:
            return False

    def apply_background(self, _ok=None):
        if not getattr(self, "_bg_uri", None):
            return
        if not getattr(self, "_browser_ready", False):
            return          # 浏览器还没起来，等它就绪会自动补一次
        try:
            js = build_background_js(
                uri=self._bg_uri,
                enabled=self.s.bg_enabled,
                dim=self.s.bg_dim,
                blur=self.s.bg_blur,
                fit=self.s.bg_fit,
                light=self._is_light_theme(),
                hollow=self.cb_bg_hollow.isChecked() if hasattr(self, "cb_bg_hollow") else True,
            )
            self.view.page().runJavaScript(js)
        except Exception:
            pass

    def _on_page_loaded(self, ok):
        if ok:
            QTimer.singleShot(300, self.apply_background)

    # ==================== 连接 ====================
    def _connect_now(self, reason):
        self._flush()
        if not self.s.url:
            QMessageBox.information(self, "提示", "请先填写校园网认证页地址")
            self._goto_tab("连接")
            self.ed_url.setFocus()
            return
        self._goto_tab("预览")
        self._start_engine(reason)

    def run_test(self):
        self._flush()
        if not self.s.url:
            QMessageBox.information(self, "提示", "请先填写校园网认证页地址")
            return
        self.append_log("=== 开始测试连接（会真实执行一次登录）===")
        self._test_mode = True
        self._goto_tab("预览")
        self._start_engine("测试")

    def run_inspect(self):
        self._flush()
        self._goto_tab("日志")
        self._ensure_browser(self.engine.inspect)

    def on_finished(self, ok, msg):
        self.s.last_status = "成功" if ok else "失败"
        self.s.last_connect_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            # 记下成功时刻，供 _start_engine 的静默期使用
            self._last_success_at = time.time()
        self.lbl_last.setText(f"上次：{self.s.last_connect_time} {self.s.last_status}")
        self._dirty()
        self.dot.set_color("success" if ok else "danger")
        if getattr(self, "_test_mode", False):
            self._test_mode = False
            self.show_report(ok, msg)
        if ok and self.s.close_page_after_success:
            self.view.setUrl(QUrl("about:blank"))
        if ok:
            # 认证成功 —— 这就是校园网，把它的名字记下来，下次不用再猜
            if getattr(self, "_trigger_ssid", ""):
                self._learn_ssid(self._trigger_ssid, "认证成功")
                self._trigger_ssid = ""
            self.tray.showMessage(APP_TITLE, f"校园网已连接：{msg}",
                                  QSystemTrayIcon.Information, 2500)
        else:
            self.tray.showMessage(APP_TITLE, f"连接失败：{msg}\n详情看【日志】页",
                                  QSystemTrayIcon.Warning, 4000)

    def show_report(self, ok, msg):
        rep = self.engine.report or {}
        lines = [f"结果：{'成功' if ok else '失败'} — {msg}",
                 f"总耗时：{rep.get('cost', 0)} 秒", ""]
        for st in rep.get("steps", []):
            lines.append(f"· {st['step']}：{'通过' if st['ok'] else '未通过'}"
                         f"（{st['detail']}，{st['t']}s）")
        af = rep.get("autofill") or {}
        if af:
            lines += ["", "表单识别详情：",
                      f"  账号框：{af.get('userSel') or '未识别'}",
                      f"  密码框：{af.get('pwdSel') or '未识别'}",
                      f"  登录按钮：{af.get('btnSel') or '未识别'}",
                      f"  验证码：{'疑似存在' if af.get('captcha') else '未发现'}",
                      f"  页面标题：{af.get('title')}"]
        box = QMessageBox(self)
        box.setWindowTitle("测试报告")
        box.setText("\n".join(lines))
        box.setIcon(QMessageBox.Information if ok else QMessageBox.Warning)
        box.setDetailedText("\n".join(f"{k}: {v}" for k, v in rep.items() if k != "steps"))
        box.exec()

    def on_need_manual(self, why):
        self._goto_tab("预览")
        QMessageBox.information(
            self, "需要你手动处理",
            f"{why}。\n\n请在预览页里手动输入验证码并点击登录，\n"
            f"程序会在稍后自动复查网络状态。")

    def open_external(self):
        url = self.ed_url.text().strip()
        if not url:
            return
        if "://" not in url:
            url = "http://" + url
        QDesktopServices.openUrl(QUrl(url))

    def save_screenshot(self):
        if not getattr(self, "_browser_ready", False):
            QMessageBox.information(self, "提示", "浏览器还没启动，先打开一次认证页")
            return
        try:
            os.makedirs(logs_dir(), exist_ok=True)
            path = os.path.join(logs_dir(), f"shot_{int(time.time())}.png")
            self.view.grab().save(path)
            self.append_log(f"页面截图已保存：{path}")
            QMessageBox.information(self, "已保存", path)
        except Exception as e:
            self.append_log(f"截图失败：{e}")

    # ==================== 浏览器（延迟启动） ====================
    def _ensure_browser(self, on_ready):
        """需要浏览器时再启动它。

        首次访问 view.page() 会让 Chromium 内核初始化，实测要 1.3 秒，
        放在启动路径上就会变成"打开后卡几秒"。所以改成：
        窗口先显示出来，真正要用浏览器的时候（或切到预览页时）再初始化。
        """
        if getattr(self, "_browser_ready", False):
            on_ready()
            return
        self._pending_browser_action = on_ready
        if not getattr(self, "_browser_starting", False):
            self._start_browser()

    def _start_browser(self):
        self._browser_starting = True
        self.set_status("正在启动内置浏览器…")
        self.append_log("正在启动内置浏览器（首次约 1 秒，之后就快了）")
        QTimer.singleShot(30, self._do_init_browser)

    def _do_init_browser(self):
        t0 = time.time()
        page = None
        try:
            page = self.view.page()
            page.setBackgroundColor(QColor(self._palette.get("bg", "#262a31")))
        except Exception:
            pass
        # Qt 会在页面不可见时把它冻结（生命周期降到 Frozen）——
        # 而本程序大量时间缩在托盘里，或者用户干脆关掉了预览页。
        # 一冻结，认证页那个单页应用就渲染不完：账号密码框有了、
        # "登录"按钮却迟迟不出现，看着就像"必须手动点一下登录"。
        # 显式钉成 Active，比依赖命令行参数透传可靠得多。
        if page is not None:
            try:
                page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
                self.append_log("已把浏览器页面钉为活跃状态（后台也能渲染表单）")
            except Exception:
                pass
        self._browser_ready = True
        self._browser_starting = False
        self.append_log(f"浏览器就绪（用时 {time.time() - t0:.1f}s）")
        self.set_status("就绪")
        self.apply_background()
        fn, self._pending_browser_action = self._pending_browser_action, None
        if fn:
            QTimer.singleShot(0, fn)

    def _keep_page_active(self):
        """页面被隐藏时，确认它没被冻结。

        Qt 默认"看不见就冻结"，对普通网页没问题，对我们这种
        "必须让它在后台把表单渲染完"的用法是致命的。
        """
        if not getattr(self, "_browser_ready", False):
            return False
        try:
            page = self.view.page()
            if page.lifecycleState() != QWebEnginePage.LifecycleState.Active:
                page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
                self.append_log("检测到浏览器页面被冻结，已重新激活")
                return True
        except Exception:
            pass
        return False

    def _start_engine(self, reason: str, submit: bool = True, auto: bool = False):
        """启动一次认证流程。

        auto=True 表示这是程序自己发起的（后台守护 / 无线触发 / 开机自动），
        这种情况下会先做几道检查 —— 没连上该管的网络、或者刚刚才连成功，
        就别再白跑一趟。用户手动点的（auto=False）一律放行，最多是快速失败。
        """
        if auto:
            quiet = time.time() - getattr(self, "_last_success_at", 0.0)
            if quiet < SUCCESS_QUIET_SEC:
                self.append_log(f"刚认证成功 {quiet:.0f} 秒，这次自动触发跳过（{reason}）")
                return
            if not self._wifi_preflight(reason):
                return
        # 每次真要干活之前，确认页面没被 Qt 冻结
        self._keep_page_active()
        self._ensure_browser(lambda: self.engine.start(reason, submit))

    # ==================== 无线网络触发 ====================
    def _wifi_preflight(self, reason: str) -> bool:
        """自动认证之前先看一眼无线网络状态。返回 True = 可以开始。

        有无线网卡但没连任何网络时，打开认证页必然失败；
        这时如果开了「断线时自动连接校园网」，就去把它连回来，
        然后等 WiFi 触发那条路接管。
        """
        if not getattr(self, "_has_wifi", False):
            return True                     # 没有无线网卡（比如插网线的台式机）
        try:
            ssid = wifi.current_ssid()
        except Exception:
            return True
        if ssid:
            if not self._accept_ssid(ssid):
                self.append_log(f"当前网络「{ssid}」不在授权名单里，跳过这次自动认证")
                return False
            return True
        # —— 没连任何无线网络 ——
        self.append_log(f"当前没有连接无线网络，先不认证（触发来源：{reason}）")
        if self._wifi_autoconnect_on():
            self._try_wifi_connect()
        else:
            self.set_status("未连接无线网络")
        return False

    def _try_wifi_connect(self):
        """掉线时，用 Windows 里保存的配置把校园网连回来。"""
        if not getattr(self, "_has_wifi", False) or not self._wifi_autoconnect_on():
            return
        try:
            if wifi.current_ssid():
                return                      # 已经连上了，不用管
        except Exception:
            return
        targets = self._wifi_targets()
        if not targets:
            self.append_log("还不认识校园网，没法自动连接 —— 先在 Windows 里手动连一次")
            return
        want = self._manual_ssid() or sorted(targets)[0]
        now = time.time()
        if now - getattr(self, "_last_wifi_connect_at", 0.0) < 30:
            return                          # 30 秒内别反复试
        self._last_wifi_connect_at = now
        ok, msg = wifi.connect(want)
        if ok:
            self.append_log(f"检测到无线网络断开，正在自动连回「{want}」…")
            self.set_status(f"正在连接 {want}…")
        else:
            self.append_log(f"自动连接「{want}」没成功：{msg}")

    def _check_wifi_hardware(self):
        try:
            self._has_wifi = bool(wifi.available() and wifi.interfaces())
        except Exception:
            self._has_wifi = False
        if not self._has_wifi:
            self.s.wifi_trigger_enabled = False
            self.cb_wifi.setChecked(False)
            self.cb_wifi.setEnabled(False)
            self.cb_wifi_auto.setEnabled(False)
            self.cb_wifi_connect.setEnabled(False)
            self.btn_clear_known.setEnabled(False)
            self.ed_ssid.setEnabled(False)
            self.btn_ssid_now.setEnabled(False)
            self.sp_wifi_interval.setEnabled(False)
            self.sp_wifi_wait.setEnabled(False)
            if hasattr(self, "lbl_wifi"):
                self.lbl_wifi.setText("这台电脑没有无线网卡")
        else:
            try:
                self._update_wifi_label(wifi.current_ssid())
            except Exception:
                pass

    def _apply_wifi_watch(self):
        if not hasattr(self, "wifi_timer"):
            return
        if getattr(self, "_has_wifi", False) and self.s.wifi_trigger_enabled \
                and self._watchdog_on:
            self.wifi_timer.start(max(1, int(self.s.wifi_check_interval)) * 1000)
        else:
            self.wifi_timer.stop()

    def _update_wifi_label(self, ssid: str):
        if not hasattr(self, "lbl_wifi"):
            return
        if not ssid:
            self.lbl_wifi.setText("未连接无线网络")
            return
        q = -1
        try:
            q = wifi.signal_quality()
        except Exception:
            pass
        self.lbl_wifi.setText(ssid + (f" · 信号 {q}%" if q >= 0 else ""))

    def _use_current_ssid(self):
        try:
            ssid = wifi.current_ssid()
        except Exception:
            ssid = ""
        if not ssid:
            QMessageBox.information(self, "提示", "当前没有连接无线网络")
            return
        self.ed_ssid.setText(ssid)
        self.s.wifi_ssid = ssid
        self._flush()
        self.append_log(f"已把「{ssid}」设为触发用的无线网络")

    # ---------- 自动识别校园网 ----------
    def _auto_detect_on(self) -> bool:
        """自动识别开关 —— 以界面为准。

        配置对象要等自动保存（600ms 防抖）才会更新，直接读 s 会慢半拍，
        出现"刚取消勾选，程序又记了一个名字"这种别扭事。
        """
        if hasattr(self, "cb_wifi_auto"):
            return bool(self.cb_wifi_auto.isChecked())
        return bool(getattr(self.s, "wifi_auto_detect", True))

    def _manual_ssid(self) -> str:
        """手填的无线网络名 —— 同样以界面为准。"""
        if hasattr(self, "ed_ssid"):
            return (self.ed_ssid.text() or "").strip()
        return (self.s.wifi_ssid or "").strip()

    def _wifi_autoconnect_on(self) -> bool:
        """「断线时自动连接校园网」开关 —— 以界面为准（配置要等防抖落盘）。"""
        if hasattr(self, "cb_wifi_connect"):
            return bool(self.cb_wifi_connect.isChecked())
        return bool(getattr(self.s, "wifi_auto_connect", False))

    def _wifi_targets(self) -> set:
        """当前"该管"的无线网络集合（小写）。

        来源有两处：手填的无线网络名 + 自动识别记下来的那些。
        两边都为空时返回空集合，含义是"任何无线网络都试一下"。
        """
        t = set()
        manual = self._manual_ssid().lower()
        if manual:
            t.add(manual)
        if self._auto_detect_on():
            for x in (self.s.wifi_known_ssids or []):
                x = str(x).strip().lower()
                if x:
                    t.add(x)
        return t

    def _accept_ssid(self, ssid: str) -> bool:
        """这个无线网络要不要管？"""
        t = self._wifi_targets()
        if not t:
            return True      # 还没认出任何校园网 → 先都试试，靠"能不能上网"判断
        return ssid.strip().lower() in t

    def _learn_ssid(self, ssid: str, why: str = "") -> None:
        """记住这个无线网络需要认证，以后连上就自动处理。"""
        ssid = (ssid or "").strip()
        if not ssid or not self._auto_detect_on():
            return
        known = [str(x).strip() for x in (self.s.wifi_known_ssids or [])]
        if any(x.lower() == ssid.lower() for x in known):
            return
        known.append(ssid)
        self.s.wifi_known_ssids = known
        self._refresh_known_ssids()
        self._dirty()
        suffix = f"（{why}）" if why else ""
        self.append_log(f"已识别出校园网「{ssid}」{suffix}，以后连上它就自动认证")

    def _forget_ssid(self, ssid: str) -> None:
        known = [str(x).strip() for x in (self.s.wifi_known_ssids or [])]
        left = [x for x in known if x.lower() != (ssid or "").strip().lower()]
        if len(left) != len(known):
            self.s.wifi_known_ssids = left
            self._refresh_known_ssids()
            self._dirty()

    def _clear_known_ssids(self):
        if not (self.s.wifi_known_ssids or []):
            self.set_status("还没有识别到任何校园网")
            return
        self.s.wifi_known_ssids = []
        self._refresh_known_ssids()
        self._flush()
        self.append_log("已清空识别记录，下次连上校园网会重新识别")

    def _refresh_known_ssids(self):
        if not hasattr(self, "lbl_known"):
            return
        known = [str(x).strip() for x in (self.s.wifi_known_ssids or []) if str(x).strip()]
        if not self._auto_detect_on():
            self.lbl_known.setText("自动识别已关闭")
        elif known:
            self.lbl_known.setText("、".join(known))
        else:
            manual = self._manual_ssid()
            self.lbl_known.setText(
                f"尚未识别（暂按手填的「{manual}」判断）" if manual
                else "尚未识别到，连上一次就会记住")

    def _wifi_tick(self):
        """每几秒看一眼无线网络。

        管哪些网络？手填的「无线网络名」+ 自动识别记下来的那些；
        两边都没配置时，任何无线网络都试（靠"能不能上网"来判定）。

        两种情况都会触发认证：
          1. 刚连上该管的网络（响应最快）
          2. 一直连着的网络其实上不了网（手动断开重连太快时，光看 SSID 变化会漏掉）
        """
        if not getattr(self, "_has_wifi", False):
            return
        try:
            ssid = wifi.current_ssid()
        except Exception:
            return
        self._update_wifi_label(ssid)

        if not self.s.wifi_trigger_enabled or self.engine.busy:
            return
        if not ssid:
            self._last_ssid = ""
            # 掉线了：如果开了「断线时自动连接校园网」，就把它连回来。
            # 连上之后会走上面「刚连上」那条路，自动认证。
            if self._wifi_autoconnect_on():
                self._try_wifi_connect()
            return
        if not self._accept_ssid(ssid):
            self._last_ssid = ssid
            return

        # 情况 1：刚连上（或从别的网络切过来）
        if ssid != self._last_ssid:
            self._last_ssid = ssid
            self._queue_wifi_trigger(ssid, f"检测到已连接无线网络「{ssid}」")
            return

        # 情况 2：网络名没变，但可能一直没网 —— 定期探一下
        now = time.time()
        if now - self._last_wifi_probe < max(5, int(self.s.wifi_net_check_interval)):
            return
        if self._wifi_probe_worker is not None and self._wifi_probe_worker.isRunning():
            return
        self._last_wifi_probe = now
        probes = self.engine._probes()
        timeout = min(3, max(1, int(self.s.probe_timeout)))
        self._wifi_probe_worker = ProbeWorker(probes, timeout, self)
        self._wifi_probe_worker.result.connect(
            lambda ok, d, name=ssid: self._on_wifi_probe(ok, d, name))
        self._wifi_probe_worker.start()

    @staticmethod
    def _looks_like_portal(detail: str) -> bool:
        """网络不通的原因，像不像"被认证页劫持"（而不是单纯断网）。

        校园网的典型表现是 302 跳转、或 200 但内容不对；
        单纯断网一般是超时 / 域名解析失败 / 连接被拒。
        只有像认证页劫持才值得记下这个网络名。
        """
        t = (detail or "").lower()
        if any(k in t for k in ("超时", "timeout", "解析", "dns", "拒绝",
                                "refused", "unreachable", "没有到主机的路由")):
            return False
        return ("302" in t) or ("301" in t) or ("劫持" in detail) or ("未匹配" in detail)

    def _on_wifi_probe(self, online: bool, detail: str, ssid: str):
        if online:
            return
        # 连上了却上不了网，而且像是被劫持到认证页 —— 这就是校园网，把名字记下来
        if self._looks_like_portal(detail):
            self._learn_ssid(ssid, "连上了但被拦到认证页")
        if self.engine.busy or not self.s.wifi_trigger_enabled:
            return
        cooldown = 30
        if time.time() - self._last_trigger_time < cooldown:
            return
        self._queue_wifi_trigger(ssid, f"无线网络「{ssid}」连上了但上不了网（{detail[:50]}）")

    def _queue_wifi_trigger(self, ssid: str, reason: str):
        if not self.s.url:
            self.append_log(f"{reason}；不过还没配置认证页地址，先跳过")
            return
        self._last_trigger_time = time.time()
        wait = max(0, int(self.s.wifi_wait))
        self.append_log(f"{reason}，{wait} 秒后自动认证")
        self.set_status(f"准备认证（{ssid}）…")
        QTimer.singleShot(wait * 1000, lambda: self._wifi_trigger(ssid))

    def _wifi_trigger(self, ssid: str):
        if not self.s.wifi_trigger_enabled:
            self.append_log("网络触发已关闭，跳过")
            return
        if self.engine.busy:
            self.append_log("上一次连接还没结束，这次触发跳过")
            return
        if not self.s.url:
            self.append_log("还没配置认证页地址，跳过自动认证")
            return
        self.append_log(f"开始自动认证（触发来源：{ssid}）")
        self._trigger_ssid = ssid          # 成功后拿它去记名
        self._start_engine(f"WiFi 触发（{ssid}）", auto=True)

    # ==================== 后台守护 ====================
    def toggle_watchdog(self):
        self._set_watchdog(not self._watchdog_on)

    def _set_watchdog(self, on: bool):
        if on:
            self.watchdog.setInterval(max(10, self.s.reconnect_interval) * 1000)
            self.watchdog.start()
            self._watchdog_on = True
            self.btn_watchdog.setText("停止后台")
            self.append_log(f"后台守护已启动，每 {self.s.reconnect_interval} 秒检查一次网络")
            self._apply_wifi_watch()
        else:
            self.watchdog.stop()
            self.wifi_timer.stop()
            self._watchdog_on = False
            self.btn_watchdog.setText("启动后台")
            self.engine.stop()
            self.append_log("后台守护已停止")

    def _watchdog_tick(self):
        if self.engine.busy or not self._watchdog_on:
            return
        self._worker = ProbeWorker(self.s.probe_url, self.s.probe_keyword,
                                   self.s.probe_timeout, self)
        self._worker.result.connect(self._on_watchdog_probe)
        self._worker.start()

    def _on_watchdog_probe(self, online, detail):
        if online:
            return
        self.append_log(f"后台检测到网络不通（{detail}），尝试自动重连")
        self._start_engine("后台自动重连", auto=True)

    # ==================== 日志 ====================
    def append_log(self, level_or_line, line=None):
        if line is None:
            level, text = "INFO", str(level_or_line)
        else:
            level, text = str(level_or_line), str(line)
        colors = getattr(self, "log_colors", {})
        color = colors.get(level, colors.get("INFO", "#6b7280"))
        # 落盘（以前只进界面不写文件，出问题没法查）
        try:
            self.log.to_file(level, text)
        except Exception:
            pass
        if not hasattr(self, "log_view"):
            return
        self.log_view.append(f'<span style="color:{color}">[{level}] {html.escape(text)}</span>')
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", os.path.join(logs_dir(), "log.txt"), "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_view.toPlainText())
            self.append_log(f"日志已导出：{path}")
        except Exception as e:
            self.append_log(f"导出日志失败：{e}")

    def set_status(self, text):
        if hasattr(self, "lbl_status"):
            self.lbl_status.setText(text)
            self.sb_status.setText(text)
        p = self._palette or {}
        if hasattr(self, "dot"):
            if "成功" in text or "已联网" in text:
                self.dot.set_color("success")
            elif "失败" in text or "未" in text or "错误" in text:
                self.dot.set_color("danger")
            else:
                self.dot.set_color("accent")

    # ==================== 生命周期 ====================
    def closeEvent(self, event):
        if self.s.close_to_tray and not self._closing and getattr(self, "tray", None):
            event.ignore()
            self.hide()
            self.tray.showMessage(APP_TITLE, "已最小化到托盘，后台继续守护",
                                  QSystemTrayIcon.Information, 2000)
            return
        self.exit_app()
        event.accept()

    def exit_app(self):
        self._closing = True
        self._flush()
        self.watchdog.stop()
        self.engine.stop()
        if getattr(self, "tray", None):
            self.tray.hide()
        QApplication.quit()
