# -*- coding: utf-8 -*-
"""Clean raw JD listing data and optionally merge negative-review counts."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import pandas as pd


def parse_sales_text(sales_text: object) -> tuple[float | None, float | None, str | None]:
    if sales_text is None or pd.isna(sales_text):
        return None, None, None

    sales_str = str(sales_text).strip().replace(",", "")
    if not sales_str:
        return None, None, None

    exact_match = re.match(r"^(\d+)$", sales_str)
    if exact_match:
        value = int(exact_match.group(1))
        return float(value), float(value), "high"

    plain_plus_match = re.match(r"^(\d+)\+$", sales_str)
    if plain_plus_match:
        value = int(plain_plus_match.group(1))
        if value < 1000:
            return float(value), float(min(value * 5, 500)), "low"
        if value < 10000:
            return float(value), float(value * 2), "medium"
        return float(value), float(value * 5), "medium"

    wan_match = re.match(r"^(\d+(?:\.\d+)?)\s*万\+?$", sales_str)
    if wan_match:
        base = float(wan_match.group(1)) * 10000
        return base, base * 5, "medium"

    qian_match = re.match(r"^(\d+(?:\.\d+)?)\s*千\+?$", sales_str)
    if qian_match:
        base = float(qian_match.group(1)) * 1000
        return base, base * 5, "medium"

    return None, None, "low"


def parse_sales_main(sales_text: object) -> float:
    lower, _, _ = parse_sales_text(sales_text)
    return float(lower or 0)


def clean_price(price: object) -> float | None:
    if price is None or pd.isna(price):
        return None
    text = re.sub(r"[¥￥$\s,]", "", str(price))
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def clean_promotion_tag(tag: object) -> str:
    if tag is None or pd.isna(tag):
        return ""
    tags = [item.strip() for item in re.split(r"[,，\s]+", str(tag).strip()) if item.strip()]
    return "|".join(tags)


def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def preprocess_raw_listing(input_csv: str, output_csv: str, existing_csv: str | None = None) -> pd.DataFrame:
    print(f"Reading raw listing data: {input_csv}")
    df = pd.read_csv(input_csv, dtype={"item_id": "string"})
    print(f"  Raw rows: {len(df)}")

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

    df["price"] = df["price"].apply(clean_price)
    df["original_price"] = df["original_price"].apply(clean_price)
    df["promotion_tag"] = df["promotion_tag"].apply(clean_promotion_tag)
    df["shop_name"] = df["shop_name"].apply(clean_text)
    df["title"] = df["title"].apply(clean_text)
    df["item_id"] = df["item_id"].apply(clean_text)

    sales_analysis = df["sales_text"].apply(parse_sales_text)
    df["sales_lower"] = sales_analysis.apply(lambda item: item[0])
    df["sales_upper"] = sales_analysis.apply(lambda item: item[1])
    df["sales_confidence"] = sales_analysis.apply(lambda item: item[2])
    df["sales_sort"] = df["sales_text"].apply(parse_sales_main)

    before_dedup = len(df)
    df = df[df["item_id"].astype(str).str.len() > 0]
    df = df.sort_values(["sales_sort", "crawl_time"], ascending=[False, False])
    df = df.drop_duplicates(subset="item_id", keep="first")
    print(f"  Deduped rows: {len(df)}; removed {before_dedup - len(df)}")

    df = df.rename(
        columns={
            "title": "product_title",
            "price": "current_price",
            "promotion_tag": "promotion_tags",
            "sales_text": "sales_text_raw",
            "category_breadcrumb": "category_path",
            "item_id": "product_id",
            "listing_time": "listing_date",
            "crawl_time": "crawl_timestamp",
        }
    )

    field_order = [
        "product_id",
        "product_title",
        "current_price",
        "original_price",
        "promotion_tags",
        "review_count",
        "sales_text_raw",
        "sales_lower",
        "sales_upper",
        "sales_confidence",
        "sales_sort",
        "shop_name",
        "category_path",
        "detail_url",
        "listing_date",
        "crawl_timestamp",
    ]
    df = df[[column for column in field_order if column in df.columns]]

    if existing_csv:
        print(f"Appending existing cleaned data: {existing_csv}")
        existing = pd.read_csv(existing_csv, dtype={"product_id": "string"})
        merged = pd.concat([df, existing], ignore_index=True, sort=False)
        if "product_id" in merged.columns:
            merged = merged.sort_values("sales_sort", ascending=False, na_position="last")
            merged = merged.drop_duplicates(subset="product_id", keep="first")
        df = merged
        print(f"  Rows after append/dedupe: {len(df)}")

    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"Saved cleaned products to {output_csv}")
    return df


def merge_negative_reviews(reviews_csv: str, products_csv: str, output_csv: str) -> pd.DataFrame:
    reviews = pd.read_csv(reviews_csv, dtype={"item_id": "string"})
    products = pd.read_csv(products_csv, dtype={"product_id": "string"})
    review_counts = reviews.groupby("item_id").size().reset_index(name="negative_review_count")

    products = products.merge(review_counts, left_on="product_id", right_on="item_id", how="left")
    products = products.drop(columns=["item_id"])
    products["negative_review_count"] = products["negative_review_count"].fillna(0).astype(int)
    products.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"Saved final products with review counts to {output_csv}")
    return products


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preprocess raw JD listing CSV.")
    parser.add_argument("--input", "-i", default="raw_listing_坚果礼盒.csv", help="Raw listing CSV")
    parser.add_argument("--output", "-o", default="cleaned_products.csv", help="Cleaned output CSV")
    parser.add_argument("--existing", "-e", default=None, help="Optional existing cleaned CSV")
    parser.add_argument("--reviews", "-r", default="negative_reviews.csv", help="Negative reviews CSV")
    parser.add_argument("--final", "-f", default="final_products.csv", help="Final output CSV")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    preprocess_raw_listing(args.input, args.output, args.existing)

    if Path(args.reviews).exists():
        merge_negative_reviews(args.reviews, args.output, args.final)
    else:
        print(f"Review file not found: {args.reviews}; copying cleaned output to final output.")
        shutil.copyfile(args.output, args.final)


if __name__ == "__main__":
    main()
