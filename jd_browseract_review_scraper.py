# -*- coding: utf-8 -*-
"""Batch crawl JD product details and reviews with BrowserAct CLI.

Input:
    ./数据/merged_products.csv

Outputs:
    ./数据/京东评论爬取/product_reviews_YYYYMMDD.csv
    ./数据/京东评论爬取/product_details_YYYYMMDD.csv
    ./数据/京东评论爬取/negative_reviews_YYYYMMDD.csv
    ./数据/京东评论爬取/crawled_items.csv

Smoke test:
    python jd_browseract_review_scraper.py --smoke-one

Normal run:
    python jd_browseract_review_scraper.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "数据" / "merged_products.csv"
ROOT_INPUT_FALLBACK = BASE_DIR / "merged_products.csv"
DEFAULT_OUTPUT_DIR = BASE_DIR / "数据" / "京东评论爬取"

DEFAULT_BROWSER_ID = "jd-scraper"
DEFAULT_BROWSERACT_BIN = "browser-act"
DEFAULT_MAX_PRODUCTS = 80
DEFAULT_MAX_REVIEW_PAGES = 5
DEFAULT_SAVE_EVERY = 10

STEALTH_SLEEP_RANGE = (5.0, 10.0)
INTERACTIVE_SLEEP_RANGE = (8.0, 15.0)
SCROLL_SLEEP_RANGE = (1.5, 2.5)

PRODUCT_REVIEW_COLUMNS = [
    "item_id",
    "score",
    "date",
    "content",
    "like_count",
    "crawl_time",
]

PRODUCT_DETAIL_COLUMNS = [
    "item_id",
    "title",
    "shop_name",
    "category",
    "review_count",
    "好评率",
    "评价标签",
    "产地",
    "保质期",
    "配料表",
    "规格",
    "crawl_time",
]

NEGATIVE_REVIEW_COLUMNS = [
    "item_id",
    "score",
    "content",
    "date",
    "crawl_time",
]

CRAWLED_COLUMNS = [
    "item_id",
    "title",
    "crawl_time",
]

FAILURE_COLUMNS = [
    "item_id",
    "stage",
    "reason",
    "crawl_time",
]

BROWSERACT_BIN = DEFAULT_BROWSERACT_BIN
BROWSERACT_BROWSER_LIST_CACHE: str | None = None
KEEP_SESSION_ON_CAPTCHA = False


FIELD_ALIASES = {
    "item_id": ["item_id", "product_id", "sku_id", "sku", "商品ID", "商品编号"],
    "title": ["title", "product_title", "name", "商品标题", "标题"],
    "detail_url": ["detail_url", "url", "product_url", "详情页链接", "链接"],
    "review_count": ["review_count", "comment_count", "comments", "评论数", "评价数"],
    "shop_name": ["shop_name", "shop", "店铺", "店铺名"],
    "category_breadcrumb": ["category_breadcrumb", "category_path", "category", "品类", "类目"],
    "price": ["price", "current_price", "sale_price", "价格", "当前价格"],
    "rank_position": ["rank_position", "rank", "ranking", "排名", "榜单排名"],
}

CAPTCHA_PATTERNS = [
    "验证码",
    "安全验证",
    "拖动滑块",
    "完成验证",
    "验证后继续",
    "captcha",
    "verify",
    "verification",
]

COMMENT_HINTS = [
    "商品评价",
    "累计评价",
    "评价",
    "评论",
    "晒单",
    "追评",
]

NEXT_PAGE_HINTS = [
    "下一页",
    "下页",
    "next",
    "Next",
    ">",
]

COMMENT_API_HINTS = [
    "comment",
    "productPageComments",
    "sclub.jd.com",
]


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int | None


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_suffix() -> str:
    return datetime.now().strftime("%Y%m%d")


def log(message: str) -> None:
    print(f"[{now_str()}] {message}", flush=True)


def sleep_random(bounds: tuple[float, float], reason: str = "") -> None:
    delay = random.uniform(*bounds)
    if reason:
        log(f"等待 {delay:.1f}s：{reason}")
    time.sleep(delay)


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def pick_column(df: pd.DataFrame, logical_name: str) -> str | None:
    existing = {str(col).strip(): col for col in df.columns}
    for candidate in FIELD_ALIASES[logical_name]:
        if candidate in existing:
            return existing[candidate]
    lowered = {str(col).strip().lower(): col for col in df.columns}
    for candidate in FIELD_ALIASES[logical_name]:
        found = lowered.get(candidate.lower())
        if found is not None:
            return found
    return None


def parse_number(value: object) -> float:
    text = normalize_text(value)
    if not text:
        return 0.0

    text = text.replace(",", "").replace("+", "")
    multiplier = 1.0
    if "亿" in text:
        multiplier = 100000000.0
    elif "万" in text:
        multiplier = 10000.0
    elif "千" in text:
        multiplier = 1000.0

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    return float(match.group()) * multiplier


def parse_int(value: object) -> int:
    return int(parse_number(value))


def jd_detail_url(item_id: str, detail_url: str = "") -> str:
    if detail_url:
        return detail_url
    return f"https://item.jd.com/{item_id}.html"


def read_products(input_path: Path, allow_root_fallback: bool) -> pd.DataFrame:
    chosen = input_path
    if not chosen.exists() and allow_root_fallback and ROOT_INPUT_FALLBACK.exists():
        log(f"未找到 {chosen}，临时使用根目录文件：{ROOT_INPUT_FALLBACK}")
        chosen = ROOT_INPUT_FALLBACK
    if not chosen.exists():
        raise FileNotFoundError(f"输入文件不存在：{chosen}")

    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            df = pd.read_csv(chosen, dtype=str, encoding=encoding)
            log(f"已读取 {chosen}，共 {len(df)} 行，编码 {encoding}")
            return df
        except UnicodeDecodeError:
            continue
    return pd.read_csv(chosen, dtype=str)


def standardize_products(df: pd.DataFrame) -> pd.DataFrame:
    cols = {key: pick_column(df, key) for key in FIELD_ALIASES}
    required = ["item_id", "title"]
    missing = [name for name in required if not cols.get(name)]
    if missing:
        raise ValueError(f"输入 CSV 缺少关键字段：{', '.join(missing)}")

    out = pd.DataFrame()
    for logical_name in FIELD_ALIASES:
        source_col = cols.get(logical_name)
        if source_col:
            out[logical_name] = df[source_col].map(normalize_text)
        else:
            out[logical_name] = ""

    out["item_id"] = out["item_id"].map(lambda x: re.sub(r"\.0$", "", normalize_text(x)))
    out = out[out["item_id"].str.len() > 0].copy()
    out["detail_url"] = [
        jd_detail_url(item_id, detail_url)
        for item_id, detail_url in zip(out["item_id"], out["detail_url"], strict=False)
    ]
    out["review_count_num"] = out["review_count"].map(parse_number)
    out["price_num"] = out["price"].map(parse_number)
    out["rank_position_num"] = out["rank_position"].map(parse_number)
    out = out.drop_duplicates(subset=["item_id"], keep="first")
    return out


def load_crawled_items(checkpoint_path: Path) -> set[str]:
    if not checkpoint_path.exists():
        return set()
    try:
        df = pd.read_csv(checkpoint_path, dtype=str, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(checkpoint_path, dtype=str)
    if "item_id" not in df.columns:
        return set()
    return {normalize_text(value) for value in df["item_id"].dropna().tolist()}


def select_products(products: pd.DataFrame, max_products: int, crawled: set[str]) -> pd.DataFrame:
    if products.empty:
        return products

    rank_top = products[products["rank_position_num"].between(1, 10, inclusive="both")]

    review_mean = products["review_count_num"].mean()
    high_review = products[products["review_count_num"] > review_mean * 2]

    priced = products[products["price_num"] > 0]
    if priced.empty:
        price_blank = products.iloc[0:0]
    else:
        q20 = priced["price_num"].quantile(0.20)
        q80 = priced["price_num"].quantile(0.80)
        price_blank = products[(products["price_num"] <= q20) | (products["price_num"] >= q80)]

    selected = pd.concat([rank_top, high_review, price_blank], ignore_index=True)
    if selected.empty:
        selected = products.copy()
        log("筛选条件未命中，回退为全量候选后按评论数排序。")

    selected = selected.drop_duplicates(subset=["item_id"], keep="first")
    selected = selected[~selected["item_id"].isin(crawled)].copy()
    selected = selected.sort_values("review_count_num", ascending=False)
    return selected.head(max_products)


def ensure_csv(path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()


def append_rows(path: Path, columns: list[str], rows: Iterable[dict[str, object]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    ensure_csv(path, columns)
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})
    return len(rows)


def append_one(path: Path, columns: list[str], row: dict[str, object]) -> None:
    append_rows(path, columns, [row])


def browseract_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("BROWSERACT_BIN", "BROWSER_ACT_BIN"):
        value = os.getenv(env_name)
        if value:
            candidates.append(Path(value).expanduser())

    for name in ("browser-act", "browser-act.cmd", "browser-act.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    home = Path.home()
    candidates.extend(
        [
            home / ".local" / "bin" / "browser-act.exe",
            home / ".local" / "bin" / "browser-act.cmd",
            Path(os.getenv("APPDATA", "")) / "Python" / "Scripts" / "browser-act.exe",
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python313" / "Scripts" / "browser-act.exe",
        ]
    )

    codex_bin_root = Path(os.getenv("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    if codex_bin_root.exists():
        candidates.extend(codex_bin_root.glob("*/*browser-act.cmd"))
        candidates.extend(codex_bin_root.glob("*/*browser-act.exe"))
        candidates.extend(codex_bin_root.glob("*/browser-act.cmd"))
        candidates.extend(codex_bin_root.glob("*/browser-act.exe"))

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not str(candidate):
            continue
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def executable_from_cmd_shim(path: Path) -> Path:
    if path.suffix.lower() not in {".cmd", ".bat"}:
        return path
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return path
    match = re.search(r'"([^"]*browser-act\.exe)"', text, re.I)
    if match:
        exe = Path(match.group(1))
        if exe.exists():
            return exe
    return path


def resolve_browseract_bin(preferred: str) -> str:
    preferred_path = Path(preferred).expanduser()
    if preferred and (preferred_path.exists() or shutil.which(preferred)):
        resolved = preferred_path if preferred_path.exists() else Path(str(shutil.which(preferred)))
        return str(executable_from_cmd_shim(resolved))

    for candidate in browseract_candidates():
        if candidate.exists():
            return str(executable_from_cmd_shim(candidate))

    checked = "\n  - ".join(str(path) for path in browseract_candidates()[:12])
    raise RuntimeError(
        "未找到 browser-act 命令。请安装 BrowserAct CLI，或用 --browseract-bin 指定完整路径。\n"
        "已检查：\n  - " + checked
    )


def run_command(args: list[str], timeout: int, label: str) -> CommandResult:
    if args and args[0] == "browser-act":
        args = [BROWSERACT_BIN, *args[1:]]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if proc.returncode != 0:
            log(f"{label} 失败，returncode={proc.returncode}，stderr={stderr[:300]}")
        return CommandResult(proc.returncode == 0, stdout, stderr, proc.returncode)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        log(f"{label} 超时：{timeout}s")
        return CommandResult(False, stdout, stderr, None)
    except FileNotFoundError:
        raise RuntimeError(f"未找到命令：{args[0]}。请检查 --browseract-bin 或 PATH。")


def browseract_skill_check(skip: bool) -> None:
    if skip:
        return
    log("执行 BrowserAct 技能/环境检查：browser-act get-skills core")
    result = run_command(
        ["browser-act", "get-skills", "core", "--skill-version", "2.0.2"],
        timeout=120,
        label="BrowserAct 技能检查",
    )
    if not result.ok:
        raise RuntimeError("BrowserAct 技能检查失败，停止运行以避免误用浏览器环境。")


def stealth_extract(url: str) -> str:
    result = run_command(
        [
            "browser-act",
            "stealth-extract",
            url,
            "--content-type",
            "markdown",
            "--timeout",
            "60",
        ],
        timeout=95,
        label="stealth-extract",
    )
    if result.ok:
        return result.stdout

    return ""


def session_cmd(session: str, args: list[str], timeout: int, label: str) -> CommandResult:
    return run_command(["browser-act", "--session", session, *args], timeout=timeout, label=label)


def close_session(session: str) -> None:
    run_command(["browser-act", "session", "close", session], timeout=30, label=f"{session} close")


def browseract_browser_available(browser_id: str) -> bool:
    global BROWSERACT_BROWSER_LIST_CACHE
    if BROWSERACT_BROWSER_LIST_CACHE is None:
        result = run_command(["browser-act", "browser", "list"], timeout=60, label="browser list")
        BROWSERACT_BROWSER_LIST_CACHE = result.stdout if result.ok else f"{result.stdout}\n{result.stderr}"
    text = BROWSERACT_BROWSER_LIST_CACHE or ""
    if "No browsers found" in text:
        return False
    return browser_id in text


def resolve_browser_id(browser_id_or_name: str) -> str:
    global BROWSERACT_BROWSER_LIST_CACHE
    if BROWSERACT_BROWSER_LIST_CACHE is None:
        result = run_command(["browser-act", "browser", "list"], timeout=60, label="browser list")
        BROWSERACT_BROWSER_LIST_CACHE = result.stdout if result.ok else f"{result.stdout}\n{result.stderr}"
    text = BROWSERACT_BROWSER_LIST_CACHE or ""
    for line in text.splitlines():
        id_match = re.search(r"\bid=([^\s]+)", line)
        name_match = re.search(r'\bname="([^"]+)"', line)
        if not id_match:
            continue
        found_id = id_match.group(1)
        found_name = name_match.group(1) if name_match else ""
        if browser_id_or_name in {found_id, found_name}:
            return found_id
    return browser_id_or_name


def contains_captcha(text: str) -> bool:
    lower = text.lower()
    return any(pattern.lower() in lower for pattern in CAPTCHA_PATTERNS)


def clean_markdown_line(line: str) -> str:
    line = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
    line = re.sub(r"^[#>*\-\s]+", "", line)
    line = re.sub(r"\s+", " ", line)
    return line.strip(" \t\r\n|")


def compact_text(text: str) -> str:
    lines = [clean_markdown_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def regex_first(patterns: list[str], text: str, flags: int = re.I | re.S) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return normalize_text(match.group(1))
    return ""


def extract_good_rate(markdown: str) -> str:
    text = compact_text(markdown)
    return regex_first(
        [
            r"(?:好评率|好评度)\s*[:：]?\s*(\d+(?:\.\d+)?%)",
            r"(\d+(?:\.\d+)?%)\s*(?:好评|买家赞|用户好评)",
            r"(?:赞不绝口|推荐度)[^\d%]{0,20}(\d+(?:\.\d+)?%)",
        ],
        text,
    )


def extract_tags(markdown: str) -> str:
    text = compact_text(markdown)
    tags: list[str] = []

    for pattern in [
        r"(?:评价标签|印象标签|大家认为|买家印象)\s*[:：]\s*([^\n]+)",
        r"(?:口感|包装|物流|味道|品质|价格|日期|回购|新鲜|分量|性价比)[^\n]{0,18}\(\d+\)",
    ]:
        for match in re.finditer(pattern, text):
            value = match.group(1) if match.lastindex else match.group(0)
            pieces = re.split(r"[|/、,，;；\s]{1,}", value)
            for piece in pieces:
                piece = normalize_text(piece)
                if 1 < len(piece) <= 24 and not re.fullmatch(r"\d+", piece):
                    tags.append(piece)

    for line in text.splitlines():
        if len(line) <= 30 and re.search(r"(好|差|快|慢|新鲜|破损|划算|回购|正品|口感|包装|物流)", line):
            tags.append(re.sub(r"\(\d+\)", "", line).strip())

    deduped = list(dict.fromkeys(tags))
    return "|".join(deduped[:20])


def extract_attribute(markdown: str, keywords: list[str], max_len: int = 120) -> str:
    text = compact_text(markdown)
    keyword_pattern = "|".join(re.escape(keyword) for keyword in keywords)
    patterns = [
        rf"(?:{keyword_pattern})\s*[:：]\s*([^\n]+)",
        rf"(?:{keyword_pattern})\s+([^\n]+)",
    ]
    value = regex_first(patterns, text)
    value = re.split(r"\s{2,}| {1,}(?:品牌|型号|净含量|产地|保质期|配料|规格)[:：]", value)[0]
    return value[:max_len]


def parse_product_details(markdown: str) -> dict[str, str]:
    return {
        "好评率": extract_good_rate(markdown),
        "评价标签": extract_tags(markdown),
        "产地": extract_attribute(markdown, ["产地", "原产地", "生产地", "生产地址"]),
        "保质期": extract_attribute(markdown, ["保质期", "质保期", "有效期"]),
        "配料表": extract_attribute(markdown, ["配料表", "配料", "成分"]),
        "规格": extract_attribute(markdown, ["规格", "净含量", "包装规格", "重量"]),
    }


def parse_score(block: str) -> int | None:
    patterns = [
        r"(?:评分|星级|score)\s*[:：]?\s*([1-5])",
        r"([1-5])\s*星",
        r"star[_-]?([1-5])",
        r"rate[_-]?([1-5])",
    ]
    for pattern in patterns:
        match = re.search(pattern, block, re.I)
        if match:
            return int(match.group(1))
    if re.search(r"差评|不满意|很差", block):
        return 1
    if re.search(r"中评|一般", block):
        return 3
    if re.search(r"好评|满意|不错", block):
        return 5
    return None


def parse_date(block: str) -> str:
    patterns = [
        r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?",
        r"(\d{4}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, block)
        if not match:
            continue
        if len(match.groups()) >= 3 and match.group(1).isdigit():
            year, month, day = match.group(1), match.group(2), match.group(3)
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        return normalize_text(match.group(1))
    return ""


def parse_like_count(block: str) -> int:
    patterns = [
        r"(?:点赞|有用|赞|like)\s*[:：]?\s*(\d+)",
        r"(\d+)\s*(?:人觉得有用|人点赞)",
    ]
    value = regex_first(patterns, block)
    return int(value) if value.isdigit() else 0


def looks_like_noise(line: str) -> bool:
    if len(line) < 3:
        return True
    noise_patterns = [
        r"加入购物车",
        r"立即购买",
        r"商品评价",
        r"全部评价",
        r"下一页",
        r"上一页",
        r"京东",
        r"客服",
        r"店铺",
        r"已隐藏",
        r"举报",
        r"点赞",
        r"好评率",
        r"累计评价",
    ]
    return any(re.search(pattern, line) for pattern in noise_patterns)


def extract_content_from_block(block: str) -> str:
    lines = [clean_markdown_line(line) for line in block.splitlines()]
    lines = [line for line in lines if line and not looks_like_noise(line)]
    cleaned: list[str] = []
    for line in lines:
        if parse_date(line):
            continue
        if re.fullmatch(r"[1-5]\s*星", line):
            continue
        line = re.sub(r"(?:评分|星级)\s*[:：]?\s*[1-5]", "", line)
        line = re.sub(r"(?:点赞|有用|赞|like)\s*[:：]?\s*\d+", "", line, flags=re.I)
        line = normalize_text(line)
        if len(line) >= 4:
            cleaned.append(line)
    if not cleaned:
        return ""
    cleaned = list(dict.fromkeys(cleaned))
    cleaned.sort(key=len, reverse=True)
    return cleaned[0][:1000]


def split_comment_blocks(markdown: str) -> list[str]:
    text = compact_text(markdown)
    if not text:
        return []

    raw_blocks = re.split(r"\n{2,}|(?=\n.*20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})", text)
    blocks = [block.strip() for block in raw_blocks if len(block.strip()) >= 12]

    if len(blocks) <= 2:
        lines = text.splitlines()
        blocks = []
        current: list[str] = []
        for line in lines:
            starts_new = bool(parse_date(line) or re.search(r"[1-5]\s*星|好评|中评|差评", line))
            if starts_new and current:
                blocks.append("\n".join(current))
                current = []
            current.append(line)
        if current:
            blocks.append("\n".join(current))
    return blocks


def parse_reviews(markdown: str, item_id: str) -> list[dict[str, object]]:
    blocks = split_comment_blocks(markdown)
    reviews: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    crawl_time = now_str()

    for block in blocks:
        score = parse_score(block)
        date = parse_date(block)
        content = extract_content_from_block(block)
        if not content:
            continue
        if not date and score is None and len(content) < 12:
            continue
        if len(content) > 300 and not re.search(r"好评|差评|追评|星|20\d{2}", block):
            continue
        key = (date, content[:120])
        if key in seen:
            continue
        seen.add(key)
        reviews.append(
            {
                "item_id": item_id,
                "score": score if score is not None else "",
                "date": date,
                "content": content,
                "like_count": parse_like_count(block),
                "crawl_time": crawl_time,
            }
        )
    return reviews


def negative_reviews_from(reviews: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for review in reviews:
        try:
            score = int(review.get("score", ""))
        except (TypeError, ValueError):
            continue
        if score <= 2:
            rows.append(
                {
                    "item_id": review.get("item_id", ""),
                    "score": score,
                    "content": review.get("content", ""),
                    "date": review.get("date", ""),
                    "crawl_time": review.get("crawl_time", now_str()),
                }
            )
    return rows


def strip_jsonp(payload: str) -> str:
    text = payload.strip()
    match = re.match(r"^[\w$]+\((.*)\)\s*;?\s*$", text, re.S)
    return match.group(1) if match else text


def jd_comment_api_urls(item_id: str, score: int, page_no: int) -> list[str]:
    query = {
        "productId": item_id,
        "score": str(score),
        "sortType": "5",
        "page": str(page_no),
        "pageSize": "10",
        "isShadowSku": "0",
        "fold": "1",
    }
    club_url = "https://club.jd.com/comment/productPageComments.action?" + urllib.parse.urlencode(query)

    body = json.dumps(
        {
            "productId": item_id,
            "score": score,
            "sortType": 5,
            "page": page_no,
            "pageSize": 10,
            "isShadowSku": 0,
            "fold": 1,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    api_query = {
        "appid": "item-v3",
        "functionId": "pc_club_productPageComments",
        "client": "pc",
        "clientVersion": "1.0.0",
        "t": str(int(time.time() * 1000)),
        "body": body,
    }
    api_url = "https://api.m.jd.com/?" + urllib.parse.urlencode(api_query)
    return [club_url, api_url]


def parse_comment_api_payload(payload: str, item_id: str) -> list[dict[str, object]]:
    text = strip_jsonp(payload)
    if not text or "系统繁忙" in text or "DOCTYPE" in text[:300].upper() or "no access" in text.lower():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    comments = data.get("comments") or data.get("data", {}).get("comments") or []
    rows: list[dict[str, object]] = []
    crawl_time = now_str()
    for item in comments:
        content = normalize_text(item.get("content") or item.get("commentData") or "")
        if not content:
            continue
        rows.append(
            {
                "item_id": item_id,
                "score": item.get("score") or item.get("commentScore") or "",
                "date": item.get("creationTime") or item.get("referenceTime") or "",
                "content": content[:1000],
                "like_count": item.get("usefulVoteCount") or item.get("usefulCount") or item.get("plusAvailable") or 0,
                "crawl_time": crawl_time,
            }
        )
    return rows


def fetch_reviews_api_http(item_id: str, detail_url: str, max_pages: int, scores: list[int]) -> tuple[list[dict[str, object]], str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Referer": detail_url,
        "Origin": "https://item.jd.com",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    errors: list[str] = []

    for score in scores:
        for page_no in range(max_pages):
            got_page = False
            for url in jd_comment_api_urls(item_id, score, page_no):
                try:
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=25) as resp:
                        payload = resp.read().decode("utf-8", "replace")
                    parsed = parse_comment_api_payload(payload, item_id)
                    if not parsed:
                        errors.append(f"score={score} page={page_no + 1}: empty_or_blocked")
                        continue
                    for row in parsed:
                        key = (
                            str(row.get("score", "")),
                            str(row.get("date", "")),
                            str(row.get("content", ""))[:120],
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append(row)
                    got_page = True
                    break
                except urllib.error.HTTPError as exc:
                    errors.append(f"score={score} page={page_no + 1}: http_{exc.code}")
                except Exception as exc:
                    errors.append(f"score={score} page={page_no + 1}: {type(exc).__name__}")
            if not got_page:
                break
            sleep_random((1.0, 2.0), "评论 API 节奏控制")

    return rows, "; ".join(errors[-8:])


def fetch_reviews_browseract_eval(session: str, item_id: str, detail_url: str, max_pages: int) -> list[dict[str, object]]:
    js = f"""
