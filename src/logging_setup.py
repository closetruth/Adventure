"""应用日志初始化。

日志写入数据目录下的 adventure.log，使用 RotatingFileHandler
控制体积（单文件最大 512KB，保留 2 个备份，总计 ≤1.5MB）。
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 512 * 1024   # 512KB
_BACKUP_COUNT = 2


def setup_logging(data_dir: Path, *, debug: bool = False) -> None:
    """配置根 logger：文件输出 + 控制台输出（仅 WARNING 及以上）。"""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # 文件 handler（INFO 及以上）
    log_path = data_dir / "adventure.log"
    file_handler = RotatingFileHandler(
        str(log_path), maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root.addHandler(file_handler)

    # 控制台 handler（仅 WARNING 及以上，避免干扰 GUI）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root.addHandler(console_handler)
