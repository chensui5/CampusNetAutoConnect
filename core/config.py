# -*- coding: utf-8 -*-
"""配置与本地存储。

配置文件放在 %APPDATA%\\CampusNetAutoConnect\\config.json，
密码经 Windows DPAPI 加密后再落盘。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from typing import Any

from . import crypto
from .crypto import protect_text, unprotect_text

APP_NAME = "CampusNetAutoConnect"
APP_TITLE = "校园网自动连接"
APP_VERSION = "1.8.0"
AUTHOR = "尘遂"


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def backgrounds_dir() -> str:
    return os.path.join(app_data_dir(), "backgrounds")


def logs_dir() -> str:
    return os.path.join(app_data_dir(), "logs")


CONFIG_PATH = os.path.join(app_data_dir(), "config.json")


@dataclass
class Settings:
    # —— 账号 ——
    url: str = ""                 # 校园网认证页地址
    username: str = ""
    password_enc: str = ""        # 加密后的密码

    # —— 启动行为 ——
    auto_start: bool = False            # 开机自启动
    auto_connect_on_launch: bool = True # 启动后自动尝试连接
    start_delay: int = 8                # 启动后延迟 N 秒再连（等网卡就绪）
    launch_minimized: bool = True       # 自启动场景最小化到托盘

    # —— 重连 ——
    reconnect_enabled: bool = True   # 后台守护：掉线自动重连
    reconnect_interval: int = 60     # 每 N 秒检查一次网络
    retry_times: int = 2             # 单次连接失败重试次数
    retry_delay: int = 3             # 重试间隔（秒）

    # —— 无线网络触发（连上指定 WiFi 后自动认证）——
    wifi_trigger_enabled: bool = True   # 连上指定无线网络后自动认证
    wifi_ssid: str = ""                 # 目标 WiFi 名（留空=任意无线网络）
    wifi_check_interval: int = 4        # 检查间隔（秒）
    wifi_net_check_interval: int = 15   # 网络是否可用的复查间隔（秒）
    wifi_wait: int = 3                  # 连上后等多久再认证（等 DHCP）

    # —— 网络探测（支持多行，任意一个通就算在线）——
    probe_url: str = (
        "http://www.msftconnecttest.com/connecttest.txt\n"
        "http://connect.rom.miui.com/generate_204\n"
        "http://www.gstatic.com/generate_204\n"
        "http://captive.apple.com/hotspot-detect.html|Success"
    )
    probe_keyword: str = "Microsoft Connect Test"
    skip_if_online: bool = True      # 已联网就跳过连接流程
    probe_timeout: int = 5

    # —— 页面交互 ——
    browser_compat_mode: bool = True  # 关闭 Chromium 沙箱，兼容受限环境
    auto_submit: bool = True         # 填完自动点登录
    page_load_timeout: int = 25      # 页面加载超时（秒）
    post_submit_wait: int = 4        # 提交后等待 N 秒再复查网络
    sel_username: str = ""           # 自定义用户名选择器（兜底）
    sel_password: str = ""
    sel_submit: str = ""
    domain: str = ""                 # 运营商 / 产品（如 联通、@telecom），留空按页面默认
    remember_checkbox: bool = True   # 勾选"记住我/同意"类复选框
    close_page_after_success: bool = False  # 成功后关闭内嵌页面

    # —— 外观 ——
    theme: str = "dark"              # dark / light / system
    bg_enabled: bool = False         # 启用自定义背景
    bg_file: str = ""                # 背景图路径
    bg_dim: int = 35                 # 暗化遮罩 0-80
    bg_blur: int = 0                 # 背景模糊 px
    bg_fit: str = "cover"            # cover / contain / auto

    # —— 托盘 ——
    minimize_to_tray: bool = True
    close_to_tray: bool = True

    # —— 其它 ——
    last_status: str = "未知"
    last_connect_time: str = ""
    first_run: bool = True

    def set_password(self, plain: str) -> None:
        self.password_enc = protect_text(plain)

    def get_password(self) -> str:
        return unprotect_text(self.password_enc)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        valid = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in (data or {}).items() if k in valid}
        return cls(**clean)


class ConfigManager:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.settings = Settings()
        self.load()

    def load(self) -> Settings:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    self.settings = Settings.from_dict(json.load(f))
                self._migrate()
        except Exception:
            self.settings = Settings()
        return self.settings

    def _migrate(self) -> None:
        """把老配置升级到新默认值（不覆盖用户自己改过的内容）。"""
        s = self.settings
        legacy_probe = "http://www.msftconnecttest.com/connecttest.txt"
        if (s.probe_url or "").strip() == legacy_probe:
            # 单一探测点在校园网里太容易误判，升级成多探测点
            s.probe_url = Settings().probe_url

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.settings.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self.settings, key, default)

    def update(self, **kv) -> None:
        for k, v in kv.items():
            if hasattr(self.settings, k):
                setattr(self.settings, k, v)
