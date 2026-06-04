# -*- coding: utf-8 -*-
"""JD product review crawler using DrissionPage auto-browser with persistent profile.

Prerequisites:
1. Run mmb_manual_login.py once to log into JD and save the profile.
   Or copy an existing .jd_playwright_profile with a valid JD login session.
2. Run:
   python jd_cdp_review_scraper.py

DrissionPage manages the browser lifecycle automatically — no need to start
Chrome manually or configure CDP ports. CAPTCHA: script pauses and waits for
manual completion in the browser.
"""

from __future__ import annotations

# 1. 导入所需库
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup
from DrissionPage import ChromiumPage, ChromiumOptions


# 2. 常量配置
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "数据" / "merged_products.csv"
CSV_FALLBACK_PATHS = [BASE_DIR / "merged_products.csv", BASE_DIR / "数据" / "merged_products.csv"]
OUTPUT_DIR = BASE_DIR / "数据" / "京东评论爬取"
CHECKPOINT_FILE = OUTPUT_DIR / "crawled_items.csv"
MAX_DAILY_PRODUCTS = 200
REQUEST_INTERVAL = (20, 35)  # 秒 — 温和间隔，不过度刺激京东
CHROME_PROFILE_DIR = BASE_DIR / ".jd_playwright_profile"
SAVE_EVERY = 50
MAX_REVIEW_PAGES = 1  # 只取第一页，避免翻页操作挂起
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
RUN_STATE_FILE = BASE_DIR / "jd_cdp_review_scraper_state.json"

PRODUCT_REVIEWS_FILE = "product_reviews.csv"
PRODUCT_DETAILS_FILE = "product_details.csv"
NEGATIVE_REVIEWS_FILE = "negative_reviews.csv"


# 评论卡片定位
COMMENT_CARD_SELECTORS = [
    'div[class~="jdc-pc-rate-card"]',
    '#comment-root ul.list > li.item',
    'div[class*="comment-item"]',
    'div[class*="rate-card"]',
    ".comment-item",
    ".jdc-rate-item",
    '[class*="rate-item"]',
    "li[data-sku]",
]

# 评分星级选择器
STAR_SELECTORS = [
    'img[class*="star"]',
    'span[class*="star"]',
    '[class*="score"] img',
    ".star-level img",
]

# 评价标签选择器
TAG_SELECTORS = [
    '[class*="tag"]',
    '[class*="label-item"]',
    ".comment-tag",
    ".tag",
]


# 3. 提取函数（适配当前京东评论区 DOM 结构）
def extract_single_review(html_text):
    """
    提取评价字段，返回包含用户昵称、评分、日期、SKU、评价内容、点赞数的一维列表

    适配京东当前评论区结构:
      li.item > div.comment-user > div.nickname
              > div.info.text-ellipsis-2 (内容)
              > div.imgs (晒图)
              > div.date, div.order-info (日期/SKU)
    同时兼容旧版 jdc-pc-rate-card 结构。
    """
    soup = BeautifulSoup(html_text, 'html.parser')

    # ── 昵称 ──
    nickname = ""
    for selector in [
        '.comment-user .nickname',
        'div[class*="nickname"]',
        '.nickname',
        'span[class*="nickname"]',
        'span[class*="user-name"]',
        '.user-info span',
    ]:
        elem = soup.select_one(selector)
        if elem:
            nickname = elem.get_text(strip=True)
            break

    # ── 评分（从 star 图片或者 CSS class 提取） ──
    score_src = ""
    # 新版：查找 star 相关的 class
    for cls_prefix in ['star', 'score', 'rate']:
        for elem in soup.select(f'[class*="{cls_prefix}"]'):
            cls = ' '.join(elem.get('class', []))
            # 尝试从 class="star5" 等提取
            m = re.search(r'(?:star|score|rate)[_-]?(\d)', cls)
            if m:
                score_src = m.group(1)
                break
        if score_src:
            break

    # 备用：从图片 URL 提取
    if not score_src:
        for img in soup.find_all('img'):
            src = img.get('src', '') or img.get('data-src', '')
            if 'rate' in src.lower() or 'star' in src.lower():
                score_src = src
                break

    # ── 日期 ──
    date = ""
    for selector in [
        'div[class*="date"]',
        'span[class*="date"]',
        'span[class*="time"]',
        '.order-info .date',
        '.date',
        'div[class*="time"]',
        '.comment-user .date',
    ]:
        elem = soup.select_one(selector)
        if elem:
            date = elem.get_text(strip=True)
            break

    # ── SKU（从 order-info 或页面结构提取） ──
    sku = ""
    for selector in [
        'div[class*="order-info"]',
        'span[class*="sku"]',
        '.product-info span',
        '.sku-name',
    ]:
        elem = soup.select_one(selector)
        if elem:
            sku = elem.get_text(strip=True)
            break

    # ── 评论内容 ──
    content = ""
    for selector in [
        'div.info.text-ellipsis-2',
        '.comment-item .info',
        'div[class*="text-ellipsis"]',
        'div.info',
        'p[class*="comment"]',
        'div[class*="comment-con"]',
        '.comment-text',
        'p[itemprop="description"]',
    ]:
        elem = soup.select_one(selector)
        if elem:
            content = elem.get_text(strip=True)
            break

    # 如果所有选择器都失败，从整个 card 文本中提取
    if not content:
        all_text = soup.get_text(' ', strip=True)
        # 过滤掉明显的元数据行
        lines = [l.strip() for l in all_text.split('  ') if l.strip() and len(l.strip()) > 15]
        if lines:
            content = max(lines, key=len)

    # ── 点赞数 ──
    like_count = "0"
    for selector in [
        'div[class*="like"]',
        'span[class*="like"]',
        '.vote-count',
        '[class*="up"]',
        'div[class*="vote"]',
        'span[class*="vote"]',
    ]:
        elem = soup.select_one(selector)
        if elem:
            match = re.search(r'\d+', elem.get_text())
            if match:
                like_count = match.group()
                break

    return [nickname, score_src, date, sku, content, like_count]


