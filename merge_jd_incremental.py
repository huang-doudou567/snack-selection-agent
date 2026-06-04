# -*- coding: utf-8 -*-
"""Incrementally merge newly crawled JD listing data into the snack dataset."""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from preprocess_jd_listing import clean_price, clean_promotion_tag, parse_sales_main


DEFAULT_EXISTING = "cleaned_snacks_data.csv"
DEFAULT_NEW = "raw_listing.csv"
MERGED_OUTPUT = "merged_products.csv"
CHANGES_OUTPUT = "data_changes_report.csv"
COVERAGE_OUTPUT = "crawl_coverage_report.txt"


def normalize_sku(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    if re.search(r"e[+-]?\d+", text, re.IGNORECASE):
        try:
            return str(int(float(text)))
        except ValueError:
            return text
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def extract_number(value: object) -> float:
    if value is None or pd.isna(value):
        return 0.0
    text = str(value).replace(",", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    number = float(match.group(0))
    if "万" in text:
        number *= 10000
    elif "千" in text:
        number *= 1000
    return number


def extract_keywords_from_existing(existing_csv: str) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    print("Extracting keyword lists from existing data...")
    df = pd.read_csv(existing_csv, dtype=str)

    brands: list[str] = []
    categories: list[str] = []
    pairs: list[tuple[str, str]] = []

    if "品牌" in df.columns:
        for raw_value in df["品牌"].dropna().unique():
            value = str(raw_value).strip()
            if not value:
                continue
            if " - " in value:
                brand, category = [part.strip() for part in value.split(" - ", 1)]
            else:
                brand, category = value, ""
            if brand and brand not in brands:
                brands.append(brand)
            if category and category not in categories:
                categories.append(category)
            if brand and category:
                pairs.append((brand, category))

    for column in ["二级分类", "三级分类"]:
        if column in df.columns:
            for value in df[column].dropna().unique():
                text = str(value).strip()
                if text and text not in categories:
                    categories.append(text)

    pd.DataFrame({"brand": brands}).to_csv("search_keywords_brands.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"category": categories}).to_csv("search_keywords_categories.csv", index=False, encoding="utf-8-sig")
    print(f"  Brands: {len(brands)}; categories: {len(categories)}; brand-category pairs: {len(pairs)}")
    return brands, categories, pairs


def load_existing_data(existing_csv: str) -> pd.DataFrame:
    print(f"Loading existing data: {existing_csv}")
    df = pd.read_csv(existing_csv, dtype=str)
    if "SKU" not in df.columns:
        raise KeyError("Existing CSV must contain SKU.")
    df["sku_normalized"] = df["SKU"].apply(normalize_sku)
    print(f"  Existing rows: {len(df)}")
    return df


def load_new_crawl_data(new_csv: str) -> pd.DataFrame:
    print(f"Loading new crawl data: {new_csv}")
    df = pd.read_csv(new_csv, dtype={"item_id": "string"})
    if "item_id" not in df.columns:
        raise KeyError("New crawl CSV must contain item_id.")

    for column in [
        "title",
        "price",
        "original_price",
        "promotion_tag",
        "review_count",
        "sales_text",
        "shop_name",
        "category_breadcrumb",
        "detail_url",
        "listing_time",
        "crawl_time",
    ]:
        if column not in df.columns:
            df[column] = ""

    df["item_id_normalized"] = df["item_id"].apply(normalize_sku)
    df["price_clean"] = df["price"].apply(clean_price)
    df["original_price_clean"] = df["original_price"].apply(clean_price)
    df["sales_sort"] = df["sales_text"].apply(parse_sales_main)
    df["promotion_tag_clean"] = df["promotion_tag"].apply(clean_promotion_tag)
    df["crawl_time_sort"] = pd.to_datetime(df["crawl_time"], errors="coerce")
    df = df[df["item_id_normalized"].notna()]
    print(f"  New crawl rows: {len(df)}")
    return df


def value_changed(old_value: object, new_value: object) -> bool:
    if new_value is None or pd.isna(new_value) or str(new_value).strip() == "":
        return False
    if old_value is None or pd.isna(old_value):
        return True
    return str(old_value).strip() != str(new_value).strip()


def detect_and_apply_changes(existing_row: dict[str, Any], new_row: pd.Series) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updated = existing_row.copy()
    changes: list[dict[str, Any]] = []

    field_map = {
        "商品名称": "title",
        "店铺名称": "shop_name",
        "促销信息": "promotion_tag_clean",
    }
    for old_field, new_field in field_map.items():
        new_value = new_row.get(new_field, "")
        if value_changed(updated.get(old_field), new_value):
            changes.append(
                {
                    "field": old_field,
                    "old_value": updated.get(old_field, ""),
                    "new_value": new_value,
                    "change_type": "updated",
                }
            )
            updated[f"{old_field}_history"] = updated.get(old_field, "")
            updated[old_field] = new_value

    new_price = new_row.get("price_clean")
    old_price = clean_price(updated.get("现价"))
    if new_price is not None and old_price is not None and abs(new_price - old_price) > 0.0001:
        changes.append(
            {
                "field": "现价",
                "old_value": old_price,
                "new_value": new_price,
                "change_type": "up" if new_price > old_price else "down",
            }
        )
        updated["现价_history"] = updated.get("现价", "")
        updated["现价"] = new_price
        updated["price_changed"] = True
    elif new_price is not None and old_price is None:
        updated["现价"] = new_price

    new_original_price = new_row.get("original_price_clean")
    if new_original_price is not None:
        updated["原价"] = new_original_price

    old_reviews = extract_number(updated.get("评论"))
    new_reviews = extract_number(new_row.get("review_count"))
    if new_reviews > old_reviews:
        changes.append(
            {
                "field": "评论",
                "old_value": old_reviews,
                "new_value": new_reviews,
                "change_type": "growth",
                "growth": new_reviews - old_reviews,
            }
        )
        updated["评论_history"] = updated.get("评论", "")
        updated["评论"] = new_row.get("review_count", "")
        updated["review_growth"] = new_reviews - old_reviews

    old_sales = str(updated.get("销售量", "")).strip()
    new_sales = str(new_row.get("sales_text", "")).strip()
    if new_sales and old_sales != new_sales:
        changes.append(
            {
                "field": "销售量",
                "old_value": old_sales,
                "new_value": new_sales,
                "change_type": "updated",
            }
        )
        updated["销售量_history"] = old_sales
        updated["销售量"] = new_sales
        updated["sales_num"] = parse_sales_main(new_sales)
        updated["sales_changed"] = True

    updated["detail_url"] = new_row.get("detail_url", "")
    updated["listing_time"] = new_row.get("listing_time", "")
    updated["crawl_time"] = new_row.get("crawl_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated["not_crawled_this_round"] = False
    updated["is_new_product"] = False
    return updated, changes


def new_product_record(new_row: pd.Series, existing_columns: list[str]) -> dict[str, Any]:
    record = {column: "" for column in existing_columns}
    item_id = str(new_row["item_id_normalized"])
    category_parts = [part.strip() for part in str(new_row.get("category_breadcrumb", "")).split(">") if part.strip()]

    record.update(
        {
            "品牌": "",
            "SKU": item_id,
            "商品名称": new_row.get("title", ""),
            "店铺名称": new_row.get("shop_name", ""),
            "原价": new_row.get("original_price_clean", ""),
            "现价": new_row.get("price_clean", ""),
            "销售量": new_row.get("sales_text", ""),
            "评论": new_row.get("review_count", ""),
            "一级分类": category_parts[0] if len(category_parts) > 0 else "",
            "二级分类": category_parts[1] if len(category_parts) > 1 else "",
            "三级分类": category_parts[2] if len(category_parts) > 2 else "",
            "促销信息": new_row.get("promotion_tag_clean", ""),
            "sales_num": parse_sales_main(new_row.get("sales_text")),
            "sku_normalized": item_id,
            "detail_url": new_row.get("detail_url", ""),
            "listing_time": new_row.get("listing_time", ""),
            "crawl_time": new_row.get("crawl_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "is_new_product": True,
            "not_crawled_this_round": False,
        }
    )
    return record


def merge_dataframes(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, int]]:
    print("Merging data...")
    new_dedup = (
        new_df.sort_values(["crawl_time_sort", "sales_sort"], ascending=[False, False], na_position="last")
        .drop_duplicates(subset="item_id_normalized", keep="first")
        .copy()
    )
    print(f"  New rows after dedupe: {len(new_dedup)}")

    existing_by_sku = {
        str(row["sku_normalized"]): row.to_dict()
        for _, row in existing_df.dropna(subset=["sku_normalized"]).iterrows()
    }

    merged_records: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    matched_skus: set[str] = set()
    existing_columns = existing_df.columns.tolist()

    for _, new_row in new_dedup.iterrows():
        item_id = str(new_row["item_id_normalized"])
        if item_id in existing_by_sku:
            updated, row_changes = detect_and_apply_changes(existing_by_sku[item_id], new_row)
            matched_skus.add(item_id)
            merged_records.append(updated)
            if row_changes:
                changes.append(
                    {
                        "item_id": item_id,
                        "sku": item_id,
                        "title": str(new_row.get("title") or updated.get("商品名称", ""))[:80],
                        "changes": row_changes,
                    }
                )
        else:
            merged_records.append(new_product_record(new_row, existing_columns))

    for sku, row in existing_by_sku.items():
        if sku in matched_skus:
            continue
        row = row.copy()
        row["not_crawled_this_round"] = True
        row["is_new_product"] = False
        merged_records.append(row)

    merged = pd.DataFrame(merged_records)
    stats = {
        "matched": len(matched_skus),
        "new": int(merged.get("is_new_product", pd.Series(dtype=bool)).fillna(False).sum()),
        "existing_not_crawled": int(merged.get("not_crawled_this_round", pd.Series(dtype=bool)).fillna(False).sum()),
        "total": len(merged),
    }
    print(f"  Matched: {stats['matched']}; new: {stats['new']}; not crawled: {stats['existing_not_crawled']}")
    return merged, changes, stats


def describe_change(change: dict[str, Any]) -> str:
    field = change["field"]
    old_value = change.get("old_value", "")
    new_value = change.get("new_value", "")
    change_type = change.get("change_type", "")

    if field == "现价" and isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
        diff = new_value - old_value
        pct = diff / old_value * 100 if old_value else 0
        if change_type == "down":
            return f"价格下调 {abs(diff):.2f} ({pct:.1f}%)"
        if change_type == "up":
            return f"价格上涨 {diff:.2f} (+{pct:.1f}%)"
    if field == "评论":
        return f"评论数增长 {change.get('growth', 0):.0f}"
    if field == "销售量":
        return f"销量变更: {old_value} -> {new_value}"
    return f"{field}: {old_value} -> {new_value}"


def generate_changes_report(changes: list[dict[str, Any]], output_path: str) -> pd.DataFrame:
    flat_rows: list[dict[str, Any]] = []
    for item in changes:
        for change in item["changes"]:
            flat_rows.append(
                {
                    "item_id": item["item_id"],
                    "sku": item["sku"],
                    "title": item["title"],
                    "field": change["field"],
                    "old_value": change.get("old_value", ""),
                    "new_value": change.get("new_value", ""),
                    "change_type": change.get("change_type", ""),
                    "growth": change.get("growth", ""),
                    "change_desc": describe_change(change),
                }
            )
    report = pd.DataFrame(flat_rows)
    report.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Saved changes report to {output_path} ({len(report)} rows)")
    return report


def generate_coverage_report(stats: dict[str, int], changes: list[dict[str, Any]], output_path: str) -> None:
    price_changes = [c for item in changes for c in item["changes"] if c["field"] == "现价"]
    price_up = len([c for c in price_changes if c.get("change_type") == "up"])
    price_down = len([c for c in price_changes if c.get("change_type") == "down"])
    review_changes = [c for item in changes for c in item["changes"] if c["field"] == "评论"]

    total = max(stats["total"], 1)
    lines = [
        "=" * 60,
        "JD snack crawl coverage report",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
        "Data stats",
        "-" * 40,
        f"Merged total rows: {stats['total']}",
        f"Matched and updated this round: {stats['matched']}",
        f"New products this round: {stats['new']}",
        f"Existing products not crawled this round: {stats['existing_not_crawled']}",
        "",
        "Coverage",
        "-" * 40,
        f"Update coverage: {stats['matched'] / total * 100:.1f}%",
        f"New product rate: {stats['new'] / total * 100:.1f}%",
        f"Not-covered rate: {stats['existing_not_crawled'] / total * 100:.1f}%",
        "",
        "Change tracking",
        "-" * 40,
        f"Price changed products: {len(price_changes)}",
        f"  Price up: {price_up}",
        f"  Price down: {price_down}",
        f"Review growth products: {len(review_changes)}",
        "",
        "Suggestions",
        "-" * 40,
    ]

    if stats["existing_not_crawled"]:
        lines.append(
            f"1. {stats['existing_not_crawled']} historical products were not covered; add more brand/category keywords."
        )
    if price_down:
        lines.append(f"2. {price_down} products dropped in price; review them for promotion opportunities.")
    if stats["new"]:
        lines.append(f"3. {stats['new']} new products were found; consider manual QA before using them downstream.")
    if not any([stats["existing_not_crawled"], price_down, stats["new"]]):
        lines.append("No immediate follow-up suggestions.")

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved coverage report to {output_path}")


def run_incremental_merge(args: argparse.Namespace) -> None:
    extract_keywords_from_existing(args.existing)
    if args.keywords_only:
        return

    existing_df = load_existing_data(args.existing)
    new_df = load_new_crawl_data(args.new)
    merged_df, changes, stats = merge_dataframes(existing_df, new_df)

    generate_changes_report(changes, args.changes)
    generate_coverage_report(stats, changes, args.coverage)

    if not args.report_only:
        merged_df.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"Saved merged data to {args.output} ({len(merged_df)} rows)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incrementally merge JD crawl data.")
    parser.add_argument("--existing", "--现有", default=DEFAULT_EXISTING, help="Existing structured CSV")
    parser.add_argument("--new", "--新", default=DEFAULT_NEW, help="New raw listing CSV")
    parser.add_argument("--output", "--输出", default=MERGED_OUTPUT, help="Merged output CSV")
    parser.add_argument("--changes", default=CHANGES_OUTPUT, help="Changes report CSV")
    parser.add_argument("--coverage", default=COVERAGE_OUTPUT, help="Coverage report TXT")
    parser.add_argument("--keywords-only", action="store_true", help="Only generate keyword CSV files")
    parser.add_argument("--report-only", "--仅报告", action="store_true", help="Generate reports but skip merged CSV write")
    return parser.parse_args()


def main() -> None:
    run_incremental_merge(parse_args())


if __name__ == "__main__":
    main()
