# -*- coding: utf-8 -*-
"""Crawl JD search listing pages for snack products (DrissionPage).

The crawler is intentionally conservative: one visible browser, random delays,
incremental CSV saves, and a manual pause when a captcha-like page is detected.
"""

from __future__ import annotations

import argparse
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus, urljoin

import pandas as pd
from DrissionPage import ChromiumPage, ChromiumOptions


SELECTORS = {
    "item_container": [
        '[data-sku].plugin_goodsCardWrapper',
        "div[data-sku]",
        "div.gl-warp > ul > li.gl-item",
        "div#J_goodsList > ul > li.gl-item",
        "li.gl-item",
        '[class*="gl-item"]',
    ],
    "title": [
        '[class*="goods_title"] [title]',
        '[class*="goods_title"] span',
        '[class*="title"] [title]',
        "div.p-name a em",
        'a[class*="p-name"] em',
        'div[class*="name"] em',
        'span[class*="title"]',
    ],
    "price": [
        '[class*="price"]',
        '[class*="Price"]',
        "div.p-price strong i",
        'span[class*="price"]',
        'em[class*="price"]',
    ],
    "original_price": [
        "div.p-price del",
        'del[class*="price"]',
        's[class*="price"]',
    ],
    "promotion_tag": [
        'div.p-market span[class*="tag"]',
        'span[class*="promo"]',
        'i[class*="tag"]',
    ],
    "review_count": [
        "div.p-commit a",
        'span[id*="comment"]',
        'a[class*="commit"]',
    ],
    "sales_text": [
        "div.p-commit strong",
        'span[class*="sale"]',
        'div[class*="sale-count"]',
    ],
    "shop_name": [
        '[class*="shop"]',
        '[class*="Shop"]',
        'span[class*="shop-name"] a',
        "div.p-shop a",
        'a[class*="shop"]',
    ],
    "detail_url": [
        "div.p-name a",
        'a[class*="p-name"]',
        'a[href*="item.jd.com"]',
    ],
    "item_id_pattern": r"item\.jd\.com/(\d+)\.html",
}

CATEGORY_SELECTORS = [
    "#crumb-wrap .crumb .item",
    "div.breadcrumb a",
    'nav[aria-label="breadcrumb"] a',
]

CAPTCHA_INDICATORS = [
    "#captcha",
    'div[class*="captcha"]',
    'iframe[src*="captcha"]',
    'iframe[src*="verify"]',
    'div[class*="slider"]',
    'div[class*="jcap"]',
]


def _iter_selectors(selectors: str | Iterable[str]) -> Iterable[str]:
    if isinstance(selectors, str):
        yield selectors
    else:
        yield from selectors


def output_path_for(keyword: str, output: str | None) -> Path:
    if output:
        return Path(output)
    safe_keyword = re.sub(r'[\\/:*?"<>|]+', "_", keyword).strip() or "jd_snacks"
    return Path(f"raw_listing_{safe_keyword}.csv")


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


def _scroll_page(page: ChromiumPage) -> None:
    amount = random.randint(300, 800)
    page.run_js(f"window.scrollBy(0, {amount})")
    human_delay(1, 3)


def _first_text(container, selectors) -> str:
    for sel in _iter_selectors(selectors):
        try:
            el = container.ele(sel, timeout=1)
            if el:
                text = el.text.strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


def _first_attr(container, selectors, attr: str) -> str:
    for sel in _iter_selectors(selectors):
        try:
            el = container.ele(sel, timeout=1)
            if el:
                value = el.attr(attr)
                if value:
                    return value.strip()
        except Exception:
            continue
    return ""


def _best_title(container, fallback_text: str) -> str:
    title = _first_attr(container, SELECTORS["title"], "title")
    if title:
        return title
    title = _first_text(container, SELECTORS["title"])
    if title:
        return re.sub(r"\s+", "", title)
    for line in fallback_text.splitlines():
        line = line.strip()
        if line and line not in {"广告"} and not line.startswith(("¥", "|")):
            return line
    return ""


