# -*- coding: utf-8 -*-
"""Fast crawler for JD React-style search result pages (DrissionPage)."""

from __future__ import annotations

import argparse
import random
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import pandas as pd
from DrissionPage import ChromiumPage, ChromiumOptions


CARD_SELECTOR = "[data-sku].plugin_goodsCardWrapper, div[data-sku]"
NEXT_SELECTOR = 'div[class*="_pagination_next"], div[class*="pagination_next"]'

AD_TEXT = "广告"
SOLD_TEXT = "已售"
CURRENCY_LINES = {"¥", "￥"}
PROMO_TOKENS = [
    "首购礼金",
    "官方直降",
    "券",
    "包邮",
    "已补",
    "折",
    "满",
]
SHOP_TOKENS = [
    "旗舰店",
    "自营",
    "专营店",
    "专卖店",
    "店",
]


def human_delay(min_sec: float = 0.5, max_sec: float = 1.2) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def clean_price(value: str) -> str:
    value = re.sub(r"[^\d.]", "", value or "")
    parts = value.split(".")
    if len(parts) > 2:
        value = parts[0] + "." + "".join(parts[1:])
    return value


def extract_prices(lines: list[str]) -> tuple[str, str]:
    prices: list[str] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped in CURRENCY_LINES:
            pieces: list[str] = []
            for next_line in lines[idx + 1 : idx + 5]:
                part = next_line.strip()
                if re.fullmatch(r"\d+|\.", part):
                    pieces.append(part)
                else:
                    break
            price = clean_price("".join(pieces))
            if price:
                prices.append(price)
        elif stripped.startswith(("¥", "￥")):
            price = clean_price(stripped)
            if price:
                prices.append(price)
    deduped = list(dict.fromkeys(prices))
    current = deduped[0] if deduped else ""
    original = deduped[1] if len(deduped) > 1 else ""
    return current, original


def extract_sales(lines: list[str]) -> str:
    for line in lines:
        compact = re.sub(r"\s+", "", line)
        match = re.search(r"已售([0-9.]+(?:万|千|w|W)?\+?)", compact)
        if match:
            return match.group(1).replace("w", "万").replace("W", "万")
    return ""


def extract_shop(lines: list[str]) -> str:
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and any(token in stripped for token in SHOP_TOKENS):
            return stripped
    return ""


def extract_promotions(lines: list[str]) -> str:
    promos = []
    for line in lines:
        stripped = line.strip()
        if stripped and any(token in stripped for token in PROMO_TOKENS):
            promos.append(stripped)
    return "|".join(dict.fromkeys(promos))


def extract_title(lines: list[str], title_attr: str = "") -> str:
    if title_attr:
        return re.sub(r"\s+", " ", title_attr).strip()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == AD_TEXT:
            continue
        if stripped in CURRENCY_LINES or stripped.startswith(("¥", "￥")):
            break
        if SOLD_TEXT in stripped:
            continue
        if stripped.startswith("|") or stripped in {"|"}:
            continue
        if any(token in stripped for token in PROMO_TOKENS):
            continue
        return stripped
    return ""


def normalize_card(raw: dict, page_number: int, source_url: str) -> dict[str, str]:
    text = raw.get("text") or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    item_id = str(raw.get("sku") or "").strip()
    hrefs = [href for href in raw.get("hrefs", []) if href]
    detail_url = ""
    for href in hrefs:
        if "item.jd.com" in href:
            detail_url = href
            break
    if detail_url and not detail_url.startswith("http"):
        detail_url = urljoin("https://item.jd.com/", detail_url)
    if not item_id and detail_url:
        match = re.search(r"item\.jd\.com/(\d+)\.html", detail_url)
        item_id = match.group(1) if match else ""
    if item_id and not detail_url:
        detail_url = f"https://item.jd.com/{item_id}.html"

    price, original_price = extract_prices(lines)
    return {
        "title": extract_title(lines, raw.get("title") or ""),
        "price": price,
        "original_price": original_price,
        "promotion_tag": extract_promotions(lines),
        "review_count": "",
        "sales_text": extract_sales(lines),
        "shop_name": extract_shop(lines),
        "category_breadcrumb": "",
        "item_id": item_id,
        "detail_url": detail_url,
        "listing_time": "",
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_page_number": str(page_number),
        "source_url": source_url,
    }


def load_all_cards(page: ChromiumPage) -> None:
    stable_rounds = 0
    last_count = -1
    for _ in range(24):
        cards = page.eles(CARD_SELECTOR)
        count = len(cards) if cards else 0
        at_bottom = page.run_js(
            "() => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 40"
        )
        if count == last_count and at_bottom:
            stable_rounds += 1
        else:
            stable_rounds = 0
        if stable_rounds >= 2:
            break
        last_count = count
        page.run_js("window.scrollBy(0, Math.floor(window.innerHeight * 0.82))")
        human_delay(0.35, 0.8)


