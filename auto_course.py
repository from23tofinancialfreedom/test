#!/usr/bin/env python3
"""
仅用于自动化测试示例：
- 打开中国烟草网络学院并等待用户扫码登录
- 进入指定班级详情页
- 自动查找“未完成”课程并进入
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

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

HOME_URL = "https://mooc.ctt.cn/#/home"
CLASS_URL = "https://mooc.ctt.cn/#/train-new/class-detail/7a803961-35aa-48e2-8f7b-5ea9796f8ffd"

QUIZ_KEYWORDS = ("测试", "测验", "练习", "作业", "考试", "答题", "问卷")
VIDEO_KEYWORDS = ("视频", "学习", "播放")


@dataclass
class Config:
    headless: bool = False
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


def wait_for_scan_login(page: Page) -> None:
    log("打开首页，等待扫码登录...")
    page.goto(HOME_URL, wait_until="domcontentloaded")

    deadline = time.time() + 10 * 60
    while time.time() < deadline:
        url = page.url
        if "#/home" in url:
            try:
                if page.locator("img[src*='avatar'], .user, .el-avatar").first.is_visible(timeout=1200):
                    log("检测到登录态，继续执行。")
                    return
            except Exception:
                pass

            # 某些情况下没有明显头像，也允许手动回车确认
            print("若你已完成扫码但未自动识别登录，请按回车继续...", end="", flush=True)
            try:
                import select, sys

                has_input = select.select([sys.stdin], [], [], 1.2)[0]
                if has_input:
                    sys.stdin.readline()
                    log("已手动确认登录。")
                    return
            except Exception:
                pass

        time.sleep(1.5)

    raise TimeoutError("等待扫码登录超时（10分钟）")


def open_class_detail(page: Page) -> None:
    log("进入班级详情页...")
    page.goto(CLASS_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)


def click_first_unfinished_course(page: Page) -> bool:
    """在班级详情页点击第一个未完成课程卡片。"""
    log("检索未完成课程...")

    # 尝试点击“未完成”筛选
    for sel in ["text=未完成", "button:has-text('未完成')", ".el-tabs__item:has-text('未完成')"]:
        try:
            page.locator(sel).first.click(timeout=1200)
            page.wait_for_timeout(800)
            break
        except Exception:
            pass

    cards = page.locator("div,li,section,article").filter(has_text=re.compile(r"未完成"))
    count = cards.count()
    if count == 0:
        log("没有发现未完成课程，任务结束。")
        return False

    for idx in range(count):
        card = cards.nth(idx)
        title = safe_text(card.inner_text())[:60]
        # 避免命中筛选栏自身的“未完成”
        if len(title) < 8:
            continue

        try:
            card.click(timeout=1500)
            log(f"进入未完成课程: {title.replace(chr(10), ' / ')}")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2500)
            return True
        except Exception:
            # 尝试点内部可点元素
            for child in ["a", "button", "img", ".cover", ".title"]:
                try:
                    card.locator(child).first.click(timeout=1200)
                    page.wait_for_timeout(2200)
                    return True
                except Exception:
                    pass

    log("找到未完成课程，但未能成功点击进入。")
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
        good = []
        for i in range(min(cnt, 80)):
            node = nodes.nth(i)
            text = safe_text(node.inner_text())
            if not text:
                continue
            if any(k in text for k in ("开始学习", "学习中", "已完成", "视频", "第一节", "第二节", "第")):
                good.append((node, text))
        if len(good) >= 2:
            return good
    return []


def is_quiz_chapter(text: str) -> bool:
    return contains_keywords(text, QUIZ_KEYWORDS)


def watch_current_video(page: Page, cfg: Config) -> bool:
    """加速播放并等待当前小节完成。"""
    start = time.time()
    log("开始监控当前视频播放进度...")

    while time.time() - start < cfg.lesson_timeout_sec:
        # 尝试给 video 提速和静音
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
        # 常见完成信号
        if any(token in body_text for token in ("已完成", "学习完成", "100%", "完成学习")):
            return True

        # 如果出现剩余时间为 00:00 也视为完成
        if re.search(r"剩余\s*0{1,2}[:：]0{1,2}", body_text):
            return True

        time.sleep(cfg.watch_poll_sec)

    log("等待当前小节完成超时，尝试继续下一节。")
    return False


def process_course(page: Page, cfg: Config) -> None:
    """处理单个课程：逐个小节学习，答题类跳过。"""
    page.wait_for_timeout(int(cfg.settle_wait_sec * 1000))

    chapters = list_chapters(page)
    if not chapters:
        log("未识别到课程目录，返回课程列表。")
        return

    for node, text in chapters:
        label = text.replace("\n", " / ")[:120]
        if "已完成" in text:
            continue

        if is_quiz_chapter(text):
            log(f"跳过答题类小节: {label}")
            continue

        if not contains_keywords(text, VIDEO_KEYWORDS) and not re.search(r"第[一二三四五六七八九十\d]+节", text):
            log(f"无法判断类型，默认尝试学习: {label}")

        try:
            node.click(timeout=1500)
            page.wait_for_timeout(1200)
        except Exception:
            continue

        log(f"学习小节: {label}")
        watch_current_video(page, cfg)


def back_to_class_list(page: Page) -> None:
    for sel in ["text=返回", "text=课程列表", "a:has-text('返回')", "button:has-text('返回')"]:
        try:
            page.locator(sel).first.click(timeout=1200)
            page.wait_for_timeout(1800)
            return
        except Exception:
            pass

    # 回退路由
    page.go_back(wait_until="domcontentloaded")
    page.wait_for_timeout(1800)


def main() -> None:
    cfg = Config()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.headless)
        context = browser.new_context()
        page = context.new_page()

        try:
            wait_for_scan_login(page)
            while True:
                open_class_detail(page)
                if not click_first_unfinished_course(page):
                    break

                process_course(page, cfg)
                back_to_class_list(page)

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
