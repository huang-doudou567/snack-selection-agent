from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
INPUT_CSV = ROOT / "merged_products.csv"
SNAPSHOT_DIR = ROOT / "snapshots"
DICT_DIR = Path(r"D:/Users/xwechat_files/wxid_hqnebvuuu45a29_1156/msg/file/2026-05")


def read_csv_robust(path: Path, **kwargs: Any) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, **kwargs)


def load_category_dictionary() -> dict[str, str]:
    """Load JD category-id to Chinese-name mapping from the provided JSON file."""
    if not DICT_DIR.exists():
        return {}

    candidates = [
        p
        for p in DICT_DIR.glob("*.json")
        if p.stat().st_size > 100_000 and "字典" in p.name
    ]
    if not candidates:
        return {}

    path = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            raw = json.loads(path.read_text(encoding=encoding))
            break
        except (UnicodeDecodeError, json.JSONDecodeError):
            raw = {}

    if not isinstance(raw, dict):
        return {}

    return {str(k).strip(): str(v).strip() for k, v in raw.items() if str(k).strip()}


def first_existing(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def numeric_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("¥", "", regex=False)
        .str.replace("￥", "", regex=False)
        .str.strip()
    )
    cleaned = cleaned.replace({"": np.nan, "nan": np.nan, "None": np.nan})
    return pd.to_numeric(cleaned, errors="coerce")


