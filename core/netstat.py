# -*- coding: utf-8 -*-
"""枚举本机网络连接（谁在联网），以及系统级收发字节数。纯 ctypes，不加第三方依赖。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import socket

_ihl = ctypes.WinDLL("iphlpapi")
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

AF_INET, AF_INET6 = 2, 23
TCP_TABLE_OWNER_PID_ALL = 5
UDP_TABLE_OWNER_PID = 1
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_TCP_STATES = {
    1: "CLOSED", 2: "LISTEN", 3: "SYN_SENT", 4: "SYN_RCVD", 5: "ESTABLISHED",
    6: "FIN_WAIT1", 7: "FIN_WAIT2", 8: "CLOSE_WAIT", 9: "CLOSING",
    10: "LAST_ACK", 11: "TIME_WAIT", 12: "DELETE_TCB",
}


class _TcpRow(ctypes.Structure):
    _fields_ = [("state", w.DWORD), ("localAddr", w.DWORD), ("localPort", w.DWORD),
                ("remoteAddr", w.DWORD), ("remotePort", w.DWORD), ("pid", w.DWORD)]


class _Tcp6Row(ctypes.Structure):
    _fields_ = [("localAddr", ctypes.c_ubyte * 16), ("localScope", w.DWORD),
                ("localPort", w.DWORD), ("remoteAddr", ctypes.c_ubyte * 16),
                ("remoteScope", w.DWORD), ("remotePort", w.DWORD),
                ("state", w.DWORD), ("pid", w.DWORD)]


class _UdpRow(ctypes.Structure):
    _fields_ = [("localAddr", w.DWORD), ("localPort", w.DWORD), ("pid", w.DWORD)]


class _Udp6Row(ctypes.Structure):
    _fields_ = [("localAddr", ctypes.c_ubyte * 16), ("localScope", w.DWORD),
                ("localPort", w.DWORD), ("pid", w.DWORD)]


class _IfRow(ctypes.Structure):
    _fields_ = [
        ("wszName", w.WCHAR * 256), ("dwIndex", w.DWORD), ("dwType", w.DWORD),
        ("dwMtu", w.DWORD), ("dwSpeed", w.DWORD), ("dwPhysAddrLen", w.DWORD),
        ("bPhysAddr", ctypes.c_ubyte * 8), ("dwAdminStatus", w.DWORD),
        ("dwOperStatus", w.DWORD), ("dwLastChange", w.DWORD), ("dwInOctets", w.DWORD),
        ("dwInUcastPkts", w.DWORD), ("dwInNUcastPkts", w.DWORD), ("dwInDiscards", w.DWORD),
        ("dwInErrors", w.DWORD), ("dwInUnknownProtos", w.DWORD), ("dwOutOctets", w.DWORD),
        ("dwOutUcastPkts", w.DWORD), ("dwOutNUcastPkts", w.DWORD), ("dwOutDiscards", w.DWORD),
        ("dwOutErrors", w.DWORD), ("dwOutQLen", w.DWORD), ("dwDescrLen", w.DWORD),
        ("bDescr", ctypes.c_ubyte * 256),
    ]


def _port(raw: int) -> int:
    v = raw & 0xFFFF
    return ((v & 0xFF) << 8) | ((v >> 8) & 0xFF)


def _ip4(raw: int) -> str:
    return socket.inet_ntoa(ctypes.string_at(ctypes.byref(w.DWORD(raw)), 4))


def _ip6(buf) -> str:
    return socket.inet_ntop(socket.AF_INET6, bytes(buf))


def _tcp_rows(cls, af: int):
    size = w.DWORD(0)
    _ihl.GetExtendedTcpTable(None, ctypes.byref(size), False, af, TCP_TABLE_OWNER_PID_ALL, 0)
    if size.value == 0:
        return []
    buf = ctypes.create_string_buffer(size.value)
    if _ihl.GetExtendedTcpTable(buf, ctypes.byref(size), False, af, TCP_TABLE_OWNER_PID_ALL, 0) != 0:
        return []
    n = ctypes.cast(buf, ctypes.POINTER(w.DWORD)).contents.value
    base, sz = ctypes.addressof(buf) + 4, ctypes.sizeof(cls)
    return [cls.from_address(base + i * sz) for i in range(n)]


def _udp_rows(cls, af: int):
    size = w.DWORD(0)
    _ihl.GetExtendedUdpTable(None, ctypes.byref(size), False, af, UDP_TABLE_OWNER_PID, 0)
    if size.value == 0:
        return []
    buf = ctypes.create_string_buffer(size.value)
    if _ihl.GetExtendedUdpTable(buf, ctypes.byref(size), False, af, UDP_TABLE_OWNER_PID, 0) != 0:
        return []
    n = ctypes.cast(buf, ctypes.POINTER(w.DWORD)).contents.value
    base, sz = ctypes.addressof(buf) + 4, ctypes.sizeof(cls)
    return [cls.from_address(base + i * sz) for i in range(n)]


_names: dict[int, str] = {}


_SYSTEM_PIDS = {0: "System Idle", 4: "System"}


def process_name(pid: int) -> str:
    if pid in _names:
        return _names[pid]
    if pid in _SYSTEM_PIDS:
        _names[pid] = _SYSTEM_PIDS[pid]
        return _names[pid]
    name = ""
    h = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = w.DWORD(1024)
            if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value)
        finally:
            _k32.CloseHandle(h)
    if not name:
        name = f"PID {pid}"
    _names[pid] = name
    return name


def list_connections() -> list[dict]:
    """返回当前所有 TCP/UDP 连接。每条含 pid/进程/协议/本地/远端/状态。"""
    out: list[dict] = []
    for af, cls in ((AF_INET, _TcpRow), (AF_INET6, _Tcp6Row)):
        for r in _tcp_rows(cls, af):
            if af == AF_INET:
                local = f"{_ip4(r.localAddr)}:{_port(r.localPort)}"
                remote = (f"{_ip4(r.remoteAddr)}:{_port(r.remotePort)}"
                          if r.remoteAddr else "*:*")
            else:
                local = f"[{_ip6(r.localAddr)}]:{_port(r.localPort)}"
                remote = (f"[{_ip6(r.remoteAddr)}]:{_port(r.remotePort)}"
                          if any(r.remoteAddr) else "*:*")
            out.append({"pid": r.pid, "proto": "TCP",
                        "local": local, "remote": remote,
                        "state": _TCP_STATES.get(r.state, str(r.state)),
                        "proc": process_name(r.pid)})
    for af, cls in ((AF_INET, _UdpRow), (AF_INET6, _Udp6Row)):
        for r in _udp_rows(cls, af):
            local = (f"{_ip4(r.localAddr)}:{_port(r.localPort)}" if af == AF_INET
                     else f"[{_ip6(r.localAddr)}]:{_port(r.localPort)}")
            out.append({"pid": r.pid, "proto": "UDP",
                        "local": local, "remote": "*:*", "state": "",
                        "proc": process_name(r.pid)})
    return out


_EXCL_IF = ("wfp", "kaspersky", "qos packet", "native wifi filter", "virtual wifi filter",
            "tap-", "miniport", "wi-fi direct", "tunnel", "loopback", "kernel debug",
            "wintun", "teredo", "6to4", "ip-https", "sstp", "ikev2", "l2tp", "pptp",
            "pppoe", "virtual adapter")


def io_totals() -> tuple[int, int]:
    """系统级累计收发字节 (in, out)。只算物理网卡，且去掉分层/虚拟网卡的重复计数。

    同一块网卡会被 NDIS 滤镜层拆成多条接口，计数完全相同 —— 按数值去重。
    """
    size = w.DWORD(0)
    _ihl.GetIfTable(None, ctypes.byref(size), False)
    if size.value == 0:
        return 0, 0
    buf = ctypes.create_string_buffer(size.value)
    if _ihl.GetIfTable(buf, ctypes.byref(size), False) != 0:
        return 0, 0
    n = ctypes.cast(buf, ctypes.POINTER(w.DWORD)).contents.value
    base, sz = ctypes.addressof(buf) + 4, ctypes.sizeof(_IfRow)
    seen: set[tuple[int, int]] = set()
    tin = tout = 0
    for i in range(n):
        row = _IfRow.from_address(base + i * sz)
        if row.dwOperStatus != 5 or row.dwType not in (6, 71):
            continue
        desc = bytes(row.bDescr[:row.dwDescrLen]).decode("mbcs", "ignore").lower()
        if any(k in desc for k in _EXCL_IF):
            continue
        key = (row.dwInOctets, row.dwOutOctets)
        if key in seen:
            continue
        seen.add(key)
        tin += row.dwInOctets
        tout += row.dwOutOctets
    return tin, tout


if __name__ == "__main__":
    rows = list_connections()
    print(f"连接数：{len(rows)}")
    by_proc: dict[str, int] = {}
    for r in rows:
        by_proc[r["proc"]] = by_proc.get(r["proc"], 0) + 1
    for name, c in sorted(by_proc.items(), key=lambda x: -x[1])[:12]:
        print(f"  {c:3}  {name}")
    tin, tout = io_totals()
    print(f"累计接收 {tin/1048576:.1f} MB / 发送 {tout/1048576:.1f} MB")
