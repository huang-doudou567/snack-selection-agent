from __future__ import annotations

import argparse
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from DrissionPage import ChromiumPage
import mmb_cdp_price_history_crawler as base


BASE_DIR = Path(__file__).resolve().parent
INPUT_CSV = BASE_DIR / "merged_products.csv"
OUTPUT_CSV = BASE_DIR / "price_history.csv"
CHECKPOINT_CSV = BASE_DIR / "crawled_price_items.csv"

DEFAULT_DAILY_LIMIT = 50
DEFAULT_LIMIT = 50
DEFAULT_DELAY_MIN = 30.0
DEFAULT_DELAY_MAX = 60.0
DEFAULT_BATCH_SIZE = 10
DEFAULT_BATCH_REST_MIN = 600.0
DEFAULT_BATCH_REST_MAX = 900.0
DEFAULT_TIMEOUT = 60


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def build_targets(input_csv: Path, checkpoint_csv: Path, limit: int | None) -> list[dict[str, str]]:
    df = pd.read_csv(input_csv, dtype=str).fillna("")
    item_col = base.resolve_column(df, ["item_id", "product_id", "SKU", "sku"], required=False)
    title_col = base.resolve_column(df, ["title", "product_title", "商品标题", "name"], required=False)
    url_col = base.resolve_column(df, ["detail_url", "url", "商品链接"], required=True)
    crawled = base.load_checkpoint(checkpoint_csv)

    targets: list[dict[str, str]] = []
    seen: set[str] = set()
    effective_limit = limit if limit is not None else DEFAULT_LIMIT

    for _, row in df.iterrows():
        detail_url = base.clean_text(row.get(url_col, ""))
        if "item.jd.com" not in detail_url:
            continue
        item_id = (
            base.normalize_item_id(row.get(item_col, ""), detail_url)
            if item_col
            else base.normalize_item_id("", detail_url)
        )
        if not item_id or item_id in crawled or item_id in seen:
            continue
        seen.add(item_id)
        targets.append(
            {
                "item_id": item_id,
                "title": base.clean_text(row.get(title_col, "")) if title_col else "",
                "detail_url": detail_url,
            }
        )
        if effective_limit and len(targets) >= effective_limit:
            break
    return targets


def query_one(page: ChromiumPage, target: dict[str, str], timeout_sec: int) -> dict[str, Any]:
    """Delegate to base module — uses the fixed DrissionPage logic."""
    return base.query_one(page, target, timeout_sec)


def build_limit(args: argparse.Namespace) -> int:
    scope, window_start, window_end = base.current_limit_window()
    used_in_window = base.count_rows_in_window(args.output, "query_time", window_start, window_end)
    remaining = max(0, args.daily_limit - used_in_window)
    print(
        "limit_scope="
        f"{scope} window_start={window_start.strftime('%Y-%m-%d %H:%M:%S')} "
        f"window_end={window_end.strftime('%Y-%m-%d %H:%M:%S')} "
        f"used_in_window={used_in_window} daily_limit={args.daily_limit} remaining={remaining}"
    )
    if remaining <= 0:
        return 0
    return min(args.limit, remaining)


