from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
INPUT_CSV = BASE_DIR / "merged_products.csv"
OUTPUT_CSV = BASE_DIR / "price_history.csv"
CHECKPOINT_CSV = BASE_DIR / "crawled_price_items.csv"

HISTORY_URL = "http://tool.manmanbuy.com/HistoryLowest.aspx"
API_URL = "http://tool.manmanbuy.com/api.ashx"
DEFAULT_SECRET = "c5c3f201a8e8fc634d37a766a0299218"

OUTPUT_COLUMNS = [
    "item_id",
    "title",
    "detail_url",
    "current_price",
    "lowest_price",
    "lowest_date",
    "highest_price",
    "price_trend",
    "query_time",
    "status",
    "error_msg",
]

CHECKPOINT_COLUMNS = ["item_id", "detail_url", "crawl_time"]


@dataclass
class TicketState:
    ticket: str
    authorization: str


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def normalize_item_id(value: Any, detail_url: str = "") -> str:
    item_id = normalize_text(value)
    if item_id and item_id.lower() != "nan":
        return item_id
    match = re.search(r"item\.jd\.com/(\d+)\.html", detail_url)
    return match.group(1) if match else ""


def resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    aliases = {
        "item_id": ["item_id", "product_id", "SKU", "sku"],
        "title": ["title", "product_title", "商品名称", "spName"],
        "detail_url": ["detail_url", "url", "商品链接"],
        "price": ["price", "current_price", "现价"],
        "shop_name": ["shop_name", "店铺", "店铺名称"],
    }
    resolved: dict[str, str] = {}
    for logical, names in aliases.items():
        for name in names:
            if name in df.columns:
                resolved[logical] = name
                break
    if "detail_url" not in resolved:
        raise ValueError(f"输入文件缺少 detail_url 列，可用列: {df.columns.tolist()}")
    return resolved


