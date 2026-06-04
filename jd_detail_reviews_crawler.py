# -*- coding: utf-8 -*-
"""Crawl JD detail pages and negative reviews from a merged listing CSV (DrissionPage)."""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from DrissionPage import ChromiumPage, ChromiumOptions


DETAIL_COLUMNS = [
    "item_id",
    "detail_url",
    "product_title",
    "shop_name",
    "brand",
    "product_number",
    "origin",
    "shelf_life",
    "domestic_or_imported",
    "flavor",
    "packing_list",
    "evaluation_tags",
    "good_rate",
    "attributes_raw",
    "crawl_status",
    "error_reason",
    "crawl_time",
]

REVIEW_COLUMNS = [
    "item_id",
    "detail_url",
    "review_page",
    "review_rating",
    "review_text",
    "review_time",
    "review_source",
    "crawl_time",
]


TEXT = {
    "product_detail": "商品详情",
    "buyer_praise": "买家赞不绝口",
    "everyone_praise": "大家赞不绝口",
    "praise": "赞不绝口",
    "bad_review": "差评",
    "comment": "商品评价",
    "everyone_comment": "大家评",
    "next_page": "下一页",
    "captcha_title": "验证",
    "drag_arrow": "拖动箭头",
    "security_check": "安全验证",
    "view_all_params": "查看全部参数",
}

FIELD_ALIASES = {
    "brand": ["品牌", "品 牌"],
    "product_number": ["商品编号", "货号"],
    "origin": ["产地", "原产地", "生产地", "生产地址"],
    "shelf_life": ["保质期", "质保期"],
    "domestic_or_imported": ["国产/进口", "国产或进口", "进口/国产", "是否进口"],
    "flavor": ["口味", "风味"],
    "packing_list": ["包装清单", "包装内容", "规格"],
}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def human_delay(min_sec: float = 8, max_sec: float = 15) -> None:
    deadline = time.time() + random.uniform(min_sec, max_sec)
    while time.time() < deadline:
        time.sleep(random.uniform(1.0, 2.4))


def _page_scroll(page: ChromiumPage) -> None:
    amount = random.randint(260, 780) * random.choice([1, 1, 1, -1])
    page.run_js(f"window.scrollBy(0, {amount})")


def is_verification_page(page: ChromiumPage) -> bool:
    title = page.title
    if TEXT["captcha_title"] in title:
        return True
    try:
        body = page.ele("body").text
    except Exception:
        return False
    return TEXT["drag_arrow"] in body or TEXT["security_check"] in body


def wait_for_manual_verification(page: ChromiumPage, timeout_sec: int = 900) -> bool:
    print("CAPTCHA detected. Please solve it manually in the visible browser window.")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(3)
        if not is_verification_page(page):
            print("Verification resolved; continuing.")
            time.sleep(3)
            return True
    print("Verification wait timed out.")
    return False


def ensure_accessible(page: ChromiumPage) -> bool:
    if is_verification_page(page):
        return wait_for_manual_verification(page)
    return True


def visible_click_by_text(page: ChromiumPage, texts: list[str]) -> bool:
    for text in texts:
        try:
            el = page.ele(f"text:{text}", timeout=2)
            if el and el.states.is_displayed:
                el.click()
                human_delay(1.8, 3.8)
                return True
        except Exception:
            continue
    return False


def first_text_from(page: ChromiumPage, selectors: list[str]) -> str:
    for sel in selectors:
        try:
            el = page.ele(sel, timeout=2)
            if el:
                text = clean_text(el.text)
                if text:
                    return text
        except Exception:
            continue
    return ""


def texts_from_elements(elements, limit: int = 200) -> list[str]:
    values: list[str] = []
    try:
        for i, el in enumerate(elements):
            if i >= limit:
                break
            text = clean_text(el.text)
            if text:
                values.append(text)
    except Exception:
        pass
    return list(dict.fromkeys(values))


def click_product_detail_tab(page: ChromiumPage) -> None:
    page.run_js("window.scrollTo(0, 0)")
    human_delay(0.8, 1.6)
    clicked = visible_click_by_text(page, [TEXT["product_detail"]])
    if not clicked:
        for sel in ["#detail .tab-main li", ".tab-main li", "a[href*='#detail']"]:
            try:
                els = page.eles(sel)
                for el in els:
                    if TEXT["product_detail"] in (el.text or ""):
                        el.click()
                        human_delay(1.8, 3.0)
                        return
            except Exception:
                continue


def click_reviews_area(page: ChromiumPage) -> None:
    visible_click_by_text(page, [TEXT["everyone_comment"], TEXT["comment"]])
    try:
        page.run_js("window.scrollTo(0, Math.floor(document.documentElement.scrollHeight * 0.55))")
    except Exception:
        pass
    human_delay(1.5, 2.8)