def page_signature(page: ChromiumPage) -> tuple[str, ...]:
    values = page.run_js(
        f"""() => [...document.querySelectorAll({CARD_SELECTOR!r})]
            .slice(0, 8)
            .map(e => e.getAttribute('data-sku') || (e.innerText || '').slice(0, 60))"""
    )
    return tuple(str(v) for v in values if v)


def extract_current_page(page: ChromiumPage, page_number: int, source_url: str) -> list[dict[str, str]]:
    raw_cards = page.run_js(
        f"""() => [...document.querySelectorAll({CARD_SELECTOR!r})].map(e => ({{
            sku: e.getAttribute('data-sku') || '',
            text: e.innerText || '',
            title: (e.querySelector('[title]') && e.querySelector('[title]').getAttribute('title')) || '',
            hrefs: [...e.querySelectorAll('a[href]')].map(a => a.href)
        }}))"""
    )
    seen: set[str] = set()
    products: list[dict[str, str]] = []
    for raw in raw_cards:
        product = normalize_card(raw, page_number, source_url)
        key = product["item_id"] or product["title"]
        if key and key not in seen:
            seen.add(key)
            products.append(product)
    return products


def click_next_page(page: ChromiumPage) -> bool:
    before = page_signature(page)
    page.run_js("window.scrollTo(0, document.documentElement.scrollHeight)")
    human_delay(1.0, 1.8)

    next_btn = page.ele(NEXT_SELECTOR, timeout=3)
    if not next_btn:
        clicked = page.run_js(
            """() => {
                const candidates = [...document.querySelectorAll('div, a, button')]
                  .filter(e => (e.innerText || '').trim() === '下一页');
                for (const e of candidates) {
                  const r = e.getBoundingClientRect();
                  const cls = typeof e.className === 'string' ? e.className : '';
                  if (r.width > 0 && r.height > 0 && !cls.includes('disabled')) {
                    e.click();
                    return true;
                  }
                }
                return false;
            }"""
        )
        if not clicked:
            print("  next button not found.")
            page.get_screenshot(path="jd_search_next_not_found.png", full_page=False)
            return False
    else:
        classes = next_btn.attr("class") or ""
        if "disabled" in classes:
            print("  next button is disabled.")
            page.get_screenshot(path="jd_search_next_disabled.png", full_page=False)
            return False
        next_btn.click()

    for _ in range(36):
        human_delay(0.55, 0.9)
        if is_verification_page(page):
            print("  verification page detected after clicking next.")
            page.get_screenshot(path="jd_search_next_verification.png", full_page=False)
            return False
        after = page_signature(page)
        if after and after != before:
            human_delay(0.8, 1.4)
            return True
    print("  next click did not change listing signature.")
    page.get_screenshot(path="jd_search_next_no_change.png", full_page=False)
    return False


def is_verification_page(page: ChromiumPage) -> bool:
    title = page.title
    if "验证" in title:
        return True
    try:
        body_text = page.ele("body").text
    except Exception:
        return False
    return "拖动箭头" in body_text or "安全验证" in body_text


def wait_for_manual_verification(page: ChromiumPage, expected_url: str, label: str, timeout_sec: int = 600) -> bool:
    print("  verification page detected; please solve it in the browser window.")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        human_delay(2.5, 4.0)
        if is_verification_page(page):
            continue
        if same_search_keyword_url(page.url, expected_url):
            cards = page.eles(CARD_SELECTOR)
            if cards:
                print("  verification resolved; search listing is back.")
                return True
        try:
            page.get(expected_url)
            human_delay(3, 5)
            if not is_verification_page(page):
                cards = page.eles(CARD_SELECTOR)
                if cards:
                    print("  verification resolved after returning to the provided URL.")
                    return True
        except Exception:
            pass
    print("  manual verification wait timed out.")
    page.get_screenshot(path=f"jd_search_{label}_verification_timeout.png", full_page=False)
    return False


def wait_for_cards_or_stop(page: ChromiumPage, expected_url: str, label: str, timeout_ms: int = 45000) -> bool:
    print(f"  current url: {page.url}")
    print(f"  title: {page.title}")
    if is_verification_page(page):
        if not wait_for_manual_verification(page, expected_url, label):
            return False
    if not same_search_keyword_url(page.url, expected_url):
        print("  URL changed away from the provided search keyword page; stopping.")
        page.get_screenshot(path=f"jd_search_{label}_url_changed.png", full_page=False)
        return False

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        cards = page.eles(CARD_SELECTOR)
        if cards:
            print(f"  listing cards ready: {len(cards)}")
            return True
        page.run_js("window.scrollBy(0, Math.floor(window.innerHeight * 0.55))")
        human_delay(0.8, 1.4)
        if is_verification_page(page):
            if not wait_for_manual_verification(page, expected_url, label):
                return False

    try:
        body_text = page.ele("body").text.strip().replace("\n", " ")[:500]
    except Exception:
        body_text = ""
    print(f"  no listing cards after waiting. body preview: {body_text}")
    page.get_screenshot(path=f"jd_search_{label}_no_cards.png", full_page=False)
    return False


