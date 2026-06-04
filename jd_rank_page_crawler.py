# -*- coding: utf-8 -*-
"""Crawl JD pro/rank pages that expose products in window.__react_data__ (DrissionPage)."""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import pandas as pd
from DrissionPage import ChromiumPage, ChromiumOptions


def set_query_param(url: str, key: str, value: str | int) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query[key] = [str(value)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


def set_query_params(url: str, values: dict[str, str | int]) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    for key, value in values.items():
        query[key] = [str(value)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


def normalize_price(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return match.group(0) if match else text


def extract_review_count(tags: list[dict]) -> str:
    for tag in tags or []:
        text = str(tag.get("text", ""))
        match = re.search(r"(\d+(?:\.\d+)?(?:万|千)?\+?)\s*人评价", text)
        if match:
            return match.group(1)
    return ""


def joined_tag_text(tags: list[dict]) -> str:
    values = []
    for tag in tags or []:
        text = str(tag.get("text") or tag.get("name") or "").strip()
        if text:
            values.append(text)
    return "|".join(dict.fromkeys(values))


def price_info(product: dict) -> tuple[str, str, str]:
    price = product.get("price") or {}
    if not isinstance(price, dict):
        price = {}
    current = (
        price.get("purchasePrice")
        or price.get("jdPrice")
        or price.get("dailyPrice")
        or price.get("finalPrice")
        or product.get("purchasePrice")
        or product.get("jdPrice")
        or product.get("price")
        or ""
    )
    original = price.get("dailyPrice") or price.get("jdPrice") or product.get("jdPrice") or ""
    promo_parts = [
        price.get("lowestPriceDayDesc", ""),
        f"补贴{price.get('subsidy')}" if price.get("subsidy") else "",
    ]
    return normalize_price(current), normalize_price(original), "|".join([p for p in promo_parts if p])


def product_to_record(product: dict, category_path: str, page_url: str) -> dict[str, str]:
    sku = str(product.get("skuId") or product.get("mainSkuId") or product.get("sku") or "").strip()
    current_price, original_price, price_tags = price_info(product)

    promotion_tags = [
        joined_tag_text(product.get("skuPromotionTags") or []),
        joined_tag_text(product.get("promotionBenefits") or []),
        price_tags,
        joined_tag_text(product.get("skuServiceIconList") or []),
    ]

    sales_text = joined_tag_text(product.get("skuBenefitTags") or [])
    review_count = extract_review_count(product.get("skuInfoTags") or [])

    return {
        "title": str(product.get("name") or product.get("skuTitle") or product.get("title") or "").strip(),
        "price": current_price,
        "original_price": original_price,
        "promotion_tag": "|".join([p for p in promotion_tags if p]),
        "review_count": review_count,
        "sales_text": sales_text,
        "shop_name": str(product.get("shopName") or product.get("storeName") or product.get("storeId") or "").strip(),
        "category_breadcrumb": category_path,
        "item_id": sku,
        "detail_url": f"https://item.jd.com/{sku}.html" if sku else "",
        "listing_time": "",
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_url": page_url,
        "rank_num": product.get("rankNum") or product.get("rank") or "",
        "spu_id": product.get("spuId", ""),
    }


def find_product_dicts(value) -> list[dict]:
    """Find product-like dicts in JD rank API/React payloads."""
    found: list[dict] = []
    if isinstance(value, dict):
        sku = value.get("skuId") or value.get("mainSkuId") or value.get("sku")
        title = value.get("name") or value.get("skuTitle") or value.get("title")
        if sku and title:
            found.append(value)
        for child in value.values():
            found.extend(find_product_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_product_dicts(child))
    return found


def dedupe_products(products: list[dict]) -> list[dict]:
    by_sku: dict[str, dict] = {}
    for product in products:
        sku = str(product.get("skuId") or product.get("mainSkuId") or product.get("sku") or "").strip()
        if sku:
            by_sku[sku] = product
    return list(by_sku.values())


def extract_product_list(react_data: dict) -> tuple[list[dict], str]:
    page_data = react_data.get("pageData") or {}
    activity_data = react_data.get("activityData") or {}
    floor_list = page_data.get("floorList") or []

    category_parts = [str(activity_data.get("title") or "京东排行榜")]
    products: list[dict] = []

    for floor in floor_list:
        result = (((floor.get("providerData") or {}).get("result")) or {})
        if result.get("productList"):
            products.extend(result.get("productList") or [])
            head = result.get("head") or {}
            tab_map = head.get("rankPageTabListMap") or {}
            title = None
            try:
                title = tab_map.get("allSubTab", [{}])[0].get("rankTypeTabs", [{}])[0].get("bodyMateria", {}).get("title")
            except Exception:
                title = None
            if title:
                category_parts.append(str(title))

    if not products:
        products = find_product_dicts(react_data)
    return dedupe_products(products), " > ".join(dict.fromkeys([p for p in category_parts if p]))


def clean_rank_label(tab: dict) -> str:
    body_title = ((tab.get("bodyMateria") or {}).get("title") or "").strip()
    for prefix in ["主体-", "主题-"]:
        if body_title.startswith(prefix):
            body_title = body_title[len(prefix) :]
    if body_title:
        return body_title

    entry_title = str(tab.get("channelEntryTitle") or "").strip()
    for suffix in ["热卖榜", "好评榜", "回购榜", "复购榜", "折扣榜", "新品榜", "PLUS省钱榜"]:
        if entry_title.endswith(suffix):
            return "回购榜" if suffix == "复购榜" else suffix
    return entry_title or str(tab.get("rankType") or "")


def discover_rank_tabs(react_data: dict) -> list[dict[str, str]]:
    page_data = react_data.get("pageData") or {}
    floor_list = page_data.get("floorList") or []
    for floor in floor_list:
        result = (((floor.get("providerData") or {}).get("result")) or {})
        head = result.get("head") or {}
        tab_map = head.get("rankPageTabListMap") or {}
        all_subtabs = tab_map.get("allSubTab") or []
        if not all_subtabs:
            continue

        selected_subtab = next((tab for tab in all_subtabs if str(tab.get("selected")) == "1"), all_subtabs[0])
        rank_tabs = selected_subtab.get("rankTypeTabs") or []
        discovered = []
        for tab in rank_tabs:
            rank_id = str(tab.get("rankId") or "").strip()
            rank_type = str(tab.get("rankType") or "").strip()
            if not rank_id or not rank_type:
                continue
            discovered.append({
                "rank_id": rank_id,
                "rank_type": rank_type,
                "rank_label": clean_rank_label(tab),
                "channel_entry_title": str(tab.get("channelEntryTitle") or "").strip(),
                "subtab": str(selected_subtab.get("tabName") or "").strip(),
            })
        if discovered:
            return discovered
    return []


def wait_for_react_rank_data(page: ChromiumPage, timeout_sec: int = 30, require_tabs: bool = False) -> dict | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        data = page.run_js("() => window.__react_data__ || null")
        if data:
            products, _ = extract_product_list(data)
            tabs = discover_rank_tabs(data)
            if require_tabs and tabs:
                return data
            if not require_tabs and (products or tabs):
                return data
        time.sleep(1)
    return page.run_js("() => window.__react_data__ || null")


def crawl_rank_page(
    start_url: str,
    max_pages: int = 20,
    output: str = "raw_listing_京东排行榜.csv",
    user_data_dir: str = ".jd_playwright_profile",
    headless: bool = False,
) -> Path:
    output_path = Path(output)
    all_records: list[dict[str, str]] = []

    co = ChromiumOptions()
    co.set_user_data_path(str(Path(user_data_dir).resolve()))
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-software-rasterizer")
    co.auto_port()
    page = ChromiumPage(co)

    try:
        seen_page_signatures: set[tuple[str, ...]] = set()
        for page_num in range(1, max_pages + 1):
            page_url = set_query_param(start_url, "pageNum", page_num)
            print(f"Crawling rank page {page_num}: {page_url}")
            page.get(page_url)
            time.sleep(random.randint(5, 8))
            for _ in range(3):
                page.run_js("window.scrollBy(0, 900)")
                time.sleep(random.uniform(0.7, 1.3))

            title = page.title
            if "验证" in title:
                print("CAPTCHA/verification page detected. Please solve it in the browser window.")
                time.sleep(60)

            react_data = page.run_js("() => window.__react_data__ || null")
            if not react_data:
                print("  No window.__react_data__ found; stopping.")
                break

            products, category_path = extract_product_list(react_data)
            print(f"  Found {len(products)} products.")
            if not products:
                break

            page_signature_ = tuple(
                str(product.get("skuId") or product.get("mainSkuId") or "") for product in products
            )
            if page_signature_ in seen_page_signatures:
                print("  Page data repeated; stopping because this URL does not expose pageNum pagination.")
                break
            seen_page_signatures.add(page_signature_)

            page_records = [product_to_record(product, category_path, page_url) for product in products]
            all_records.extend(page_records)
            pd.DataFrame(all_records).drop_duplicates(subset=["item_id"], keep="last").to_csv(
                output_path, index=False, encoding="utf-8-sig"
            )
            print(f"  Saved {len(all_records)} cumulative rows to {output_path}")

            time.sleep(random.uniform(2.5, 4.5))
    finally:
        page.quit()

    if all_records:
        df = pd.DataFrame(all_records).drop_duplicates(subset=["item_id"], keep="last")
    else:
        df = pd.DataFrame(columns=[
            "title", "price", "original_price", "promotion_tag", "review_count",
            "sales_text", "shop_name", "category_breadcrumb", "item_id",
            "detail_url", "listing_time", "crawl_time",
        ])
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Final saved rows: {len(df)} -> {output_path}")
    return output_path


def crawl_rank_tabs(
    start_url: str,
    output: str = "raw_listing_京东排行榜_tabs.csv",
    user_data_dir: str = ".jd_playwright_profile",
    headless: bool = False,
) -> Path:
    output_path = Path(output)
    all_records: list[dict[str, str]] = []

    co = ChromiumOptions()
    co.set_user_data_path(str(Path(user_data_dir).resolve()))
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-software-rasterizer")
    co.auto_port()
    page = ChromiumPage(co)

    try:
        print(f"Opening source rank page: {start_url}")
        page.get(start_url)
        time.sleep(random.randint(5, 8))
        source_data = wait_for_react_rank_data(page, timeout_sec=45, require_tabs=True)
        if not source_data:
            raise RuntimeError("No window.__react_data__ found on the source page.")

        tabs = discover_rank_tabs(source_data)
        if not tabs:
            tabs = [
                {"rank_id": "3165709", "rank_type": "10", "rank_label": "热卖榜", "channel_entry_title": "热卖榜", "subtab": "全部"},
                {"rank_id": "3173000", "rank_type": "19", "rank_label": "好评榜", "channel_entry_title": "好评榜", "subtab": "全部"},
                {"rank_id": "3989075", "rank_type": "22", "rank_label": "回购榜", "channel_entry_title": "回购榜", "subtab": "全部"},
                {"rank_id": "3097991", "rank_type": "16", "rank_label": "折扣榜", "channel_entry_title": "折扣榜", "subtab": "全部"},
                {"rank_id": "4795725", "rank_type": "8", "rank_label": "新品榜", "channel_entry_title": "新品榜", "subtab": "全部"},
                {"rank_id": "4919621", "rank_type": "24", "rank_label": "PLUS省钱榜", "channel_entry_title": "PLUS省钱榜", "subtab": "全部"},
            ]
        print(f"Discovered {len(tabs)} rank tabs: {', '.join(tab['rank_label'] for tab in tabs)}")

        for tab in tabs:
            print(f"Crawling tab {tab['rank_label']} by clicking and scrolling")
            page.run_js("window.scrollTo(0, 0)")
            time.sleep(1)

            current_products: dict[str, dict] = {}

            # Use DrissionPage listener to capture API responses
            page.listen.start("api.m.jd.com/client.action")

            try:
                el = page.ele(f'text:{tab["rank_label"]}', timeout=3)
                if el:
                    el.click()
                else:
                    print(f"  Tab button not found: {tab['rank_label']}; trying URL fallback.")
                    tab_url = set_query_params(
                        start_url,
                        {"pageNum": 1, "rankId": tab["rank_id"], "rankType": tab["rank_type"]},
                    )
                    page.get(tab_url)

                time.sleep(random.randint(5, 8))

                # Collect intercepted API response data
                for packet in page.listen.steps():
                    try:
                        payload = packet.response.body
                        if isinstance(payload, str):
                            payload = json.loads(payload)
                        for product in find_product_dicts(payload):
                            sku = str(product.get("skuId") or product.get("mainSkuId") or product.get("sku") or "").strip()
                            if sku:
                                current_products[sku] = product
                    except Exception:
                        pass
                page.listen.stop()

                react_data = wait_for_react_rank_data(page, timeout_sec=12)
                if react_data:
                    products, category_path = extract_product_list(react_data)
                    for product in products:
                        sku = str(product.get("skuId") or product.get("mainSkuId") or product.get("sku") or "").strip()
                        if sku:
                            current_products[sku] = product
                else:
                    category_path = "京东排行榜"

                stable_rounds = 0
                last_count = len(current_products)
                last_height = 0
                for scroll_round in range(1, 80):
                    page.run_js("window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
                    time.sleep(random.uniform(1.2, 2.2))
                    metrics = page.run_js(
                        "() => ({y: window.scrollY, h: document.documentElement.scrollHeight, inner: window.innerHeight})"
                    )
                    count = len(current_products)
                    at_bottom = metrics["y"] + metrics["inner"] >= metrics["h"] - 8
                    if count == last_count and metrics["h"] == last_height:
                        stable_rounds += 1
                    else:
                        stable_rounds = 0
                    last_count = count
                    last_height = metrics["h"]
                    print(
                        f"  {tab['rank_label']} scroll {scroll_round}: products={count}, "
                        f"height={metrics['h']}, bottom={at_bottom}"
                    )
                    if stable_rounds >= 4 and at_bottom:
                        break

                tab_url = page.url
                print(f"  Found {len(current_products)} products for {tab['rank_label']}.")
                for product in current_products.values():
                    record = product_to_record(
                        product,
                        f"{category_path} > {tab['subtab']} > {tab['rank_label']}",
                        tab_url,
                    )
                    record["rank_tab"] = tab["rank_label"]
                    record["rank_id"] = tab["rank_id"]
                    record["rank_type"] = tab["rank_type"]
                    record["channel_entry_title"] = tab["channel_entry_title"]
                    all_records.append(record)
            finally:
                try:
                    page.listen.stop()
                except Exception:
                    pass

            pd.DataFrame(all_records).drop_duplicates(subset=["item_id", "rank_tab"], keep="last").to_csv(
                output_path, index=False, encoding="utf-8-sig"
            )
            print(f"  Saved {len(all_records)} cumulative tab rows to {output_path}")
            page.run_js("window.scrollTo(0, 0)")
            time.sleep(random.uniform(2.5, 4.5))
    finally:
        page.quit()

    if all_records:
        df = pd.DataFrame(all_records)
        df = df.drop_duplicates(subset=["item_id", "rank_tab"], keep="last")
    else:
        df = pd.DataFrame()
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Final saved tab rows: {len(df)} -> {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl JD pro/rank pages from window.__react_data__.")
    parser.add_argument("--url", required=True, help="JD rank/pro page URL")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--output", "-o", default="raw_listing_京东排行榜.csv")
    parser.add_argument("--user-data-dir", default=".jd_playwright_profile")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--tabs", action="store_true", help="Crawl top rank tabs instead of pageNum pagination")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.tabs:
        crawl_rank_tabs(
            start_url=args.url,
            output=args.output,
            user_data_dir=args.user_data_dir,
            headless=args.headless,
        )
    else:
        crawl_rank_page(
            start_url=args.url,
            max_pages=args.max_pages,
            output=args.output,
            user_data_dir=args.user_data_dir,
            headless=args.headless,
        )


if __name__ == "__main__":
    main()