def click_praise_tab(page: ChromiumPage) -> None:
    visible_click_by_text(page, [TEXT["buyer_praise"], TEXT["everyone_praise"], TEXT["praise"]])


def click_bad_filter(page: ChromiumPage) -> None:
    visible_click_by_text(page, [TEXT["bad_review"], "1星", "2星"])


def parse_attributes_from_raw(raw: str) -> dict[str, str]:
    result = {key: "" for key in FIELD_ALIASES}
    segments = re.split(r"[|;\n\r]+", raw)
    compact_segments = [clean_text(s) for s in segments if clean_text(s)]
    joined = " | ".join(compact_segments)
    for key, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            for pattern in [
                rf"{re.escape(alias)}\s*[:：]\s*([^|;；，,]{{1,80}})",
                rf"{re.escape(alias)}\s+([^|;；，,]{{1,80}})",
            ]:
                match = re.search(pattern, joined)
                if match:
                    result[key] = clean_text(match.group(1))
                    break
            if result[key]:
                break
    return result


def collect_attribute_text(page: ChromiumPage) -> str:
    visible_click_by_text(page, [TEXT["view_all_params"]])
    human_delay(1.0, 2.0)
    selectors = [
        ".layui-layer-content",
        ".ui-dialog-content",
        "[role='dialog']",
        ".Ptable",
        ".Ptable-item",
        "#parameter2",
        ".parameter2",
        "[class*='parameter']",
        "#detail",
        ".detail-content",
    ]
    chunks: list[str] = []
    for sel in selectors:
        try:
            els = page.eles(sel)
            texts = texts_from_elements(els, limit=80)
            chunks.extend(texts)
        except Exception:
            continue
    return " | ".join(dict.fromkeys(clean_text(x) for x in chunks if clean_text(x)))


def collect_evaluation_tags(page: ChromiumPage) -> str:
    selectors = [
        ".comment-tag-list span",
        ".comment-tag-list a",
        ".tag-list span",
        "[class*='comment'][class*='tag'] span",
        "[class*='tag'] span",
    ]
    tags: list[str] = []
    for sel in selectors:
        tags = texts_from_elements(page.eles(sel), limit=120)
        tags = [tag for tag in tags if len(tag) <= 40]
        if tags:
            break
    return "|".join(tags)


def collect_good_rate(page: ChromiumPage) -> str:
    text = first_text_from(
        page,
        [".percent-con", "#comment .percent", "[class*='goodRate']", "[class*='good-rate']", "[class*='rate']"],
    )
    if text:
        return text
    try:
        body = page.ele("body").text
        match = re.search(r"(\d+(?:\.\d+)?%)\s*[^\n]{0,12}(?:好评|赞不绝口)", body)
        return clean_text(match.group(0)) if match else ""
    except Exception:
        return ""


def extract_details(page: ChromiumPage, item_id: str, detail_url: str) -> dict[str, str]:
    title = first_text_from(page, ["#crumb-wrap .sku-name", ".sku-name", "h1"])
    if title in {"最小单价计算器", "规格参数"} or len(title) < 8:
        title = ""
    shop_name = first_text_from(page, ["#popbox .name", ".J-hove-wrap .name", ".shopName", ".shop-name", "#store-selector"])

    click_product_detail_tab(page)
    human_delay(8, 15)
    raw_attributes = collect_attribute_text(page)
    parsed = parse_attributes_from_raw(raw_attributes)

    click_reviews_area(page)
    click_praise_tab(page)
    human_delay(8, 15)
    tags = collect_evaluation_tags(page)
    good_rate = collect_good_rate(page)

    return {
        "item_id": item_id,
        "detail_url": detail_url,
        "product_title": title,
        "shop_name": shop_name,
        "brand": parsed["brand"],
        "product_number": parsed["product_number"] or item_id,
        "origin": parsed["origin"],
        "shelf_life": parsed["shelf_life"],
        "domestic_or_imported": parsed["domestic_or_imported"],
        "flavor": parsed["flavor"],
        "packing_list": parsed["packing_list"],
        "evaluation_tags": tags,
        "good_rate": good_rate,
        "attributes_raw": raw_attributes[:4000],
        "crawl_status": "ok",
        "error_reason": "",
        "crawl_time": now(),
    }