def extract_product_details(page_content):
    """
    提取商品详情页信息：评价标签、好评率、商品属性（产地、保质期、配料表）
    """
    soup = BeautifulSoup(page_content, 'html.parser')
    details = {}

    # 好评率
    rate_match = re.search(r'(\d+\.?\d*)%', page_content)
    if rate_match:
        details['好评率'] = rate_match.group(1) + '%'

    # 评价标签（口感好、包装破损等）
    tags = []
    for selector in ['[class*="tag"]', '[class*="label"]', '.tag-item']:
        for elem in soup.select(selector):
            text = elem.get_text(strip=True)
            if text and len(text) < 20:
                tags.append(text)
    details['评价标签'] = '|'.join(tags[:20])  # 最多20个标签

    # 商品属性提取（产地、保质期、配料表等）
    attr_map = {
        '产地': ['产地', '生产地', '原产地'],
        '保质期': ['保质期', '有效期', '生产日期'],
        '配料表': ['配料', '配料表', '成分'],
        '规格': ['规格', '净含量', '包装']
    }

    text_content = page_content
    for attr_name, keywords in attr_map.items():
        for kw in keywords:
            match = re.search(rf'{kw}[：:]\s*([^\s<,，]+[^\n<]*)', text_content)
            if match:
                details[attr_name] = match.group(1).strip()[:100]
                break

    return details


def extract_negative_reviews(page_content):
    """
    提取差评内容（筛选1-2星评价）
    """
    soup = BeautifulSoup(page_content, 'html.parser')
    negative_reviews = []

    # 定位所有评论卡片
    cards = soup.select('div[class*="comment"], div[class*="rate"], .comment-item')

    for card in cards:
        # 判断是否为差评（1-2星）
        star_elem = card.select_one('[class*="star"], [class*="score"]')
        if star_elem:
            star_text = star_elem.get_text()
            if '1' in star_text or '2' in star_text or '差' in star_text:
                content = card.get_text(strip=True)
                if len(content) > 10:  # 过滤过短的评论
                    negative_reviews.append(content[:500])  # 截取前500字符

    return negative_reviews


