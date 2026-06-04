# -*- coding: utf-8 -*-
"""Crawl negative JD product reviews for top-selling listing rows (DrissionPage)."""

from __future__ import annotations

import argparse
import random
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from DrissionPage import ChromiumPage, ChromiumOptions

from preprocess_jd_listing import parse_sales_main


REVIEW_SELECTORS = {
    "review_tab": [
        "div#detail > div.tab-main > ul > li:nth-child(2)",
        'div.comment-tag-list a:has-text("商品评价")',
        'a[href*="#comment"]',
        'li[data-tab="comment"]',
    ],
    "negative_filter": [
        'div.filter-list a:has-text("差评")',
        'span[data-type="bad"]',
        'a[href*="type=bad"]',
        "div.comment-filter a:nth-child(3)",
    ],
    "review_item": [
        "div.comment-item",
        "div.J-comment-list > div",
        "li.comment-item",
    ],
    "review_text": [
        "div.comment-con",
        "p.comment-content",
        "div.comment-text",
        'span[itemprop="description"]',
    ],
    "review_rating": [
        "span.star",
        "div.star",
        "i.star-level",
        'span[class*="rating"]',
    ],
    "next_page": [
        "div.comment-page a.next",
        "a.pg-next",
        'span[class*="next"]',
    ],
}


def _make_browser_page(user_data_dir: str | None = None) -> ChromiumPage:
    co = ChromiumOptions()
    if user_data_dir:
        co.set_user_data_path(str(Path(user_data_dir).resolve()))
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-software-rasterizer")
    co.auto_port()
    return ChromiumPage(co)


def human_delay(min_sec: float = 2, max_sec: float = 5) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def _first_text(container, selectors: list[str]) -> str:
    for sel in selectors:
        try:
            el = container.ele(sel, timeout=1)
            if el:
                text = el.text.strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


def _click_first(page: ChromiumPage, selectors: list[str]) -> bool:
    for sel in selectors:
        try:
            el = page.ele(sel, timeout=2)
            if el and el.states.is_displayed:
                el.click()
                human_delay(1, 3)
                return True
        except Exception:
            continue
    return False


def _parse_rating(class_name: str, text: str = "") -> int | None:
    match = re.search(r"star[_-]?(\d)", class_name or "")
    if match:
        return int(match.group(1))
    match = re.search(r"(\d)\s*星", text or "")
    if match:
        return int(match.group(1))
    return None


def _extract_negative_reviews(page: ChromiumPage, item_id: str, max_pages: int = 3) -> list[dict]:
    reviews: list[dict] = []
    base_url = f"https://item.jd.com/{item_id}.html"

    try:
        page.get(base_url)
        human_delay(2, 4)

        if not _click_first(page, REVIEW_SELECTORS["review_tab"]):
            review_url = (
                "https://sclub.jd.com/comment/productPageComments.action"
                f"?productId={item_id}&score=1&sortType=5&page=0&pageSize=10"
            )
            page.get(review_url)
            human_delay(2, 3)

        _click_first(page, REVIEW_SELECTORS["negative_filter"])

        for page_num in range(max_pages):
            print(f"  Crawling negative review page {page_num + 1}...")
            try:
                page.wait.load_complete()
            except Exception:
                pass
            human_delay(1, 2)

            found_items = False
            review_cards = []
            for sel in REVIEW_SELECTORS["review_item"]:
                review_cards = page.eles(sel)
                if review_cards:
                    found_items = True
                    break

            for card in review_cards:
                review_text = _first_text(card, REVIEW_SELECTORS["review_text"])
                rating = None
                for rs in REVIEW_SELECTORS["review_rating"]:
                    try:
                        re_el = card.ele(rs, timeout=1)
                        if re_el:
                            rating = _parse_rating(
                                re_el.attr("class") or "",
                                re_el.text,
                            )
                            break
                    except Exception:
                        continue
                if review_text and (rating is None or rating <= 2):
                    reviews.append({
                        "item_id": item_id,
                        "review_text": review_text,
                        "review_rating": rating if rating is not None else "",
                        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })

            if not found_items:
                print("  No review cards found on this page.")

            if page_num < max_pages - 1:
                if not _click_first(page, REVIEW_SELECTORS["next_page"]):
                    print("  No next button found; stopping this product.")
                    break
                human_delay(5, 10)

    except Exception as exc:
        print(f"  Failed to crawl {item_id}: {exc}")

    return reviews


def select_top_products(input_csv: str, top_n: int) -> pd.DataFrame:
    df = pd.read_csv(input_csv, dtype={"item_id": "string"})
    if "item_id" not in df.columns:
        raise KeyError("Input CSV must contain item_id.")
    if "sales_text" not in df.columns:
        df["sales_text"] = ""
    df["sales_sort"] = df["sales_text"].apply(parse_sales_main)
    df = df[df["item_id"].notna() & (df["item_id"].astype(str).str.len() > 0)]
    return df.sort_values("sales_sort", ascending=False).drop_duplicates("item_id").head(top_n)


def crawl_negative_reviews(
    input_csv: str,
    top_n: int = 20,
    output: str = "negative_reviews.csv",
    review_pages: int = 3,
    headless: bool = False,
    user_data_dir: str | None = None,
) -> Path:
    top_products = select_top_products(input_csv, top_n)
    print(f"Selected top {len(top_products)} products by sales_text.")

    all_reviews: list[dict] = []
    page = _make_browser_page(user_data_dir=user_data_dir)

    try:
        for idx, (_, row) in enumerate(top_products.iterrows(), 1):
            item_id = str(row["item_id"]).strip()
            title = str(row.get("title", ""))[:50]
            print(f"\n[{idx}/{len(top_products)}] Crawling {item_id} {title}")
            reviews = _extract_negative_reviews(page, item_id, max_pages=review_pages)
            all_reviews.extend(reviews)
            print(f"  Collected {len(reviews)} reviews.")
            human_delay(5, 10)
    finally:
        page.quit()

    output_path = Path(output)
    pd.DataFrame(all_reviews).to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Saved {len(all_reviews)} reviews to {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl negative JD reviews.")
    parser.add_argument("--input", "-i", default="raw_listing_坚果礼盒.csv", help="Listing CSV from step 1")
    parser.add_argument("--top-n", type=int, default=20, help="Number of top products to crawl")
    parser.add_argument("--review-pages", type=int, default=3, help="Review pages per product")
    parser.add_argument("--output", "-o", default="negative_reviews.csv", help="Output CSV")
    parser.add_argument("--headless", action="store_true", help="Run Chromium headless")
    parser.add_argument("--user-data-dir", help="Persistent browser profile directory for a logged-in JD session")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawl_negative_reviews(
        input_csv=args.input,
        top_n=args.top_n,
        output=args.output,
        review_pages=args.review_pages,
        headless=args.headless,
        user_data_dir=args.user_data_dir,
    )


if __name__ == "__main__":
    main()
