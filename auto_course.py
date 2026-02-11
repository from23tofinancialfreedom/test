#!/usr/bin/env python3
"""
仅用于自动化测试示例：
- 默认使用 Edge 浏览器启动（如不可用会回退到 Chromium）
- 自动点击“登录”，切换“微信登录”，等待微信扫码
- 登录后自动点击头像进入个人主页/学习中心
- 自动查找需要学习的班级并进入
- 每个班级下自动翻页（每页约 4 门）查找未完成课程并学习
- 识别到答题/测验类小节时直接跳过
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
    browser_channel: str = "msedge"
    settle_wait_sec: float = 2.0
    watch_poll_sec: float = 8.0
    lesson_timeout_sec: int = 90 * 60
    login_timeout_sec: int = 12 * 60


def log(msg: str) -> None:
    print(f"[auto-course] {msg}")


def safe_text(value: Optional[str]) -> str:
    return (value or "").strip()


def contains_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


def launch_browser(playwright: Playwright, cfg: Config) -> Browser:
    try:
        log("尝试使用 Edge 启动浏览器...")
        return playwright.chromium.launch(headless=cfg.headless, channel=cfg.browser_channel)
    except Exception as exc:
        log(f"Edge 启动失败，回退 Chromium：{exc}")
        return playwright.chromium.launch(headless=cfg.headless)


def click_if_visible(page: Page, selectors: list[str], timeout: int = 1200) -> bool:
    for sel in selectors:
        try:
            page.locator(sel).first.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def ensure_login_page_and_wechat_tab(page: Page) -> None:
    """自动点击登录，并切到微信登录区域。"""
    log("进入首页并尝试点击登录...")
    page.goto(HOME_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)

    # 已登录则无需点登录
    try:
        if page.locator("[class*='avatar'], [class*='user'], .el-avatar").first.is_visible(timeout=800):
            log("已是登录态，跳过登录按钮点击。")
            return
    except Exception:
        pass

    clicked = click_if_visible(page, ["text=登录", "a:has-text('登录')", "button:has-text('登录')"])
    if clicked:
        log("已点击登录按钮。")
        page.wait_for_timeout(1500)

    # 切换到微信登录（有些页面本来就默认展示）
    if click_if_visible(page, ["text=微信登录", "a:has-text('微信登录')", "button:has-text('微信登录')"], timeout=1000):
        log("已点击微信登录。")
        page.wait_for_timeout(600)


def wait_for_scan_login(page: Page, cfg: Config) -> None:
    """等待微信扫码登录成功。"""
    log("等待微信扫码登录...")
    deadline = time.time() + cfg.login_timeout_sec
    last_hint = 0.0

    while time.time() < deadline:
        if "mooc.ctt.cn" in page.url:
            try:
                avatar_ok = page.locator("[class*='avatar'], [class*='user'], .el-avatar").first.is_visible(timeout=700)
            except Exception:
                avatar_ok = False

            try:
                nav_ok = page.locator("text=首页").first.is_visible(timeout=700)
            except Exception:
                nav_ok = False

            body = ""
            try:
                body = safe_text(page.locator("body").inner_text())
            except Exception:
                pass

            has_login_prompt = any(k in body for k in ("扫码登录", "微信登录", "请登录", "APP扫码登录"))
            if avatar_ok and nav_ok:
                log("检测到头像与导航，登录成功。")
                return
            if nav_ok and not has_login_prompt:
                log("已离开登录页并进入站内，判定登录成功。")
                return

        now = time.time()
        if now - last_hint >= 15:
            last_hint = now
            log("仍在等待扫码完成，请使用微信扫码并在手机端确认登录。")
        time.sleep(1.5)

    raise TimeoutError("等待扫码登录超时")


def open_home_via_avatar(page: Page) -> None:
    """登录后点击头像展开菜单，并进入学习中心/班级入口。"""
    log("尝试点击头像并进入主页入口...")
    if click_if_visible(page, ["[class*='avatar']", ".el-avatar", "img[src*='avatar']", "[class*='user']"], timeout=1500):
        page.wait_for_timeout(900)

    # 优先班级入口，再退化学习中心
    if click_if_visible(
        page,
        [
            "text=班级",
            "a:has-text('班级')",
            "button:has-text('班级')",
            "text=学习中心",
            "a:has-text('学习中心')",
            "button:has-text('学习中心')",
        ],
        timeout=1500,
    ):
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)
        return

    page.goto(CENTER_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)


def open_first_pending_class(page: Page, visited_classes: set[str]) -> bool:
    """从“任务日历”区域优先进入班级（你截图里的班级任务入口）。"""
    log("查找任务日历中的班级入口...")

    page.goto(CENTER_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    click_if_visible(page, ["text=我的任务"], timeout=1000)
    page.wait_for_timeout(900)

    # 方案1：优先点击任务行右侧“全天”（截图中可点入口）
    day_links = page.locator("a:has-text('全天'), span:has-text('全天')")
    day_count = day_links.count()
    for i in range(min(day_count, 8)):
        try:
            before = page.url
            day_links.nth(i).click(timeout=1200)
            page.wait_for_timeout(1500)
            body = safe_text(page.locator("body").inner_text())
            if page.url != before or any(x in body for x in ("在线课程", "未完成", "已完成", "进度")):
                visited_classes.add(f"DAYLINK::{page.url}")
                log("已从任务日历进入班级课程页（全天入口）。")
                return True
        except Exception:
            continue

    # 方案2：点击任务日历里“班 ...”任务标题（避免匹配整页大容器）
    title_nodes = page.locator("a,span,p,li,em,strong").filter(has_text=re.compile(r"^\s*班|班级|培训班"))
    title_count = title_nodes.count()
    for i in range(min(title_count, 80)):
        node = title_nodes.nth(i)
        text = safe_text(node.inner_text())
        if len(text) < 3 or len(text) > 80:
            continue
        key = text.replace("\n", " ")[:80]
        if key in visited_classes:
            continue

        try:
            before = page.url
            node.click(timeout=1200)
            page.wait_for_timeout(1500)
            body = safe_text(page.locator("body").inner_text())
            if page.url != before or any(x in body for x in ("在线课程", "未完成", "已完成", "进度")):
                visited_classes.add(key)
                log(f"进入班级：{key}")
                return True
        except Exception:
            continue

    # 方案3：头像菜单中的“班级”快捷入口
    if click_if_visible(page, ["[class*='avatar']", ".el-avatar", "img[src*='avatar']", "[class*='user']"], timeout=1000):
        page.wait_for_timeout(700)
        if click_if_visible(page, ["text=班级", "a:has-text('班级')"], timeout=1200):
            page.wait_for_timeout(1200)
            log("通过头像菜单进入班级。")
            return True

    log("未找到可进入的任务日历班级入口。")
    return False


def find_unfinished_cards_on_current_page(page: Page):
    return page.locator("div,li,section,article").filter(has_text=re.compile(r"未完成"))


def goto_next_course_page(page: Page) -> bool:
    """课程卡片分页：每页4个，自动翻下一页。"""
    # 优先点击“> / 下一页”
    for sel in [
        "button:has-text('>')",
        "a:has-text('>')",
        "button:has-text('下一页')",
        "a:has-text('下一页')",
        "li:has-text('下一页')",
    ]:
        try:
            btn = page.locator(sel).first
            cls = safe_text(btn.get_attribute("class"))
            if any(x in cls for x in ("disabled", "is-disabled")):
                continue
            btn.click(timeout=1200)
            page.wait_for_timeout(1200)
            log("已翻到下一页课程。")
            return True
        except Exception:
            continue

    # 兼容只有数字页码的情况：点击当前激活页码的下一个
    try:
        active = page.locator(".is-active, .active").first
        active_txt = safe_text(active.inner_text())
        if active_txt.isdigit():
            next_no = str(int(active_txt) + 1)
            if click_if_visible(page, [f"button:has-text('{next_no}')", f"a:has-text('{next_no}')", f"li:has-text('{next_no}')"], timeout=900):
                page.wait_for_timeout(1200)
                log(f"已翻到课程第 {next_no} 页。")
                return True
    except Exception:
        pass

    return False


def click_next_unfinished_course(page: Page, visited_courses: set[str]) -> bool:
    """在当前班级内逐页查找未完成课程并点击进入。"""
    # 优先筛选未完成
    click_if_visible(page, ["text=未完成", "button:has-text('未完成')", "a:has-text('未完成')"], timeout=900)
    page.wait_for_timeout(500)

    while True:
        cards = find_unfinished_cards_on_current_page(page)
        count = cards.count()

        for i in range(count):
            card = cards.nth(i)
            text = safe_text(card.inner_text())
            if len(text) < 8:
                continue
            key = text.replace("\n", " ")[:120]
            if key in visited_courses:
                continue
            if "未完成" not in text:
                continue

            for sel in [None, "a", "button", "img", ".cover", ".title"]:
                try:
                    target = card if sel is None else card.locator(sel).first
                    target.click(timeout=1500)
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(1500)
                    visited_courses.add(key)
                    log(f"进入未完成课程：{key[:60]}")
                    return True
                except Exception:
                    continue

        if not goto_next_course_page(page):
            log("该班级内未找到更多未完成课程。")
            return False


def list_chapters(page: Page):
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
        for i in range(min(cnt, 120)):
            node = nodes.nth(i)
            text = safe_text(node.inner_text())
            if not text:
                continue
            if any(k in text for k in ("开始学习", "学习中", "已完成", "视频", "第一节", "第二节", "第")):
                items.append((node, text))
        if len(items) >= 2:
            return items

    return []


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
        log("未识别到课程目录，返回班级课程页。")
        return

    for node, text in chapters:
        label = text.replace("\n", " / ")[:120]
        if "已完成" in text:
            continue
        if contains_keywords(text, QUIZ_KEYWORDS):
            log(f"跳过答题类小节：{label}")
            continue

        if not contains_keywords(text, VIDEO_KEYWORDS) and not re.search(r"第[一二三四五六七八九十\d]+节", text):
            log(f"无法判断类型，默认尝试学习：{label}")

        try:
            node.click(timeout=1500)
            page.wait_for_timeout(1000)
        except Exception:
            continue

        log(f"学习小节：{label}")
        watch_current_video(page, cfg)


def back_to_course_list(page: Page) -> None:
    if click_if_visible(
        page,
        ["text=返回", "text=课程列表", "text=班级", "a:has-text('返回')", "button:has-text('返回')"],
        timeout=1200,
    ):
        page.wait_for_timeout(1500)
        return

    page.go_back(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)


def main() -> None:
    cfg = Config()
    with sync_playwright() as p:
        browser = launch_browser(p, cfg)
        context = browser.new_context()
        page = context.new_page()

        try:
            ensure_login_page_and_wechat_tab(page)
            wait_for_scan_login(page, cfg)
            open_home_via_avatar(page)

            visited_classes: set[str] = set()
            class_round = 0
            while class_round < 20:
                class_round += 1
                if not open_first_pending_class(page, visited_classes):
                    log("未找到可进入班级，结束。")
                    break

                visited_courses: set[str] = set()
                course_round = 0
                while course_round < 200:
                    course_round += 1
                    if not click_next_unfinished_course(page, visited_courses):
                        break
                    process_course(page, cfg)
                    back_to_course_list(page)

                page.goto(CENTER_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                log("班级处理完成，继续检查下一个班级。")

            log("全部流程结束。")
        except PlaywrightTimeoutError as exc:
            log(f"页面操作超时：{exc}")
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
