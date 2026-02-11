#!/usr/bin/env python3
"""
仅用于自动化测试示例：
- 默认使用 Edge 浏览器启动（如不可用会回退到 Chromium）
- 打开中国烟草网络学院并等待用户扫码登录
- 登录后进入“个人中心-学习中心”页面
- 自动查找未完成课程并进入
- 在课程目录里自动播放视频类小节
- 识别到答题/测验类小节时直接跳过

依赖：pip install playwright
首次使用：python -m playwright install chromium
运行：python auto_course.py
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Browser, Page, Playwright, TimeoutError as PlaywrightTimeoutError, sync_playwright

HOME_URL = "https://mooc.ctt.cn/#/home"
CENTER_URL = "https://mooc.ctt.cn/#/center/index"

QUIZ_KEYWORDS = ("测试", "测验", "练习", "作业", "考试", "答题", "问卷")
VIDEO_KEYWORDS = ("视频", "学习", "播放")


@dataclass
class Config:
    headless: bool = False
    browser_channel: str = "msedge"  # 默认 Edge
    settle_wait_sec: float = 2.0
    watch_poll_sec: float = 8.0
    lesson_timeout_sec: int = 90 * 60


def log(msg: str) -> None:
    print(f"[auto-course] {msg}")


def safe_text(value: Optional[str]) -> str:
    return (value or "").strip()


def contains_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


def launch_browser(playwright: Playwright, cfg: Config) -> Browser:
    """默认 Edge，失败时回退 Chromium。"""
    try:
        log("尝试使用 Edge 启动浏览器...")
        return playwright.chromium.launch(headless=cfg.headless, channel=cfg.browser_channel)
    except Exception as exc:
        log(f"Edge 启动失败，回退 Chromium：{exc}")
        return playwright.chromium.launch(headless=cfg.headless)


def wait_for_scan_login(page: Page) -> None:
    log("打开首页，等待扫码登录...")
    page.goto(HOME_URL, wait_until="domcontentloaded")

    deadline = time.time() + 10 * 60
    while time.time() < deadline:
        if "mooc.ctt.cn" in page.url:
            try:
                if page.locator("img[src*='avatar'], .user, .el-avatar").first.is_visible(timeout=1200):
                    log("检测到登录态，继续执行。")
                    return
            except Exception:
                pass

            # 登录后若自动跳转到个人/课程页，也视为成功
            if any(token in page.url for token in ("#/center", "#/train-new", "#/home")):
                try:
                    if page.locator("text=退出登录").first.is_visible(timeout=600):
                        log("检测到登录态（退出按钮）。")
                        return
                except Exception:
                    pass

        time.sleep(1.5)

    raise TimeoutError("等待扫码登录超时（10分钟）")


def open_learning_center(page: Page) -> None:
    log("进入学习中心页面...")
    page.goto(CENTER_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2200)


def click_first_unfinished_course(page: Page) -> bool:
    """在当前页面点击第一个未完成课程卡片。"""
    log("检索未完成课程...")

    # 优先点筛选“未完成”
    for sel in ["text=未完成", "button:has-text('未完成')", ".el-tabs__item:has-text('未完成')"]:
        try:
            page.locator(sel).first.click(timeout=1200)
            page.wait_for_timeout(800)
            break
        except Exception:
            pass

    # 找到包含“未完成”的课程卡片
    cards = page.locator("div,li,section,article").filter(has_text=re.compile(r"未完成"))
    count = cards.count()
    if count == 0:
        log("没有发现未完成课程，任务结束。")
        return False

    for idx in range(count):
        card = cards.nth(idx)
        text = safe_text(card.inner_text())
        if len(text) < 8:
            continue

        # 跳过工具栏和筛选区域
        if text in ("未完成", "已完成", "全部"):
            continue

        for click_sel in [None, "a", "button", "img", ".cover", ".title"]:
            try:
                target = card if click_sel is None else card.locator(click_sel).first
                target.click(timeout=1500)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)
                log(f"进入未完成课程：{text.replace(chr(10), ' / ')[:60]}")
                return True
            except Exception:
                continue

    log("找到未完成课程，但未能进入。")
    return False


def list_chapters(page: Page):
    """读取右侧目录条目。"""
    candidates = [
        ".catalog *",
        ".directory *",
        "[class*='catalog'] *",
        "[class*='chapter'] *",
        "[class*='menu'] *",
    ]

    for sel in candidates:
        nodes = page.locator(sel)
        try:
            cnt = nodes.count()
        except Exception:
            continue
        if cnt < 2:
            continue
        items = []
        for i in range(min(cnt, 100)):
            node = nodes.nth(i)
            text = safe_text(node.inner_text())
            if not text:
                continue
            if any(k in text for k in ("开始学习", "学习中", "已完成", "视频", "第一节", "第二节", "第")):
                items.append((node, text))
        if len(items) >= 2:
            return items
    return []


def is_quiz_chapter(text: str) -> bool:
    return contains_keywords(text, QUIZ_KEYWORDS)


def watch_current_video(page: Page, cfg: Config) -> bool:
    start = time.time()
    log("开始监控当前视频播放进度...")

    while time.time() - start < cfg.lesson_timeout_sec:
        page.evaluate(
            """
            () => {
              const videos = Array.from(document.querySelectorAll('video'));
              for (const v of videos) {
                v.muted = true;
                try { v.playbackRate = 16; } catch (e) {}
                if (v.paused) { v.play().catch(() => {}); }
              }
            }
            """
        )

        body_text = safe_text(page.locator("body").inner_text())
        if any(token in body_text for token in ("已完成", "学习完成", "100%", "完成学习")):
            return True
        if re.search(r"剩余\s*0{1,2}[:：]0{1,2}", body_text):
            return True

        time.sleep(cfg.watch_poll_sec)

    log("等待当前小节完成超时，尝试继续下一节。")
    return False


def process_course(page: Page, cfg: Config) -> None:
    page.wait_for_timeout(int(cfg.settle_wait_sec * 1000))

    chapters = list_chapters(page)
    if not chapters:
        log("未识别到课程目录，返回学习中心。")
        return

    for node, text in chapters:
        label = text.replace("\n", " / ")[:120]
        if "已完成" in text:
            continue
        if is_quiz_chapter(text):
            log(f"跳过答题类小节：{label}")
            continue
        if not contains_keywords(text, VIDEO_KEYWORDS) and not re.search(r"第[一二三四五六七八九十\d]+节", text):
            log(f"无法判断类型，默认尝试学习：{label}")

        try:
            node.click(timeout=1500)
            page.wait_for_timeout(1200)
        except Exception:
            continue

        log(f"学习小节：{label}")
        watch_current_video(page, cfg)


def back_to_center(page: Page) -> None:
    for sel in ["text=返回", "text=学习中心", "text=我的学习", "a:has-text('返回')", "button:has-text('返回')"]:
        try:
            page.locator(sel).first.click(timeout=1200)
            page.wait_for_timeout(1800)
            return
        except Exception:
            pass

    page.goto(CENTER_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1800)


def main() -> None:
    cfg = Config()

    with sync_playwright() as p:
        browser = launch_browser(p, cfg)
        context = browser.new_context()
        page = context.new_page()

        try:
            wait_for_scan_login(page)
            while True:
                open_learning_center(page)
                if not click_first_unfinished_course(page):
                    break

                process_course(page, cfg)
                back_to_center(page)
                log("本轮课程处理完成，继续检查下一个未完成课程。")

            log("全部课程处理结束。")
        except PlaywrightTimeoutError as e:
            log(f"页面操作超时: {e}")
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
