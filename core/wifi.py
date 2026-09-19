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