def same_search_keyword_url(actual_url: str, expected_url: str) -> bool:
    actual = urlsplit(actual_url)
    expected = urlsplit(expected_url)
    if actual.netloc != expected.netloc or actual.path != expected.path:
        return False
    actual_query = parse_qs(actual.query)
    expected_query = parse_qs(expected.query)
    return actual_query.get("keyword") == expected_query.get("keyword")


def click_sales_sort(page: ChromiumPage, expected_url: str) -> bool:
    print("Clicking sales sort...")
    page.run_js("window.scrollTo(0, 0)")
    human_delay(0.8, 1.4)
    before = page_signature(page)
    clicked = page.run_js(
        """() => {
            const targetText = '销量';
            const candidates = [...document.querySelectorAll('a, button, div, span')]
              .filter(e => (e.innerText || '').trim() === targetText);
            for (const e of candidates) {
              const r = e.getBoundingClientRect();
              if (r.width > 0 && r.height > 0) {
                e.click();
                return true;
              }
            }
            return false;
        }"""
    )
    if not clicked:
        print("  sales sort control not found.")
        page.get_screenshot(path="jd_search_sales_sort_not_found.png", full_page=False)
        return False

    for _ in range(36):
        human_delay(0.55, 0.9)
        if is_verification_page(page):
            print("  verification page detected after clicking sales sort.")
            page.get_screenshot(path="jd_search_sales_sort_verification.png", full_page=False)
            return False
        if not same_search_keyword_url(page.url, expected_url):
            print(f"  sales sort changed away from the provided search page: {page.url}")
            page.get_screenshot(path="jd_search_sales_sort_url_changed.png", full_page=False)
            return False
        cards = page.eles(CARD_SELECTOR)
        after = page_signature(page)
        if cards and (after != before or page.url != expected_url):
            print(f"  sales sort ready. current url: {page.url}")
            print(f"  listing cards after sales sort: {len(cards)}")
            return True

    cards = page.eles(CARD_SELECTOR)
    if cards:
        print("  sales sort click completed without a visible SKU change; continuing with current sorted page.")
        return True
    print("  sales sort click did not produce listing cards.")
    page.get_screenshot(path="jd_search_sales_sort_no_cards.png", full_page=False)
    return False


def save_rows(rows: list[dict[str, str]], output: Path) -> None:
    if rows:
        pd.DataFrame(rows).to_csv(output, index=False, encoding="utf-8-sig")


def crawl_search_page(
    url: str,
    output: Path,
    max_pages: int,
    user_data_dir: str,
    start_page: int = 1,
    click_sales: bool = False,
    headless: bool = False,
) -> Path:
    all_rows: list[dict[str, str]] = []

    co = ChromiumOptions()
    co.set_user_data_path(str(Path(user_data_dir).resolve()))
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-software-rasterizer")
    co.auto_port()
    page = ChromiumPage(co)

    try:
        page.get("https://www.jd.com/")
        human_delay(2, 4)
        page.get(url)
        human_delay(3, 5)
        if not wait_for_cards_or_stop(page, url, "entry"):
            return output
        if click_sales and not click_sales_sort(page, url):
            return output
        if start_page > 1:
            print(f"Skipping to search page {start_page}...")
            for page_number in range(1, start_page):
                if is_verification_page(page):
                    print("  verification page detected; stopping for manual handling.")
                    return output
                load_all_cards(page)
                cards = page.eles(CARD_SELECTOR)
                print(f"  skip page {page_number}, cards={len(cards) if cards else 0}")
                if not click_next_page(page):
                    print(f"  failed to reach page {page_number + 1}; stopping.")
                    return output
                print(f"  reached page {page_number + 1}")

        end_page = start_page + max_pages - 1
        for page_number in range(start_page, end_page + 1):
            if is_verification_page(page):
                print("  verification page detected; stopping for manual handling.")
                break
            print(f"Crawling search page {page_number}...")
            load_all_cards(page)
            products = extract_current_page(page, page_number, page.url)
            all_rows.extend(products)
            save_rows(all_rows, output)
            unique_count = pd.Series([row["item_id"] for row in all_rows if row["item_id"]]).nunique()
            print(f"  page rows={len(products)}, total rows={len(all_rows)}, unique sku={unique_count}")
            if page_number >= end_page:
                break
            if not click_next_page(page):
                print("  no next page or page did not change; stopping.")
                break
    finally:
        save_rows(all_rows, output)
        page.quit()
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl JD search pages with bottom pagination.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", default="raw_listing_snack_gold_search.csv")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--click-sales", action="store_true")
    parser.add_argument("--user-data-dir", default=".jd_playwright_profile")
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawl_search_page(
        url=args.url,
        output=Path(args.output),
        max_pages=args.max_pages,
        user_data_dir=args.user_data_dir,
        start_page=args.start_page,
        click_sales=args.click_sales,
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