def load_checkpoint(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except pd.errors.EmptyDataError:
        return set()
    if "item_id" not in df.columns:
        return set()
    return set(df["item_id"].astype(str).str.strip())


def append_rows(path: Path, rows: list[dict[str, Any]], columns: list[str], dedup_keys: list[str]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame(rows)
    for col in columns:
        if col not in new_df.columns:
            new_df[col] = ""
    new_df = new_df[columns]
    if path.exists() and path.stat().st_size > 0:
        try:
            old_df = pd.read_csv(path, dtype=str).fillna("")
        except pd.errors.EmptyDataError:
            old_df = pd.DataFrame(columns=columns)
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df
    combined = combined.drop_duplicates(subset=dedup_keys, keep="last")
    combined.to_csv(path, index=False, encoding="utf-8-sig")


def build_targets(input_csv: Path, checkpoint_path: Path, limit: int | None = None) -> list[dict[str, str]]:
    df = pd.read_csv(input_csv, dtype=str).fillna("")
    cols = resolve_columns(df)
    crawled_ids = load_checkpoint(checkpoint_path)
    targets: list[dict[str, str]] = []

    for _, row in df.iterrows():
        detail_url = normalize_text(row.get(cols["detail_url"], ""))
        if not detail_url or "item.jd.com" not in detail_url:
            continue
        item_id = normalize_item_id(row.get(cols.get("item_id", ""), ""), detail_url)
        if not item_id or item_id in crawled_ids:
            continue
        targets.append(
            {
                "item_id": item_id,
                "title": normalize_text(row.get(cols.get("title", ""), "")),
                "detail_url": detail_url,
            }
        )
        if limit and len(targets) >= limit:
            break

    return targets


def extract_ticket(html: str) -> str:
    patterns = [
        r'id=["\']ticket["\'][^>]*value=["\']([^"\']+)["\']',
        r'name=["\']ticket["\'][^>]*value=["\']([^"\']+)["\']',
        r'value=["\']([^"\']+)["\'][^>]*id=["\']ticket["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    raise RuntimeError("未能从 HistoryLowest.aspx 提取 #ticket value")


class ManmanbuyClient:
    def __init__(self, secret: str = DEFAULT_SECRET, timeout: int = 30) -> None:
        self.secret = secret
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36"
                ),
                "Referer": HISTORY_URL,
                "Origin": "http://tool.manmanbuy.com",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self.ticket_state: TicketState | None = None

    def refresh_ticket(self) -> TicketState:
        resp = self.session.get(HISTORY_URL, timeout=self.timeout)
        resp.raise_for_status()
        ticket = extract_ticket(resp.text)
        authorization = "BasicAuth " + ticket[-4:] + ticket[:-4]
        self.ticket_state = TicketState(ticket=ticket, authorization=authorization)
        return self.ticket_state

    def make_token(self, params: dict[str, Any]) -> str:
        pieces = [self.secret]
        for key in sorted(params.keys()):
            pieces.append(str(key))
            pieces.append(quote(str(params[key]), safe=""))
        pieces.append(self.secret)
        raw = "".join(pieces).upper()
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    def query(self, jd_url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            if self.ticket_state is None or attempt > 1:
                self.refresh_ticket()
            assert self.ticket_state is not None

            timestamp_ms = int(time.time() * 1000)
            params: dict[str, Any] = {
                "method": "getHistoryTrend",
                "key": jd_url,
                "t": timestamp_ms,
            }
            params["token"] = self.make_token(params)

            headers = {"Authorization": self.ticket_state.authorization}
            try:
                resp = self.session.post(API_URL, data=params, headers=headers, timeout=self.timeout)
                if resp.status_code in {401, 403}:
                    last_error = RuntimeError(f"HTTP {resp.status_code}, ticket 可能失效")
                    self.ticket_state = None
                    continue
                resp.raise_for_status()
                text = resp.text.strip()
                if "Authorization" in text and "ticket" in text.lower():
                    last_error = RuntimeError("响应提示授权异常，ticket 可能失效")
                    self.ticket_state = None
                    continue
                return resp.json()
            except Exception as exc:
                last_error = exc
                self.ticket_state = None
                if attempt >= 3:
                    raise
                time.sleep(1.5 * attempt)

        raise RuntimeError(f"慢慢买 API 查询失败: {last_error}")


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    text = re.sub(r"[^\d.]+", "", text)
    try:
        return float(text)
    except ValueError:
        return None


def parse_date_price(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        rows = value
    else:
        text = str(value)
        rows = []
        pattern = re.compile(
            r"\[\s*(\d{10,13})\s*,\s*([0-9.]+|null)\s*,\s*\"((?:\\\"|[^\"])*)\"\s*\]"
        )
        for match in pattern.finditer(text):
            rows.append([match.group(1), match.group(2), match.group(3).replace('\\"', '"')])

    trend: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        ts_raw = row[0]
        price = to_float(row[1])
        promo = str(row[2]) if len(row) > 2 and row[2] is not None else ""
        if price is None:
            continue
        try:
            timestamp = int(float(ts_raw))
        except (TypeError, ValueError):
            timestamp = 0
        trend.append({"timestamp": timestamp, "price": price, "promo": promo})
    return trend


def get_data_payload(api_json: Any) -> dict[str, Any] | None:
    if not isinstance(api_json, dict):
        return None
    data = api_json.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        return data
    return None


def parse_result(target: dict[str, str], api_json: Any) -> dict[str, Any]:
    query_time = now_str()
    data = get_data_payload(api_json)
    if not data:
        if isinstance(api_json, dict):
            error_msg = normalize_text(api_json.get("msg") or api_json.get("message") or "商品不在库或无历史价格")
        else:
            error_msg = f"API返回非对象响应: {repr(api_json)[:120]}"
        return {
            "item_id": target["item_id"],
            "title": target["title"],
            "detail_url": target["detail_url"],
            "current_price": "",
            "lowest_price": "",
            "lowest_date": "",
            "highest_price": "",
            "price_trend": "[]",
            "query_time": query_time,
            "status": "no_result",
            "error_msg": error_msg,
        }

    current_price = to_float(data.get("currentPrice"))
    lowest_price = to_float(data.get("lowerPrice"))
    lowest_date = normalize_text(data.get("lowerDate"))
    trend = parse_date_price(data.get("datePrice"))
    prices = [x["price"] for x in trend if x.get("price") is not None]
    for value in [current_price, lowest_price]:
        if value is not None:
            prices.append(value)
    highest_price = max(prices) if prices else None
    title = normalize_text(data.get("spName")) or target["title"]

    status = "success" if any([current_price is not None, lowest_price is not None, trend]) else "no_result"
    return {
        "item_id": target["item_id"],
        "title": title,
        "detail_url": target["detail_url"],
        "current_price": "" if current_price is None else current_price,
        "lowest_price": "" if lowest_price is None else lowest_price,
        "lowest_date": lowest_date,
        "highest_price": "" if highest_price is None else highest_price,
        "price_trend": json.dumps(trend, ensure_ascii=False, separators=(",", ":")),
        "query_time": query_time,
        "status": status,
        "error_msg": "" if status == "success" else "无有效价格走势数据",
    }


def checkpoint_row(target: dict[str, str]) -> dict[str, str]:
    return {"item_id": target["item_id"], "detail_url": target["detail_url"], "crawl_time": now_str()}


def run(args: argparse.Namespace) -> None:
    targets = build_targets(args.input, args.checkpoint, args.limit)
    print(f"输入: {args.input}")
    print(f"已跳过断点: {len(load_checkpoint(args.checkpoint))}")
    print(f"本次待查询: {len(targets)}")
    if not targets:
        print("没有待查询商品。")
        return

    client = ManmanbuyClient(secret=args.secret, timeout=args.timeout)
    output_buffer: list[dict[str, Any]] = []
    checkpoint_buffer: list[dict[str, Any]] = []

    try:
        client.refresh_ticket()
        print("[OK] ticket 初始化成功")
    except Exception as exc:
        print(f"[ERROR] ticket 初始化失败: {exc}")
        if not args.allow_no_ticket:
            raise

    for index, target in enumerate(targets, start=1):
        print(f"\n[{index}/{len(targets)}] {target['item_id']} {target['title'][:40]}")
        print(f"URL: {target['detail_url']}")
        try:
            api_json = client.query(target["detail_url"])
            row = parse_result(target, api_json)
            print(
                f"[{row['status']}] current={row['current_price'] or '-'} "
                f"lowest={row['lowest_price'] or '-'} date={row['lowest_date'] or '-'}"
            )
        except Exception as exc:
            row = {
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
            print(f"[ERROR] {row['error_msg']}")

        output_buffer.append(row)
        if row.get("status") in {"success", "no_result"}:
            checkpoint_buffer.append(checkpoint_row(target))

        if index % args.save_every == 0:
            append_rows(args.output, output_buffer, OUTPUT_COLUMNS, ["item_id"])
            append_rows(args.checkpoint, checkpoint_buffer, CHECKPOINT_COLUMNS, ["item_id"])
            output_buffer.clear()
            checkpoint_buffer.clear()
            print(f"[OK] 已保存进度到 {args.output}")

        if index < len(targets):
            time.sleep(random.uniform(args.delay_min, args.delay_max))

    append_rows(args.output, output_buffer, OUTPUT_COLUMNS, ["item_id"])
    append_rows(args.checkpoint, checkpoint_buffer, CHECKPOINT_COLUMNS, ["item_id"])
    print(f"\n[OK] 完成。本次处理 {len(targets)} 条。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="慢慢买京东历史价格查询")
    parser.add_argument("--input", type=Path, default=INPUT_CSV, help="输入 merged_products.csv")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV, help="输出 price_history.csv")
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT_CSV, help="断点 crawled_price_items.csv")
    parser.add_argument("--limit", type=int, default=200, help="本次最多处理条数")
    parser.add_argument("--delay-min", type=float, default=5.0, help="请求最小间隔秒")
    parser.add_argument("--delay-max", type=float, default=10.0, help="请求最大间隔秒")
    parser.add_argument("--save-every", type=int, default=10, help="每多少条保存一次")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP 超时秒")
    parser.add_argument("--secret", default=DEFAULT_SECRET, help="慢慢买 token secret")
    parser.add_argument("--allow-no-ticket", action="store_true", help="ticket 初始化失败时仍继续进入循环")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
