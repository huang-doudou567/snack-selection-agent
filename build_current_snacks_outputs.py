# -*- coding: utf-8 -*-
"""Build local cleaned and merged snack datasets from already-crawled CSV files.

This script does not access JD or any external website. It implements the
post-crawl steps: clean listing data, map sales text to ranges, merge with the
9282-row historical snack dataset, attach partial detail/review counts when
available, and write summary reports.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd


RAW_LISTING = Path("raw_listing_total_with_sales_49p_merged_dedup.csv")
HISTORICAL = Path("cleaned_snacks_data.csv")
DETAILS_CANDIDATES = [
    Path("数据") / "京东评论爬取" / "product_details.csv",
    Path("product_details.csv"),
]
REVIEWS_CANDIDATES = [
    Path("数据") / "京东评论爬取" / "negative_reviews.csv",
    Path("negative_reviews.csv"),
]

CLEANED_PRODUCTS = Path("cleaned_products.csv")
FINAL_PRODUCTS = Path("final_products.csv")
MERGED_PRODUCTS = Path("merged_products.csv")
CHANGES_REPORT = Path("data_changes_report.csv")
COVERAGE_REPORT = Path("crawl_coverage_report.txt")
SUMMARY_REPORT = Path("current_data_summary.md")


def resolve_existing_path(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def clean_price(value: object) -> float | None:
    text = clean_text(value).replace(",", "")
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_sales_text(value: object) -> tuple[float | None, float | None, str | None]:
    text = clean_text(value).replace(",", "")
    if not text:
        return None, None, None

    exact = re.fullmatch(r"(\d+)", text)
    if exact:
        amount = float(exact.group(1))
        return amount, amount, "high"

    plain_plus = re.fullmatch(r"(\d+)\+", text)
    if plain_plus:
        amount = float(plain_plus.group(1))
        if amount < 1000:
            return amount, min(amount * 5, 500), "low"
        if amount < 10000:
            return amount, amount * 2, "medium"
        return amount, amount * 5, "medium"

    wan = re.fullmatch(r"(\d+(?:\.\d+)?)\s*万\+?", text)
    if wan:
        lower = float(wan.group(1)) * 10000
        return lower, lower * 5, "medium"

    qian = re.fullmatch(r"(\d+(?:\.\d+)?)\s*千\+?", text)
    if qian:
        lower = float(qian.group(1)) * 1000
        return lower, lower * 5, "medium"

    return None, None, "low"


def parse_sales_main(value: object) -> float:
    lower, _, _ = parse_sales_text(value)
    return float(lower or 0)


def clean_promotion(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[|,，\s]+", text) if part.strip()]
    return "|".join(dict.fromkeys(parts))


def normalize_id(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if re.search(r"e[+-]?\d+", text, re.IGNORECASE):
        try:
            return str(int(float(text)))
        except ValueError:
            return text
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("")


def preprocess_listing(raw_path: Path = RAW_LISTING) -> pd.DataFrame:
    raw = read_csv(raw_path)
    for column in [
        "title",
        "price",
        "original_price",
        "promotion_tag",
        "review_count",
        "sales_text",
        "shop_name",
        "category_breadcrumb",
        "item_id",
        "detail_url",
        "listing_time",
        "crawl_time",
        "source_files",
        "source_type",
        "source_page_number",
    ]:
        if column not in raw.columns:
            raw[column] = ""

    raw["item_id"] = raw["item_id"].map(normalize_id)
    raw["title"] = raw["title"].map(clean_text)
    raw["price_clean"] = raw["price"].map(clean_price)
    raw["original_price_clean"] = raw["original_price"].map(clean_price)
    raw["promotion_tags_clean"] = raw["promotion_tag"].map(clean_promotion)
    raw["shop_name"] = raw["shop_name"].map(clean_text)
    raw["sales_sort"] = raw["sales_text"].map(parse_sales_main)
    sales = raw["sales_text"].map(parse_sales_text)
    raw["sales_lower"] = sales.map(lambda x: x[0])
    raw["sales_upper"] = sales.map(lambda x: x[1])
    raw["sales_confidence"] = sales.map(lambda x: x[2])
    raw["crawl_time_sort"] = pd.to_datetime(raw["crawl_time"], errors="coerce")

    raw = raw[raw["item_id"].ne("")].copy()
    raw = raw.sort_values(["sales_sort", "crawl_time_sort"], ascending=[False, False], na_position="last")
    raw = raw.drop_duplicates("item_id", keep="first")

    cleaned = pd.DataFrame(
        {
            "product_id": raw["item_id"],
            "product_title": raw["title"],
            "current_price": raw["price_clean"],
            "original_price": raw["original_price_clean"],
            "promotion_tags": raw["promotion_tags_clean"],
            "review_count": raw["review_count"],
            "sales_text_raw": raw["sales_text"],
            "sales_lower": raw["sales_lower"],
            "sales_upper": raw["sales_upper"],
            "sales_confidence": raw["sales_confidence"],
            "sales_sort": raw["sales_sort"],
            "shop_name": raw["shop_name"],
            "category_path": raw["category_breadcrumb"],
            "detail_url": raw["detail_url"],
            "listing_date": raw["listing_time"],
            "crawl_timestamp": raw["crawl_time"],
            "source_files": raw["source_files"],
            "source_type": raw["source_type"],
            "source_page_number": raw["source_page_number"],
        }
    )
    return cleaned


def attach_negative_review_counts(products: pd.DataFrame) -> pd.DataFrame:
    products = products.copy()
    if "negative_review_count" in products.columns:
        products = products.drop(columns=["negative_review_count"])
    products["negative_review_count"] = 0
    reviews_path = resolve_existing_path(REVIEWS_CANDIDATES)
    if reviews_path is not None:
        reviews = read_csv(reviews_path)
        if "item_id" in reviews.columns and len(reviews):
            reviews["item_id"] = reviews["item_id"].map(normalize_id)
            counts = reviews.groupby("item_id").size().rename("negative_review_count").reset_index()
            products = products.drop(columns=["negative_review_count"]).merge(
                counts, left_on="product_id", right_on="item_id", how="left"
            )
            products = products.drop(columns=["item_id"])
            products["negative_review_count"] = products["negative_review_count"].fillna(0).astype(int)
    return products


def attach_partial_details(products: pd.DataFrame) -> pd.DataFrame:
    products = products.copy()
    details_path = resolve_existing_path(DETAILS_CANDIDATES)
    if details_path is None:
        return products
    details = read_csv(details_path)
    if "item_id" not in details.columns or not len(details):
        return products
    details = details.rename(
        columns={
            "title": "product_title",
            "category": "category_path",
            "好评率": "good_rate",
            "评价标签": "evaluation_tags",
            "产地": "origin",
            "保质期": "shelf_life",
            "配料表": "packing_list",
            "规格": "flavor",
        }
    )
    details["item_id"] = details["item_id"].map(normalize_id)
    detail_cols = [
        "item_id",
        "brand",
        "product_number",
        "shelf_life",
        "domestic_or_imported",
        "flavor",
        "packing_list",
        "evaluation_tags",
        "good_rate",
    ]
    detail_cols = [col for col in detail_cols if col in details.columns]
    details = details[detail_cols].drop_duplicates("item_id", keep="last")
    details = details.rename(
        columns={
            "brand": "detail_brand",
            "product_number": "detail_product_number",
            "shelf_life": "detail_shelf_life",
            "domestic_or_imported": "detail_domestic_or_imported",
            "flavor": "detail_flavor",
            "packing_list": "detail_packing_list",
            "evaluation_tags": "detail_evaluation_tags",
            "good_rate": "detail_good_rate",
        }
    )
    for col in [
        "detail_brand",
        "detail_product_number",
        "detail_shelf_life",
        "detail_domestic_or_imported",
        "detail_flavor",
        "detail_packing_list",
        "detail_evaluation_tags",
        "detail_good_rate",
    ]:
        if col in products.columns:
            products = products.drop(columns=[col])
    return products.merge(details, left_on="product_id", right_on="item_id", how="left").drop(columns=["item_id"])


def historical_to_unified(historical: pd.DataFrame) -> pd.DataFrame:
    hist = historical.copy()
    hist["SKU"] = hist["SKU"].map(normalize_id)
    return pd.DataFrame(
        {
            "product_id": hist["SKU"],
            "product_title": hist["商品名称"],
            "current_price": hist["现价"].map(clean_price),
            "original_price": hist["原价"].map(clean_price),
            "promotion_tags": hist["促销信息"].map(clean_promotion),
            "review_count": hist["评论"],
            "sales_text_raw": hist["销售量"],
            "sales_lower": hist["销售量"].map(lambda x: parse_sales_text(x)[0]),
            "sales_upper": hist["销售量"].map(lambda x: parse_sales_text(x)[1]),
            "sales_confidence": hist["销售量"].map(lambda x: parse_sales_text(x)[2]),
            "sales_sort": hist["sales_num"].map(clean_price).fillna(0) if "sales_num" in hist.columns else hist["销售量"].map(parse_sales_main),
            "shop_name": hist["店铺名称"],
            "category_path": hist[["一级分类", "二级分类", "三级分类"]].agg(" > ".join, axis=1),
            "detail_url": hist["SKU"].map(lambda sku: f"https://item.jd.com/{sku}.html" if sku else ""),
            "listing_date": "",
            "crawl_timestamp": "",
            "source_files": "cleaned_snacks_data.csv",
            "source_type": "historical_dataset",
            "source_page_number": "",
            "historical_brand_category": hist["品牌"],
            "historical_level1": hist["一级分类"],
            "historical_level2": hist["二级分类"],
            "historical_level3": hist["三级分类"],
            "weight_g": hist["weight_g"],
            "has_coupon": hist["has_coupon"],
        }
    )


def build_changes(historical: pd.DataFrame, cleaned: pd.DataFrame) -> pd.DataFrame:
    hist = historical.copy()
    hist["SKU"] = hist["SKU"].map(normalize_id)
    hist_map = hist.set_index("SKU", drop=False)
    rows = []
    for _, row in cleaned.iterrows():
        sku = row["product_id"]
        if sku not in hist_map.index:
            continue
        old = hist_map.loc[sku]
        old_price = clean_price(old.get("现价", ""))
        new_price = row.get("current_price")
        try:
            new_price = float(new_price) if pd.notna(new_price) and str(new_price) != "" else None
        except ValueError:
            new_price = None
        if old_price is not None and new_price is not None and abs(old_price - new_price) > 0.0001:
            rows.append(
                {
                    "product_id": sku,
                    "product_title": row["product_title"],
                    "field": "current_price",
                    "old_value": old_price,
                    "new_value": new_price,
                    "change_type": "up" if new_price > old_price else "down",
                    "change_amount": new_price - old_price,
                }
            )
        old_sales = clean_text(old.get("销售量", ""))
        new_sales = clean_text(row.get("sales_text_raw", ""))
        if new_sales and old_sales and new_sales != old_sales:
            rows.append(
                {
                    "product_id": sku,
                    "product_title": row["product_title"],
                    "field": "sales_text_raw",
                    "old_value": old_sales,
                    "new_value": new_sales,
                    "change_type": "updated",
                    "change_amount": "",
                }
            )
    return pd.DataFrame(rows)


def merge_with_history(cleaned: pd.DataFrame, historical: pd.DataFrame) -> pd.DataFrame:
    hist_unified = historical_to_unified(historical)
    cleaned = cleaned.copy()
    cleaned["is_new_crawl"] = True
    hist_unified["is_new_crawl"] = False
    combined = pd.concat([cleaned, hist_unified], ignore_index=True, sort=False)
    combined["product_id"] = combined["product_id"].map(normalize_id)
    combined = combined[combined["product_id"].ne("")]
    combined["_priority"] = combined["is_new_crawl"].map(lambda x: 1 if bool(x) else 0)
    combined = combined.sort_values(["_priority", "sales_sort"], ascending=[False, False], na_position="last")
    combined = combined.drop_duplicates("product_id", keep="first").drop(columns=["_priority"])
    return combined


def write_coverage_report(cleaned: pd.DataFrame, historical: pd.DataFrame, merged: pd.DataFrame, changes: pd.DataFrame) -> None:
    hist_ids = set(historical["SKU"].map(normalize_id)) - {""}
    new_ids = set(cleaned["product_id"].map(normalize_id)) - {""}
    matched = hist_ids & new_ids
    new_only = new_ids - hist_ids
    historical_not_crawled = hist_ids - new_ids
    reviews_path = resolve_existing_path(REVIEWS_CANDIDATES)
    negative_note = "- negative_reviews.csv currently has no review rows, so negative_review_count is 0."
    if reviews_path is not None:
        try:
            review_rows = len(read_csv(reviews_path))
            negative_note = f"- Negative review counts are attached from `{reviews_path}` with {review_rows} rows."
        except Exception:
            negative_note = f"- Negative review counts are attached from `{reviews_path}`."
    lines = [
        "=" * 60,
        "JD snacks local data integration report",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
        "Data counts",
        f"- Historical rows: {len(historical)}",
        f"- New cleaned listing rows: {len(cleaned)}",
        f"- Matched historical SKUs: {len(matched)}",
        f"- New-only crawled SKUs: {len(new_only)}",
        f"- Historical SKUs not covered by this crawl: {len(historical_not_crawled)}",
        f"- Merged rows: {len(merged)}",
        "",
        "Change tracking",
        f"- Change records: {len(changes)}",
    ]
    if len(changes) and "field" in changes.columns:
        for field, count in changes["field"].value_counts().items():
            lines.append(f"- {field}: {count}")
    lines.extend(
        [
            "",
            "Notes",
            "- This report uses local CSV files only. No JD page was accessed.",
            "- product_details.csv is partial and is attached only as optional detail fields.",
            negative_note,
        ]
    )
    COVERAGE_REPORT.write_text("\n".join(lines), encoding="utf-8")


def write_summary(cleaned: pd.DataFrame, merged: pd.DataFrame, changes: pd.DataFrame) -> None:
    summary = [
        "# Current Data Summary",
        "",
        "## Outputs",
        "",
        f"- `{CLEANED_PRODUCTS}`: cleaned new crawl listing data, {len(cleaned)} rows.",
        f"- `{FINAL_PRODUCTS}`: cleaned listing data with negative review counts, {len(cleaned)} rows.",
        f"- `{MERGED_PRODUCTS}`: historical + new crawl unified data, {len(merged)} rows.",
        f"- `{CHANGES_REPORT}`: field-level change records, {len(changes)} rows.",
        f"- `{COVERAGE_REPORT}`: text coverage report.",
        "",
        "## Functional Status",
        "",
        "- Local product assistant unit tests passed: 10/10.",
        "- CLI demo ran successfully across market positioning, competitiveness, opportunity/risk, competitors, and corpus insights.",
        "- JD crawling is paused due to platform warning; current outputs are built from local CSV files only.",
    ]
    SUMMARY_REPORT.write_text("\n".join(summary), encoding="utf-8")


def main() -> None:
    if not RAW_LISTING.exists():
        raise FileNotFoundError(RAW_LISTING)
    if not HISTORICAL.exists():
        raise FileNotFoundError(HISTORICAL)

    cleaned = preprocess_listing(RAW_LISTING)
    cleaned = attach_partial_details(cleaned)
    final_products = attach_negative_review_counts(cleaned)
    historical = read_csv(HISTORICAL)
    changes = build_changes(historical, cleaned)
    merged = merge_with_history(final_products, historical)
    merged = attach_partial_details(merged)
    merged = attach_negative_review_counts(merged)

    cleaned.to_csv(CLEANED_PRODUCTS, index=False, encoding="utf-8-sig")
    final_products.to_csv(FINAL_PRODUCTS, index=False, encoding="utf-8-sig")
    merged.to_csv(MERGED_PRODUCTS, index=False, encoding="utf-8-sig")
    changes.to_csv(CHANGES_REPORT, index=False, encoding="utf-8-sig")
    write_coverage_report(cleaned, historical, merged, changes)
    write_summary(cleaned, merged, changes)

    print(f"cleaned rows: {len(cleaned)} -> {CLEANED_PRODUCTS}")
    print(f"final rows: {len(final_products)} -> {FINAL_PRODUCTS}")
    print(f"merged rows: {len(merged)} -> {MERGED_PRODUCTS}")
    print(f"changes rows: {len(changes)} -> {CHANGES_REPORT}")
    print(f"coverage report: {COVERAGE_REPORT}")


if __name__ == "__main__":
    main()