def extract_negative_reviews_from_page(
    page: ChromiumPage,
    item_id: str,
    detail_url: str,
    max_pages: int = 3,
    stay_min: float = 8,
    stay_max: float = 15,
) -> list[dict[str, str]]:
    click_reviews_area(page)
    click_praise_tab(page)
    click_bad_filter(page)

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    item_selectors = [".comment-item", "#comment .comment-column", "[class*='comment-item']", "[class*='CommentItem']"]
    text_selectors = [".comment-con", ".comment-content", "[class*='comment-con']", "[class*='content']", "p"]

    for page_no in range(1, max_pages + 1):
        human_delay(stay_min, stay_max)
        cards = []
        for sel in item_selectors:
            cards = page.eles(sel)
            if cards:
                break
        if not cards:
            break

        for card in cards:
            review_text = ""
            for sel in text_selectors:
                try:
                    el = card.ele(sel, timeout=1)
                    if el:
                        review_text = clean_text(el.text)
                        if review_text:
                            break
                except Exception:
                    continue
            if not review_text or review_text in seen:
                continue
            seen.add(review_text)
            rating = ""
            try:
                star_el = card.ele("[class*='star']", timeout=1)
                if star_el:
                    star_class = star_el.attr("class") or ""
                    match = re.search(r"star(?:-level)?-?(\d)", star_class)
                    rating = match.group(1) if match else ""
            except Exception:
                pass
            rows.append({
                "item_id": item_id,
                "detail_url": detail_url,
                "review_page": str(page_no),
                "review_rating": rating,
                "review_text": review_text,
                "review_time": "",
                "review_source": "page",
                "crawl_time": now(),
            })

        if page_no >= max_pages:
            break

        clicked_next = False
        for sel in ["#comment .ui-pager-next", "#comment a", ".comment-page a", "a.pg-next"]:
            try:
                els = page.eles(sel)
                for el in els:
                    if TEXT["next_page"] in (el.text or ""):
                        classes = el.attr("class") or ""
                        if "disable" in classes or "disabled" in classes:
                            continue
                        if el.states.is_displayed:
                            el.click()
                            human_delay(2.0, 4.0)
                            clicked_next = True
                            break
                if clicked_next:
                    break
            except Exception:
                continue
        if not clicked_next:
            break

    return rows


def detail_is_effective(row: dict[str, str]) -> bool:
    if str(row.get("attributes_raw", "")).startswith("ERROR:"):
        return False
    useful_fields = [
        "brand", "origin", "shelf_life", "domestic_or_imported",
        "flavor", "packing_list", "evaluation_tags", "good_rate", "attributes_raw",
    ]
    return any(clean_text(str(row.get(f, ""))) for f in useful_fields)


