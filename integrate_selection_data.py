# -*- coding: utf-8 -*-
"""Consolidate local snack product data for the selection web app.

The script is intentionally read-only for crawlers/external sites: it only reads
local CSV snapshots and writes normalized outputs for Streamlit.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
OUTPUT_PRODUCTS = ROOT / "integrated_selection_products.csv"
OUTPUT_CATEGORY_SUMMARY = ROOT / "integrated_category_summary.csv"
OUTPUT_QUALITY_JSON = ROOT / "selection_data_quality_report.json"
OUTPUT_QUALITY_MD = ROOT / "selection_data_quality_report.md"


CORE_COLUMNS = [
    "品牌",
    "SKU",
    "商品名称",
    "店铺名称",
    "原价",
    "现价",
    "随机销量",
    "评论",
    "一级分类",
    "二级分类",
    "三级分类",
    "促销信息",
    "weight_g",
    "has_coupon",
    "brand_from_name",
    "flavor",
    "weight_from_text",
    "package_type",
    "specification",
    "is_gift",
    "keywords",
    "brand_match_status",
    "weight_match_status",
    "extraction_notes",
]


def read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, dtype=str).fillna("")


def existing(path: str) -> Path | None:
    candidate = ROOT / path
    return candidate if candidate.exists() else None


def largest_file(file_name: str, preferred: Iterable[Path | None] = ()) -> Path | None:
    files = [path for path in preferred if path and path.exists()]
    files.extend(path for path in ROOT.rglob(file_name) if path.is_file())
    if not files:
        return None
    return sorted(set(files), key=lambda item: item.stat().st_size, reverse=True)[0]


def normalize_sku(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    if re.search(r"e[+-]?\d+", text, re.IGNORECASE):
        try:
            return str(int(float(text)))
        except ValueError:
            return text
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    digits = re.findall(r"\d+", text)
    return max(digits, key=len) if digits else text


def to_number(value: object) -> float:
    text = str(value or "").replace(",", "").strip()
    if not text or text.lower() == "nan":
        return np.nan
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return np.nan
    try:
        return float(match.group(0))
    except ValueError:
        return np.nan


def parse_sales(value: object) -> float:
    text = str(value or "").replace(",", "").strip()
    if not text or text.lower() == "nan":
        return 0.0
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    amount = float(match.group(0))
    if "万" in text:
        amount *= 10000
    elif "千" in text:
        amount *= 1000
    return amount


def extract_weight_from_title(value: object) -> float:
    text = clean_text(value).lower()
    if not text:
        return np.nan

    multi = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|克)\s*[*x×]\s*(\d+)", text)
    if multi:
        return float(multi.group(1)) * float(multi.group(2))
    kg_multi = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|千克|公斤)\s*[*x×]\s*(\d+)", text)
    if kg_multi:
        return float(kg_multi.group(1)) * 1000 * float(kg_multi.group(2))

    kg = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|千克|公斤)", text)
    if kg:
        return float(kg.group(1)) * 1000
    gram = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|克)", text)
    if gram:
        return float(gram.group(1))
    return np.nan


def clean_text(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() == "nan" else text


def clean_brand(value: object) -> str:
    text = clean_text(value)
    if " - " in text:
        text = text.split(" - ", 1)[0].strip()
    return text


def clean_category(value: object) -> str:
    text = clean_text(value)
    rank_tokens = ["榜", "全部", "主体-", "京东排行榜"]
    if any(token in text for token in rank_tokens):
        return ""
    return text


def col(df: pd.DataFrame, name: str, default: object = "") -> pd.Series:
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index)


def nonempty(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip()
    return ~text.str.lower().isin({"", "nan", "none", "nat"})


def merge_first(left: pd.Series, right: pd.Series) -> pd.Series:
    result = left.copy()
    mask = ~nonempty(result)
    result.loc[mask] = right.loc[mask]
    return result


def merge_prefer_right(left: pd.Series, right: pd.Series) -> pd.Series:
    result = left.copy()
    mask = nonempty(right)
    result.loc[mask] = right.loc[mask]
    return result


def structured_frame(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame(columns=CORE_COLUMNS + ["source_flags"])
    raw = read_csv(path)
    df = pd.DataFrame(
        {
            "品牌": col(raw, "品牌").map(clean_brand),
            "SKU": col(raw, "SKU").map(normalize_sku),
            "商品名称": col(raw, "商品名称").map(clean_text),
            "店铺名称": col(raw, "店铺名称").map(clean_text),
            "原价": col(raw, "原价").map(to_number),
            "现价": col(raw, "现价").map(to_number),
            "随机销量": col(raw, "随机销量").where(nonempty(col(raw, "随机销量")), col(raw, "sales_num")).map(parse_sales),
            "评论": col(raw, "评论").map(parse_sales),
            "一级分类": col(raw, "一级分类").map(clean_text),
            "二级分类": col(raw, "二级分类").map(clean_text),
            "三级分类": col(raw, "三级分类").map(clean_text),
            "促销信息": col(raw, "促销信息").map(clean_text),
            "weight_g": col(raw, "weight_g").map(to_number),
            "has_coupon": col(raw, "has_coupon").map(clean_text),
            "brand_from_name": col(raw, "brand_from_name").map(clean_brand),
            "flavor": col(raw, "flavor").map(clean_text),
            "weight_from_text": col(raw, "weight_from_text").map(to_number),
            "package_type": col(raw, "package_type").map(clean_text),
            "specification": col(raw, "specification").map(clean_text),
            "is_gift": col(raw, "is_gift").map(clean_text),
            "keywords": col(raw, "keywords").map(clean_text),
            "brand_match_status": col(raw, "brand_match_status").map(clean_text),
            "weight_match_status": col(raw, "weight_match_status").map(clean_text),
            "extraction_notes": col(raw, "extraction_notes").map(clean_text),
            "source_flags": "structured",
        }
    )
    return df[df["SKU"].ne("")]


def merged_frame(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame(columns=CORE_COLUMNS + ["source_flags"])
    raw = read_csv(path)
    category = col(raw, "historical_level3")
    if "category_path" in raw.columns:
        category = category.mask(category.astype(str).str.strip().eq(""), raw["category_path"].astype(str).str.split(">").str[-1].str.strip())

    df = pd.DataFrame(
        {
            "品牌": col(raw, "detail_brand").map(clean_brand),
            "SKU": col(raw, "product_id").map(normalize_sku),
            "商品名称": col(raw, "product_title").map(clean_text),
            "店铺名称": col(raw, "shop_name").map(clean_text),
            "原价": col(raw, "original_price").map(to_number),
            "现价": col(raw, "current_price").map(to_number),
            "随机销量": col(raw, "sales_sort").where(nonempty(col(raw, "sales_sort")), col(raw, "sales_text_raw")).map(parse_sales),
            "评论": col(raw, "review_count").map(parse_sales),
            "一级分类": col(raw, "historical_level1").map(clean_text),
            "二级分类": col(raw, "historical_level2").map(clean_text),
            "三级分类": category.map(clean_category),
            "促销信息": col(raw, "promotion_tags").map(clean_text),
            "weight_g": col(raw, "weight_g").map(to_number),
            "has_coupon": col(raw, "has_coupon").map(clean_text),
            "brand_from_name": col(raw, "detail_brand").map(clean_brand),
            "flavor": col(raw, "detail_flavor").map(clean_text),
            "weight_from_text": col(raw, "weight_g").map(to_number),
            "package_type": col(raw, "detail_packing_list").map(clean_text),
            "specification": col(raw, "detail_packing_list").map(clean_text),
            "is_gift": "",
            "keywords": col(raw, "detail_evaluation_tags").map(clean_text),
            "brand_match_status": "",
            "weight_match_status": "",
            "extraction_notes": "",
            "source_files": col(raw, "source_files").map(clean_text),
            "source_type": col(raw, "source_type").map(clean_text),
            "detail_url": col(raw, "detail_url").map(clean_text),
            "listing_date": col(raw, "listing_date").map(clean_text),
            "crawl_timestamp": col(raw, "crawl_timestamp").map(clean_text),
            "detail_shelf_life": col(raw, "detail_shelf_life").map(clean_text),
            "detail_good_rate": col(raw, "detail_good_rate").map(clean_text),
            "negative_review_count_listing": col(raw, "negative_review_count").map(parse_sales),
            "source_flags": "merged",
        }
    )
    return df[df["SKU"].ne("")]


def combine_products(structured: pd.DataFrame, merged: pd.DataFrame) -> pd.DataFrame:
    combined = merged.drop_duplicates("SKU", keep="first").set_index("SKU", drop=False)
    structured = structured.drop_duplicates("SKU", keep="first").set_index("SKU", drop=False)

    if combined.empty:
        combined = structured.copy()
    else:
        overlap = combined.index.intersection(structured.index)
        prefer_structured = {
            "品牌",
            "一级分类",
            "二级分类",
            "三级分类",
            "weight_g",
            "brand_from_name",
            "flavor",
            "weight_from_text",
            "package_type",
            "specification",
            "is_gift",
            "keywords",
            "brand_match_status",
            "weight_match_status",
            "extraction_notes",
        }
        for name in CORE_COLUMNS:
            if name == "SKU":
                continue
            if name in prefer_structured:
                combined.loc[overlap, name] = merge_prefer_right(combined.loc[overlap, name], structured.loc[overlap, name])
            else:
                combined.loc[overlap, name] = merge_first(combined.loc[overlap, name], structured.loc[overlap, name])
        combined.loc[overlap, "source_flags"] = combined.loc[overlap, "source_flags"].astype(str) + "+structured"
        missing = structured.index.difference(combined.index)
        combined = pd.concat([combined, structured.loc[missing]], axis=0, sort=False)

    combined = combined.reset_index(drop=True)
    for name in CORE_COLUMNS:
        if name not in combined.columns:
            combined[name] = ""
    return combined


def aggregate_reviews(path: Path | None, text_col: str) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame(columns=["SKU"])
    raw = read_csv(path)
    raw["SKU"] = col(raw, "item_id").map(normalize_sku)
    raw[text_col] = col(raw, text_col).map(clean_text)
    raw = raw[raw["SKU"].ne("")]
    if raw.empty:
        return pd.DataFrame(columns=["SKU"])
    return raw.groupby("SKU").agg(
        review_rows=(text_col, "size"),
        review_nonempty=(text_col, lambda item: int(nonempty(item).sum())),
        review_unique=(text_col, lambda item: int(item[nonempty(item)].nunique())),
    ).reset_index()


def latest_per_sku(df: pd.DataFrame, sku_col: str, time_col: str = "crawl_time") -> pd.DataFrame:
    if df.empty:
        return df
    frame = df.copy()
    frame["SKU"] = col(frame, sku_col).map(normalize_sku)
    frame = frame[frame["SKU"].ne("")]
    if time_col in frame.columns:
        frame["_time"] = pd.to_datetime(frame[time_col], errors="coerce")
        frame = frame.sort_values("_time")
    return frame.drop_duplicates("SKU", keep="last").drop(columns=[col for col in ["_time"] if col in frame.columns])


def attach_supplements(data: pd.DataFrame, sources: dict[str, Path | None]) -> pd.DataFrame:
    result = data.copy()

    details_path = sources.get("details")
    if details_path:
        details = latest_per_sku(read_csv(details_path), "item_id")
        detail_cols = [
            "SKU",
            "review_count",
            "好评率",
            "评价标签",
            "产地",
            "保质期",
            "配料表",
            "规格",
            "crawl_time",
        ]
        details = details[[name for name in detail_cols if name in details.columns]].rename(
            columns={
                "review_count": "jd_detail_review_count",
                "好评率": "jd_good_rate",
                "评价标签": "jd_evaluation_tags",
                "产地": "jd_origin",
                "保质期": "jd_shelf_life",
                "配料表": "jd_ingredients",
                "规格": "jd_specification",
                "crawl_time": "jd_detail_crawl_time",
            }
        )
        result = result.merge(details, on="SKU", how="left")
        if "jd_detail_review_count" in result.columns:
            result["评论"] = pd.to_numeric(result["评论"], errors="coerce").fillna(0)
            detail_reviews = pd.to_numeric(result["jd_detail_review_count"], errors="coerce")
            result["评论"] = np.maximum(result["评论"], detail_reviews.fillna(0))
        for target, supplement in [("specification", "jd_specification"), ("detail_shelf_life", "jd_shelf_life")]:
            if supplement in result.columns:
                if target not in result.columns:
                    result[target] = ""
                result[target] = merge_first(result[target], result[supplement])

    reviews_path = sources.get("reviews")
    if reviews_path:
        reviews = aggregate_reviews(reviews_path, "content").rename(
            columns={
                "review_rows": "jd_review_rows",
                "review_nonempty": "jd_review_nonempty",
                "review_unique": "jd_review_unique",
            }
        )
        result = result.merge(reviews, on="SKU", how="left")

    negative_path = sources.get("negative")
    if negative_path:
        negative = aggregate_reviews(negative_path, "content").rename(
            columns={
                "review_rows": "jd_negative_rows",
                "review_nonempty": "jd_negative_nonempty",
                "review_unique": "jd_negative_unique",
            }
        )
        result = result.merge(negative, on="SKU", how="left")

    checkpoint_path = sources.get("checkpoint")
    if checkpoint_path:
        checkpoint = latest_per_sku(read_csv(checkpoint_path), "item_id")
        keep = [name for name in ["SKU", "status", "reviews_count", "negative_reviews_count", "error", "crawl_time"] if name in checkpoint.columns]
        checkpoint = checkpoint[keep].rename(
            columns={
                "status": "jd_crawl_status",
                "reviews_count": "jd_crawled_reviews_count",
                "negative_reviews_count": "jd_crawled_negative_count",
                "error": "jd_crawl_error",
                "crawl_time": "jd_checkpoint_time",
            }
        )
        result = result.merge(checkpoint, on="SKU", how="left")

    price_path = sources.get("price_history")
    if price_path:
        price = read_csv(price_path)
        price["SKU"] = col(price, "item_id").map(normalize_sku)
        price["_status_rank"] = col(price, "status").eq("success").astype(int)
        price["_time"] = pd.to_datetime(col(price, "query_time"), errors="coerce")
        price = price.sort_values(["SKU", "_status_rank", "_time"]).drop_duplicates("SKU", keep="last")
        price["mmb_trend_points"] = col(price, "price_trend").map(count_trend_points)
        keep = [
            "SKU",
            "current_price",
            "lowest_price",
            "lowest_date",
            "highest_price",
            "mmb_trend_points",
            "query_time",
            "status",
            "error_msg",
        ]
        price = price[[name for name in keep if name in price.columns]].rename(
            columns={
                "current_price": "mmb_current_price",
                "lowest_price": "mmb_lowest_price",
                "lowest_date": "mmb_lowest_date",
                "highest_price": "mmb_highest_price",
                "query_time": "mmb_query_time",
                "status": "mmb_status",
                "error_msg": "mmb_error_msg",
            }
        )
        result = result.merge(price, on="SKU", how="left")

    return result


def count_trend_points(value: object) -> int:
    text = clean_text(value)
    if not text:
        return 0
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return 0
    return len(parsed) if isinstance(parsed, list) else 0


def finalize_products(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    for name in CORE_COLUMNS:
        if name not in result.columns:
            result[name] = ""

    result["品牌"] = merge_first(result["品牌"], result["brand_from_name"]).replace("", "未知品牌")
    result["brand_from_name"] = merge_first(result["brand_from_name"], result["品牌"])
    result["三级分类"] = result["三级分类"].replace("", "未识别三级分类")
    result["weight_from_text"] = pd.to_numeric(result["weight_from_text"], errors="coerce")
    result["weight_g"] = pd.to_numeric(result["weight_g"], errors="coerce").fillna(result["weight_from_text"])
    title_weight = result["商品名称"].map(extract_weight_from_title)
    result["weight_g"] = result["weight_g"].fillna(title_weight)
    result["weight_from_text"] = result["weight_from_text"].fillna(result["weight_g"])
    result["现价"] = pd.to_numeric(result["现价"], errors="coerce")
    result["原价"] = pd.to_numeric(result["原价"], errors="coerce")
    result["随机销量"] = pd.to_numeric(result["随机销量"], errors="coerce").fillna(0)
    result["评论"] = pd.to_numeric(result["评论"], errors="coerce").fillna(0)
    result["unit_price"] = result["现价"] / result["weight_g"]
    result.loc[
        (result["现价"] <= 0) | (result["weight_g"] <= 0) | ~np.isfinite(result["unit_price"]),
        "unit_price",
    ] = np.nan
    result["has_coupon"] = result["has_coupon"].replace("", "0")
    result["is_gift"] = result["is_gift"].replace("", "False")
    result["data_integrated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    result["_unit_price_valid_sort"] = result["unit_price"].notna().astype(int)
    ordered = CORE_COLUMNS + [name for name in result.columns if name not in CORE_COLUMNS and name != "_unit_price_valid_sort"]
    return result.sort_values(
        ["_unit_price_valid_sort", "三级分类", "随机销量", "评论"],
        ascending=[False, True, False, False],
    )[ordered]


def coverage(data: pd.DataFrame, column: str) -> dict[str, object]:
    if column not in data.columns:
        return {"nonempty": 0, "coverage": 0.0}
    mask = nonempty(data[column])
    return {"nonempty": int(mask.sum()), "coverage": round(float(mask.mean()), 4)}


def build_quality_report(data: pd.DataFrame, raw_sources: dict[str, tuple[Path | None, int]]) -> dict[str, object]:
    row_count = len(data)
    price = pd.to_numeric(data["现价"], errors="coerce")
    weight = pd.to_numeric(data["weight_g"], errors="coerce")
    unit_price = pd.to_numeric(data["unit_price"], errors="coerce")

    report = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "output_products": str(OUTPUT_PRODUCTS.name),
        "row_count": row_count,
        "unique_sku_count": int(data["SKU"].nunique()),
        "duplicate_sku_count": int(data["SKU"].duplicated().sum()),
        "source_rows": {
            name: {"path": str(path) if path else "", "rows": rows}
            for name, (path, rows) in raw_sources.items()
        },
        "coverage": {
            "title": coverage(data, "商品名称"),
            "brand": coverage(data, "品牌"),
            "category": coverage(data, "三级分类"),
            "category_recognized": {
                "nonempty": int(data["三级分类"].ne("未识别三级分类").sum()),
                "coverage": round(float(data["三级分类"].ne("未识别三级分类").mean()), 4),
            },
            "price": {"nonempty": int(price.notna().sum()), "coverage": round(float(price.notna().mean()), 4)},
            "weight": {"nonempty": int(weight.notna().sum()), "coverage": round(float(weight.notna().mean()), 4)},
            "unit_price_valid": {"nonempty": int(unit_price.notna().sum()), "coverage": round(float(unit_price.notna().mean()), 4)},
            "flavor": coverage(data, "flavor"),
            "package_type": coverage(data, "package_type"),
            "jd_reviews": coverage(data, "jd_review_nonempty"),
            "jd_negative_reviews": coverage(data, "jd_negative_nonempty"),
            "mmb_price_history": coverage(data, "mmb_lowest_price"),
        },
        "quality_flags": {
            "missing_sku": int((~nonempty(data["SKU"])).sum()),
            "missing_title": int((~nonempty(data["商品名称"])).sum()),
            "missing_category": int(data["三级分类"].eq("未识别三级分类").sum()),
            "invalid_price": int((price.isna() | (price <= 0)).sum()),
            "invalid_weight": int((weight.isna() | (weight <= 0)).sum()),
            "extreme_price_over_1000": int((price > 1000).sum()),
            "extreme_weight_over_10000g": int((weight > 10000).sum()),
            "duplicate_title_price_weight": int(data.duplicated(["商品名称", "现价", "weight_g"]).sum()),
        },
    }

    if "jd_crawl_status" in data.columns:
        report["jd_status_counts"] = data["jd_crawl_status"].replace("", np.nan).dropna().value_counts().to_dict()
    if "mmb_status" in data.columns:
        report["mmb_status_counts"] = data["mmb_status"].replace("", np.nan).dropna().value_counts().to_dict()
    return report


def category_summary(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.copy()
    for name in ["现价", "随机销量", "评论", "unit_price", "jd_negative_nonempty"]:
        if name in frame.columns:
            frame[name] = pd.to_numeric(frame[name], errors="coerce").fillna(0)
    grouped = frame.groupby("三级分类", dropna=False).agg(
        商品数量=("SKU", "nunique"),
        品牌数=("品牌", "nunique"),
        平均现价=("现价", "mean"),
        价格中位数=("现价", "median"),
        单位价中位数=("unit_price", "median"),
        随机销量总量=("随机销量", "sum"),
        评论总量=("评论", "sum"),
        差评文本量=("jd_negative_nonempty", "sum"),
        历史价覆盖=("mmb_lowest_price", lambda item: float(nonempty(item).mean()) if len(item) else 0.0),
    )
    return grouped.reset_index().sort_values("商品数量", ascending=False)


def write_markdown(report: dict[str, object]) -> None:
    coverage_rows = report["coverage"]
    lines = [
        "# 选品数据整合与质量报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 统一商品数：{report['row_count']:,}",
        f"- 唯一 SKU 数：{report['unique_sku_count']:,}",
        f"- 重复 SKU 数：{report['duplicate_sku_count']:,}",
        "",
        "## 数据源",
        "",
    ]
    for name, item in report["source_rows"].items():
        lines.append(f"- {name}: {item['rows']:,} 行；`{item['path']}`")

    lines.extend(["", "## 覆盖率", ""])
    for name, item in coverage_rows.items():
        lines.append(f"- {name}: {item['nonempty']:,} / {report['row_count']:,} ({item['coverage']:.1%})")

    lines.extend(["", "## 质量告警", ""])
    for name, value in report["quality_flags"].items():
        lines.append(f"- {name}: {value:,}")

    if report.get("jd_status_counts"):
        lines.extend(["", "## 京东抓取状态", ""])
        for name, value in report["jd_status_counts"].items():
            lines.append(f"- {name}: {value:,}")
    if report.get("mmb_status_counts"):
        lines.extend(["", "## 慢慢买历史价状态", ""])
        for name, value in report["mmb_status_counts"].items():
            lines.append(f"- {name}: {value:,}")

    OUTPUT_QUALITY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    sources = {
        "structured": existing("structured_snacks_data_with_random_sales.csv") or existing("cleaned_snacks_data.csv"),
        "merged": existing("merged_products.csv") or existing("final_products.csv"),
        "details": largest_file("product_details.csv", [ROOT / "数据" / "京东评论爬取" / "product_details.csv"]),
        "reviews": largest_file("product_reviews.csv", [ROOT / "数据" / "京东评论爬取" / "product_reviews.csv"]),
        "negative": largest_file("negative_reviews.csv", [ROOT / "数据" / "京东评论爬取" / "negative_reviews.csv"]),
        "checkpoint": largest_file("crawled_items.csv", [ROOT / "数据" / "京东评论爬取" / "crawled_items.csv"]),
        "price_history": existing("price_history.csv"),
    }

    raw_structured = structured_frame(sources["structured"])
    raw_merged = merged_frame(sources["merged"])
    combined = combine_products(raw_structured, raw_merged)
    integrated = finalize_products(attach_supplements(combined, sources))

    raw_rows = {
        "structured": (sources["structured"], len(raw_structured)),
        "merged": (sources["merged"], len(raw_merged)),
    }
    for name in ["details", "reviews", "negative", "checkpoint", "price_history"]:
        path = sources[name]
        raw_rows[name] = (path, len(read_csv(path)) if path else 0)

    report = build_quality_report(integrated, raw_rows)
    integrated.to_csv(OUTPUT_PRODUCTS, index=False, encoding="utf-8-sig")
    category_summary(integrated).to_csv(OUTPUT_CATEGORY_SUMMARY, index=False, encoding="utf-8-sig")
    OUTPUT_QUALITY_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report)

    print(f"Wrote {OUTPUT_PRODUCTS.name}: {len(integrated):,} rows")
    print(f"Wrote {OUTPUT_CATEGORY_SUMMARY.name}")
    print(f"Wrote {OUTPUT_QUALITY_MD.name}")


if __name__ == "__main__":
    main()