def parse_count(value: Any) -> float:
    if pd.isna(value):
        return np.nan
    text = str(value).strip().replace(",", "")
    if not text or text.lower() == "nan":
        return np.nan
    multiplier = 1
    if "万" in text:
        multiplier = 10_000
    elif "千" in text:
        multiplier = 1_000
    text = text.replace("万", "").replace("千", "").replace("+", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return np.nan
    return float(match.group()) * multiplier


def clean_sku(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    elif "e+" in text.lower():
        try:
            text = str(int(float(text)))
        except ValueError:
            pass
    return text


def translate_category(value: Any, cat_dict: dict[str, str]) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return cat_dict.get(text, text)


def split_category_path(path_value: Any) -> tuple[str, str, str]:
    if pd.isna(path_value):
        return "", "", ""
    raw = str(path_value)
    if "京东排行榜" in raw or "主体-热卖榜" in raw:
        return "", "", ""
    parts = [
        p.strip()
        for p in re.split(r"\s*>\s*|\s*/\s*", raw)
        if p.strip()
    ]
    if parts and (parts[-1].endswith("榜") or parts[-1] in {"全部", "综合", "销量"}):
        return "", "", ""
    if len(parts) >= 3:
        return parts[-3], parts[-2], parts[-1]
    if len(parts) == 2:
        return "", parts[0], parts[1]
    if len(parts) == 1:
        return "", "", parts[0]
    return "", "", ""


def brand_from_row(row: pd.Series) -> str:
    for col in ("detail_brand", "brand", "品牌", "brand_from_name"):
        value = row.get(col)
        if pd.notna(value) and str(value).strip():
            return str(value).strip()

    brand_category = row.get("historical_brand_category")
    if pd.notna(brand_category) and str(brand_category).strip():
        return str(brand_category).split(" - ", 1)[0].strip()

    shop_name = str(row.get("shop_name", "") or row.get("店铺名称", "")).strip()
    if shop_name:
        brand = re.sub(
            r"(京东自营|自营)?(官方)?(旗舰店|专营店|专卖店|自营店|食品店|店铺|店)$",
            "",
            shop_name,
        ).strip()
        if brand:
            return brand[:12]

    title = str(row.get("product_title", "") or row.get("商品名称", "")).strip()
    title = re.sub(r"^[【\[][^】\]]+[】\]]", "", title)
    match = re.match(r"[\u4e00-\u9fa5A-Za-z0-9()（）]+", title)
    return match.group(0)[:12] if match else "未知品牌"


def normalize_dataset(df: pd.DataFrame, cat_dict: dict[str, str]) -> pd.DataFrame:
    sku_col = first_existing(df, ["SKU", "sku", "product_id", "item_id"])
    if not sku_col:
        raise ValueError("未找到 SKU/product_id/item_id 字段，无法建立快照。")
    df["SKU"] = df[sku_col].apply(clean_sku)
    df = df.dropna(subset=["SKU"]).copy()
    df = df.drop_duplicates(subset=["SKU"], keep="first")

    price_col = first_existing(df, ["price", "current_price", "现价"])
    review_col = first_existing(df, ["review_count", "评论", "reviews"])
    sales_col = first_existing(df, ["sales_text_raw", "sales_text", "随机销量", "sales_sort"])
    shop_col = first_existing(df, ["shop_name", "店铺名称", "shop"])
    title_col = first_existing(df, ["product_title", "商品名称", "title"])

    df["price"] = numeric_series(df[price_col]) if price_col else np.nan
    df["review_count"] = df[review_col].apply(parse_count) if review_col else np.nan
    df["sales_text"] = df[sales_col].astype(str).replace("nan", "") if sales_col else ""
    df["shop_name_norm"] = df[shop_col].fillna("").astype(str).str.strip() if shop_col else ""
    df["product_title_norm"] = df[title_col].fillna("").astype(str).str.strip() if title_col else ""
    df["brand"] = df.apply(brand_from_row, axis=1)

    if "historical_level1" in df.columns:
        level1 = df["historical_level1"].fillna("")
    elif "一级分类" in df.columns:
        level1 = df["一级分类"].fillna("")
    else:
        level1 = pd.Series([""] * len(df), index=df.index)

    if "historical_level2" in df.columns:
        level2 = df["historical_level2"].fillna("")
    elif "二级分类" in df.columns:
        level2 = df["二级分类"].fillna("")
    else:
        level2 = pd.Series([""] * len(df), index=df.index)

    if "historical_level3" in df.columns:
        level3 = df["historical_level3"].fillna("")
    elif "三级分类" in df.columns:
        level3 = df["三级分类"].fillna("")
    else:
        level3 = pd.Series([""] * len(df), index=df.index)

    if "category_path" in df.columns:
        parsed = df["category_path"].apply(split_category_path)
        parsed_df = pd.DataFrame(parsed.tolist(), index=df.index, columns=["p1", "p2", "p3"])
        level1 = level1.where(level1.astype(str).str.strip().ne(""), parsed_df["p1"])
        level2 = level2.where(level2.astype(str).str.strip().ne(""), parsed_df["p2"])
        level3 = level3.where(level3.astype(str).str.strip().ne(""), parsed_df["p3"])

    df["category_level1"] = level1.apply(lambda x: translate_category(x, cat_dict))
    df["category_level2"] = level2.apply(lambda x: translate_category(x, cat_dict))
    df["category_level3_raw"] = level3.astype(str).str.strip()
    df["category_level3"] = level3.apply(lambda x: translate_category(x, cat_dict))
    df["category_level3"] = df["category_level3"].replace("", "未识别三级分类")

    if "weight_g" in df.columns:
        df["weight_g"] = numeric_series(df["weight_g"])
    else:
        df["weight_g"] = np.nan

    if "has_coupon" in df.columns:
        df["has_coupon"] = pd.to_numeric(df["has_coupon"], errors="coerce").fillna(0).astype(int)
    else:
        promo_col = first_existing(df, ["promotion_tags", "促销信息"])
        promo = df[promo_col].fillna("").astype(str) if promo_col else pd.Series([""] * len(df), index=df.index)
        df["has_coupon"] = promo.str.contains("券|满减|折扣|特价|优惠", regex=True).astype(int)

    return df


def calculate_concentration(group: pd.DataFrame, n: int) -> float:
    counts = group["brand"].replace("", "未知品牌").value_counts()
    if counts.sum() == 0:
        return 0.0
    return round(counts.head(n).sum() / counts.sum() * 100, 2)


def build_category_stats(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby("category_level3", dropna=False)
    stats = grouped.agg(
        商品数量=("SKU", "count"),
        品牌数=("brand", "nunique"),
        店铺数=("shop_name_norm", lambda s: s.replace("", np.nan).nunique()),
        价格均值=("price", "mean"),
        价格中位数=("price", "median"),
        最低价=("price", "min"),
        最高价=("price", "max"),
        评论均值=("review_count", "mean"),
        评论中位数=("review_count", "median"),
        评论总量=("review_count", "sum"),
        有价格数据=("price", lambda s: s.notna().sum()),
        有评论数据=("review_count", lambda s: s.notna().sum()),
    )
    stats["CR3"] = grouped.apply(lambda g: calculate_concentration(g, 3), include_groups=False)
    stats["CR5"] = grouped.apply(lambda g: calculate_concentration(g, 5), include_groups=False)
    stats["平均SKU密度_店铺数除以商品数"] = (stats["店铺数"] / stats["商品数量"]).round(4)
    stats = stats.reset_index().rename(columns={"category_level3": "三级分类"})
    numeric_cols = ["价格均值", "价格中位数", "最低价", "最高价", "评论均值", "评论中位数", "评论总量"]
    stats[numeric_cols] = stats[numeric_cols].round(2)
    return stats.sort_values(["商品数量", "评论总量"], ascending=False)


def write_report(df: pd.DataFrame, stats: pd.DataFrame, snapshot_date: str, report_path: Path, dict_hits: int) -> None:
    category_count = df["category_level3"].nunique()
    price_missing = df["price"].isna().mean() * 100 if len(df) else 0
    review_missing = df["review_count"].isna().mean() * 100 if len(df) else 0

    top_categories = "\n".join(
        f"- **{row['三级分类']}**：{int(row['商品数量'])} 个商品"
        for _, row in stats.head(20).iterrows()
    )

    price_rows = "\n".join(
        f"| {row['三级分类']} | ¥{row['价格中位数']:.2f} | {int(row['商品数量'])} |"
        for _, row in stats.head(15).iterrows()
    )
    review_rows = "\n".join(
        f"| {row['三级分类']} | {row['评论中位数']:.0f} | {row['评论均值']:.0f} |"
        for _, row in stats.head(15).iterrows()
    )
    cr_rows = "\n".join(
        f"| {row['三级分类']} | {row['CR3']:.1f}% | {row['CR5']:.1f}% |"
        for _, row in stats.sort_values("CR3", ascending=False).head(15).iterrows()
    )

    content = f"""# 数据基准报告

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> 数据快照日期: {snapshot_date}
> 总商品数: {len(df):,}

---

## 1. 数据质量概况

| 指标 | 数值 |
|------|------|
| 总商品数 | {len(df):,} |
| 三级分类数量 | {category_count} |
| 有价格数据 | {df['price'].notna().sum():,} |
| 有评论数据 | {df['review_count'].notna().sum():,} |
| 价格缺失率 | {price_missing:.2f}% |
| 评论缺失率 | {review_missing:.2f}% |
| 分类字典命中翻译 | {dict_hits:,} |

---

## 2. 各品类商品数量

{top_categories}

---

## 3. 各品类价格中位数

| 品类 | 价格中位数 | 商品数量 |
|------|-----------|----------|
{price_rows}

---

## 4. 各品类评论数中位数

| 品类 | 评论中位数 | 平均评论 |
|------|-----------|----------|
{review_rows}

---

## 5. 品牌集中度

| 品类 | CR3 | CR5 |
|------|-----|-----|
{cr_rows}

---

## 6. 数据说明

- CR3/CR5: 每个三级品类中 Top3/Top5 品牌按 SKU 数量计算的集中度。
- 平均 SKU 密度: 店铺数 / 商品数，用于观察同品类店铺分散程度。
- 分类字段优先级: 历史三级分类 > category_path 解析结果 > 未识别三级分类。
- 京东分类字典用于将数字类目 ID 翻译为中文；当前历史数据大多已经是中文类目。

---

*本报告由 Codex 自动生成*
"""
    report_path.write_text(content, encoding="utf-8-sig")


def main() -> None:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    snapshot_date = datetime.now().strftime("%Y-%m-%d")

    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"未找到输入文件: {INPUT_CSV}")

    cat_dict = load_category_dictionary()
    df = read_csv_robust(INPUT_CSV, dtype=str, low_memory=False)
    normalized = normalize_dataset(df, cat_dict)
    normalized["snapshot_date"] = snapshot_date

    dict_hits = normalized["category_level3_raw"].astype(str).isin(cat_dict.keys()).sum()

    snapshot_file = SNAPSHOT_DIR / f"snapshot_{snapshot_date}.csv"
    normalized.to_csv(snapshot_file, index=False, encoding="utf-8-sig")

    stats = build_category_stats(normalized)
    stats_file = SNAPSHOT_DIR / "baseline_category_stats.csv"
    stats.to_csv(stats_file, index=False, encoding="utf-8-sig")

    report_file = SNAPSHOT_DIR / "baseline_report.md"
    write_report(normalized, stats, snapshot_date, report_file, int(dict_hits))

    timeseries_cols = ["SKU", "snapshot_date", "price", "review_count", "sales_text"]
    if "sales_sort" in normalized.columns:
        normalized["sales_sort"] = numeric_series(normalized["sales_sort"])
        timeseries_cols.append("sales_sort")
    timeseries = normalized[timeseries_cols].copy()
    timeseries["price_change"] = 0
    timeseries["review_change"] = 0
    timeseries_file = SNAPSHOT_DIR / "trend_timeseries.csv"
    timeseries.to_csv(timeseries_file, index=False, encoding="utf-8-sig")

    print("基准快照建立完成")
    print(f"输入数据: {INPUT_CSV.name}")
    print(f"商品数: {len(normalized):,}")
    print(f"三级分类数: {normalized['category_level3'].nunique():,}")
    print(f"分类字典条目: {len(cat_dict):,}")
    print(f"分类字典命中翻译: {int(dict_hits):,}")
    print(f"快照文件: {snapshot_file}")
    print(f"分类统计: {stats_file}")
    print(f"基准报告: {report_file}")
    print(f"时间序列: {timeseries_file}")


if __name__ == "__main__":
    main()
