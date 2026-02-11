#!/usr/bin/env python3
"""一键启动脚本（傻瓜版）

功能：
1) 自动检测 Python 依赖 playwright；缺失则自动安装
2) 自动检测 Chromium 浏览器内核；缺失则自动安装
3) 启动 auto_course.py

使用：
  python start.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUTO_SCRIPT = ROOT / "auto_course.py"


def run_cmd(cmd: list[str], desc: str) -> None:
    print(f"\n[启动器] {desc}")
    print(f"[启动器] 执行命令: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(f"[启动器] 失败（exit={result.returncode}）：{desc}")


def ensure_playwright_installed() -> None:
    if importlib.util.find_spec("playwright") is not None:
        print("[启动器] 已检测到 playwright 依赖。")
        return

    run_cmd([sys.executable, "-m", "pip", "install", "playwright"], "安装 playwright")


def ensure_chromium_installed() -> None:
    run_cmd(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        "安装/校验 Playwright Chromium 内核",
    )


def start_auto_course() -> None:
    if not AUTO_SCRIPT.exists():
        raise SystemExit(f"[启动器] 未找到脚本：{AUTO_SCRIPT}")

    run_cmd([sys.executable, str(AUTO_SCRIPT)], "启动刷课脚本")


def main() -> None:
    print("=" * 60)
    print("中国烟草网络学院 - 一键启动")
    print("=" * 60)
    print("说明：启动后会打开浏览器，请按提示扫码登录。")

    ensure_playwright_installed()
    ensure_chromium_installed()
    start_auto_course()


if __name__ == "__main__":
    main()
