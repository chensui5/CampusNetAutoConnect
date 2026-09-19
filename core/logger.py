# -*- coding: utf-8 -*-
"""日志：同时写文件和推送到界面。"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from .config import logs_dir


class QtLogHandler(logging.Handler, QObject):
    """把日志实时推给 GUI。"""
    record = Signal(str, str)  # (level, formatted_line)

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.record.emit(record.levelname, msg)
        except Exception:
            pass


class LogBus:
    """单例日志总线。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        os.makedirs(logs_dir(), exist_ok=True)
        self.logger = logging.getLogger("campusnet")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()
        self.logger.propagate = False

        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                datefmt="%H:%M:%S")
        self.file_path = os.path.join(
            logs_dir(), datetime.now().strftime("%Y-%m-%d") + ".log")
        # 文件用一条独立的 logger，和界面那条互不干扰（否则会重复写/循环）
        self.file_logger = logging.getLogger("campusnet.file")
        self.file_logger.setLevel(logging.DEBUG)
        self.file_logger.propagate = False
        self.file_logger.handlers.clear()
        try:
            fh = logging.FileHandler(self.file_path, encoding="utf-8")
            fh.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
            self.file_logger.addHandler(fh)
            self.file_handler = fh
        except Exception:
            self.file_handler = None

        self.qt_handler = QtLogHandler()
        self.qt_handler.setFormatter(fmt)
        self.logger.addHandler(self.qt_handler)

    def to_file(self, level: str, text: str) -> None:
        """把一条日志写进文件（界面上的每一行都会落盘）。"""
        if not getattr(self, "file_handler", None):
            return
        lv = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
              "WARNING": logging.WARNING, "ERROR": logging.ERROR}.get(
                  str(level).upper(), logging.INFO)
        try:
            self.file_logger.log(lv, text)
        except Exception:
            pass

    def tail(self, lines: int = 200) -> str:
        """读回最近的日志文本。"""
        try:
            with open(self.file_path, "r", encoding="utf-8", errors="ignore") as f:
                return "".join(f.readlines()[-lines:])
        except Exception:
            return ""

    def debug(self, msg): self.logger.debug(msg); self.to_file("DEBUG", msg)
    def info(self, msg): self.logger.info(msg); self.to_file("INFO", msg)
    def warn(self, msg): self.logger.warning(msg); self.to_file("WARNING", msg)
    def error(self, msg): self.logger.error(msg); self.to_file("ERROR", msg)

    def recent_files(self):
        try:
            files = sorted(
                [f for f in os.listdir(logs_dir()) if f.endswith(".log")],
                reverse=True)
            return [os.path.join(logs_dir(), f) for f in files]
        except Exception:
            return []


def get_logger() -> LogBus:
    return LogBus()
