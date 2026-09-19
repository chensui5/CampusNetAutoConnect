# -*- coding: utf-8 -*-
"""开机自启动：写/删 Windows 注册表 Run 项。"""

from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "CampusNetAutoConnect"


def _launch_command() -> str:
    """生成自启动命令行。"""
    if getattr(sys, "frozen", False):
        # 打包后的 exe
        return f'"{sys.executable}" --auto'
    # 开发环境：用 pythonw 无窗启动
    script = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
    )
    py = sys.executable
    pyw = py.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = py
    return f'"{pyw}" "{script}" --auto'


def _recorded_command() -> str:
    """读注册表里当前记着的启动命令；没有就返回空。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return str(value or "")
    except Exception:
        return ""


def _exe_of(cmd: str) -> str:
    """从命令行里取出可执行文件路径（小写，方便比较）。"""
    cmd = (cmd or "").strip()
    if not cmd:
        return ""
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        return (cmd[1:end] if end > 0 else cmd[1:]).lower()
    return cmd.split(" ")[0].lower()


def is_enabled() -> bool:
    """注册表里有这项，**而且指的就是现在这份程序**。

    程序被移动或改名之后，旧的启动项会指向一个不存在的路径——
    这时候不能算"已开启"，否则用户以为开着、其实开机根本没反应。
    """
    recorded = _recorded_command()
    if not recorded:
        return False
    return _exe_of(recorded) == _exe_of(_launch_command())


def repair_if_stale() -> tuple[bool, str]:
    """如果开着自启但指向别处（被移动/改名过），改回当前位置。"""
    recorded = _recorded_command()
    if not recorded:
        return False, ""
    if _exe_of(recorded) == _exe_of(_launch_command()):
        return False, ""
    ok, msg = enable()
    return ok, ("开机自启动项已更新为当前位置" if ok else f"更新自启动项失败：{msg}")


def enable() -> tuple[bool, str]:
    try:
        import winreg
        cmd = _launch_command()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        return True, cmd
    except Exception as e:
        return False, str(e)


def disable() -> tuple[bool, str]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, APP_NAME)
        return True, ""
    except FileNotFoundError:
        return True, ""
    except Exception as e:
        return False, str(e)


def set_enabled(on: bool) -> tuple[bool, str]:
    return enable() if on else disable()
