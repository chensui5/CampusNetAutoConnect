# -*- coding: utf-8 -*-
"""Windows DPAPI 封装。

用当前 Windows 账户的凭据加密敏感数据：密文只有同一账户在同一台机器上才能解开。
纯 ctypes 实现，不依赖 pywin32。
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

CRYPTPROTECT_UI_FORBIDDEN = 0x01

_ENTROPY = b"CampusNetAutoConnect::v1"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.WinDLL("crypt32.dll", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]


def _make_blob(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf


def _read_blob(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _kernel32.LocalFree(blob.pbData)


def protect(data: bytes) -> bytes:
    if not data:
        return b""
    in_blob, _keep = _make_blob(data)
    ent_blob, _keep2 = _make_blob(_ENTROPY)
    out_blob = DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(in_blob), "CampusNetAutoConnect", ctypes.byref(ent_blob),
        None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob))
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData 失败")
    return _read_blob(out_blob)


def unprotect(data: bytes) -> bytes:
    if not data:
        return b""
    in_blob, _keep = _make_blob(data)
    ent_blob, _keep2 = _make_blob(_ENTROPY)
    out_blob = DATA_BLOB()
    descr = wintypes.LPWSTR()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), ctypes.byref(descr), ctypes.byref(ent_blob),
        None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob))
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData 失败")
    if descr:
        try:
            _kernel32.LocalFree(descr)
        except Exception:
            pass
    return _read_blob(out_blob)


def protect_text(text: str) -> str:
    if not text:
        return ""
    try:
        return base64.b64encode(protect(text.encode("utf-8"))).decode("ascii")
    except Exception:
        return ""


def unprotect_text(token: str) -> str:
    if not token:
        return ""
    try:
        return unprotect(base64.b64decode(token.encode("ascii"))).decode("utf-8")
    except Exception:
        return ""
