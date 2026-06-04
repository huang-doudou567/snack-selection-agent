from __future__ import annotations

import atexit
import argparse
import json
import os
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import pandas as pd
from DrissionPage import ChromiumPage, ChromiumOptions


BASE_DIR = Path(__file__).resolve().parent
INPUT_CSV = BASE_DIR / "merged_products.csv"
OUTPUT_CSV = BASE_DIR / "price_history.csv"
CHECKPOINT_CSV = BASE_DIR / "crawled_price_items.csv"
RUN_STATE_FILE = BASE_DIR / "mmb_cdp_price_history_state.json"
SCREENSHOT_DIR = BASE_DIR / "mmb_screenshots"
ACTIVE_LOCK_FILE = BASE_DIR / "mmb_price_history_active.lock.json"
FALLBACK_PROFILE_DIR = BASE_DIR / ".mmb_playwright_profile"

HOME_URL = "https://www.manmanbuy.com"
HISTORY_URL = "http://tool.manmanbuy.com/HistoryLowest.aspx"

DEFAULT_LIMIT = 100
DEFAULT_DELAY_MIN = 15.0
DEFAULT_DELAY_MAX = 25.0
DEFAULT_BATCH_SIZE = 10
DEFAULT_BATCH_REST_MIN = 30.0
DEFAULT_BATCH_REST_MAX = 60.0
DEFAULT_TIMEOUT = 60
DEFAULT_SCROLL_MIN = 1.0
DEFAULT_SCROLL_MAX = 3.0
DEFAULT_POST_QUERY_MIN = 2.0
DEFAULT_POST_QUERY_MAX = 5.0
DEFAULT_LOCK_STALE_SECONDS = 3 * 60 * 60
# 爬取窗口: 23:00-06:00（风控最松，每日100条）
CRAWL_WINDOW_START_HOUR = 23
CRAWL_WINDOW_END_HOUR = 6

OUTPUT_COLUMNS = [
    "item_id", "title", "detail_url", "current_price", "lowest_price",
    "lowest_date", "highest_price", "price_trend", "query_time", "status", "error_msg",
]
CHECKPOINT_COLUMNS = ["item_id", "detail_url", "crawl_time"]

RISK_CONTROL_PATTERNS = [
    r"验证码", r"安全验证", r"滑块", r"访问异常", r"请求过于频繁",
    r"操作频繁", r"风控", r"异常访问", r"微信登录", r"扫码登录",
    r"二维码已过期", r"请点击刷新", r"verify", r"captcha", r"validate",
]

BLOCKED_PATTERNS = [
    r"\b402\b", r"\b403\b", r"access[_\s-]?blocked",
    r"access[_\s-]?denied", r"访问受限", r"访问异常", r"风控", r"风险控制",
]

NO_RESULT_PATTERNS = [
    r"暂无", r"没有找到", r"未找到", r"无结果", r"未收录",
    r"请输入正确", r"请填写",
]


class VerificationRequired(RuntimeError):
    pass


