# -*- coding: utf-8 -*-
"""读取 Windows 当前连接的无线网络（SSID）。

直接调 wlanapi.dll，不依赖 netsh，也没有中文编码问题。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

try:
    _wlanapi = ctypes.WinDLL("wlanapi.dll", use_last_error=True)
except OSError:                                     # 极少数精简系统没有这个库
    _wlanapi = None

WLAN_INTERFACE_STATE_CONNECTED = 1
WLAN_INTF_OPCODE_CURRENT_CONNECTION = 7
WLAN_CLIENT_VERSION = 2

# —— 连接用到的常量 ——
WLAN_CONNECTION_MODE_PROFILE = 0        # 按已保存的配置文件连
DOT11_BSS_TYPE_ANY = 3                  # 不限定基础设施/自组网


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    def __str__(self) -> str:
        d4 = "".join(f"{b:02x}" for b in self.Data4)
        return (f"{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-"
                f"{d4[:4]}-{d4[4:]}")


class DOT11_SSID(ctypes.Structure):
    _fields_ = [("uSSIDLength", ctypes.c_ulong),
                ("ucSSID", ctypes.c_ubyte * 32)]

    def text(self) -> str:
        try:
            n = min(int(self.uSSIDLength), 32)
            return bytes(self.ucSSID[:n]).decode("utf-8", "ignore")
        except Exception:
            return ""


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [("InterfaceGuid", GUID),
                ("strInterfaceDescription", ctypes.c_wchar * 256),
                ("isState", ctypes.c_uint)]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", ctypes.c_ulong),
                ("dwIndex", ctypes.c_ulong),
                ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]


DOT11_MAC_ADDRESS = ctypes.c_ubyte * 6


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("dot11Ssid", DOT11_SSID),
                ("dot11BssType", ctypes.c_uint),
                ("dot11Bssid", DOT11_MAC_ADDRESS),
                ("dot11PhyType", ctypes.c_uint),
                ("uDot11PhyIndex", ctypes.c_ulong),
                ("wlanSignalQuality", ctypes.c_ulong),
                ("ulRxRate", ctypes.c_ulong),
                ("ulTxRate", ctypes.c_ulong)]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("bSecurityEnabled", wintypes.BOOL),
                ("bOneXEnabled", wintypes.BOOL),
                ("dot11AuthAlgorithm", ctypes.c_uint),
                ("dot11CipherAlgorithm", ctypes.c_uint)]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("isState", ctypes.c_uint),
                ("wlanConnectionMode", ctypes.c_uint),
                ("strProfileName", ctypes.c_wchar * 256),
                ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
                ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES)]


class WLAN_PROFILE_INFO(ctypes.Structure):
    _fields_ = [("strProfileName", ctypes.c_wchar * 256),
                ("dwFlags", ctypes.c_ulong)]


class WLAN_PROFILE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", ctypes.c_ulong),
                ("dwIndex", ctypes.c_ulong),
                ("ProfileInfo", WLAN_PROFILE_INFO * 1)]


class WLAN_CONNECTION_PARAMETERS(ctypes.Structure):
    _fields_ = [("wlanConnectionMode", ctypes.c_uint),
                ("strProfile", ctypes.c_wchar_p),
                ("pDot11Ssid", ctypes.POINTER(DOT11_SSID)),
                ("pDesiredBssidList", ctypes.c_void_p),
                ("dot11BssType", ctypes.c_uint),
                ("dwFlags", wintypes.DWORD)]


if _wlanapi is not None:
    _wlanapi.WlanOpenHandle.argtypes = [
        wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.HANDLE)]
    _wlanapi.WlanOpenHandle.restype = wintypes.DWORD
    _wlanapi.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _wlanapi.WlanCloseHandle.restype = wintypes.DWORD
    _wlanapi.WlanEnumInterfaces.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST))]
    _wlanapi.WlanEnumInterfaces.restype = wintypes.DWORD
    _wlanapi.WlanQueryInterface.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.c_uint, ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint)]
    _wlanapi.WlanQueryInterface.restype = wintypes.DWORD
    _wlanapi.WlanFreeMemory.argtypes = [ctypes.c_void_p]
    _wlanapi.WlanFreeMemory.restype = None
    _wlanapi.WlanGetProfileList.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(WLAN_PROFILE_INFO_LIST))]
    _wlanapi.WlanGetProfileList.restype = wintypes.DWORD
    _wlanapi.WlanConnect.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(GUID),
        ctypes.POINTER(WLAN_CONNECTION_PARAMETERS), ctypes.c_void_p]
    _wlanapi.WlanConnect.restype = wintypes.DWORD


def available() -> bool:
    """系统是否提供无线接口能力。"""
    return _wlanapi is not None


def interfaces() -> list[dict]:
    """列出无线网卡及状态。"""
    if _wlanapi is None:
        return []
    out: list[dict] = []
    handle = wintypes.HANDLE()
    ver = wintypes.DWORD()
    if _wlanapi.WlanOpenHandle(WLAN_CLIENT_VERSION, None,
                               ctypes.byref(ver), ctypes.byref(handle)) != 0:
        return []
    try:
        plist = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        if _wlanapi.WlanEnumInterfaces(handle, None, ctypes.byref(plist)) != 0:
            return []
        try:
            n = int(plist.contents.dwNumberOfItems)
            base = ctypes.addressof(plist.contents.InterfaceInfo)
            step = ctypes.sizeof(WLAN_INTERFACE_INFO)
            for i in range(n):
                info = WLAN_INTERFACE_INFO.from_address(base + i * step)
                out.append({"guid": str(info.InterfaceGuid),
                            "desc": info.strInterfaceDescription,
                            "state": int(info.isState)})
        finally:
            _wlanapi.WlanFreeMemory(ctypes.cast(plist, ctypes.c_void_p))
    finally:
        _wlanapi.WlanCloseHandle(handle, None)
    return out


def current_ssid() -> str:
    """当前连接的无线网络名；没连无线就返回空字符串。"""
    if _wlanapi is None:
        return ""
    handle = wintypes.HANDLE()
    ver = wintypes.DWORD()
    if _wlanapi.WlanOpenHandle(WLAN_CLIENT_VERSION, None,
                               ctypes.byref(ver), ctypes.byref(handle)) != 0:
        return ""
    try:
        plist = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        if _wlanapi.WlanEnumInterfaces(handle, None, ctypes.byref(plist)) != 0:
            return ""
        try:
            n = int(plist.contents.dwNumberOfItems)
            base = ctypes.addressof(plist.contents.InterfaceInfo)
            step = ctypes.sizeof(WLAN_INTERFACE_INFO)
            for i in range(n):
                info = WLAN_INTERFACE_INFO.from_address(base + i * step)
                if int(info.isState) != WLAN_INTERFACE_STATE_CONNECTED:
                    continue
                data = ctypes.c_void_p()
                size = wintypes.DWORD()
                opcode_type = ctypes.c_uint()
                rc = _wlanapi.WlanQueryInterface(
                    handle, ctypes.byref(info.InterfaceGuid),
                    WLAN_INTF_OPCODE_CURRENT_CONNECTION, None,
                    ctypes.byref(size), ctypes.byref(data), ctypes.byref(opcode_type))
                if rc != 0 or not data:
                    continue
                try:
                    conn = ctypes.cast(
                        data, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)).contents
                    ssid = conn.wlanAssociationAttributes.dot11Ssid.text()
                    if ssid:
                        return ssid
                finally:
                    _wlanapi.WlanFreeMemory(data)
        finally:
            _wlanapi.WlanFreeMemory(ctypes.cast(plist, ctypes.c_void_p))
    finally:
        _wlanapi.WlanCloseHandle(handle, None)
    return ""


def _open() -> wintypes.HANDLE | None:
    """打开一个 WLAN 句柄；失败返回 None。"""
    if _wlanapi is None:
        return None
    handle = wintypes.HANDLE()
    ver = wintypes.DWORD()
    if _wlanapi.WlanOpenHandle(WLAN_CLIENT_VERSION, None,
                               ctypes.byref(ver), ctypes.byref(handle)) != 0:
        return None
    return handle


def _first_interface(handle):
    """(接口信息, 接口列表指针)；调用方负责 WlanFreeMemory 释放列表。"""
    plist = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
    if _wlanapi.WlanEnumInterfaces(handle, None, ctypes.byref(plist)) != 0:
        return None, None
    if int(plist.contents.dwNumberOfItems) <= 0:
        _wlanapi.WlanFreeMemory(ctypes.cast(plist, ctypes.c_void_p))
        return None, None
    info = WLAN_INTERFACE_INFO.from_address(
        ctypes.addressof(plist.contents.InterfaceInfo))
    return info, plist


def profiles() -> list[str]:
    """这台电脑保存过的无线网络名（即"连过、记住密码"的那些）。"""
    handle = _open()
    if handle is None:
        return []
    try:
        info, plist = _first_interface(handle)
        if info is None:
            return []
        try:
            out = ctypes.POINTER(WLAN_PROFILE_INFO_LIST)()
            rc = _wlanapi.WlanGetProfileList(
                handle, ctypes.byref(info.InterfaceGuid), None, ctypes.byref(out))
            if rc != 0 or not out:
                return []
            try:
                n = int(out.contents.dwNumberOfItems)
                base = ctypes.addressof(out.contents.ProfileInfo)
                step = ctypes.sizeof(WLAN_PROFILE_INFO)
                return [WLAN_PROFILE_INFO.from_address(base + i * step).strProfileName
                        for i in range(n)]
            finally:
                _wlanapi.WlanFreeMemory(ctypes.cast(out, ctypes.c_void_p))
        finally:
            _wlanapi.WlanFreeMemory(ctypes.cast(plist, ctypes.c_void_p))
    except Exception:
        return []
    finally:
        _wlanapi.WlanCloseHandle(handle, None)


def connect(ssid: str) -> tuple[bool, str]:
    """发起连接到已保存的无线网络。

    只负责"发起"（毫秒级返回），连上没有由调用方靠 current_ssid() 复查 ——
    在界面线程里阻塞等 DHCP 会卡住整个窗口。

    用的就是 Windows 自己那份配置文件，所以这个网络必须在这台电脑上连过一次。
    """
    ssid = (ssid or "").strip()
    if not ssid:
        return False, "网络名为空"
    handle = _open()
    if handle is None:
        return False, "打不开无线服务（WLAN AutoConfig 可能没启动）"
    try:
        info, plist = _first_interface(handle)
        if info is None:
            return False, "没有找到无线网卡"
        try:
            saved = profiles()
            real = next((p for p in saved if p.strip().lower() == ssid.lower()), None)
            if real is None:
                return False, (f"这台电脑没保存过「{ssid}」的连接信息，"
                               f"先在 Windows 里手动连一次并勾上自动连接")

            raw = ssid.encode("utf-8")[:32]
            dssid = DOT11_SSID()
            dssid.uSSIDLength = len(raw)
            for i, b in enumerate(raw):
                dssid.ucSSID[i] = b

            params = WLAN_CONNECTION_PARAMETERS()
            params.wlanConnectionMode = WLAN_CONNECTION_MODE_PROFILE
            params.strProfile = real
            params.pDot11Ssid = ctypes.pointer(dssid)
            params.pDesiredBssidList = None
            params.dot11BssType = DOT11_BSS_TYPE_ANY
            params.dwFlags = 0

            rc = _wlanapi.WlanConnect(
                handle, ctypes.byref(info.InterfaceGuid),
                ctypes.byref(params), None)
            if rc != 0:
                return False, f"发起连接失败（错误码 {rc}）"
            return True, f"已发起连接到「{real}」"
        finally:
            _wlanapi.WlanFreeMemory(ctypes.cast(plist, ctypes.c_void_p))
    except Exception as e:
        return False, f"连接出错：{e}"
    finally:
        _wlanapi.WlanCloseHandle(handle, None)


def signal_quality() -> int:
    """当前无线信号强度 0-100，未连接返回 -1。"""
    if _wlanapi is None:
        return -1
    handle = wintypes.HANDLE()
    ver = wintypes.DWORD()
    if _wlanapi.WlanOpenHandle(WLAN_CLIENT_VERSION, None,
                               ctypes.byref(ver), ctypes.byref(handle)) != 0:
        return -1
    try:
        plist = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        if _wlanapi.WlanEnumInterfaces(handle, None, ctypes.byref(plist)) != 0:
            return -1
        try:
            n = int(plist.contents.dwNumberOfItems)
            base = ctypes.addressof(plist.contents.InterfaceInfo)
            step = ctypes.sizeof(WLAN_INTERFACE_INFO)
            for i in range(n):
                info = WLAN_INTERFACE_INFO.from_address(base + i * step)
                if int(info.isState) != WLAN_INTERFACE_STATE_CONNECTED:
                    continue
                data = ctypes.c_void_p()
                size = wintypes.DWORD()
                opcode_type = ctypes.c_uint()
                rc = _wlanapi.WlanQueryInterface(
                    handle, ctypes.byref(info.InterfaceGuid),
                    WLAN_INTF_OPCODE_CURRENT_CONNECTION, None,
                    ctypes.byref(size), ctypes.byref(data), ctypes.byref(opcode_type))
                if rc != 0 or not data:
                    continue
                try:
                    conn = ctypes.cast(
                        data, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)).contents
                    return int(conn.wlanAssociationAttributes.wlanSignalQuality)
                finally:
                    _wlanapi.WlanFreeMemory(data)
        finally:
            _wlanapi.WlanFreeMemory(ctypes.cast(plist, ctypes.c_void_p))
    finally:
        _wlanapi.WlanCloseHandle(handle, None)
    return -1
