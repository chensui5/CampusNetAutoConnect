# -*- coding: utf-8 -*-
"""测速：下载吞吐 + 连接延迟。纯标准库，跑在后台线程，不卡界面。

测速一律直连、不走代理 —— 走代理测出来的是代理，不是你的线路。
"""

from __future__ import annotations

import time
import urllib.request

from PySide6.QtCore import QThread, Signal

# 默认源：教育网/国内镜像优先（校园网里最快最准），逗号分隔多行逐个尝试
DEFAULT_URLS = (
    "https://mirrors.tuna.tsinghua.edu.cn/ubuntu-releases/22.04/ubuntu-22.04.5-desktop-amd64.iso\n"
    "https://mirrors.ustc.edu.cn/ubuntu-releases/22.04/ubuntu-22.04.5-desktop-amd64.iso\n"
    "https://speed.cloudflare.com/__down?bytes=104857600"
)
_CHUNK = 65536
_UA = "CampusNetAutoConnect"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def split_urls(text: str) -> list[str]:
    urls = [u.strip() for u in (text or "").splitlines() if u.strip()]
    return urls or DEFAULT_URLS.splitlines()


class SpeedTestWorker(QThread):
    progress = Signal(int)      # 0-100
    live = Signal(float)        # 实时速率（Mbps），测速过程中每约 0.4 秒一次
    done = Signal(dict)         # {"mbps","latency_ms","mb","sec","url"}
    failed = Signal(str)

    def __init__(self, urls="", seconds: int = 8, parent=None):
        super().__init__(parent)
        self.urls = split_urls(urls) if isinstance(urls, str) else [u for u in urls if u]
        self.seconds = max(2, int(seconds))
        self._stop = False

    def stop(self):
        self._stop = True

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        t0 = time.time()
        first = None
        total = 0
        with _OPENER.open(req, timeout=10) as resp:
            last_t, last_n = t0, 0
            while not self._stop:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                if first is None:
                    first = time.time()
                total += len(chunk)
                now = time.time()
                if now - last_t >= 0.4:
                    self.live.emit((total - last_n) * 8 / (now - last_t) / 1e6)
                    last_t, last_n = now, total
                el = now - t0
                self.progress.emit(min(99, int(el / self.seconds * 100)))
                if el >= self.seconds:
                    break
        el = time.time() - t0
        if total <= 0 or el <= 0:
            raise RuntimeError("没有收到数据")
        return {"mbps": total * 8 / el / 1e6,
                "latency_ms": (first - t0) * 1000 if first else 0.0,
                "mb": total / 1048576, "sec": el, "url": url}

    def run(self):
        last = ""
        for url in self.urls:
            if self._stop:
                return
            try:
                res = self._fetch(url)
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
                continue
            self.progress.emit(100)
            self.done.emit(res)
            return
        self.failed.emit(last or "所有测速地址都连不上")