def current_limit_window(now_dt: datetime | None = None) -> tuple[str, datetime, datetime]:
    now_dt = now_dt or datetime.now()
    # 跨夜窗口: 23:00-06:00
    if now_dt.hour >= CRAWL_WINDOW_START_HOUR or now_dt.hour < CRAWL_WINDOW_END_HOUR:
        if now_dt.hour >= CRAWL_WINDOW_START_HOUR:
            start = now_dt.replace(hour=CRAWL_WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
        else:
            start = (now_dt - timedelta(days=1)).replace(hour=CRAWL_WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=7)
        return "night_window", start, end
    start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return "calendar_day", start, end


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_item_id(value: Any, detail_url: str = "") -> str:
    text = clean_text(value)
    if text and text.lower() not in {"nan", "none"}:
        try:
            if re.fullmatch(r"\d+(?:\.0+)?", text):
                return str(int(float(text)))
        except ValueError:
            pass
        return text
    match = re.search(r"item\.jd\.com/(\d+)\.html", detail_url)
    return match.group(1) if match else ""


def resolve_column(df: pd.DataFrame, aliases: list[str], required: bool = True) -> str:
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for alias in aliases:
        if alias.lower() in lower_map:
            return lower_map[alias.lower()]
    if required:
        raise KeyError(f"缺少必要字段，候选列名: {aliases}，实际列名: {df.columns.tolist()}")
    return ""


def load_checkpoint(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return set()
    if "item_id" not in df.columns:
        return set()
    return set(df["item_id"].astype(str).str.strip())


def count_rows_today(path: Path, today_prefix: str) -> int:
    if not path.exists():
        return 0
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return 0
    if "query_time" not in df.columns:
        return 0
    return int(df["query_time"].astype(str).str.startswith(today_prefix).sum())


def count_rows_in_window(path: Path, column: str, start: datetime, end: datetime) -> int:
    if not path.exists():
        return 0
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return 0
    if column not in df.columns:
        return 0
    stamps = pd.to_datetime(df[column].astype(str).str.strip(), errors="coerce")
    return int(((stamps >= start) & (stamps < end)).sum())


def describe_limit_window(now_dt: datetime | None = None) -> str:
    scope, start, end = current_limit_window(now_dt)
    return f"{scope} {start.strftime('%Y-%m-%d %H:%M:%S')} -> {end.strftime('%Y-%m-%d %H:%M:%S')}"


def _pid_is_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def load_active_lock(lock_path: Path = ACTIVE_LOCK_FILE) -> dict[str, Any]:
    if not lock_path.exists():
        return {}
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def acquire_active_lock(script_name: str, lock_path: Path = ACTIVE_LOCK_FILE, stale_seconds: int = DEFAULT_LOCK_STALE_SECONDS) -> None:
    current = load_active_lock(lock_path)
    if current:
        heartbeat_at = pd.to_datetime(str(current.get("heartbeat_at", "")), errors="coerce")
        heartbeat_age = None
        if pd.notna(heartbeat_at):
            heartbeat_age = (datetime.now() - heartbeat_at.to_pydatetime()).total_seconds()
        if _pid_is_alive(int(current.get("pid", 0) or 0)) and (heartbeat_age is None or heartbeat_age < stale_seconds):
            raise RuntimeError(
                f"Another price-history crawler is already active: {current.get('script_name', 'unknown')} "
                f"(pid={current.get('pid')}, heartbeat_at={current.get('heartbeat_at')})"
            )
    update_active_lock(script_name=script_name, lock_path=lock_path)
    atexit.register(release_active_lock, lock_path)


def update_active_lock(script_name: str, lock_path: Path = ACTIVE_LOCK_FILE) -> None:
    payload = {
        "script_name": script_name,
        "pid": os.getpid(),
        "started_at": load_active_lock(lock_path).get("started_at") or datetime.now().isoformat(timespec="seconds"),
        "heartbeat_at": datetime.now().isoformat(timespec="seconds"),
    }
    lock_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def release_active_lock(lock_path: Path = ACTIVE_LOCK_FILE) -> None:
    try:
        if lock_path.exists():
            current = load_active_lock(lock_path)
            if not current or int(current.get("pid", 0) or 0) == os.getpid():
                lock_path.unlink()
    except Exception:
        pass


def build_targets(input_csv: Path, checkpoint_csv: Path, limit: int | None) -> list[dict[str, str]]:
    df = pd.read_csv(input_csv, dtype=str).fillna("")
    item_col = resolve_column(df, ["item_id", "product_id", "SKU", "sku"], required=False)
    title_col = resolve_column(df, ["title", "product_title", "商品标题", "name"], required=False)
    url_col = resolve_column(df, ["detail_url", "url", "商品链接"], required=True)
    crawled = load_checkpoint(checkpoint_csv)

    targets: list[dict[str, str]] = []
    seen: set[str] = set()
    effective_limit = min(limit, DEFAULT_LIMIT) if limit is not None else DEFAULT_LIMIT

    for _, row in df.iterrows():
        detail_url = clean_text(row.get(url_col, ""))
        if "item.jd.com" not in detail_url:
            continue
        item_id = normalize_item_id(row.get(item_col, ""), detail_url) if item_col else normalize_item_id("", detail_url)
        if not item_id or item_id in crawled or item_id in seen:
            continue
        seen.add(item_id)
        targets.append({"item_id": item_id, "title": clean_text(row.get(title_col, "")) if title_col else "", "detail_url": detail_url})
        if effective_limit and len(targets) >= effective_limit:
            break
    return targets


def append_rows(path: Path, rows: list[dict[str, Any]], columns: list[str], dedup_key: str) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame(rows)
    for column in columns:
        if column not in new_df.columns:
            new_df[column] = ""
    new_df = new_df[columns]
    if path.exists():
        try:
            old_df = pd.read_csv(path, dtype=str).fillna("")
        except Exception:
            old_df = pd.DataFrame(columns=columns)
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df
    if dedup_key in combined.columns:
        combined[dedup_key] = combined[dedup_key].astype(str)
        combined = combined.drop_duplicates(subset=[dedup_key], keep="last")
    combined.to_csv(path, index=False, encoding="utf-8-sig")


def connect_browser_page():
    """启动独立托管 Chrome（DrissionPage auto-port，自动管理浏览器生命周期）。"""
    FALLBACK_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    co.set_user_data_path(str(FALLBACK_PROFILE_DIR.resolve()))
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-software-rasterizer")
    co.set_argument("--accept-lang=zh-CN,zh;q=0.9,en;q=0.8")
    co.set_local_port(9517)

    page = ChromiumPage(co)
    # 全局超时，防止任何操作无限挂起
    try:
        page.set.timeouts(page_load=15, script=10)
    except Exception:
        pass
    print(f"[BROWSER] 启动独立 Chrome，Profile: {FALLBACK_PROFILE_DIR}")
    return page


def load_run_state() -> dict[str, Any]:
    if not RUN_STATE_FILE.exists():
        return {}
    try:
        return json.loads(RUN_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def mark_run_started() -> None:
    state = {
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    RUN_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_single_run_per_day() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    state = load_run_state()
    if state.get("run_date") == today:
        raise RuntimeError(
            f"mmb_cdp_price_history_crawler.py already ran today ({today}); wait until tomorrow."
        )
    mark_run_started()


def human_delay(min_sec: float, max_sec: float) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def simulate_scroll(page: ChromiumPage, min_seconds: float = DEFAULT_SCROLL_MIN, max_seconds: float = DEFAULT_SCROLL_MAX) -> None:
    deadline = time.time() + random.uniform(min_seconds, max_seconds)
    while time.time() < deadline:
        page.run_js(f"window.scrollBy(0, {random.randint(350, 900)})")
        time.sleep(random.uniform(0.25, 0.65))


def safe_body_text(page: ChromiumPage) -> str:
    """Get body text via run_js — avoids DrissionPage element.text bug with JS-rendered pages."""
    try:
        text = page.run_js("return document.body ? document.body.innerText : ''")
        return text if text else ""
    except Exception:
        return ""


def _plain_substring_indicator(pattern: str) -> str:
    r"""将正则表达式中的元字符（\b、\s、\d 等）去除，保留纯文本子串用于 is_verification_page"""
    plain = re.sub(r"\\[bB]|\\[sS]|\\[dDwW]", "", pattern)
    plain = re.sub(r"\[\^[^\]]*\]", "", plain)  # 去除否定字符类如 [^。;\n]
    plain = re.sub(r"\[\d{1,2},\d{0,2}\]", "", plain)  # 去除量词如 {1,40}、{,20}
    plain = plain.replace("(", "").replace(")", "").replace("|", "").replace("[", "").replace("]", "")
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain


def is_verification_page(page: ChromiumPage) -> bool:
    text = safe_body_text(page)
    url = page.url
    combined = f"{url}\n{text}".lower()
    # 纯文本子串指标（不含正则元字符）
    plain_indicators = [
        "验证码", "安全验证", "滑块", "访问频繁", "异常访问", "请求过于频繁",
        "请完成验证", "微信登录", "扫码登录", "二维码已过期", "请点击刷新",
        "captcha", "verify", "validate", "风控",
    ]
    for p in RISK_CONTROL_PATTERNS:
        plain = _plain_substring_indicator(p)
        if plain:
            plain_indicators.append(plain.lower())
    return any(ind in combined for ind in plain_indicators)


def first_visible(page: ChromiumPage, selectors: list[str]):
    for sel in selectors:
        try:
            el = page.ele(sel, timeout=1)
            if el and el.states.is_displayed:
                return el
        except Exception:
            continue
    return None


def wait_page_ready(page: ChromiumPage, seconds: int = 10) -> None:
    """Wait for JS-rendered page to be fully ready. MMB pages need ~8-10s for React hydration."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        text = safe_body_text(page)
        if text and len(text) > 100:  # Page has rendered meaningful content
            return
        time.sleep(1)
    # Even if text still empty, we've waited long enough — caller will handle


def goto_history_page(page: ChromiumPage) -> None:
    page.get(HOME_URL)
    wait_page_ready(page, 10)
    if is_verification_page(page):
        raise VerificationRequired("慢慢买首页出现验证码或异常页面")

    clicked = False
    for text in ["查历史价", "历史价", "历史价格"]:
        try:
            el = page.ele(f"text:{text}", timeout=2)
            if el and el.states.is_displayed:
                el.click()
                clicked = True
                break
        except Exception:
            continue

    if clicked:
        time.sleep(3)
        wait_page_ready(page, 6)

    if not find_query_input(page):
        page.get(HISTORY_URL)
        wait_page_ready(page, 10)

    if is_verification_page(page):
        raise VerificationRequired("慢慢买历史价页面出现验证码或异常页面")


def find_query_input(page: ChromiumPage):
    selectors = [
        "#historykey", "input[name='historykey']", "input[id*='history']",
        "input[placeholder*='链接']", "input[placeholder*='商品']",
        "input[placeholder*='地址']", "input[type='search']", "input[type='text']",
    ]
    return first_visible(page, selectors)


def click_query_button(page: ChromiumPage) -> None:
    if is_verification_page(page):
        raise VerificationRequired("查询按钮被登录/验证弹窗遮挡")

    def js_click(el) -> bool:
        try:
            page.run_js(
                """(el) => {
                    if (typeof window.doSearch === 'function') {
                        window.doSearch();
                        return true;
                    }
                    el.click();
                    return true;
                }""",
                el,
            )
            return True
        except Exception:
            return False

    text_candidates = ["商品历史价格查询", "查询历史价格", "历史价格查询", "查历史价", "查询"]
    for text in text_candidates:
        try:
            el = page.ele(f"text:{text}", timeout=3)
            if el and el.states.is_displayed:
                try:
                    el.click()
                    return
                except Exception:
                    if js_click(el):
                        return
        except Exception:
            continue

    selectors = [
        "#searchHistory", "#btnSearch",
        "form[action*='HistoryLowest'] button[type='submit']",
        "form[action*='HistoryLowest'] input[type='submit']",
        "form[action*='HistoryLowest'] [class*='search'][class*='btn']",
        "button[type='submit']", "input[type='button'][value*='查询']",
        "input[type='submit']", ".search-btn", "[class*='search'][class*='btn']",
    ]
    el = first_visible(page, selectors)
    if el:
        try:
            el.click()
        except Exception:
            if not js_click(el):
                raise
        return
    raise RuntimeError('未找到"商品历史价格查询"按钮')


# 确认包含真正的搜索结果内容（而非仅页面导航模板文字）
RESULT_TEXT_MARKERS = [
    r"25\s*个?月\s*历史\s*最低",  # "25个月历史最低"（最可靠的结果标志）
    r"60\s*天\s*均价",
    r"\d+天\s*均\s*价",
    r"历史最低价",
    r"到手价",
    r"价格走势图",
    r"趋势图",
    r"当前价",
    r"历史价格趋势",
]

RESULT_HTML_MARKERS = [
    "container",     # echarts container div
    "discount-wrap",
    "discountList",
    "historyprice",
]


def wait_for_result(page: ChromiumPage, timeout_sec: int) -> str:
    deadline = time.time() + timeout_sec
    # Wait at least 3s before first check — search response takes time
    time.sleep(3)
    while time.time() < deadline:
        if is_verification_page(page):
            raise VerificationRequired("查询过程中出现验证码或异常页面")
        text = safe_body_text(page)
        # Only proceed if we actually got text (page has rendered)
        if not text or len(text) < 20:
            time.sleep(1.5)
            continue
        if any(re.search(p, text, flags=re.IGNORECASE) for p in RISK_CONTROL_PATTERNS):
            raise VerificationRequired("检测到验证码或风险控制提示")
        # Check for REAL result markers (not just nav text)
        for marker in RESULT_TEXT_MARKERS:
            if re.search(marker, text):
                return text
        if any(re.search(p, text, flags=re.IGNORECASE) for p in NO_RESULT_PATTERNS):
            return text
        # Also check HTML for result containers (echarts chart loaded)
        for html_marker in RESULT_HTML_MARKERS:
            try:
                if page.run_js(f"return !!document.getElementById('{html_marker}')"):
                    # Chart container exists — check if echarts has rendered data
                    has_chart = page.run_js(
                        "try { const c=document.getElementById('container'); "
                        "return !!(c && echarts && echarts.getInstanceByDom(c)); } catch(e) { return false; }"
                    )
                    if has_chart:
                        return text
            except Exception:
                continue
        time.sleep(1.5)
    raise TimeoutError(f"等待结果区域超时 {timeout_sec} 秒")


def parse_price(text: str) -> str:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*元?", text)
    return match.group(1) if match else ""


def parse_lowest_25m(text: str) -> tuple[str, str]:
    lines = [clean_text(x) for x in text.splitlines() if clean_text(x)]
    for idx, line in enumerate(lines):
        if re.search(r"25\s*个?月\s*历史\s*最低", line):
            block = " ".join(lines[idx : idx + 4])
            price_match = re.search(
                r"25\s*个?月\s*历史\s*最低(?:价)?[：:\s]*¥?\s*([0-9]+(?:\.[0-9]+)?)\s*元?",
                block,
            )
            price = price_match.group(1) if price_match else parse_price(block)
            date_match = re.search(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})日?", block)
            date = ""
            if date_match:
                date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
            return price, date
    return "", ""


def parse_avg_60d(text: str) -> str:
    match = re.search(r"60\s*天\s*均价[：:\s]*¥?\s*([0-9]+(?:\.[0-9]+)?)\s*元?", text)
    return match.group(1) if match else ""


def extract_coupon(block: str) -> str:
    for pattern in [
        r"优惠券[：:\s]*([^，。;\n]{1,40})",
        r"(满\s*\d+[^，。;\n]{0,20})",
        r"(每满\s*\d+[^，。;\n]{0,20})",
        r"(券后[^，。;\n]{0,30})",
        r"([0-9]+元券)",
        r"([0-9]+折)",
        r"(立减[^，。;\n]{0,30})",
    ]:
        match = re.search(pattern, block)
        if match:
            return clean_text(match.group(1))
    return ""


def extract_page_price(block: str) -> str:
    match = re.search(
        r"(?:页面价|网页价|网页价格|原价|京东价|当前价)[：:\s]*[¥￥]?\s*([0-9]+(?:\.[0-9]+)?)",
        block,
    )
    return match.group(1) if match else ""


def parse_price_detail(text: str) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    normalized = "\n".join(clean_text(x) for x in text.splitlines() if clean_text(x))
    normalized = re.sub(r"\n{2,}", "\n", normalized)

    date_pattern = re.compile(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})日?")
    date_matches = list(date_pattern.finditer(normalized))
    for pos, date_match in enumerate(date_matches):
        date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        end = date_matches[pos + 1].start() if pos + 1 < len(date_matches) else min(len(normalized), date_match.end() + 260)
        block = normalized[date_match.start():end]

        final_match = re.search(r"(?:到手价|到手)[：:\s]*[¥￥]?\s*([0-9]+(?:\.[0-9]+)?)", block)
        page_price = extract_page_price(block)
        if final_match:
            final_price = final_match.group(1)
        else:
            prices = re.findall(r"[¥￥]\s*([0-9]+(?:\.[0-9]+)?)|([0-9]+(?:\.[0-9]+)?)\s*元", block)
            prices = [a or b for a, b in prices]
            final_price = prices[0] if prices else ""

        coupon = extract_coupon(block)
        if not final_price:
            continue
        key = (date, final_price, page_price, coupon)
        if key in seen:
            continue
        seen.add(key)
        details.append({
            "date": date,
            "final_price": float(final_price) if final_price else None,
            "page_price": float(page_price) if page_price else None,
            "coupon": coupon,
        })
        if len(details) >= 120:
            break
    return details


def parse_chart_price_rows(rows: Any) -> list[list[Any]]:
    details: list[list[Any]] = []
    seen: set[tuple[int, float, str]] = set()
    if not isinstance(rows, list):
        return details
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        try:
            timestamp = int(float(row[0]))
            final_price = float(row[1])
        except (TypeError, ValueError):
            continue
        promo = clean_text(row[2]) if len(row) > 2 else ""
        if not timestamp or final_price <= 0:
            continue
        key = (timestamp, final_price, promo)
        if key in seen:
            continue
        seen.add(key)
        details.append([timestamp, final_price, promo])
    details.sort(key=lambda x: x[0])
    return details


def extract_chart_price_detail(page: ChromiumPage) -> list[list[Any]]:
    try:
        rows = page.run_js(
            r"""
() => {
  const out = [];
  const pushRows = rows => {
    if (!Array.isArray(rows)) return;
    rows.forEach(row => {
      if (Array.isArray(row) && row.length >= 2) {
        out.push([row[0], row[1], row[2] || '']);
      }
    });
  };
  const el = document.getElementById('container');
  const inst = window.echarts && el ? window.echarts.getInstanceByDom(el) : null;
  if (inst) {
    const opt = inst.getOption();
    (opt.series || []).forEach(series => pushRows(series.data));
  }
  for (const key of Object.keys(window)) {
    if (/datePrice|priceData|historyPrice|trend/i.test(key)) {
      try {
        const value = window[key];
        if (Array.isArray(value)) {
          pushRows(value);
        } else if (value && typeof value === 'object') {
          for (const innerKey of ['datePrice', 'priceData', 'historyPrice', 'trend', 'data']) {
            try { pushRows(value[innerKey]); } catch (e) {}
          }
        }
      } catch (e) {}
    }
  }
  return out;
}
"""
        )
    except Exception:
        rows = []
    return parse_chart_price_rows(rows)


def wait_for_chart_price_detail(page: ChromiumPage, timeout_sec: int = 15) -> list[list[Any]]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        details = extract_chart_price_detail(page)
        if details:
            return details
        time.sleep(1.0)
    return []


def scroll_price_detail_widget(page: ChromiumPage) -> str:
    try:
        return page.run_js(
            r"""
async () => {
  const candidates = [
    document.querySelector('.discount-wrap'),
    document.querySelector('#discountList'),
    ...Array.from(document.querySelectorAll('div,ul')).filter(el => {
      const text = (el.innerText || '').trim();
      const style = getComputedStyle(el);
      return text.includes('到手价') &&
             (style.overflowY === 'scroll' || style.overflowY === 'auto' || el.scrollHeight > el.clientHeight + 20);
    })
  ].filter(Boolean);
  const wrap = candidates[0];
  if (!wrap) return '';
  wrap.scrollIntoView({block: 'center', inline: 'nearest'});
  const seen = new Set();
  const out = [];
  const collect = () => {
    const nodes = wrap.querySelectorAll('li');
    const source = nodes.length ? Array.from(nodes) : [wrap];
    source.forEach(node => {
      const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
      if (text && !seen.has(text)) {
        seen.add(text);
        out.push(text);
      }
    });
  };
  collect();
  const maxTop = Math.max(0, wrap.scrollHeight - wrap.clientHeight);
  const steps = Math.max(4, Math.min(12, Math.ceil(wrap.scrollHeight / Math.max(wrap.clientHeight, 1)) + 2));
  for (let i = 0; i < steps; i++) {
    wrap.scrollTop = Math.round(maxTop * i / Math.max(steps - 1, 1));
    wrap.dispatchEvent(new Event('scroll', {bubbles: true}));
    await new Promise(resolve => setTimeout(resolve, 450));
    collect();
  }
  wrap.scrollTop = 0;
  return out.join('\n');
}
"""
        )
    except Exception:
        return ""


def convert_detail_to_trend(details: list[dict[str, Any]]) -> list[list[Any]]:
    trend: list[list[Any]] = []
    for item in details:
        try:
            timestamp = int(datetime.strptime(str(item.get("date")), "%Y-%m-%d").timestamp() * 1000)
            price = float(item.get("final_price"))
        except (TypeError, ValueError):
            continue
        promo = clean_text(item.get("coupon", ""))
        if item.get("page_price") is not None:
            promo = clean_text(f"页面价 {item.get('page_price')} {promo}")
        trend.append([timestamp, price, promo])
    trend.sort(key=lambda x: x[0])
    return trend


def extract_result(text: str, chart_details: list[list[Any]] | None = None) -> dict[str, Any]:
    lowest_price, lowest_date = parse_lowest_25m(text)
    avg_price = parse_avg_60d(text)
    details = parse_price_detail(text)
    trend = chart_details or []
    if not trend and details:
        trend = convert_detail_to_trend(details)

    trend_prices = [float(row[1]) for row in trend if isinstance(row, list) and len(row) >= 2]
    current_price: Any = trend_prices[-1] if trend_prices else (float(avg_price) if avg_price else "")
    highest_candidates = list(trend_prices)
    for value in [current_price, lowest_price, avg_price]:
        try:
            if value != "":
                highest_candidates.append(float(value))
        except (TypeError, ValueError):
            continue
    highest_price: Any = max(highest_candidates) if highest_candidates else ""

    has_signal = bool(lowest_price or avg_price or trend)
    no_result = any(re.search(p, text, flags=re.IGNORECASE) for p in NO_RESULT_PATTERNS)
    if has_signal:
        status = "success"
        error_msg = ""
    elif no_result:
        status = "no_result"
        error_msg = "未解析到商品历史价格结果"
    else:
        status = "error"
        error_msg = "未解析到完整历史价格结果"

    return {
        "current_price": current_price,
        "lowest_price": lowest_price,
        "lowest_date": lowest_date,
        "highest_price": highest_price,
        "price_trend": json.dumps(trend, ensure_ascii=False, separators=(",", ":")),
        "status": status,
        "error_msg": error_msg,
    }


def query_one(page: ChromiumPage, target: dict[str, str], timeout_sec: int) -> dict[str, Any]:
    """查询单个商品历史价格，失败时自动重试一次"""
    last_exc = None
    for attempt in range(2):
        try:
            return _query_one_attempt(page, target, timeout_sec)
        except (VerificationRequired, RuntimeError) as exc:
            # 验证码和致命错误不重试，直接抛
            raise
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                print(f"  [RETRY] 第1次查询失败 ({type(exc).__name__})，3秒后重试...")
                time.sleep(3)
                # 刷新页面状态 — 需要等页面 JS 重新渲染
                try:
                    page.get(HOME_URL)
                    wait_page_ready(page, 10)
                except Exception:
                    pass
    # 两次都失败
    raise last_exc  # type: ignore[misc]


def _query_one_attempt(page: ChromiumPage, target: dict[str, str], timeout_sec: int) -> dict[str, Any]:
    """直接通过 URL 参数查询，跳过页面交互避免挂起。"""
    detail_url = target["detail_url"]

    # 直接构造查询 URL: HistoryLowest.aspx?url=JD_ITEM_URL
    import urllib.parse
    encoded_url = urllib.parse.quote(detail_url, safe='')
    query_url = f"{HISTORY_URL}?url={encoded_url}"

    print(f"  查询 URL: {query_url[:100]}...")
    try:
        page.get(query_url, timeout=15)
    except Exception as e:
        raise RuntimeError(f"查询页面加载失败: {e}") from e

    # 等待结果渲染
    time.sleep(5)
    wait_page_ready(page, 10)

    text = wait_for_result(page, timeout_sec)
    if not text or len(text) < 50:
        raise RuntimeError(f"查询结果为空或过短")
    time.sleep(random.uniform(1.0, 2.0))

    # 跳过 scroll 和 chart（可能挂起），直接从页面文本提取
    widget_text = ""
    chart_details = []

    merged_text = "\n".join(x for x in [safe_body_text(page) or text, widget_text] if x)
    parsed = extract_result(merged_text, chart_details=chart_details)

    return {
        "item_id": target["item_id"],
        "title": target["title"],
        "detail_url": target["detail_url"],
        "current_price": parsed["current_price"],
        "lowest_price": parsed["lowest_price"],
        "lowest_date": parsed["lowest_date"],
        "highest_price": parsed["highest_price"],
        "price_trend": parsed["price_trend"],
        "query_time": now_str(),
        "status": parsed["status"],
        "error_msg": parsed["error_msg"],
    }


def error_row(target: dict[str, str], exc: Exception) -> dict[str, Any]:
    return {
        "item_id": target["item_id"],
        "title": target["title"],
        "detail_url": target["detail_url"],
        "current_price": "",
        "lowest_price": "",
        "lowest_date": "",
        "highest_price": "",
        "price_trend": "[]",
        "query_time": now_str(),
        "status": "error",
        "error_msg": f"{type(exc).__name__}: {exc}"[:500],
    }


def checkpoint_row(target: dict[str, str]) -> dict[str, str]:
    return {"item_id": target["item_id"], "detail_url": target["detail_url"], "crawl_time": now_str()}


def save_screenshot(page: ChromiumPage, prefix: str) -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.get_screenshot(str(path), full_page=False)
        print(f"[SCREENSHOT] 已保存截图: {path} ({path.stat().st_size} bytes)")
    except Exception as exc:
        # 截图失败不阻塞，直接跳过
        pass
    return path


def run(args: argparse.Namespace) -> None:
    acquire_active_lock("mmb_cdp_price_history_crawler.py")

    targets = build_targets(args.input, args.checkpoint, args.limit)
    print(f"输入文件: {args.input}")
    print(f"断点已爬: {len(load_checkpoint(args.checkpoint))}")
    print(f"本次待查: {len(targets)}")
    if not targets:
        return

    ensure_single_run_per_day()

    output_buffer: list[dict[str, Any]] = []
    checkpoint_buffer: list[dict[str, str]] = []

    page = connect_browser_page()

    idle_streak = 0           # 连续无有效产出计数
    max_idle_streak = 10      # 连续 N 轮无有效产出 → 自动停止（网络波动时更宽容）
    try:
        for idx, target in enumerate(targets, start=1):
            update_active_lock("mmb_cdp_price_history_crawler.py")
            print(f"\n[{idx}/{len(targets)}] {target['item_id']} {target['title'][:50]}")
            print(f"URL: {target['detail_url']}")
            try:
                row = query_one(page, target, args.timeout)
                print(
                    f"[{row['status']}] current={row['current_price'] or '-'} "
                    f"lowest={row['lowest_price'] or '-'} date={row['lowest_date'] or '-'}"
                )
            except VerificationRequired as exc:
                row = error_row(target, exc)
                shot = save_screenshot(page, "verification")
                row["error_msg"] = f"{row['error_msg']} | screenshot={shot}"
                output_buffer.append(row)
                append_rows(args.output, output_buffer, OUTPUT_COLUMNS, "item_id")
                output_buffer.clear()
                print(f"[STOP] 检测到验证码/异常页面，已截图: {shot}")
                print("请在浏览器中手动处理后，再重新运行脚本；error 不入断点。")
                break
            except Exception as exc:
                row = error_row(target, exc)
                shot = save_screenshot(page, "error")
                row["error_msg"] = f"{row['error_msg']} | screenshot={shot}"
                print(f"[error] {row['error_msg']}")

            # 跟踪有效产出：no_result 是正常结果（商品未被收录），只有 error 算无效
            if row["status"] in {"success", "no_result"}:
                idle_streak = 0
            else:
                idle_streak += 1
                print(f"  [IDLE] 无有效产出 (状态={row['status']})，连续无效={idle_streak}/{max_idle_streak}")

            output_buffer.append(row)
            if row["status"] in {"success", "no_result"}:
                checkpoint_buffer.append(checkpoint_row(target))

            if idx % args.save_every == 0:
                append_rows(args.output, output_buffer, OUTPUT_COLUMNS, "item_id")
                append_rows(args.checkpoint, checkpoint_buffer, CHECKPOINT_COLUMNS, "item_id")
                output_buffer.clear()
                checkpoint_buffer.clear()
                print(f"[SAVE] 已保存到 {args.output}")
                if idx < len(targets):
                    print(f"[REST] 已处理 {idx} 条，休息 {args.batch_rest_min:.0f}-{args.batch_rest_max:.0f} 秒")
                    update_active_lock("mmb_cdp_price_history_crawler.py")
                    human_delay(args.batch_rest_min, args.batch_rest_max)

            if idx < len(targets) and idx % args.save_every != 0:
                human_delay(args.delay_min, args.delay_max)

            if idle_streak >= max_idle_streak:
                print(f"[IDLE] 连续 {max_idle_streak} 轮无有效产出，自动停止。")
                break
    finally:
        append_rows(args.output, output_buffer, OUTPUT_COLUMNS, "item_id")
        append_rows(args.checkpoint, checkpoint_buffer, CHECKPOINT_COLUMNS, "item_id")
        page.quit()

    print("\n完成。")

    # 不自动关机，需人工确认
    from datetime import datetime
    now = datetime.now()
    print(f"\n[DONE] 当前时间 {now.strftime('%H:%M')}，本轮爬取完成。如需关机请手动操作。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="慢慢买历史价格查询（DrissionPage 自动浏览器模式）")
    parser.add_argument("--input", type=Path, default=INPUT_CSV, help="输入 merged_products.csv")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV, help="输出 price_history.csv")
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT_CSV, help="断点 crawled_price_items.csv")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="本次最多处理条数，默认 100 且硬上限 100")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="结果加载超时时间（秒）")
    parser.add_argument("--delay-min", type=float, default=DEFAULT_DELAY_MIN, help="查询间隔下限（秒）")
    parser.add_argument("--delay-max", type=float, default=DEFAULT_DELAY_MAX, help="查询间隔上限（秒）")
    parser.add_argument("--batch-rest-min", type=float, default=DEFAULT_BATCH_REST_MIN, help="每 10 条后的最短休息秒数")
    parser.add_argument("--batch-rest-max", type=float, default=DEFAULT_BATCH_REST_MAX, help="每 10 条后的最长休息秒数")
    parser.add_argument("--save-every", type=int, default=DEFAULT_BATCH_SIZE, help="每隔多少条落盘一次")
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
