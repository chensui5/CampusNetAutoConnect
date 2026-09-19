# -*- coding: utf-8 -*-
"""联网状态探测。

思路：校园网未认证时会把 HTTP 请求劫持到认证页，
所以不能只看"能不能连上"，要看返回的正文是不是我们期望的内容。
默认探测 http://www.msftconnecttest.com/connecttest.txt，
未劫持时正文固定为 "Microsoft Connect Test"。
"""

from __future__ import annotations

import socket
import ssl
from urllib.parse import urlparse

DEFAULT_URL = "http://www.msftconnecttest.com/connecttest.txt"
DEFAULT_KEYWORD = "Microsoft Connect Test"


def _recv_all(sock: socket.socket, limit: int = 65536) -> bytes:
    chunks = []
    total = 0
    sock.settimeout(3)
    while total < limit:
        try:
            data = sock.recv(4096)
        except socket.timeout:
            break
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
        total += len(data)
    return b"".join(chunks)


def http_probe(url: str, keyword: str = "", timeout: float = 5.0) -> tuple[bool, str]:
    """用裸 socket 发一次 GET，规避系统代理污染结果。

    返回 (是否联网, 详情文本)。
    """
    try:
        p = urlparse(url)
        scheme = p.scheme or "http"
        host = p.hostname
        if not host:
            return False, "探测地址无效"
        port = p.port or (443 if scheme == "https" else 80)
        path = p.path or "/"
        if p.query:
            path += "?" + p.query

        addr = socket.gethostbyname(host)
        sock = socket.create_connection((addr, port), timeout=timeout)
        if scheme == "https":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=host)

        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) CampusNetAutoConnect/1.0\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n\r\n"
        )
        sock.sendall(req.encode("ascii", "ignore"))
        raw = _recv_all(sock)
        try:
            sock.close()
        except Exception:
            pass

        text = raw.decode("utf-8", "ignore")
        if not text:
            return False, "探测无响应"

        head, _, body = text.partition("\r\n\r\n")
        status_line = head.split("\r\n")[0] if head else ""
        status_code = 0
        parts = status_line.split()
        if len(parts) >= 2:
            try:
                status_code = int(parts[1])
            except ValueError:
                status_code = 0

        # 204 也算通过（generate_204 类探测点）
        if keyword and keyword.lower() in body.lower():
            return True, f"HTTP {status_code} · 内容匹配成功"
        if status_code == 204:
            return True, f"HTTP 204 · 网络可达"
        if status_code == 0:
            return False, f"响应异常：{status_line[:60]}"
        return False, f"HTTP {status_code} · 未匹配期望内容（可能被劫持到认证页）"
    except socket.gaierror:
        return False, "DNS 解析失败"
    except socket.timeout:
        return False, "连接超时"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def check_online(url: str = DEFAULT_URL, keyword: str = DEFAULT_KEYWORD,
                 timeout: float = 5.0) -> tuple[bool, str]:
    return http_probe(url, keyword, timeout)


DEFAULT_PROBES = (
    "http://www.msftconnecttest.com/connecttest.txt\n"
    "http://connect.rom.miui.com/generate_204\n"
    "http://www.gstatic.com/generate_204\n"
    "http://captive.apple.com/hotspot-detect.html|Success"
)


def parse_probes(probe_url: str, default_keyword: str = "") -> list[tuple[str, str]]:
    """把配置里的探测地址解析成 [(url, 期望内容), ...]。

    支持多行，每行一个地址；想单独指定期望内容就写 `地址|期望内容`。
    """
    probes: list[tuple[str, str]] = []
    for raw in (probe_url or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            u, k = line.split("|", 1)
            probes.append((u.strip(), k.strip()))
        else:
            probes.append((line, default_keyword))
    if not probes:
        probes = [(DEFAULT_URL, DEFAULT_KEYWORD)]
    return probes


def check_online_multi(probes: list[tuple[str, str]], timeout: float = 5.0) -> tuple[bool, str]:
    """依次探测多个地址，任意一个通过就算在线（校园网里单一探测点常常不通）。"""
    details = []
    for url, keyword in probes:
        ok, detail = http_probe(url, keyword, timeout)
        details.append(f"{url} → {detail}")
        if ok:
            return True, detail
    return False, "；".join(details) if details else "无可用探测点"