(async () => {{
  const itemId = {json.dumps(item_id)};
  const rows = [];
  for (let page = 0; page < {max_pages}; page++) {{
    const url = `https://club.jd.com/comment/productPageComments.action?productId=${{itemId}}&score=0&sortType=5&page=${{page}}&pageSize=10&isShadowSku=0&fold=1`;
    try {{
      const resp = await fetch(url, {{credentials: 'include', headers: {{accept: 'application/json,text/plain,*/*'}}}});
      const text = await resp.text();
      if (!text || text.includes('系统繁忙') || text.slice(0, 300).toUpperCase().includes('DOCTYPE')) break;
      const data = JSON.parse(text.replace(/^\\w+\\((.*)\\);?$/, '$1'));
      const comments = data.comments || [];
      if (!comments.length) break;
      for (const c of comments) {{
        rows.push({{
          item_id: itemId,
          score: c.score || '',
          date: c.creationTime || c.referenceTime || '',
          content: (c.content || '').replace(/\\s+/g, ' ').trim(),
          like_count: c.usefulVoteCount || 0,
          crawl_time: new Date().toISOString().slice(0, 19).replace('T', ' ')
        }});
      }}
      await new Promise(r => setTimeout(r, 1200 + Math.random() * 900));
    }} catch (e) {{
      break;
    }}
  }}
  return JSON.stringify(rows);
}})()
""".strip()
    result = session_cmd(session, ["eval", js], timeout=90, label=f"{session} eval comment api")
    if not result.ok or not result.stdout:
        return []
    raw = result.stdout.strip()
    json_match = re.search(r"(\[\s*\{.*\}\s*\])", raw, re.S)
    if json_match:
        raw = json_match.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows: list[dict[str, object]] = []
    for row in data:
        content = normalize_text(row.get("content", ""))
        if not content:
            continue
        row["content"] = content[:1000]
        row["item_id"] = item_id
        rows.append(row)
    return rows


def find_index_from_state(state_text: str, hints: list[str]) -> str | None:
    lines = state_text.splitlines()
    hint_pattern = re.compile("|".join(re.escape(hint) for hint in hints), re.I)
    index_patterns = [
        re.compile(r"^\s*\[?(\d{1,4})\]?\s*[:.)-]?\s*(.+)$"),
        re.compile(r"index\s*[:=]\s*(\d{1,4}).{0,120}", re.I),
    ]
    for line in lines:
        if not hint_pattern.search(line):
            continue
        for pattern in index_patterns:
            match = pattern.search(line)
            if match:
                return match.group(1)
    return None


def solve_captcha_if_needed(session: str, text: str, objective: str) -> bool:
    if not contains_captcha(text):
        return True

    log(f"{session} 检测到验证码，先尝试 solve-captcha。")
    session_cmd(session, ["solve-captcha"], timeout=180, label=f"{session} solve-captcha")
    session_cmd(session, ["wait", "stable", "--timeout", "10"], timeout=25, label=f"{session} wait stable")
    markdown = session_cmd(session, ["get", "markdown"], timeout=70, label=f"{session} captcha recheck").stdout
    if not contains_captcha(markdown):
        log(f"{session} 自动验证码处理成功。")
        return True

    log(f"{session} 自动处理失败，进入 remote-assist。")
    session_cmd(
        session,
        ["remote-assist", "--objective", objective],
        timeout=900,
        label=f"{session} remote-assist",
    )
    session_cmd(session, ["wait", "stable", "--timeout", "10"], timeout=25, label=f"{session} wait stable")
    markdown = session_cmd(session, ["get", "markdown"], timeout=70, label=f"{session} captcha final check").stdout
    if contains_captcha(markdown):
        log(f"{session} 验证码仍未解除，跳过当前商品。")
        if KEEP_SESSION_ON_CAPTCHA:
            log(f"{session} 已按配置保留会话，便于手动完成验证后重跑。")
        return False
    return True


def discover_comment_requests(session: str, item_id: str, output_dir: Path) -> None:
    result = session_cmd(
        session,
        ["network", "requests", "--filter", "comment"],
        timeout=45,
        label=f"{session} network requests",
    )
    if not result.stdout:
        return
    if not any(hint in result.stdout for hint in COMMENT_API_HINTS):
        return
    logs_dir = output_dir / "network_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{item_id}_comment_requests_{today_suffix()}.txt"
    log_path.write_text(result.stdout, encoding="utf-8")
    log(f"已保存评论网络请求线索：{log_path}")


def interactive_extract_reviews(
    item_id: str,
    url: str,
    browser_id: str,
    max_pages: int,
    output_dir: Path,
) -> list[dict[str, object]]:
    session = f"jd-{item_id}"
    all_reviews: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    keep_session = False

    if not browseract_browser_available(browser_id):
        log(f"BrowserAct 未找到浏览器实例 {browser_id}，跳过完整浏览器交互。")
        return []

    try:
        log(f"{session} 打开商品详情页。")
        opened = session_cmd(
            session,
            ["browser", "open", browser_id, url],
            timeout=120,
            label=f"{session} open",
        )
        if not opened.ok:
            return []

        session_cmd(session, ["wait", "stable", "--timeout", "10"], timeout=25, label=f"{session} wait stable")
        state = session_cmd(session, ["state"], timeout=45, label=f"{session} state").stdout
        if not solve_captcha_if_needed(session, state, f"完成京东商品 {item_id} 的验证码验证，停留在商品评论区域。"):
            keep_session = KEEP_SESSION_ON_CAPTCHA
            return []

        comment_index = find_index_from_state(state, COMMENT_HINTS)
        if comment_index:
            log(f"{session} 点击评论入口 index={comment_index}。")
            session_cmd(session, ["click", comment_index], timeout=45, label=f"{session} click comments")
            session_cmd(session, ["wait", "stable", "--timeout", "10"], timeout=25, label=f"{session} wait stable")

        for page_no in range(1, max_pages + 1):
            log(f"{session} 抓取评论第 {page_no}/{max_pages} 页。")
            for _ in range(2):
                session_cmd(
                    session,
                    ["scroll", "down", "--amount", "500"],
                    timeout=30,
                    label=f"{session} scroll",
                )
                sleep_random(SCROLL_SLEEP_RANGE, "滚动后等待评论渲染")

            markdown_result = session_cmd(session, ["get", "markdown"], timeout=80, label=f"{session} get markdown")
            markdown = markdown_result.stdout
            if not solve_captcha_if_needed(session, markdown, f"完成京东商品 {item_id} 评论页验证码验证。"):
                keep_session = KEEP_SESSION_ON_CAPTCHA
                break

            page_reviews = parse_reviews(markdown, item_id)
            new_count = 0
            for review in page_reviews:
                key = (normalize_text(review.get("date")), normalize_text(review.get("content"))[:120])
                if key in seen:
                    continue
                seen.add(key)
                all_reviews.append(review)
                new_count += 1
            log(f"{session} 第 {page_no} 页解析到 {new_count} 条新评论。")

            if not page_reviews:
                api_rows = fetch_reviews_browseract_eval(session, item_id, url, max_pages=max_pages)
                if api_rows:
                    for review in api_rows:
                        key = (normalize_text(review.get("date")), normalize_text(review.get("content"))[:120])
                        if key in seen:
                            continue
                        seen.add(key)
                        all_reviews.append(review)
                    log(f"{session} 通过页内评论 API 兜底解析到 {len(api_rows)} 条评论。")
                    break

            if page_no >= max_pages:
                break

            state = session_cmd(session, ["state"], timeout=45, label=f"{session} state next").stdout
            next_index = find_index_from_state(state, NEXT_PAGE_HINTS)
            if not next_index:
                log(f"{session} 未找到下一页按钮，结束评论翻页。")
                if not all_reviews:
                    discover_comment_requests(session, item_id, output_dir)
                break
            session_cmd(session, ["click", next_index], timeout=45, label=f"{session} click next")
            session_cmd(session, ["wait", "stable", "--timeout", "10"], timeout=25, label=f"{session} wait next")
            sleep_random(INTERACTIVE_SLEEP_RANGE, "翻页节奏控制")

        if not all_reviews:
            discover_comment_requests(session, item_id, output_dir)
        return all_reviews

    finally:
        if not keep_session:
            close_session(session)


def build_detail_row(product: pd.Series, details: dict[str, str]) -> dict[str, object]:
    return {
        "item_id": product["item_id"],
        "title": product["title"],
        "shop_name": product["shop_name"],
        "category": product["category_breadcrumb"],
        "review_count": product["review_count"],
        "好评率": details.get("好评率", ""),
        "评价标签": details.get("评价标签", ""),
        "产地": details.get("产地", ""),
        "保质期": details.get("保质期", ""),
        "配料表": details.get("配料表", ""),
        "规格": details.get("规格", ""),
        "crawl_time": now_str(),
    }


def crawl_one_product(
    product: pd.Series,
    browser_id: str,
    max_pages: int,
    output_paths: dict[str, Path],
) -> tuple[int, int]:
    item_id = str(product["item_id"])
    title = str(product["title"])
    url = str(product["detail_url"])
    review_count = int(product.get("review_count_num", 0) or 0)

    log(f"开始商品 {item_id}：{title[:60]}，评论数={review_count}")

    details_markdown = stealth_extract(url)
    details = parse_product_details(details_markdown)
    detail_row = build_detail_row(product, details)
    append_one(output_paths["details"], PRODUCT_DETAIL_COLUMNS, detail_row)
    sleep_random(STEALTH_SLEEP_RANGE, "stealth-extract 后节奏控制")

    reviews: list[dict[str, object]] = []
    if review_count > 0:
        reviews = interactive_extract_reviews(
            item_id=item_id,
            url=url,
            browser_id=browser_id,
            max_pages=max_pages,
            output_dir=output_paths["output_dir"],
        )
        sleep_random(INTERACTIVE_SLEEP_RANGE, "完整浏览器交互后节奏控制")
    else:
        log(f"{item_id} 评论数为 0，跳过完整浏览器评论抓取。")

    negative_rows = negative_reviews_from(reviews)
    review_count_saved = append_rows(output_paths["reviews"], PRODUCT_REVIEW_COLUMNS, reviews)
    negative_count_saved = append_rows(output_paths["negative"], NEGATIVE_REVIEW_COLUMNS, negative_rows)
    append_one(
        output_paths["crawled"],
        CRAWLED_COLUMNS,
        {"item_id": item_id, "title": title, "crawl_time": now_str()},
    )
    log(f"完成商品 {item_id}：评论 {review_count_saved} 条，差评 {negative_count_saved} 条。")
    return review_count_saved, negative_count_saved


def build_output_paths(output_dir: Path) -> dict[str, Path]:
    suffix = today_suffix()
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "output_dir": output_dir,
        "reviews": output_dir / f"product_reviews_{suffix}.csv",
        "details": output_dir / f"product_details_{suffix}.csv",
        "negative": output_dir / f"negative_reviews_{suffix}.csv",
        "crawled": output_dir / "crawled_items.csv",
    }


def ensure_outputs(paths: dict[str, Path]) -> None:
    ensure_csv(paths["reviews"], PRODUCT_REVIEW_COLUMNS)
    ensure_csv(paths["details"], PRODUCT_DETAIL_COLUMNS)
    ensure_csv(paths["negative"], NEGATIVE_REVIEW_COLUMNS)
    ensure_csv(paths["crawled"], CRAWLED_COLUMNS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BrowserAct 京东商品评论批量爬虫")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="输入 CSV，默认 ./数据/merged_products.csv")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="输出目录")
    parser.add_argument("--browser-id", default=DEFAULT_BROWSER_ID, help="BrowserAct 浏览器实例名，默认 jd-scraper")
    parser.add_argument(
        "--browseract-bin",
        default=os.getenv("BROWSERACT_BIN", DEFAULT_BROWSERACT_BIN),
        help="browser-act 可执行文件路径；默认从 PATH 和 Codex 工具目录自动寻找",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_MAX_PRODUCTS, help="每天最多抓取商品数，默认 80")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_REVIEW_PAGES, help="每个商品最多评论页数，默认 5")
    parser.add_argument("--save-every", type=int, default=DEFAULT_SAVE_EVERY, help="进度日志间隔，默认每 10 个商品")
    parser.add_argument("--smoke-one", action="store_true", help="首次运行建议开启：只抓 1 个商品")
    parser.add_argument("--allow-root-fallback", action="store_true", help="找不到 ./数据/merged_products.csv 时使用根目录 merged_products.csv")
    parser.add_argument("--skip-browseract-skill-check", action="store_true", help="跳过 browser-act get-skills core 检查")
    parser.add_argument("--keep-session-on-captcha", action="store_true", help="验证码无法自动处理时保留 BrowserAct 会话，便于人工接管后重跑")
    return parser.parse_args()


def main() -> int:
    global BROWSERACT_BIN, KEEP_SESSION_ON_CAPTCHA
    args = parse_args()
    random.seed()
    BROWSERACT_BIN = resolve_browseract_bin(args.browseract_bin)
    KEEP_SESSION_ON_CAPTCHA = bool(args.keep_session_on_captcha)
    log(f"使用 BrowserAct CLI：{BROWSERACT_BIN}")

    browseract_skill_check(skip=args.skip_browseract_skill_check)
    args.browser_id = resolve_browser_id(args.browser_id)
    log(f"使用 BrowserAct 浏览器：{args.browser_id}")

    output_paths = build_output_paths(args.output_dir)
    ensure_outputs(output_paths)

    raw_products = read_products(args.input, allow_root_fallback=args.allow_root_fallback)
    products = standardize_products(raw_products)
    crawled = load_crawled_items(output_paths["crawled"])

    limit = 1 if args.smoke_one else args.limit
    selected = select_products(products, max_products=limit, crawled=crawled)
    if selected.empty:
        log("没有待爬商品：可能都已在 crawled_items.csv 中。")
        return 0

    log(f"本次待爬 {len(selected)} 个商品，输出目录：{args.output_dir}")
    total_reviews = 0
    total_negative = 0
    failures: list[str] = []

    for idx, (_, product) in enumerate(selected.iterrows(), start=1):
        item_id = str(product["item_id"])
        try:
            review_rows, negative_rows = crawl_one_product(product, args.browser_id, args.max_pages, output_paths)
            total_reviews += review_rows
            total_negative += negative_rows
        except KeyboardInterrupt:
            log("收到中断信号，已保存已有 CSV 和断点记录。")
            raise
        except Exception as exc:
            failures.append(item_id)
            log(f"商品 {item_id} 失败：{exc}")

        if idx % max(args.save_every, 1) == 0:
            log(
                f"阶段保存点：已处理 {idx}/{len(selected)}，"
                f"累计评论 {total_reviews} 条，累计差评 {total_negative} 条，失败 {len(failures)} 个。"
            )

    log(
        f"运行结束：商品 {len(selected)} 个，评论 {total_reviews} 条，"
        f"差评 {total_negative} 条，失败 {len(failures)} 个。"
    )
    if failures:
        log("失败 item_id：" + ", ".join(failures[:50]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"程序退出：{exc}")
        raise