def run(args: argparse.Namespace) -> None:
    base.acquire_active_lock("mmb_price_history_batch.py")

    try:
        effective_limit = build_limit(args)
        if effective_limit <= 0:
            print("daily limit reached for current limit window, stopping")
            return

        targets = build_targets(args.input, args.checkpoint, effective_limit)
        print(f"input={args.input}")
        print(f"checkpointed={len(base.load_checkpoint(args.checkpoint))}")
        print(f"pending={len(targets)}")
        if not targets:
            return

        output_buffer: list[dict[str, Any]] = []
        checkpoint_buffer: list[dict[str, str]] = []

        page = base.connect_browser_page()
        print(f"[BROWSER] DrissionPage auto-browser ready")

        try:
            for idx, target in enumerate(targets, start=1):
                base.update_active_lock("mmb_price_history_batch.py")
                print(f"[{idx}/{len(targets)}] {target['item_id']} {target['title'][:50]}")
                print(f"URL: {target['detail_url']}")

                try:
                    row = query_one(page, target, args.timeout)
                    print(
                        f"[{row['status']}] current={row['current_price'] or '-'} "
                        f"lowest={row['lowest_price'] or '-'} date={row['lowest_date'] or '-'}"
                    )
                except base.VerificationRequired as exc:
                    row = base.error_row(target, exc)
                    shot = base.save_screenshot(page, "verification")
                    row["error_msg"] = f"{row['error_msg']} | screenshot={shot}"
                    output_buffer.append(row)
                    base.append_rows(args.output, output_buffer, base.OUTPUT_COLUMNS, "item_id")
                    output_buffer.clear()
                    print(f"[STOP] verification or risk-control page detected, screenshot={shot}")
                    break
                except Exception as exc:
                    row = base.error_row(target, exc)
                    shot = base.save_screenshot(page, "error")
                    row["error_msg"] = f"{row['error_msg']} | screenshot={shot}"
                    output_buffer.append(row)
                    print(f"[STOP] hard failure: {row['error_msg']}")
                    break

                output_buffer.append(row)
                if row["status"] in {"success", "no_result"}:
                    checkpoint_buffer.append(base.checkpoint_row(target))

                if idx % args.save_every == 0:
                    base.append_rows(args.output, output_buffer, base.OUTPUT_COLUMNS, "item_id")
                    base.append_rows(args.checkpoint, checkpoint_buffer, base.CHECKPOINT_COLUMNS, "item_id")
                    output_buffer.clear()
                    checkpoint_buffer.clear()
                    print(f"[SAVE] wrote {args.output}")
                    if idx < len(targets):
                        print(f"[REST] batch rest {args.batch_rest_min:.0f}-{args.batch_rest_max:.0f}s")
                        base.update_active_lock("mmb_price_history_batch.py")
                        time.sleep(random.uniform(args.batch_rest_min, args.batch_rest_max))

                if idx < len(targets) and idx % args.save_every != 0 and row["status"] != "no_result":
                    time.sleep(random.uniform(args.delay_min, args.delay_max))
                elif idx < len(targets) and row["status"] == "no_result":
                    print("[SKIP] no_result, moving to next item immediately")
        finally:
            base.append_rows(args.output, output_buffer, base.OUTPUT_COLUMNS, "item_id")
            base.append_rows(args.checkpoint, checkpoint_buffer, base.CHECKPOINT_COLUMNS, "item_id")
            try:
                page.quit()
            except Exception:
                pass

        print("done")
    finally:
        base.release_active_lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Conservative Manmanbuy price-history crawler for JD items")
    parser.add_argument("--input", type=Path, default=INPUT_CSV, help="merged_products.csv")
    parser.add_argument("--output", type=Path, default=OUTPUT_CSV, help="price_history.csv")
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT_CSV, help="crawled_price_items.csv")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="per-run cap")
    parser.add_argument("--daily-limit", type=int, default=DEFAULT_DAILY_LIMIT, help="daily cap across runs")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="page wait timeout in seconds")
    parser.add_argument("--delay-min", type=float, default=DEFAULT_DELAY_MIN, help="inter-item delay minimum")
    parser.add_argument("--delay-max", type=float, default=DEFAULT_DELAY_MAX, help="inter-item delay maximum")
    parser.add_argument("--batch-rest-min", type=float, default=DEFAULT_BATCH_REST_MIN, help="rest after each batch minimum")
    parser.add_argument("--batch-rest-max", type=float, default=DEFAULT_BATCH_REST_MAX, help="rest after each batch maximum")
    parser.add_argument("--save-every", type=int, default=DEFAULT_BATCH_SIZE, help="flush interval")
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