def _price_values_from_text(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", text)
    values = []
    for match in re.finditer(r"[¥￥]\s*(\d+(?:\.\d+)?)", compact):
        values.append(match.group(1))
    return values


def _sales_from_text(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    for pattern in [
        r"已售(\d+(?:\.\d+)?(?:万|千|w|W)?\+?)",
        r"(\d+(?:\.\d+)?(?:万|千|w|W)?\+?)已售出",
        r"(\d+(?:\.\d+)?(?:万|千|w|W)?\+?)人已买",
    ]:
        match = re.search(pattern, compact)
        if match:
            return match.group(1).replace("w", "万").replace("W", "万")
    return ""


def _shop_from_text(text: str) -> str:
    for line in reversed([line.strip() for line in text.splitlines() if line.strip()]):
        if line.endswith(("店", "旗舰店", "专营店", "自营旗舰店")):
            return line
    return ""


def _promotions_from_text(text: str) -> str:
    promo_lines = []
    for line in [line.strip() for line in text.splitlines() if line.strip()]:
        if any(token in line for token in ["减", "券", "包邮", "礼金", "立减", "满"]):
            promo_lines.append(line)
    return "|".join(dict.fromkeys(promo_lines))


def _find_items(page: ChromiumPage):
    for sel in SELECTORS["item_container"]:
        items = page.eles(sel)
        if items:
            return items
    return page.eles(SELECTORS["item_container"][0])


def _listing_signature(page: ChromiumPage, limit: int = 8) -> tuple[str, ...]:
    items = _find_items(page)
    sig: list[str] = []
    try:
        for i, item in enumerate(items):
            if i >= limit:
                break
            sku = item.attr("data-sku")
            if not sku:
                text = item.text.strip()
                sku = text[:80]
            if sku:
                sig.append(sku)
    except Exception:
        pass
    return tuple(sig)


def _extract_category_breadcrumb(page: ChromiumPage) -> str:
    for sel in CATEGORY_SELECTORS:
        try:
            els = page.eles(sel)
            crumbs = [e.text.strip() for e in els if e.text.strip()]
            if crumbs:
                return " > ".join(crumbs)
        except Exception:
            continue
    return ""


def _extract_product_info(item, category_breadcrumb: str = "") -> dict[str, str]:
    try:
        item_text = item.text
    except Exception:
        item_text = ""

    data_sku = item.attr("data-sku") or ""
    detail_url = _first_attr(item, SELECTORS["detail_url"], "href")
    if detail_url and not detail_url.startswith("http"):
        detail_url = urljoin("https://item.jd.com/", detail_url)

    match = re.search(SELECTORS["item_id_pattern"], detail_url or "")
    item_id = match.group(1) if match else data_sku
    if item_id and not detail_url:
        detail_url = f"https://item.jd.com/{item_id}.html"

    raw_price = _first_text(item, SELECTORS["price"])
    raw_original = _first_text(item, SELECTORS["original_price"])
    text_prices = _price_values_from_text(item_text)
    price = re.sub(r"[¥￥$\s]", "", raw_price)
    if not re.search(r"\d", price) and text_prices:
        price = text_prices[0]
    original_price = re.sub(r"[¥￥$\s]", "", raw_original)
    if not re.search(r"\d", original_price) and len(text_prices) > 1:
        original_price = text_prices[1]

    return {
        "title": _best_title(item, item_text),
        "price": price,
        "original_price": original_price,
        "promotion_tag": _first_text(item, SELECTORS["promotion_tag"]) or _promotions_from_text(item_text),
        "review_count": _first_text(item, SELECTORS["review_count"]),
        "sales_text": _first_text(item, SELECTORS["sales_text"]) or _sales_from_text(item_text),
        "shop_name": _first_text(item, SELECTORS["shop_name"]) or _shop_from_text(item_text),
        "category_breadcrumb": category_breadcrumb,
        "item_id": item_id,
        "detail_url": detail_url,
        "listing_time": "",
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _check_captcha(page: ChromiumPage) -> bool:
    for sel in CAPTCHA_INDICATORS:
        try:
            if page.ele(sel, timeout=0.5):
                return True
        except Exception:
            continue
    return False


def _handle_captcha(page: ChromiumPage) -> None:  # noqa: ARG001
    print("CAPTCHA DETECTED - solve it manually in the browser window.")
    print("Waiting 60 seconds before checking again...")
    time.sleep(60)
    if _check_captcha(page):
        print("Captcha still appears to be present. Waiting another 60 seconds...")
        time.sleep(60)


def _go_to_next_page(page: ChromiumPage) -> bool:
    before_url = page.url
    before_sig = _listing_signature(page)
    page.run_js("window.scrollTo(0, document.documentElement.scrollHeight)")
    human_delay(0.8, 1.4)

    next_selectors = [
        'div[class*="_pagination_next"]',
        'div[class*="pagination_next"]',
        'a[class*="pg-next"]',
        'a[class*="next"]',
        '#J_bottomPage span[class*="next"]',
        "div.p-wrap a.p-next",
    ]
    for sel in next_selectors:
        try:
            btn = page.ele(sel, timeout=2)
            if not btn or not btn.states.is_displayed:
                continue
            classes = btn.attr("class") or ""
            if "disabled" in classes or "pg-disabled" in classes:
                return False
            btn.click()
            for _ in range(30):
                human_delay(0.4, 0.7)
                try:
                    after_sig = _listing_signature(page)
                    if page.url != before_url or (after_sig and after_sig != before_sig):
                        human_delay(1, 2)
                        return True
                except Exception:
                    continue
        except Exception:
            continue

    match = re.search(r"([?&]page=)(\d+)", page.url)
    if match:
        page_num = int(match.group(2))
        next_url = re.sub(r"([?&]page=)\d+", rf"\g<1>{page_num + 1}", page.url)
        page.get(next_url)
        human_delay(2, 3)
        return True

    return False


def _save_products(products: list[dict[str, str]], output: Path) -> None:
    if not products:
        return
    pd.DataFrame(products).to_csv(output, index=False, encoding="utf-8-sig")


def crawl_jd_listing(
    keyword: str,
    max_pages: int = 50,
    save_interval: int = 10,
    output: str | None = None,
    headless: bool = False,
    user_data_dir: str | None = None,
    start_url: str | None = None,
) -> Path:
    output_path = output_path_for(keyword, output)
    all_products: list[dict[str, str]] = []
    page = _make_browser_page(user_data_dir=user_data_dir)

    try:
        if start_url:
            entry_url = start_url
        else:
            encoded_keyword = quote_plus(keyword)
            entry_url = f"https://search.jd.com/Search?keyword={encoded_keyword}&enc=utf-8&wq={encoded_keyword}"

        page.get(entry_url)
        human_delay(2, 4)

        category_breadcrumb = _extract_category_breadcrumb(page)

        for page_num in range(1, max_pages + 1):
            print(f"Crawling page {page_num}...")

            if _check_captcha(page):
                _handle_captcha(page)

            for _ in range(3):
                _scroll_page(page)

            try:
                page.wait.load_complete()
            except Exception:
                pass

            items = _find_items(page)
            item_count = len(items)
            print(f"  Found {item_count} listing cards.")

            for i, item in enumerate(items):
                try:
                    item.scroll_into_view()
                    human_delay(0.2, 0.6)
                    product = _extract_product_info(item, category_breadcrumb)
                    if product["item_id"] or product["title"]:
                        all_products.append(product)
                        print(f"  OK {product['item_id'] or '-'} {product['title'][:40]}")
                except Exception as exc:
                    print(f"  Failed to extract item {i}: {exc}")

            if page_num % save_interval == 0:
                _save_products(all_products, output_path)
                print(f"  Saved {len(all_products)} records to {output_path}")

            if page_num < max_pages:
                if not _go_to_next_page(page):
                    print("Reached the last page.")
                    break

    finally:
        _save_products(all_products, output_path)
        page.quit()

    print(f"Saved {len(all_products)} records to {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl JD snack listing pages.")
    parser.add_argument("keyword", nargs="?", default=None, help="Search keyword, e.g. 坚果礼盒")
    parser.add_argument("--keyword", dest="keyword_flag", help="Search keyword")
    parser.add_argument("--max-pages", type=int, default=50, help="Maximum pages to crawl")
    parser.add_argument("--save-interval", type=int, default=10, help="Save every N pages")
    parser.add_argument("--output", "-o", help="Output CSV path")
    parser.add_argument("--headless", action="store_true", help="Run Chromium headless")
    parser.add_argument("--user-data-dir", help="Persistent browser profile directory for a logged-in JD session")
    parser.add_argument("--url", help="Start from a JD category/list page URL instead of a search URL")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    keyword = args.keyword_flag or args.keyword or input("请输入搜索关键词: ").strip() or "坚果礼盒"
    crawl_jd_listing(
        keyword=keyword,
        max_pages=args.max_pages,
        save_interval=args.save_interval,
        output=args.output,
        headless=args.headless,
        user_data_dir=args.user_data_dir,
        start_url=args.url,
    )


if __name__ == "__main__":
    main()