def crawl_one(
    page: ChromiumPage,
    item_id: str,
    detail_url: str,
    stay_min: float = 8,
    stay_max: float = 15,
    max_review_pages: int = 3,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    print(f"Opening {item_id} {detail_url}")
    page.get(detail_url)
    if not ensure_accessible(page):
        raise RuntimeError("verification not resolved")
    human_delay(stay_min, stay_max)
    details = extract_details(page, item_id, detail_url)
    reviews = extract_negative_reviews_from_page(
        page, item_id, detail_url,
        max_pages=max_review_pages, stay_min=stay_min, stay_max=stay_max,
    )
    if not detail_is_effective(details):
        details["crawl_status"] = "no_effective_detail"
        details["error_reason"] = "opened page but no attributes/tags/good_rate extracted"
    print(
        f"  details brand={details['brand'] or '-'} number={details['product_number'] or '-'} "
        f"good_rate={details['good_rate'] or '-'} status={details['crawl_status']} negative_reviews={len(reviews)}"
    )
    return details, reviews


def load_existing(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return pd.read_csv(path, dtype=str).fillna("").to_dict("records")


def existing_detail_is_effective(row: dict[str, str]) -> bool:
    return detail_is_effective({key: str(value or "") for key, value in row.items()})


def save_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False, encoding="utf-8-sig")


def choose_input_csv(path_text: str) -> Path:
    requested = Path(path_text)
    if requested.exists():
        return requested
    fallback = Path("raw_listing_total_with_sales_49p_merged_dedup.csv")
    if fallback.exists():
        return fallback
    raise FileNotFoundError(path_text)


def crawl_all(
    input_csv: Path,
    details_output: Path,
    reviews_output: Path,
    user_data_dir: str,
    save_every: int,
    limit: int | None,
    overwrite: bool,
    stay_min: float,
    stay_max: float,
    max_review_pages: int,
    max_consecutive_ineffective: int,
    headless: bool = False,
) -> None:
    df = pd.read_csv(input_csv, dtype=str).fillna("")
    if "item_id" not in df.columns and "product_id" in df.columns:
        df["item_id"] = df["product_id"]
    if "detail_url" not in df.columns or "item_id" not in df.columns:
        raise ValueError(f"{input_csv} must contain product_id/item_id and detail_url")
    df = df[df["detail_url"].str.startswith("http")].copy()
    df["item_id"] = df["item_id"].astype(str).str.strip()
    df = df[df["item_id"].ne("")].drop_duplicates("item_id", keep="first")
    if limit:
        df = df.head(limit).copy()

    existing_detail_rows = [] if overwrite else load_existing(details_output)
    detail_rows = [row for row in existing_detail_rows if existing_detail_is_effective(row)]
    review_rows = [] if overwrite else load_existing(reviews_output)
    done_ids = {str(row.get("item_id", "")).strip() for row in detail_rows} - {""}
    todo = df[~df["item_id"].isin(done_ids)].copy()
    ineffective_existing = len(existing_detail_rows) - len(detail_rows)
    print(
        f"Input products={len(df)}, effective_done={len(done_ids)}, "
        f"ineffective_existing_will_retry={ineffective_existing}, todo={len(todo)}"
    )

    co = ChromiumOptions()
    co.set_user_data_path(str(Path(user_data_dir).resolve()))
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-gpu")
    co.set_argument("--disable-software-rasterizer")
    co.auto_port()
    page = ChromiumPage(co)

    consecutive_ineffective = 0
    try:
        for idx, (_, row) in enumerate(todo.iterrows(), start=1):
            item_id = str(row["item_id"]).strip()
            detail_url = str(row["detail_url"]).strip()
            try:
                details, reviews = crawl_one(
                    page, item_id, detail_url,
                    stay_min=stay_min, stay_max=stay_max, max_review_pages=max_review_pages,
                )
                if not details.get("product_title"):
                    details["product_title"] = str(row.get("product_title", "") or row.get("title", "")).strip()
                if not details.get("shop_name"):
                    details["shop_name"] = str(row.get("shop_name", "")).strip()
                detail_rows.append(details)
                review_rows.extend(reviews)
                if detail_is_effective(details) or reviews:
                    consecutive_ineffective = 0
                else:
                    consecutive_ineffective += 1
            except Exception as exc:
                print(f"  failed item {item_id}: {exc}")
                detail_rows.append({
                    "item_id": item_id,
                    "detail_url": detail_url,
                    "product_title": "",
                    "shop_name": "",
                    "brand": "",
                    "product_number": item_id,
                    "origin": "",
                    "shelf_life": "",
                    "domestic_or_imported": "",
                    "flavor": "",
                    "packing_list": "",
                    "evaluation_tags": "",
                    "good_rate": "",
                    "attributes_raw": f"ERROR: {exc}",
                    "crawl_status": "failed",
                    "error_reason": str(exc)[:500],
                    "crawl_time": now(),
                })
                consecutive_ineffective += 1

            save_csv(details_output, detail_rows, DETAIL_COLUMNS)
            save_csv(reviews_output, review_rows, REVIEW_COLUMNS)
            if idx % save_every == 0:
                print(f"Saved checkpoint after {idx} products.")
            if consecutive_ineffective >= max_consecutive_ineffective:
                print(
                    f"Stopping early: {consecutive_ineffective} consecutive products produced no effective data. "
                    "Likely blocked, captcha-gated, or page structure changed."
                )
                break
    finally:
        save_csv(details_output, detail_rows, DETAIL_COLUMNS)
        save_csv(reviews_output, review_rows, REVIEW_COLUMNS)
        page.quit()
    print(f"Done. details={len(detail_rows)}, reviews={len(review_rows)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl JD detail attributes and negative reviews.")
    parser.add_argument("--input", default="merged_products.csv")
    parser.add_argument("--details-output", default="product_details.csv")
    parser.add_argument("--reviews-output", default="negative_reviews.csv")
    parser.add_argument("--user-data-dir", default=".jd_playwright_profile")
    parser.add_argument("--save-every", type=int, default=50)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--stay-min", type=float, default=20)
    parser.add_argument("--stay-max", type=float, default=40)
    parser.add_argument("--max-review-pages", type=int, default=3)
    parser.add_argument("--max-consecutive-ineffective", type=int, default=8)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawl_all(
        input_csv=choose_input_csv(args.input),
        details_output=Path(args.details_output),
        reviews_output=Path(args.reviews_output),
        user_data_dir=args.user_data_dir,
        save_every=args.save_every,
        limit=args.limit,
        overwrite=args.overwrite,
        stay_min=args.stay_min,
        stay_max=args.stay_max,
        max_review_pages=args.max_review_pages,
        max_consecutive_ineffective=args.max_consecutive_ineffective,
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