def extract_jd_good_rate(page_content: str) -> str:
    """更严格地提取京东好评率，避免误抓任意百分号。"""
    patterns = [
        r"(?:好评率|好评度)\s*[:：]?\s*(\d+(?:\.\d+)?%)",
        r"(\d+(?:\.\d+)?%)\s*好评",
        r"(超?\d+(?:\.\d+)?%)\s*买家赞不绝口",
        r"赞不绝口[^0-9]{0,12}(超?\d+(?:\.\d+)?%)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_content)
        if match:
            return match.group(1)
    return ""


def extract_jd_review_tags(page_content: str) -> str:
    """从评论区文本中提取京东评价标签，过滤导航和计数项。"""
    soup = BeautifulSoup(page_content, "html.parser")
    tags: list[str] = []
    blocked = {"全部", "好评", "中评", "差评", "追评", "图/视频", "查看全部参数"}

    for elem in soup.select("#comment-root .tags .item"):
        texts = [child.get_text(strip=True) for child in elem.find_all("div", recursive=False)]
        text = texts[0] if texts else elem.get_text(strip=True)
        if text and text not in blocked and len(text) <= 20 and text not in tags:
            tags.append(text)
        if len(tags) >= 20:
            return "|".join(tags)
    if tags:
        return "|".join(tags)

    for selector in TAG_SELECTORS + ['[class*="comment"] span', '[class*="rate"] span']:
        for elem in soup.select(selector):
            text = elem.get_text(strip=True)
            if not text or text in blocked or len(text) > 20:
                continue
            if re.fullmatch(r"\d+万?\+?", text):
                continue
            if text not in tags:
                tags.append(text)
            if len(tags) >= 20:
                return "|".join(tags)
    return "|".join(tags)


def extract_product_details_strict(page_content: str) -> dict[str, str]:
    """保留原始提取函数结果，但用京东语义规则修正好评率和标签。"""
    details = extract_product_details(page_content)
    text_lines = [line.strip() for line in BeautifulSoup(page_content, "html.parser").get_text("\n", strip=True).splitlines() if line.strip()]
    strict_rate = extract_jd_good_rate(page_content)
    if strict_rate:
        details["好评率"] = strict_rate
    else:
        details["好评率"] = ""

    strict_tags = extract_jd_review_tags(page_content)
    if strict_tags:
        details["评价标签"] = strict_tags
    label_groups = {
        "产地": ["产地", "生产地", "原产地"],
        "保质期": ["保质期", "有效期"],
        "配料表": ["配料表", "配料", "成分"],
        "规格": ["规格", "净含量", "包装形式", "包装清单"],
    }
    for key, labels in label_groups.items():
        for index, line in enumerate(text_lines):
            if line in labels and index > 0 and len(text_lines[index - 1]) <= 100:
                details[key] = text_lines[index - 1][:100]
                break
            if line in labels and index + 1 < len(text_lines) and len(text_lines[index + 1]) <= 100:
                details[key] = text_lines[index + 1][:100]
                break
    return details


def parse_star_from_card(card) -> str:
    """从文本、图片链接、class、alt/title 中解析星级。"""
    candidates: list[str] = [card.get_text(" ", strip=True)]
    for elem in card.select('[class*="star"], [class*="score"], img'):
        for attr in ["class", "src", "data-src", "alt", "title", "aria-label"]:
            value = elem.get(attr)
            if isinstance(value, list):
                value = " ".join(value)
            if value:
                candidates.append(str(value))
    joined = " ".join(candidates)
    patterns = [
        r"star[_-]?(?:level[_-]?)?([1-5])",
        r"score[_-]?([1-5])",
        r"rate[_-]?([1-5])",
        r"([1-5])\s*星",
    ]
    for pattern in patterns:
        match = re.search(pattern, joined, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    if "差评" in joined:
        return "1"
    return ""


def extract_jd_negative_reviews(page_content: str, assume_filtered_bad: bool = False) -> list[dict[str, str]]:
    """提取差评内容，兼容星级图片/class；如果已点击差评筛选，可将可见卡片视为差评候选。"""
    soup = BeautifulSoup(page_content, "html.parser")
    rows: list[dict[str, str]] = []
    cards = []
    for selector in COMMENT_CARD_SELECTORS:
        cards = soup.select(selector)
        if cards:
            break
    if not cards:
        cards = soup.select('div[class*="comment"], div[class*="rate"], .comment-item')

    for card in cards:
        star_level = parse_star_from_card(card)
        text = card.get_text(" ", strip=True)
        is_negative = star_level in {"1", "2"} or assume_filtered_bad
        if not is_negative:
            continue
        content = ""
        for selector in [
            'p[class*="comment"]',
            'div[class*="comment-con"]',
            '.comment-text',
            'p[itemprop="description"]',
            '.jdc-pc-rate-card-main-desc',
            '.info.text-ellipsis-2',
            "[class*='main-desc']",
            '[class*="content"]',
        ]:
            elem = card.select_one(selector)
            if elem:
                content = elem.get_text(" ", strip=True)
                break
        if not content:
            content = text
        content = clean_text(content)
        if len(content) > 10:
            rows.append({"content": content[:500], "star_level": star_level or "1-2"})
    return rows


# 四、错误处理机制
class JDScraperError(Exception):
    """自定义异常"""


class CaptchaTimeoutError(JDScraperError):
    """验证码等待超时——应跳过该商品，计入当日验证码计数"""


def safe_extract(func, default=None, *args, **kwargs):
    """安全的函数调用"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"  [WARN] 提取失败: {e}")
        return default


def retry_on_failure(func, max_retries=3, delay=5):
    """失败重试装饰器"""
    def wrapper(*args, **kwargs):
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  [WARN] 第{attempt+1}次失败，{delay}秒后重试...")
                    time.sleep(delay)
                else:
                    print(f"  [ERROR] 重试次数用尽: {e}")
                    raise
    return wrapper


def handle_network_error(e, context="操作"):
    """网络错误处理"""
    error_msg = str(e).lower()

    if 'timeout' in error_msg:
        print(f"[TIMEOUT] {context}超时")
    elif 'network' in error_msg or 'connection' in error_msg:
        print(f"[NETWORK] {context}网络错误，延长等待时间...")
        time.sleep(30)
    elif '403' in error_msg or 'Forbidden' in error_msg:
        print(f"[FORBIDDEN] {context}被拒绝访问，疑似IP封禁")
        print("建议：更换IP或等待一段时间后重试")
    else:
        print(f"[ERROR] {context}异常: {e}")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def ensure_dir(path: str | Path) -> None:
    os.makedirs(path, exist_ok=True)


def to_number(value: Any) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text or text.lower() == "nan":
        return 0.0
    multiplier = 1.0
    if "万" in text:
        multiplier = 10000.0
    elif "千" in text:
        multiplier = 1000.0
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) * multiplier if match else 0.0


def normalize_sku(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    if "e+" in text.lower():
        try:
            return str(int(float(text)))
        except ValueError:
            return text
    return text


def resolve_csv_path() -> str:
    for path in [CSV_PATH, *CSV_FALLBACK_PATHS]:
        if os.path.exists(path):
            return str(path)
    raise FileNotFoundError(f"未找到输入文件，已尝试: {[CSV_PATH, *CSV_FALLBACK_PATHS]}")


def normalize_input_columns(df: pd.DataFrame) -> pd.DataFrame:
    """适配 merged_products.csv 与提示词里的标准字段名。"""
    out = df.copy()
    if "item_id" not in out.columns and "product_id" in out.columns:
        out["item_id"] = out["product_id"]
    if "title" not in out.columns and "product_title" in out.columns:
        out["title"] = out["product_title"]
    if "price" not in out.columns and "current_price" in out.columns:
        out["price"] = out["current_price"]
    if "category_breadcrumb" not in out.columns:
        if "category_path" in out.columns:
            out["category_breadcrumb"] = out["category_path"]
        elif "historical_level3" in out.columns:
            out["category_breadcrumb"] = out["historical_level3"]
        else:
            out["category_breadcrumb"] = ""
    if "rank_position" not in out.columns:
        if "source_page_number" in out.columns:
            out["rank_position"] = out["source_page_number"].map(to_number)
        else:
            out["rank_position"] = 999999
    if "review_count" not in out.columns:
        out["review_count"] = 0
    if "shop_name" not in out.columns:
        out["shop_name"] = ""

    out["item_id"] = out["item_id"].map(normalize_sku)
    out["detail_url"] = out["detail_url"].astype(str).str.strip()
    out["title"] = out["title"].fillna("").astype(str)
    out["price"] = out["price"].map(to_number)
    out["review_count"] = out["review_count"].map(to_number)
    out["rank_position"] = out["rank_position"].map(to_number)
    out["shop_name"] = out["shop_name"].fillna("").astype(str)
    out["category_breadcrumb"] = out["category_breadcrumb"].fillna("").astype(str)
    return out


# 4. 筛选函数
def build_priority_pool(csv_path):
    """
    构建重点商品优先池
    返回：按优先级排序后的完整候选列表
    """
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    df = normalize_input_columns(df)
    df = df[df["detail_url"].str.startswith("http") & df["item_id"].ne("")]

    # 优先级1：各品类TOP10（rank_position <= 10）
    top10 = df[df['rank_position'] <= 10].copy()

    # 优先级2：评论数异常高的（评论数 > 均值*2）
    mean_reviews = df['review_count'].mean()
    high_comments = df[df['review_count'] > mean_reviews * 2].copy()

    # 优先级3：价格带空白区的（低价区间和高价区间）
    # 计算价格分布，找出价格段的边界
    price_quantiles = df['price'].quantile([0.2, 0.4, 0.6, 0.8])
    low_price = df[df['price'] < price_quantiles[0.2]]
    high_price = df[df['price'] > price_quantiles[0.8]]

    # 合并去重
    targets = pd.concat([top10, high_comments, low_price, high_price]).drop_duplicates(subset=['item_id'])

    targets = targets.sort_values('review_count', ascending=False)
    return targets[['item_id', 'title', 'detail_url', 'review_count', 'shop_name', 'category_breadcrumb']].values.tolist()


def filter_target_products(csv_path, max_daily=80, crawled_ids: set[str] | None = None):
    """
    从完整优先池中跳过已覆盖商品，直接取本轮待爬批次。
    这样无需手动持续增加 MAX_DAILY_PRODUCTS，脚本会自动向后推进。
    """
    priority_pool = build_priority_pool(csv_path)
    if crawled_ids:
        priority_pool = [item for item in priority_pool if not should_skip_item(item[0], crawled_ids)]
    return priority_pool[:max_daily]


# 5. 验证码处理
def check_captcha(page: ChromiumPage) -> bool:
    """
    检测验证码弹窗
    返回：True-发现验证码，False-正常
    """
    captcha_indicators = [
        '验证', 'captcha', 'Captcha',
        '[class*="captcha"]',
        '[class*="verify"]',
        '[id*="captcha"]',
        '#captcha',
        '.yzm',  # 滑块验证码
        '[class*="slider"]'
    ]

    current_url = ""
    page_title = ""
    body_text = ""
    try:
        current_url = page.url.lower()
    except Exception:
        pass
    try:
        page_title = page.title
    except Exception:
        pass
    try:
        body = page.ele("body", timeout=3)
        if body:
            body_text = body.text
    except Exception:
        pass

    if any(token in current_url for token in ["risk_handler", "captcha", "verify", "authcode"]):
        return True
    if any(token in page_title for token in ["京东验证", "验证"]):
        return True
    if any(token in body_text for token in ["验证一下", "快速验证", "购物无忧", "请完成验证"]):
        return True

    page_content = page.html

    for indicator in captcha_indicators:
        if indicator in page_content:
            return True

    # 检查是否有模态弹窗
    try:
        modal = page.ele('[class*="modal"], [class*="dialog"], .pop-mask', timeout=1)
        if modal and modal.states.is_displayed:
            return True
    except Exception:
        pass

    return False


def check_login_state(page: ChromiumPage) -> dict[str, bool | str]:
    """检测京东登录状态，返回当前是否已登录及用户昵称。"""
    try:
        page.get("https://www.jd.com/", timeout=15)
    except Exception:
        return {"logged_in": False, "nickname": "页面加载失败"}

    time.sleep(random.uniform(1.5, 3.0))

    try:
        body_text = page.run_js("return document.body ? document.body.innerText : ''")
    except Exception:
        body_text = ""

    if "请登录" in body_text and "你好，请登录" in body_text:
        return {"logged_in": False, "nickname": "未登录"}

    # 尝试读取页面上的用户昵称
    nickname = ""
    try:
        nick_el = page.ele('[class*="nickname"]', timeout=2)
        if nick_el:
            nickname = nick_el.text
    except Exception:
        pass

    if not nickname:
        try:
            nick_el = page.ele('#ttbar-login .nickname', timeout=2)
            if nick_el:
                nickname = nick_el.text
        except Exception:
            pass

    if not nickname:
        try:
            nick_el = page.ele('[class*="user"]', timeout=2)
            if nick_el and nick_el.text:
                nickname = nick_el.text.strip()[:30]
        except Exception:
            pass

    return {"logged_in": True, "nickname": nickname or "已登录（昵称未识别）"}


def check_access_blocked(page: ChromiumPage) -> bool:
    """检测京东详情页 403/风控拦截跳转。"""
    try:
        current_url = page.url.lower()
    except Exception:
        current_url = ""
    if "reason=403" in current_url or "from=pc_item" in current_url:
        return True
    try:
        body = page.ele("body", timeout=3)
        body_text = body.text if body else ""
    except Exception:
        body_text = ""
    blocked_markers = ["reason=403", "访问受限", "拒绝访问", "Forbidden"]
    return any(marker in body_text for marker in blocked_markers)


def wait_for_manual_verification(page: ChromiumPage, screenshot_dir: str | Path = './screenshots', max_wait_seconds: int = 0):
    """
    验证码处理——自动尝试解除，失败则跳过商品。
    """
    print("  [CAPTCHA] 检测到验证码，尝试自动解除...")
    for attempt in range(3):
        time.sleep(random.uniform(5, 10))
        # 方案1: 点击验证按钮（部分滑块验证可自动过）
        try:
            btns = page.eles("text:验证", timeout=2) or page.eles("text:确认", timeout=2)
            if btns:
                btns[0].click()
                time.sleep(3)
        except Exception:
            pass
        # 方案2: 刷新页面
        try:
            page.refresh()
            time.sleep(random.uniform(5, 8))
        except Exception:
            pass
        # 检查是否解除了
        if not check_captcha(page):
            print("  [CAPTCHA] 验证码已自动解除")
            return True
        print(f"  [CAPTCHA] 尝试 {attempt+1}/3 未解除，继续等待...")

    print("  [CAPTCHA] 未能自动解除，跳过该商品")
    return False


# 2. 每日爬取限制 / 3. 模拟真人操作
def human_like_delay():
    """随机延时，模拟真人浏览"""
    time.sleep(random.uniform(*REQUEST_INTERVAL))


def simulate_scroll(page: ChromiumPage, scroll_count: int = 2):
    """模拟真人滚动浏览——更慢更自然"""
    for _ in range(scroll_count):
        try:
            page.run_js(f"window.scrollBy(0, {random.randint(200, 500)})", timeout=5)
        except Exception:
            pass
        time.sleep(random.uniform(2.5, 5.0))
        # 经常停顿更久（模拟阅读评价）
        if random.random() < 0.4:
            time.sleep(random.uniform(3, 8))


# 4. 进度保存（每50个商品保存一次）
def save_checkpoint(crawled_items, output_dir):
    """保存已爬取记录，支持断点续爬"""
    import pandas as pd

    if not crawled_items:
        return

    checkpoint_file = os.path.join(output_dir, 'crawled_items.csv')

    if os.path.exists(checkpoint_file):
        try:
            existing = pd.read_csv(checkpoint_file, dtype=str).fillna("")
        except pd.errors.EmptyDataError:
            existing = pd.DataFrame()
        if "item_id" in existing.columns:
            existing = existing[~existing['item_id'].isin([str(item['item_id']) for item in crawled_items])]
        else:
            existing = pd.DataFrame()
        new_records = pd.DataFrame(crawled_items)
        combined = pd.concat([existing, new_records], ignore_index=True)
    else:
        combined = pd.DataFrame(crawled_items)

    combined.to_csv(checkpoint_file, index=False, encoding='utf-8-sig')
    print(f"[OK] 断点记录已保存 ({len(crawled_items)}条新记录)")


# 5. 断点续爬逻辑
def load_checkpoint(checkpoint_file):
    """加载已爬取记录"""
    import pandas as pd

    if os.path.exists(checkpoint_file) and os.path.getsize(checkpoint_file) > 0:
        try:
            df = pd.read_csv(checkpoint_file, dtype=str).fillna("")
        except pd.errors.EmptyDataError:
            return set()
        if {"status", "comment_card_count", "item_id"}.issubset(df.columns):
            card_counts = pd.to_numeric(df["comment_card_count"], errors="coerce").fillna(0)
            df = df[((df["status"] == "success") & (card_counts > 0)) | (df["status"] == "access_blocked")]
        return set(df['item_id'].astype(str).tolist())
    return set()


def should_skip_item(item_id, crawled_ids):
    """判断是否跳过（已爬取）"""
    return str(item_id) in crawled_ids


# 日运行状态管理（确保同一日历日仅运行一次）
def load_run_state() -> dict:
    if not RUN_STATE_FILE.exists():
        return {}
    try:
        return json.loads(RUN_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def mark_run_started() -> None:
    state = {
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "started_at": now_str(),
    }
    RUN_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_single_run_per_day() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    state = load_run_state()
    if state.get("run_date") == today:
        raise RuntimeError(
            f"jd_cdp_review_scraper.py already ran today ({today}); wait until tomorrow."
        )
    mark_run_started()


# 五、去重逻辑
def deduplicate_reviews(reviews):
    """
    评论去重
    使用 评论内容+日期 的组合作为去重键
    """
    seen = set()
    unique_reviews = []

    for review in reviews:
        # 创建去重键
        content = review.get('content', '')[:100]  # 取前100字符
        date = review.get('date', '')
        dedup_key = f"{content}_{date}"

        if dedup_key not in seen:
            seen.add(dedup_key)
            unique_reviews.append(review)

    return unique_reviews


def deduplicate_products(products):
    """
    商品去重（基于item_id）
    """
    seen_ids = set()
    unique_products = []

    for product in products:
        item_id = str(product['item_id'])
        if item_id not in seen_ids:
            seen_ids.add(item_id)
            unique_products.append(product)

    return unique_products


# 6. 主爬取逻辑辅助函数
def click_if_exists(page: ChromiumPage, text_or_selector: str, by_text: bool = True, timeout: int = 2500) -> bool:
    try:
        if by_text:
            el = page.ele(f"text:{text_or_selector}", timeout=timeout / 1000)
        else:
            el = page.ele(text_or_selector, timeout=timeout / 1000)
        if el and el.states.is_displayed:
            el.click()
            time.sleep(random.uniform(1.5, 3.0))
            return True
    except Exception:
        return False
    return False


def goto_detail(page: ChromiumPage, detail_url: str, timeout: int = 30) -> None:
    """访问商品详情页，DrissionPage 原生 timeout 防止无限挂起。"""
    try:
        page.get(detail_url, timeout=timeout)
    except Exception as e:
        try:
            page.stop_loading()
        except Exception:
            pass
        raise JDScraperError(f"页面加载失败 ({timeout}s): {detail_url[:80]} — {e}")

    # 模拟真人阅读页面: 停顿 8-20 秒
    time.sleep(random.uniform(8, 20))

    # 检查重定向
    current_url = page.url.lower() if page.url else ""
    if "login" in current_url or "passport" in current_url:
        raise JDScraperError(f"页面重定向到登录页，profile 需刷新")

    if check_access_blocked(page):
        raise JDScraperError(f"403/访问受限")

    if check_captcha(page):
        if not wait_for_manual_verification(page, SCREENSHOT_DIR):
            raise CaptchaTimeoutError("验证码未解除")

    # 模拟人类浏览：随机滚动（减少次数）
    simulate_scroll(page, scroll_count=random.randint(1, 2))


def open_comments_area(page: ChromiumPage) -> None:
    """滚动到评论区（不触发任何点击和 load_complete，防止无限挂起）。"""
    try:
        page.run_js(
            "window.scrollTo(0, Math.floor(document.documentElement.scrollHeight * 0.4))",
            timeout=8,
        )
    except Exception:
        pass
    time.sleep(random.uniform(5.0, 10.0))  # 模拟阅读评论区


def get_review_content_signature(page: ChromiumPage) -> tuple[str, ...]:
    """取前几条评论正文作为筛选是否生效的轻量指纹。"""
    signatures: list[str] = []
    for card_html in get_comment_card_html(page)[:8]:
        soup = BeautifulSoup(card_html, "html.parser")
        elem = soup.select_one(
            ".jdc-pc-rate-card-main-desc, .info.text-ellipsis-2, [class*='main-desc'], "
            "p[class*='comment'], div[class*='comment-con'], .comment-text"
        )
        text = clean_text(elem.get_text(" ", strip=True) if elem else soup.get_text(" ", strip=True))
        if text:
            signatures.append(text[:120])
    return tuple(signatures)


def has_active_bad_filter(page: ChromiumPage) -> bool:
    """判断评论区里"差评"筛选是否处于选中态。"""
    soup = BeautifulSoup(page.html, "html.parser")
    for elem in soup.select("#comment-root [class*='active'], #comment-root [class*='selected'], #comment-root [class*='current'], #comment-root [class*='on']"):
        text = elem.get_text(" ", strip=True)
        if "差评" in text:
            return True
    return False


def click_negative_filter(page: ChromiumPage) -> bool:
    before_signature = get_review_content_signature(page)
    for text in ["差评", "1星", "2星"]:
        clicked = False
        try:
            root = page.ele("#comment-root", timeout=2)
            if root:
                el = root.ele(f"text:{text}", timeout=2)
                if el and el.states.is_displayed:
                    el.click()
                    clicked = True
        except Exception:
            pass

        if not clicked:
            clicked = click_if_exists(page, text, by_text=True)

        if clicked:
            time.sleep(random.uniform(3.0, 5.0))
            after_signature = get_review_content_signature(page)
            if has_active_bad_filter(page) or (after_signature and after_signature != before_signature):
                return True
            print("  [WARN] 已点击差评筛选，但未确认评论列表切换；本页不按差评筛选结果计数")
            return False
    return False


def get_comment_card_html(page: ChromiumPage) -> list[str]:
    """直接从页面 HTML 用 BeautifulSoup 提取评论卡片（避免 DrissionPage eles() 挂起）。"""
    try:
        page_html = page.html
    except Exception:
        return []
    soup = BeautifulSoup(page_html, "html.parser")
    items = soup.select('#comment-root ul.list > li.item')
    if not items:
        items = soup.select('#comment-root .item')
    if not items:
        items = soup.select('[class*="comment-item"]')
    return [str(it) for it in items[:60]]


def parse_star_level(score_src: str, html_text: str = "") -> str:
    text = f"{score_src} {html_text}"
    patterns = [
        r"star[_-]?(\d)",
        r"rate[_-]?(\d)",
        r"score[_-]?(\d)",
        r"(\d)\s*星",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    if "差评" in text:
        return "1-2"
    return ""


def extract_reviews_from_page(page: ChromiumPage, item_id: str, title: str) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for card_html in get_comment_card_html(page):
        nickname, score_src, date, sku, content, like_count = extract_single_review(card_html)
        soup = BeautifulSoup(card_html, "html.parser")
        card_text = soup.get_text(" ", strip=True)
        if not nickname:
            elem = soup.select_one(".jdc-pc-rate-card-nick, .nickname, .comment-user .nickname")
            nickname = elem.get_text(strip=True) if elem else ""
        if not date:
            elem = soup.select_one(".date, .date.list, span[class*='date']")
            date = elem.get_text(strip=True) if elem else ""
        if not sku:
            elem = soup.select_one(".info, span.info, [class*='sku']")
            sku = elem.get_text(strip=True) if elem else ""
        if not content:
            elem = soup.select_one(".jdc-pc-rate-card-main-desc, .info.text-ellipsis-2, [class*='main-desc']")
            content = elem.get_text(strip=True) if elem else ""
        if not content and len(card_text) > 10:
            content = card_text[:500]
        if not content:
            continue
        reviews.append(
            {
                "item_id": str(item_id),
                "title": title,
                "nickname": nickname,
                "score": parse_star_from_card(soup) or parse_star_level(score_src, card_text) or score_src,
                "date": date,
                "sku": sku,
                "content": content,
                "like_count": like_count,
                "crawl_time": now_str(),
            }
        )
    return reviews


def extract_negative_rows_from_page(page: ChromiumPage, item_id: str, title: str, assume_filtered_bad: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_content = page.html
    for item in extract_jd_negative_reviews(page_content, assume_filtered_bad=assume_filtered_bad):
        rows.append(
            {
                "item_id": str(item_id),
                "title": title,
                "content": item["content"],
                "star_level": item["star_level"],
                "crawl_time": now_str(),
            }
        )

    for review in extract_reviews_from_page(page, item_id, title):
        star = str(review.get("score", ""))
        if star in {"1", "2", "1-2"}:
            rows.append(
                {
                    "item_id": str(item_id),
                    "title": title,
                    "content": review["content"][:500],
                    "star_level": star or "1-2",
                    "crawl_time": now_str(),
                }
            )
    return rows


def diagnostic_review_state(page: ChromiumPage) -> dict[str, Any]:
    page_content = page.html
    soup = BeautifulSoup(page_content, "html.parser")
    card_count = 0
    used_selector = ""
    for selector in COMMENT_CARD_SELECTORS:
        count = len(soup.select(selector))
        if count:
            card_count = count
            used_selector = selector
            break
    text = soup.get_text(" ", strip=True)
    return {
        "comment_card_count": card_count,
        "comment_selector": used_selector,
        "has_bad_filter_text": "差评" in text,
        "has_good_rate_text": bool(extract_jd_good_rate(page_content)),
    }


def crawl_comments_pages(page: ChromiumPage, item_id: str, title: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """抓取评论——单页版，不翻页不点差评（避免 DrissionPage 元素操作挂起）。"""
    all_reviews: list[dict[str, Any]] = []
    negative_rows: list[dict[str, Any]] = []
    open_comments_area(page)

    # 抓当前可见的评论
    all_reviews.extend(extract_reviews_from_page(page, item_id, title))

    # 同时从 HTML 提取差评
    page_content = page.html
    for item in extract_jd_negative_reviews(page_content, assume_filtered_bad=False):
        negative_rows.append({
            "item_id": str(item_id),
            "title": title,
            "content": item["content"],
            "star_level": item["star_level"],
            "crawl_time": now_str(),
        })

    return all_reviews, negative_rows


def extract_detail_row(page: ChromiumPage, item_id: str, title: str, shop_name: str, category: str) -> dict[str, Any]:
    open_comments_area(page)
    page_content = page.html
    details = extract_product_details_strict(page_content)
    return {
        "item_id": str(item_id),
        "title": title,
        "shop_name": shop_name,
        "category": category,
        "review_count": "",
        "好评率": details.get("好评率", ""),
        "评价标签": details.get("评价标签", ""),
        "产地": details.get("产地", ""),
        "保质期": details.get("保质期", ""),
        "配料表": details.get("配料表", ""),
        "规格": details.get("规格", ""),
        "crawl_time": now_str(),
    }


# 7. 数据保存
def append_and_save_csv(path: str | Path, rows: list[dict[str, Any]], columns: list[str], dedup_keys: list[str]) -> None:
    if not rows:
        return
    path = Path(path)
    ensure_dir(path.parent)
    new_df = pd.DataFrame(rows)
    for col in columns:
        if col not in new_df.columns:
            new_df[col] = ""
    new_df = new_df[columns]
    if path.exists() and path.stat().st_size:
        existing = pd.read_csv(path, dtype=str).fillna("")
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    combined = combined.drop_duplicates(subset=dedup_keys, keep="last")
    combined.to_csv(path, index=False, encoding="utf-8-sig")


def save_all_outputs(
    output_dir: str | Path,
    product_reviews: list[dict[str, Any]],
    product_details: list[dict[str, Any]],
    negative_reviews: list[dict[str, Any]],
) -> None:
    output_dir = Path(output_dir)
    append_and_save_csv(
        output_dir / PRODUCT_REVIEWS_FILE,
        product_reviews,
        ["item_id", "title", "nickname", "score", "date", "sku", "content", "like_count", "crawl_time"],
        ["item_id", "content", "date"],
    )
    append_and_save_csv(
        output_dir / PRODUCT_DETAILS_FILE,
        product_details,
        ["item_id", "title", "shop_name", "category", "review_count", "好评率", "评价标签", "产地", "保质期", "配料表", "规格", "crawl_time"],
        ["item_id"],
    )
    append_and_save_csv(
        output_dir / NEGATIVE_REVIEWS_FILE,
        negative_reviews,
        ["item_id", "title", "content", "star_level", "crawl_time"],
        ["item_id", "content"],
    )


def connect_to_chrome() -> ChromiumPage:
    """启动 Chrome — 极简参数，不触达 JD 反指纹检测。"""
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    co.set_user_data_path(str(CHROME_PROFILE_DIR.resolve()))
    # 只加必须的参数
    co.set_argument("--no-sandbox")
    co.set_local_port(9515)

    page = ChromiumPage(co)
    try:
        page.set.timeouts(page_load=15, script=10)
    except Exception:
        pass

    print(f"[BROWSER] Chrome 已启动，Profile: {CHROME_PROFILE_DIR}")
    return page


def empty_detail_row(item_id: str, title: str, shop_name: str, category: str, review_count: Any) -> dict[str, Any]:
    """生成空的详情行，当商品无法爬取时使用"""
    return {
        "item_id": item_id,
        "title": title,
        "shop_name": shop_name,
        "category": category,
        "review_count": review_count,
        "好评率": "",
        "评价标签": "",
        "产地": "",
        "保质期": "",
        "配料表": "",
        "规格": "",
        "crawl_time": now_str(),
    }


def crawl_one_product(page: ChromiumPage, item: list[Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    item_id, title, detail_url, review_count, shop_name, category = item
    item_id = str(item_id)
    title = str(title or "")
    detail_url = str(detail_url)
    print(f"\n[ITEM] 爬取商品 {item_id}: {title[:40]}")
    print(f"  URL: {detail_url}")

    try:
        goto_detail(page, detail_url)
        detail_row = extract_detail_row(page, item_id, title, str(shop_name or ""), str(category or ""))
        detail_row["review_count"] = review_count
        reviews, negative_rows = crawl_comments_pages(page, item_id, title)
        diag = diagnostic_review_state(page)
        status = "success"
        error = ""
        print(f"  [OK] 详情字段: 好评率={detail_row.get('好评率') or '-'} 标签长度={len(detail_row.get('评价标签', ''))}")
        print(
            f"  [OK] 评论={len(reviews)} 差评={len(negative_rows)} "
            f"cards={diag['comment_card_count']} selector={diag['comment_selector'] or '-'}"
        )
    except CaptchaTimeoutError as exc:
        handle_network_error(exc, context=f"商品 {item_id}")
        detail_row = empty_detail_row(item_id, title, str(shop_name or ""), str(category or ""), review_count)
        reviews = []
        negative_rows = []
        error = str(exc)
        status = "captcha_timeout"
        diag = {}
    except Exception as exc:
        print(f"[ERROR] 商品 {item_id} 异常: {type(exc).__name__}: {exc}")
        detail_row = empty_detail_row(item_id, title, str(shop_name or ""), str(category or ""), review_count)
        reviews = []
        negative_rows = []
        error = f"{type(exc).__name__}: {exc}"
        status = "access_blocked" if "403/访问受限" in error else "failed"
        diag = {}

    checkpoint_row = {
        "item_id": item_id,
        "title": title,
        "detail_url": detail_url,
        "status": status,
        "review_count": review_count,
        "reviews_count": len(reviews),
        "negative_reviews_count": len(negative_rows),
        "comment_card_count": diag.get("comment_card_count", ""),
        "comment_selector": diag.get("comment_selector", ""),
        "has_bad_filter_text": diag.get("has_bad_filter_text", ""),
        "has_good_rate_text": diag.get("has_good_rate_text", ""),
        "error": error[:500],
        "crawl_time": now_str(),
    }
    human_like_delay()
    return detail_row, reviews, negative_rows, checkpoint_row


# 8. 入口 main 函数
def main() -> None:
    ensure_dir(OUTPUT_DIR)
    ensure_dir(SCREENSHOT_DIR)

    ensure_single_run_per_day()  # 同一天不重复运行

    csv_path = resolve_csv_path()
    print(f"读取输入文件: {csv_path}")
    crawled_ids = load_checkpoint(CHECKPOINT_FILE)
    priority_pool = build_priority_pool(csv_path)
    remaining_pool = [item for item in priority_pool if not should_skip_item(item[0], crawled_ids)]
    targets = remaining_pool[:MAX_DAILY_PRODUCTS]
    targets = deduplicate_products(
        [
            {
                "item_id": item[0],
                "title": item[1],
                "detail_url": item[2],
                "review_count": item[3],
                "shop_name": item[4],
                "category_breadcrumb": item[5],
            }
            for item in targets
        ]
    )
    target_rows = [
        [item["item_id"], item["title"], item["detail_url"], item["review_count"], item["shop_name"], item["category_breadcrumb"]]
        for item in targets
    ]

    todo = [item for item in target_rows if not should_skip_item(item[0], crawled_ids)]
    covered_in_pool = len(priority_pool) - len(remaining_pool)
    print(
        f"优先池总数: {len(priority_pool)}，已覆盖: {covered_in_pool}，"
        f"本轮抽取: {len(target_rows)}，本次待爬: {len(todo)}"
    )

    if not todo:
        print("没有待爬商品。")
        return

    product_reviews_buffer: list[dict[str, Any]] = []
    product_details_buffer: list[dict[str, Any]] = []
    negative_reviews_buffer: list[dict[str, Any]] = []
    checkpoint_buffer: list[dict[str, Any]] = []

    page = connect_to_chrome()
    page.set.timeouts(page_load=10, script=5)
    print("[OK] Chrome 已启动")

    consecutive_blocked = 0
    captcha_count = 0
    max_captcha_daily = 20
    idle_streak = 0           # 连续无有效产出计数
    max_idle_streak = 6       # 连续 N 轮无效 → 自动停止
    try:
        for index, item in enumerate(todo, start=1):
            detail_row, reviews, negative_rows, checkpoint_row = crawl_one_product(page, item)
            status = checkpoint_row.get("status", "")

            if status == "captcha_timeout":
                save_checkpoint([checkpoint_row], OUTPUT_DIR)
                captcha_count += 1
                idle_streak += 1
                print(f"[CAPTCHA] 验证码超时，跳过该商品。当日累计验证码={captcha_count}/{max_captcha_daily}，连续无效={idle_streak}")
                if captcha_count >= max_captcha_daily:
                    print(f"[CAPTCHA] 当日验证码已达 {max_captcha_daily} 次，停止本轮爬取。")
                    break
                if idle_streak >= max_idle_streak:
                    print(f"[IDLE] 连续 {max_idle_streak} 轮无效，自动停止。")
                    break
                continue

            if status == "access_blocked":
                save_checkpoint([checkpoint_row], OUTPUT_DIR)
                consecutive_blocked += 1
                idle_streak += 1
                print(f"[BLOCKED] 京东返回 403/访问受限，跳过该商品。连续拦截={consecutive_blocked}，连续无效={idle_streak}")
                if consecutive_blocked >= 10:
                    print("[BLOCKED] 连续 3 个商品被拦截，本轮停止，避免触发更强风控。")
                    break
                if idle_streak >= max_idle_streak:
                    print(f"[IDLE] 连续 {max_idle_streak} 轮无效，自动停止。")
                    break
                continue

            if status == "failed":
                save_checkpoint([checkpoint_row], OUTPUT_DIR)
                consecutive_blocked = 0
                idle_streak += 1
                print(f"[FAILED] 商品 {checkpoint_row.get('item_id')} 抓取失败: {checkpoint_row.get('error', '')[:100]}")
                print(f"[FAILED] 已跳过错品，连续无效={idle_streak}")
                if idle_streak >= max_idle_streak:
                    print(f"[IDLE] 连续 {max_idle_streak} 轮无效，自动停止。")
                    break
                continue

            # success：重置无效计数（即使无评论，页面本身是正常的）
            idle_streak = 0
            consecutive_blocked = 0
            product_details_buffer.append(detail_row)
            product_reviews_buffer.extend(deduplicate_reviews(reviews))
            negative_reviews_buffer.extend(negative_rows)
            checkpoint_buffer.append(checkpoint_row)

            should_save_now = True
            if should_save_now:
                save_all_outputs(OUTPUT_DIR, product_reviews_buffer, product_details_buffer, negative_reviews_buffer)
                save_checkpoint(checkpoint_buffer, OUTPUT_DIR)
                product_reviews_buffer.clear()
                product_details_buffer.clear()
                negative_reviews_buffer.clear()
                checkpoint_buffer.clear()
                print(f"[OK] 已增量保存：{OUTPUT_DIR}")
    finally:
        save_all_outputs(OUTPUT_DIR, product_reviews_buffer, product_details_buffer, negative_reviews_buffer)
        save_checkpoint(checkpoint_buffer, OUTPUT_DIR)
        page.quit()
        print("[OK] 最终结果已保存")

    # 不自动关机，需人工确认
    from datetime import datetime
    now = datetime.now()
    print(f"\n[DONE] 当前时间 {now.strftime('%H:%M')}，本轮爬取完成。如需关机请手动操作。")


if __name__ == "__main__":
    main()
