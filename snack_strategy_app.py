# -*- coding: utf-8 -*-
"""Streamlit dashboard for snack category strategy analysis.

This app uses local CSV files only. It does not crawl JD or any external site.
"""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

DATA_CANDIDATES = [
    Path("integrated_selection_products.csv"),
    Path("structured_snacks_data_with_random_sales.csv"),
    Path("cleaned_snacks_data.csv"),
]
MERGED_CANDIDATES = [Path("merged_products.csv"), Path("final_products.csv")]
JD_CRAWL_DIR = Path("数据") / "京东评论爬取"
REVIEWS_CANDIDATES = [JD_CRAWL_DIR / "negative_reviews.csv", Path("negative_reviews.csv")]
PRODUCT_REVIEWS_CANDIDATES = [JD_CRAWL_DIR / "product_reviews.csv", Path("product_reviews.csv")]
PRODUCT_DETAILS_CANDIDATES = [JD_CRAWL_DIR / "product_details.csv", Path("product_details.csv")]
JD_CHECKPOINT_CANDIDATES = [JD_CRAWL_DIR / "crawled_items.csv", Path("crawled_items.csv")]
PRICE_HISTORY_CANDIDATES = [Path("price_history.csv")]
PRICE_CHECKPOINT_CANDIDATES = [Path("crawled_price_items.csv")]
LOG_DIR = Path("logs")
SNAPSHOT_DIR = Path("snapshots")
BASELINE_STATS_PATH = SNAPSHOT_DIR / "baseline_category_stats.csv"
BASELINE_REPORT_PATH = SNAPSHOT_DIR / "baseline_report.md"
TREND_TIMESERIES_PATH = SNAPSHOT_DIR / "trend_timeseries.csv"
QUALITY_REPORT_PATH = Path("selection_data_quality_report.json")
SINGLE_PRODUCT_APP_URL = "http://localhost:8502"


def path_cache_token(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def paths_cache_token(paths: Iterable[Path | None]) -> str:
    parts: list[str] = []
    for path in paths:
        if path is None:
            continue
        parts.append(f"{path}:{path_cache_token(path)}")
    return "|".join(parts)


@st.cache_data(show_spinner=False)
def read_csv(path: str, cache_token: int = 0) -> pd.DataFrame:
    _ = cache_token
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, dtype=str).fillna("")


def first_existing(candidates: Iterable[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def best_existing(candidates: Iterable[Path], file_name: str | None = None) -> Path | None:
    """Return the most useful local file, preferring explicit candidates then large discovered files."""
    explicit = [path for path in candidates if path.exists()]
    if explicit:
        return sorted(explicit, key=lambda item: item.stat().st_size, reverse=True)[0]
    if file_name:
        discovered = [path for path in Path(".").rglob(file_name) if path.is_file()]
        if discovered:
            return sorted(discovered, key=lambda item: item.stat().st_size, reverse=True)[0]
    return None


def load_optional_csv(candidates: Iterable[Path], file_name: str, columns: list[str] | None = None) -> tuple[pd.DataFrame, str]:
    path = best_existing(candidates, file_name)
    if path is None:
        return pd.DataFrame(columns=columns or []), ""
    try:
        return read_csv(str(path), path_cache_token(path)), str(path)
    except Exception:
        return pd.DataFrame(columns=columns or []), str(path)


def column_or_default(df: pd.DataFrame, column: str, default: object = "") -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([default] * len(df), index=df.index)


def latest_snapshot_path() -> Path | None:
    if not SNAPSHOT_DIR.exists():
        return None
    files = sorted(SNAPSHOT_DIR.glob("snapshot_*.csv"), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0] if files else None


def to_number(value: object) -> float:
    if value is None or pd.isna(value):
        return np.nan
    text = str(value).replace(",", "").strip()
    if not text:
        return np.nan
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return np.nan
    try:
        return float(match.group(0))
    except ValueError:
        return np.nan


def normalize_sku(value: object) -> str:
    text = str(value or "").strip()
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


def parse_sales(value: object) -> float:
    text = str(value or "").replace(",", "").strip()
    if not text:
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


def parse_keywords(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return [item.strip() for item in re.split(r"[|,，\s]+", text) if item.strip()]


def clean_brand(value: object) -> str:
    text = str(value or "").strip()
    if " - " in text:
        text = text.split(" - ", 1)[0].strip()
    return text


def has_promotion_text(text: object) -> bool:
    value = str(text or "").strip()
    return bool(value and value not in {"[]", "nan", "None"})


def classify_promo(text: object) -> str:
    value = str(text or "")
    if not has_promotion_text(value):
        return "无促销"
    if any(token in value for token in ["券", "礼金"]):
        return "优惠券/礼金"
    if any(token in value for token in ["满", "减", "每"]):
        return "满减"
    if any(token in value for token in ["直降", "特价", "秒杀", "折扣", "折"]):
        return "限时特价/折扣"
    if "包邮" in value:
        return "包邮"
    return "其他促销"


def make_price_band(series: pd.Series) -> pd.Series:
    prices = pd.to_numeric(series, errors="coerce")
    valid = prices.dropna()
    if len(valid) < 3 or valid.nunique() < 3:
        return pd.Series(["中价"] * len(series), index=series.index)
    q1, q2 = valid.quantile([0.33, 0.66]).tolist()
    if q1 >= q2:
        median = valid.median()
        bands = np.where(prices < median, "低价", np.where(prices > median, "高价", "中价"))
        return pd.Series(bands, index=series.index).where(prices.notna(), "未知")
    return pd.cut(prices, [-np.inf, q1, q2, np.inf], labels=["低价", "中价", "高价"], duplicates="drop").astype(str).replace("nan", "未知")


@st.cache_data(show_spinner=False)
def load_base_data(cache_token: str) -> tuple[pd.DataFrame, dict[str, str]]:
    _ = cache_token
    structured_path = first_existing(DATA_CANDIDATES)
    merged_path = first_existing(MERGED_CANDIDATES)
    if structured_path is None and merged_path is None:
        raise FileNotFoundError("未找到 structured/merged 数据文件。")

    frames: list[pd.DataFrame] = []
    meta: dict[str, str] = {}

    if structured_path is not None:
        raw = read_csv(str(structured_path), path_cache_token(structured_path))
        meta["structured"] = str(structured_path)
        df = pd.DataFrame(
            {
                "sku": column_or_default(raw, "SKU").map(normalize_sku),
                "title": column_or_default(raw, "商品名称"),
                "shop": column_or_default(raw, "店铺名称"),
                "brand": column_or_default(raw, "brand_from_name").where(
                    column_or_default(raw, "brand_from_name").astype(str).str.strip().ne(""),
                    column_or_default(raw, "品牌"),
                ).map(clean_brand),
                "brand_raw": column_or_default(raw, "品牌"),
                "price": column_or_default(raw, "现价").map(to_number),
                "original_price": column_or_default(raw, "原价").map(to_number),
                "sales": column_or_default(raw, "随机销量").where(
                    column_or_default(raw, "随机销量").astype(str).str.strip().ne(""),
                    column_or_default(raw, "sales_num").where(
                        column_or_default(raw, "sales_num").astype(str).str.strip().ne(""),
                        column_or_default(raw, "销售量"),
                    ),
                ).map(parse_sales),
                "comments": column_or_default(raw, "评论").map(parse_sales),
                "level1": column_or_default(raw, "一级分类"),
                "level2": column_or_default(raw, "二级分类"),
                "category": column_or_default(raw, "三级分类"),
                "promotion": column_or_default(raw, "促销信息"),
                "weight_g": column_or_default(raw, "weight_from_text").where(
                    column_or_default(raw, "weight_from_text").astype(str).str.strip().ne(""),
                    column_or_default(raw, "weight_g"),
                ).map(to_number),
                "flavor": column_or_default(raw, "flavor"),
                "package_type": column_or_default(raw, "package_type"),
                "specification": column_or_default(raw, "specification"),
                "keywords": column_or_default(raw, "keywords").map(parse_keywords),
                "brand_match_status": column_or_default(raw, "brand_match_status"),
                "weight_match_status": column_or_default(raw, "weight_match_status"),
                "extraction_notes": column_or_default(raw, "extraction_notes"),
                "source": "structured",
            }
        )
        frames.append(df)

    if merged_path is not None:
        raw = read_csv(str(merged_path), path_cache_token(merged_path))
        meta["merged"] = str(merged_path)
        category = column_or_default(raw, "historical_level3")
        if "category_path" in raw.columns:
            category = category.mask(category.astype(str).str.strip().eq(""), raw["category_path"].astype(str).str.split(">").str[-1].str.strip())
        df = pd.DataFrame(
            {
                "sku": column_or_default(raw, "product_id").map(normalize_sku),
                "title": column_or_default(raw, "product_title"),
                "shop": column_or_default(raw, "shop_name"),
                "brand": column_or_default(raw, "detail_brand").map(clean_brand),
                "brand_raw": column_or_default(raw, "historical_brand_category"),
                "price": column_or_default(raw, "current_price").map(to_number),
                "original_price": column_or_default(raw, "original_price").map(to_number),
                "sales": column_or_default(raw, "sales_sort").where(
                    column_or_default(raw, "sales_sort").astype(str).str.strip().ne(""),
                    column_or_default(raw, "sales_text_raw"),
                ).map(parse_sales),
                "comments": column_or_default(raw, "review_count").map(parse_sales),
                "level1": column_or_default(raw, "historical_level1"),
                "level2": column_or_default(raw, "historical_level2"),
                "category": category,
                "promotion": column_or_default(raw, "promotion_tags"),
                "weight_g": column_or_default(raw, "weight_g").map(to_number),
                "flavor": column_or_default(raw, "detail_flavor"),
                "package_type": column_or_default(raw, "detail_packing_list"),
                "specification": "",
                "keywords": [[] for _ in range(len(raw))],
                "brand_match_status": "",
                "weight_match_status": "",
                "extraction_notes": "",
                "source": "merged",
            }
        )
        frames.append(df)

    data = pd.concat(frames, ignore_index=True, sort=False)
    data["sku"] = data["sku"].astype(str).str.strip()
    data = data[data["sku"].ne("")]
    data["brand"] = data["brand"].replace("", np.nan)
    data["brand"] = data["brand"].fillna(data["brand_raw"].map(clean_brand)).replace("", "未知品牌")
    data["category"] = data["category"].astype(str).str.strip().replace("", "未分类")
    data["unit_price"] = data["price"] / data["weight_g"]
    data.loc[(data["price"] <= 0) | (data["weight_g"] <= 0) | ~np.isfinite(data["unit_price"]), "unit_price"] = np.nan
    data["discount_rate"] = (data["original_price"] - data["price"]) / data["original_price"]
    data.loc[(data["original_price"] <= 0) | (data["discount_rate"] < 0) | ~np.isfinite(data["discount_rate"]), "discount_rate"] = 0
    data["has_promotion"] = data["promotion"].map(has_promotion_text)
    data["promo_type"] = data["promotion"].map(classify_promo)
    data["price_band"] = data.groupby("category", group_keys=False)["price"].apply(make_price_band)
    data = data.drop_duplicates("sku", keep="first")
    return data, meta


@st.cache_data(show_spinner=False)
def load_reviews(cache_token: str) -> pd.DataFrame:
    _ = cache_token
    path = best_existing(REVIEWS_CANDIDATES, "negative_reviews.csv")
    if path is None:
        return pd.DataFrame(columns=["item_id", "review_text"])
    df = read_csv(str(path), path_cache_token(path))
    if "review_text" not in df.columns and "content" in df.columns:
        df = df.rename(columns={"content": "review_text"})
    if "review_text" not in df.columns:
        return pd.DataFrame(columns=["item_id", "review_text"])
    return df


@st.cache_data(show_spinner=False)
def load_collection_data(cache_token: str) -> dict[str, object]:
    _ = cache_token
    details, details_path = load_optional_csv(PRODUCT_DETAILS_CANDIDATES, "product_details.csv")
    reviews, reviews_path = load_optional_csv(PRODUCT_REVIEWS_CANDIDATES, "product_reviews.csv")
    negative, negative_path = load_optional_csv(REVIEWS_CANDIDATES, "negative_reviews.csv")
    jd_checkpoint, jd_checkpoint_path = load_optional_csv(JD_CHECKPOINT_CANDIDATES, "crawled_items.csv")
    price_history, price_history_path = load_optional_csv(PRICE_HISTORY_CANDIDATES, "price_history.csv")
    price_checkpoint, price_checkpoint_path = load_optional_csv(PRICE_CHECKPOINT_CANDIDATES, "crawled_price_items.csv")

    for frame in [details, reviews, negative, jd_checkpoint, price_history, price_checkpoint]:
        for column in frame.columns:
            if column in {"review_count", "current_price", "lowest_price", "highest_price"}:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return {
        "details": details,
        "details_path": details_path,
        "reviews": reviews,
        "reviews_path": reviews_path,
        "negative": negative,
        "negative_path": negative_path,
        "jd_checkpoint": jd_checkpoint,
        "jd_checkpoint_path": jd_checkpoint_path,
        "price_history": price_history,
        "price_history_path": price_history_path,
        "price_checkpoint": price_checkpoint,
        "price_checkpoint_path": price_checkpoint_path,
    }


@st.cache_data(show_spinner=False)
def load_snapshot_outputs(cache_token: str) -> dict[str, object]:
    _ = cache_token
    snapshot_path = latest_snapshot_path()
    snapshot = read_csv(str(snapshot_path), path_cache_token(snapshot_path)) if snapshot_path else pd.DataFrame()
    category_stats = read_csv(str(BASELINE_STATS_PATH), path_cache_token(BASELINE_STATS_PATH)) if BASELINE_STATS_PATH.exists() else pd.DataFrame()
    timeseries = read_csv(str(TREND_TIMESERIES_PATH), path_cache_token(TREND_TIMESERIES_PATH)) if TREND_TIMESERIES_PATH.exists() else pd.DataFrame()
    report = BASELINE_REPORT_PATH.read_text(encoding="utf-8-sig") if BASELINE_REPORT_PATH.exists() else ""

    for df in [snapshot, category_stats, timeseries]:
        for col in df.columns:
            if col in {
                "price",
                "review_count",
                "sales_sort",
                "price_change",
                "review_change",
                "商品数量",
                "品牌数",
                "店铺数",
                "价格均值",
                "价格中位数",
                "最低价",
                "最高价",
                "评论均值",
                "评论中位数",
                "评论总量",
                "有价格数据",
                "有评论数据",
                "CR3",
                "CR5",
                "平均SKU密度_店铺数除以商品数",
            }:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    return {
        "snapshot_path": snapshot_path,
        "snapshot": snapshot,
        "category_stats": category_stats,
        "timeseries": timeseries,
        "report": report,
    }


@st.cache_data(show_spinner=False)
def load_quality_report(cache_token: int) -> dict[str, object]:
    _ = cache_token
    if not QUALITY_REPORT_PATH.exists():
        return {}
    try:
        return json.loads(QUALITY_REPORT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def pct_text(value: object) -> str:
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "-"


def valid_category_data(data: pd.DataFrame) -> pd.DataFrame:
    return data[
        data["category"].astype(str).str.strip().ne("")
        & data["category"].astype(str).ne("未分类")
        & data["category"].astype(str).ne("未识别三级分类")
    ].copy()


def build_category_opportunity(data: pd.DataFrame, min_sku: int = 30, weight_mode: str = "均衡增长") -> pd.DataFrame:
    valid = valid_category_data(data)
    if valid.empty:
        return pd.DataFrame()

    summary = (
        valid.groupby("category")
        .agg(
            SKU数=("sku", "nunique"),
            品牌数=("brand", "nunique"),
            店铺数=("shop", lambda item: item.replace("", np.nan).dropna().nunique()),
            均价=("price", "mean"),
            中位价=("price", "median"),
            单位价中位数=("unit_price", "median"),
            销量代理=("sales", "sum"),
            评论热度=("comments", "sum"),
            平均评论=("comments", "mean"),
            促销占比=("has_promotion", "mean"),
        )
        .reset_index()
    )
    summary = summary[summary["SKU数"] >= min_sku].copy()
    if summary.empty:
        return summary

    summary["品牌集中度代理"] = summary["SKU数"] / summary["品牌数"].replace(0, np.nan)
    summary["供给稀缺度"] = 1 - summary["SKU数"].rank(pct=True)
    summary["需求热度"] = (
        summary["销量代理"].rank(pct=True) * 0.55
        + summary["评论热度"].rank(pct=True) * 0.35
        + summary["平均评论"].rank(pct=True) * 0.10
    )
    summary["价格健康度"] = 1 - summary["单位价中位数"].replace(0, np.nan).rank(pct=True).fillna(0.5)
    summary["竞争缓和度"] = 1 - summary["品牌集中度代理"].rank(pct=True).fillna(0.5)
    summary["促销弹性"] = summary["促销占比"].fillna(0).rank(pct=True)

    if weight_mode == "需求优先":
        weights = {"需求热度": 0.55, "供给稀缺度": 0.15, "价格健康度": 0.15, "竞争缓和度": 0.10, "促销弹性": 0.05}
    elif weight_mode == "蓝海优先":
        weights = {"需求热度": 0.30, "供给稀缺度": 0.35, "价格健康度": 0.15, "竞争缓和度": 0.15, "促销弹性": 0.05}
    else:
        weights = {"需求热度": 0.40, "供给稀缺度": 0.25, "价格健康度": 0.15, "竞争缓和度": 0.15, "促销弹性": 0.05}

    summary["趋势机会分"] = sum(summary[name] * weight for name, weight in weights.items()) * 100
    summary["趋势机会分"] = summary["趋势机会分"].round(1)
    summary["预测结论"] = np.select(
        [
            (summary["需求热度"] >= 0.70) & (summary["供给稀缺度"] >= 0.45),
            (summary["需求热度"] >= 0.70) & (summary["供给稀缺度"] < 0.45),
            (summary["供给稀缺度"] >= 0.70),
        ],
        ["优先测试", "高热高竞争", "蓝海观察"],
        default="常规跟踪",
    )
    summary["建议动作"] = np.select(
        [
            summary["预测结论"].eq("优先测试"),
            summary["预测结论"].eq("高热高竞争"),
            summary["预测结论"].eq("蓝海观察"),
        ],
        ["小批量上新，重点验证转化与复购", "做差异化规格/口味，避免纯价格战", "先补充竞品与评价样本，再做低成本测款"],
        default="保持监控，等待价格或评论信号增强",
    )
    return summary.sort_values("趋势机会分", ascending=False)


def category_selector(data: pd.DataFrame, label: str = "选择三级分类", key: str = "category_selector") -> str:
    categories = sorted([c for c in data["category"].dropna().unique().tolist() if c and c != "未分类"])
    default = categories.index("梅子干") if "梅子干" in categories else 0
    if not categories:
        st.warning("没有可用三级分类。")
        return "未分类"
    return st.selectbox(label, categories, index=default, key=key)


def get_category_data(data: pd.DataFrame, category: str) -> pd.DataFrame:
    return data[data["category"].eq(category)].copy()


def score_products(cat: pd.DataFrame) -> pd.DataFrame:
    scored = cat.copy()
    valid_unit = scored["unit_price"].dropna()
    if len(valid_unit):
        scored["unit_price_percentile"] = scored["unit_price"].rank(pct=True).fillna(1) * 100
    else:
        scored["unit_price_percentile"] = 100
    max_comments = max(float(scored["comments"].max() or 0), 1.0)
    scored["comment_heat_score"] = np.minimum(scored["comments"] / max_comments * 100, 100)
    scored["value_score_raw"] = (
        100
        - scored["unit_price_percentile"] * 0.40
        - scored["discount_rate"].fillna(0) * 30
        + scored["comment_heat_score"] * 0.30
    )
    scored["value_score"] = scored["value_score_raw"].clip(0, 100).round(2)
    scored["category_rank"] = scored["value_score"].rank(ascending=False, method="min").astype(int)
    return scored.sort_values(["value_score", "comments"], ascending=[False, False])


def metric_card(label: str, value: str, help_text: str | None = None) -> None:
    st.metric(label, value, help=help_text)


def render_bar_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    *,
    title: str = "",
    color: str | None = None,
    key: str | None = None,
    sort: str | list[str] = "-y",
) -> None:
    chart_df = df[[x, y] + ([color] if color else [])].copy()
    chart_df[y] = pd.to_numeric(chart_df[y], errors="coerce")
    chart_df = chart_df.dropna(subset=[x, y])
    if chart_df.empty:
        st.info("暂无可绘制数据。")
        return

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(9, 3.8))

    if color:
        pivot = chart_df.pivot_table(index=x, columns=color, values=y, aggfunc="sum", fill_value=0)
        if isinstance(sort, list):
            pivot = pivot.reindex([item for item in sort if item in pivot.index])
        elif sort == "-y":
            pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
        pivot.plot(kind="bar", ax=ax, width=0.82)
        ax.legend(title=color, fontsize=8)
    else:
        plot_df = chart_df.groupby(x, as_index=False)[y].sum()
        if isinstance(sort, list):
            plot_df[x] = pd.Categorical(plot_df[x], categories=sort, ordered=True)
            plot_df = plot_df.sort_values(x)
        elif sort == "-y":
            plot_df = plot_df.sort_values(y, ascending=False)
        ax.bar(plot_df[x].astype(str), plot_df[y])

    ax.set_title(title or "")
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.tick_params(axis="x", rotation=35, labelsize=8)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    st.pyplot(fig, clear_figure=True)


def render_competition(data: pd.DataFrame) -> None:
    category = category_selector(data, key="competition_category")
    cat = get_category_data(data, category)
    sku_count = len(cat)
    brand_counts = cat["brand"].value_counts()
    store_count = cat["shop"].replace("", np.nan).dropna().nunique()
    cr3 = brand_counts.head(3).sum() / sku_count if sku_count else 0
    cr5 = brand_counts.head(5).sum() / sku_count if sku_count else 0
    density = store_count / sku_count if sku_count else 0
    price_diversity = cat["price_band"].nunique() / 3
    competition_index = (
        (1 - cr3) * 40
        + min(sku_count / 300, 1) * 25
        + min(store_count / 100, 1) * 25
        + min(price_diversity, 1) * 10
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("品类竞争指数", f"{competition_index:.1f}/100")
    c2.metric("SKU 数", f"{sku_count:,}")
    c3.metric("CR3 / CR5", f"{cr3:.1%} / {cr5:.1%}")
    c4.metric("店铺数/商品数", f"{density:.2%}")

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("品牌梯队图")
        tier = brand_counts.head(20).rename_axis("品牌").reset_index(name="SKU数量")
        tier["份额"] = tier["SKU数量"] / sku_count
        render_bar_chart(tier, "品牌", "SKU数量", key="competition_brand_tier_chart")
        st.dataframe(tier, width="stretch", hide_index=True)
    with right:
        st.subheader("价格带热力图")
        heat = pd.crosstab(cat["price_band"], cat["brand"]).reindex(["低价", "中价", "高价", "未知"]).fillna(0)
        top_brands = brand_counts.head(8).index.tolist()
        heat = heat[[b for b in top_brands if b in heat.columns]]
        st.dataframe(heat.style.background_gradient(axis=None, cmap="Reds"), width="stretch")
        st.write("价格带分布")
        band_df = cat["price_band"].value_counts().reindex(["低价", "中价", "高价", "未知"]).fillna(0).rename_axis("价格带").reset_index(name="商品数量")
        render_bar_chart(band_df, "价格带", "商品数量", key="competition_price_band_chart", sort=["低价", "中价", "高价", "未知"])


def render_value_score(data: pd.DataFrame) -> None:
    category = category_selector(data, key="value_score_category")
    cat = get_category_data(data, category)
    scored = score_products(cat)
    st.caption("公式：100 - 每克单价排名百分位×40 - 促销折扣率×30 + 评论热度分×30，最终裁剪到 0-100。")
    options = scored["title"].head(500).tolist()
    if not options:
        st.warning("该品类暂无可评分商品。")
        return
    selected_title = st.selectbox("选择商品", options, key="value_score_product")
    row = scored[scored["title"].eq(selected_title)].iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("综合评分", f"{row['value_score']:.1f}")
    c2.metric("品类内排名", f"{int(row['category_rank'])}/{len(scored)}")
    c3.metric("每克单价", f"{row['unit_price']:.4f}" if pd.notna(row["unit_price"]) else "缺失")
    c4.metric("评论热度分", f"{row['comment_heat_score']:.1f}")
    st.dataframe(
        scored[
            [
                "category_rank",
                "sku",
                "title",
                "brand",
                "price",
                "weight_g",
                "unit_price",
                "comments",
                "discount_rate",
                "value_score",
            ]
        ].head(50),
        width="stretch",
        hide_index=True,
    )


def render_price_gap(data: pd.DataFrame) -> None:
    category = category_selector(data, key="price_gap_category")
    bin_size = st.number_input("价格粒度（元/档）", min_value=1, max_value=100, value=5, step=1, key="price_gap_bin_size")
    cat = get_category_data(data, category)
    prices = cat["price"].dropna()
    if prices.empty:
        st.warning("该品类缺少价格数据。")
        return
    max_price = max(float(prices.max()), float(bin_size))
    bins = np.arange(0, max_price + bin_size, bin_size)
    if len(bins) < 2:
        bins = np.array([0, bin_size])
    cat["price_bin"] = pd.cut(cat["price"], bins=bins, right=False)
    report = (
        cat.groupby("price_bin", observed=False)
        .agg(
            商品数量=("sku", "count"),
            平均评论=("comments", "mean"),
            平均销量=("sales", "mean"),
            总需求代理=("comments", "sum"),
        )
        .reset_index()
    )
    report["价格区间"] = report["price_bin"].astype(str)
    count_median = report["商品数量"].median()
    demand_median = report["总需求代理"].median()
    report["判断"] = np.where(
        (report["商品数量"] <= count_median) & (report["总需求代理"] >= demand_median),
        "蓝海候选",
        np.where((report["商品数量"] > count_median) & (report["总需求代理"] >= demand_median), "红海高需", "普通/低需"),
    )
    chart_df = report[["价格区间", "商品数量", "总需求代理"]].melt("价格区间", var_name="指标", value_name="数值")
    render_bar_chart(chart_df, "价格区间", "数值", color="指标", key="price_gap_chart", sort=None)
    st.dataframe(report[["价格区间", "商品数量", "平均评论", "平均销量", "总需求代理", "判断"]], width="stretch", hide_index=True)


def render_brand_portfolio(data: pd.DataFrame) -> None:
    category = category_selector(data, key="brand_portfolio_category")
    cat = get_category_data(data, category)
    brands = sorted(cat["brand"].dropna().unique().tolist())
    selected = st.multiselect("已有品牌列表", brands, default=brands[: min(3, len(brands))], key="brand_portfolio_existing")
    current = cat[cat["brand"].isin(selected)].copy()
    candidates = cat[~cat["brand"].isin(selected)].copy()

    st.subheader("已有品牌覆盖")
    if current.empty:
        st.info("请选择至少一个已有品牌。")
    else:
        coverage = current.groupby("brand").agg(SKU数量=("sku", "count"), 覆盖价格带=("price_band", lambda x: "、".join(sorted(set(x)))), 口味数=("flavor", lambda x: x.replace("", np.nan).dropna().nunique())).reset_index()
        st.dataframe(coverage, width="stretch", hide_index=True)

    current_bands = set(current["price_band"].dropna())
    current_flavors = set(current["flavor"].replace("", np.nan).dropna())
    category_bands = set(cat["price_band"].dropna())
    category_flavors = set(cat["flavor"].replace("", np.nan).dropna())
    missing_bands = sorted(category_bands - current_bands)
    missing_flavors = sorted(category_flavors - current_flavors)[:10]
    st.write(f"缺失价格带：{', '.join(missing_bands) if missing_bands else '暂无明显缺失'}")
    st.write(f"缺失口味 Top：{', '.join(missing_flavors) if missing_flavors else '暂无明显缺失'}")

    if candidates.empty:
        st.info("暂无候选品牌。")
        return

    recs = []
    for brand, group in candidates.groupby("brand"):
        bands = set(group["price_band"].dropna())
        flavors = set(group["flavor"].replace("", np.nan).dropna())
        score = len(bands & set(missing_bands)) * 25 + len(flavors & set(missing_flavors)) * 10 + min(len(group), 20)
        recs.append(
            {
                "推荐品牌": brand,
                "补充得分": score,
                "SKU数量": len(group),
                "覆盖价格带": "、".join(sorted(bands)),
                "补充口味": "、".join(sorted((flavors & set(missing_flavors)))) or "-",
                "推荐理由": f"补足价格带 {', '.join(sorted(bands & set(missing_bands))) or '覆盖宽度'}；SKU {len(group)} 个。",
            }
        )
    st.subheader("推荐引入品牌")
    st.dataframe(pd.DataFrame(recs).sort_values("补充得分", ascending=False).head(15), width="stretch", hide_index=True)


def render_promotion_effect(data: pd.DataFrame) -> None:
    category = category_selector(data, key="promotion_category")
    cat = get_category_data(data, category)
    promo_summary = (
        cat.groupby("promo_type")
        .agg(SKU数量=("sku", "count"), 平均销量=("sales", "mean"), 中位销量=("sales", "median"), 平均评论=("comments", "mean"), 平均折扣率=("discount_rate", "mean"))
        .reset_index()
        .sort_values("平均销量", ascending=False)
    )
    baseline = promo_summary.loc[promo_summary["promo_type"].eq("无促销"), "平均销量"]
    base = float(baseline.iloc[0]) if len(baseline) else float(cat["sales"].mean() or 0)
    promo_summary["相对无促销销量提升"] = promo_summary["平均销量"] / base - 1 if base else np.nan
    render_bar_chart(promo_summary.rename(columns={"promo_type": "促销类型"}), "促销类型", "平均销量", key="promotion_sales_chart")
    st.dataframe(promo_summary, width="stretch", hide_index=True)


def render_quality(data: pd.DataFrame) -> None:
    structured = data[data["source"].eq("structured")].copy()
    if structured.empty:
        st.warning("当前数据缺少结构化质检字段。")
        return
    brand_success = structured["brand_match_status"].astype(str).str.lower().isin(["1", "true", "consistent", "match"]).mean()
    weight_success = structured["weight_match_status"].astype(str).str.lower().isin(["1", "true", "consistent", "match"]).mean()
    c1, c2, c3 = st.columns(3)
    c1.metric("品牌匹配成功率", f"{brand_success:.1%}")
    c2.metric("重量提取成功率", f"{weight_success:.1%}")
    c3.metric("质检样本数", f"{len(structured):,}")
    fail = structured[
        ~structured["brand_match_status"].astype(str).str.lower().isin(["1", "true", "consistent", "match"])
        | ~structured["weight_match_status"].astype(str).str.lower().isin(["1", "true", "consistent", "match"])
    ]
    pattern = fail["extraction_notes"].replace("", "无备注").value_counts().head(20).rename_axis("失败/备注模式").reset_index(name="数量")
    st.subheader("常见失败模式")
    st.dataframe(pattern, width="stretch", hide_index=True)
    st.subheader("问题样例")
    st.dataframe(fail[["sku", "title", "brand", "weight_g", "brand_match_status", "weight_match_status", "extraction_notes"]].head(50), width="stretch", hide_index=True)


def classify_review_reason(text: str) -> str:
    rules = {
        "口感": ["难吃", "味道", "口感", "太甜", "太咸", "发苦", "不脆"],
        "包装": ["包装", "破损", "漏气", "压坏", "盒子", "袋子"],
        "物流": ["物流", "快递", "配送", "慢", "延迟"],
        "品质": ["变质", "发霉", "过期", "异味", "质量", "坏了"],
        "规格/缺斤少两": ["少", "重量", "克", "分量", "缺斤"],
    }
    for label, keywords in rules.items():
        if any(keyword in text for keyword in keywords):
            return label
    return "其他"


def render_review_attribution() -> None:
    reviews = load_reviews(paths_cache_token([best_existing(REVIEWS_CANDIDATES, "negative_reviews.csv")]))
    if reviews.empty or "review_text" not in reviews.columns or reviews["review_text"].astype(str).str.strip().eq("").all():
        st.warning("差评文本数据暂未就绪。当前 `negative_reviews.csv` 没有有效评论行，因此只展示模块占位和分类规则。")
        st.write("后续有评论文本后，将按口感、包装、物流、品质、规格/缺斤少两等原因进行归因。")
        return
    reviews = reviews.copy()
    reviews["reason"] = reviews["review_text"].map(classify_review_reason)
    summary = reviews.groupby(["item_id", "reason"]).size().reset_index(name="数量").sort_values("数量", ascending=False)
    reason_df = reviews["reason"].value_counts().rename_axis("归因").reset_index(name="数量")
    render_bar_chart(reason_df, "归因", "数量", key="review_reason_chart")
    st.dataframe(summary, width="stretch", hide_index=True)
    st.subheader("评论样例")
    st.dataframe(reviews[["item_id", "reason", "review_text"]].head(100), width="stretch", hide_index=True)


def render_selection_forecast(data: pd.DataFrame) -> None:
    min_sku = st.slider("最小品类样本数", min_value=10, max_value=300, value=30, step=10, key="forecast_min_sku")
    top_n = st.slider("展示 Top N", min_value=5, max_value=30, value=15, step=5, key="forecast_top_n")
    weight_mode = st.radio("预测偏好", ["均衡增长", "需求优先", "蓝海优先"], horizontal=True, key="forecast_weight_mode")
    summary = build_category_opportunity(data, min_sku=min_sku, weight_mode=weight_mode)
    if summary.empty:
        st.info("当前筛选条件下没有足够样本的品类。")
        return

    ranked = summary.sort_values("趋势机会分", ascending=False).head(top_n)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("预测品类数", f"{len(summary):,}")
    c2.metric("Top 机会品类", ranked.iloc[0]["category"] if not ranked.empty else "-")
    c3.metric("最高机会分", f"{ranked.iloc[0]['趋势机会分']:.1f}" if not ranked.empty else "-")
    c4.metric("评分口径", weight_mode)

    chart_df = ranked[["category", "趋势机会分"]].rename(columns={"category": "三级分类"})
    render_bar_chart(chart_df, "三级分类", "趋势机会分", key="selection_forecast_chart")

    show_cols = [
        "category",
        "趋势机会分",
        "预测结论",
        "建议动作",
        "SKU数",
        "品牌数",
        "中位价",
        "单位价中位数",
        "销量代理",
        "评论热度",
        "促销占比",
    ]
    st.dataframe(ranked[show_cols].rename(columns={"category": "三级分类"}), width="stretch", hide_index=True)
    st.caption("预测为基于当前本地快照的机会评分，不等同于真实销量预测；需要结合后续多日快照、成本和供应链验证。")


def render_decision_home(data: pd.DataFrame) -> None:
    report = load_quality_report(path_cache_token(QUALITY_REPORT_PATH))
    coverage = report.get("coverage", {}) if report else {}
    opportunity = build_category_opportunity(data, min_sku=30, weight_mode="均衡增长")

    st.subheader("今日选品决策首页")
    st.caption("按“看机会、定策略、控风险”的顺序组织，优先展示能直接推动选品动作的结论。")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("统一 SKU", f"{len(data):,}")
    c2.metric("可识别品类", f"{valid_category_data(data)['category'].nunique():,}")
    c3.metric("价格覆盖", pct_text(coverage.get("price", {}).get("coverage", data["price"].notna().mean())))
    c4.metric("单位价覆盖", pct_text(coverage.get("unit_price_valid", {}).get("coverage", data["unit_price"].notna().mean())))
    c5.metric("历史价覆盖", pct_text(coverage.get("mmb_price_history", {}).get("coverage", 0)))

    path_cols = st.columns(3)
    with path_cols[0]:
        st.markdown("**第一步：看机会**")
        st.write("用趋势预测、品类竞争和价格带空白，先判断哪个品类值得进入。")
    with path_cols[1]:
        st.markdown("**第二步：定策略**")
        st.write("用单品性价比、品牌组合和促销效果，确定货盘、价格和上新打法。")
    with path_cols[2]:
        st.markdown("**第三步：控风险**")
        st.write("用差评归因、数据质量和趋势追踪，判断结论可信度与补数优先级。")

    if opportunity.empty:
        st.warning("当前数据不足以生成品类机会榜。")
        return

    top_categories = opportunity.head(10).copy()
    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Top 机会品类")
        render_bar_chart(
            top_categories[["category", "趋势机会分"]].rename(columns={"category": "三级分类"}),
            "三级分类",
            "趋势机会分",
            key="home_opportunity_chart",
        )
        st.dataframe(
            top_categories[
                ["category", "趋势机会分", "预测结论", "建议动作", "SKU数", "品牌数", "中位价", "销量代理", "评论热度"]
            ].rename(columns={"category": "三级分类"}),
            width="stretch",
            hide_index=True,
        )

    with right:
        st.subheader("今日建议测试商品")
        candidate_rows: list[pd.DataFrame] = []
        for category in top_categories["category"].head(5):
            scored = score_products(get_category_data(data, str(category)))
            if scored.empty:
                continue
            picked = scored.head(3).copy()
            picked["机会品类"] = category
            candidate_rows.append(picked)
        if candidate_rows:
            candidates = pd.concat(candidate_rows, ignore_index=True, sort=False)
            candidates = candidates.sort_values(["value_score", "comments"], ascending=[False, False]).head(12)
            st.dataframe(
                candidates[
                    ["机会品类", "sku", "title", "brand", "price", "weight_g", "unit_price", "comments", "value_score"]
                ].rename(
                    columns={
                        "sku": "SKU",
                        "title": "商品名称",
                        "brand": "品牌",
                        "price": "现价",
                        "weight_g": "重量_g",
                        "unit_price": "单位价",
                        "comments": "评论热度",
                        "value_score": "性价比分",
                    }
                ),
                width="stretch",
                hide_index=True,
            )
            st.link_button("打开单品智能分析新窗口", SINGLE_PRODUCT_APP_URL, width="stretch")
        else:
            st.info("当前 Top 品类缺少可评分商品。")

    risk_left, risk_right = st.columns(2)
    with risk_left:
        st.subheader("高热高竞争品类")
        crowded = opportunity[opportunity["预测结论"].eq("高热高竞争")].head(10)
        if crowded.empty:
            st.info("暂无明显高热高竞争品类。")
        else:
            st.dataframe(
                crowded[["category", "趋势机会分", "SKU数", "品牌数", "销量代理", "建议动作"]].rename(columns={"category": "三级分类"}),
                width="stretch",
                hide_index=True,
            )
    with risk_right:
        st.subheader("数据质量告警")
        if report:
            flags = report.get("quality_flags", {})
            alerts = pd.DataFrame(
                [
                    {"问题": "未识别三级分类", "数量": flags.get("missing_category", 0), "影响": "影响品类竞争、趋势预测和价格带判断"},
                    {"问题": "无效/缺失重量", "数量": flags.get("invalid_weight", 0), "影响": "影响单位价和性价比评分"},
                    {"问题": "无效/缺失价格", "数量": flags.get("invalid_price", 0), "影响": "影响价格带和促销判断"},
                    {"问题": "疑似重复商品", "数量": flags.get("duplicate_title_price_weight", 0), "影响": "影响 SKU 供给密度判断"},
                ]
            )
            st.dataframe(alerts, width="stretch", hide_index=True)
        else:
            st.info("尚未生成质量报告，可运行 `python integrate_selection_data.py` 后刷新。")


def render_single_product_assistant_embed() -> None:
    st.subheader("🔍 单品智能分析")
    st.caption("点击下方按钮，在新窗口打开单品分析工具")
    col_a, col_b = st.columns(2)
    with col_a:
        st.link_button("📎 粘贴链接自动解析", f"{SINGLE_PRODUCT_APP_URL}?mode=link", width="stretch")
        st.caption("支持京东/淘宝链接、分享文案、SKU")
    with col_b:
        st.link_button("✏️ 手动输入商品信息", f"{SINGLE_PRODUCT_APP_URL}?mode=manual", width="stretch")
        st.caption("直接填写品类、价格、重量等字段")


def nonempty_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return 0
    return int(df[column].astype(str).str.strip().ne("").sum())


def latest_file(pattern: str) -> Path | None:
    if not LOG_DIR.exists():
        return None
    files = sorted(LOG_DIR.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0] if files else None


def file_mtime_text(path: Path | str | None) -> str:
    if not path:
        return "-"
    file_path = Path(path)
    if not file_path.exists():
        return "-"
    return pd.Timestamp.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def read_log_tail(path: Path | None, max_chars: int = 6000) -> str:
    if path is None or not path.exists():
        return ""
    try:
        raw = path.read_bytes()
    except Exception:
        return ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    elif raw.count(b"\x00") > max(8, len(raw) // 20):
        encodings = ("utf-16", "utf-16-le", "utf-16-be", "utf-8-sig", "gb18030", "utf-8")
    else:
        encodings = ("utf-8-sig", "gb18030", "utf-16", "utf-8")
    text = ""
    best_score = float("inf")
    for encoding in encodings:
        try:
            candidate = raw.decode(encoding)
        except Exception:
            continue
        score = candidate.count("\ufffd") * 1000 + candidate.count("\x00") * 10
        if score < best_score:
            text = candidate
            best_score = score
    text = text.replace("\x00", "")
    return text[-max_chars:]


def status_counts(df: pd.DataFrame, column: str = "status") -> dict[str, int]:
    if df.empty or column not in df.columns:
        return {}
    return df[column].astype(str).str.strip().replace("", "unknown").value_counts().to_dict()


def render_mechanism_audit(data: pd.DataFrame) -> None:
    report = load_quality_report(path_cache_token(QUALITY_REPORT_PATH))
    outputs = load_collection_data(
        paths_cache_token(
            [
                best_existing(PRODUCT_DETAILS_CANDIDATES, "product_details.csv"),
                best_existing(PRODUCT_REVIEWS_CANDIDATES, "product_reviews.csv"),
                best_existing(REVIEWS_CANDIDATES, "negative_reviews.csv"),
                best_existing(JD_CHECKPOINT_CANDIDATES, "crawled_items.csv"),
                best_existing(PRICE_HISTORY_CANDIDATES, "price_history.csv"),
                best_existing(PRICE_CHECKPOINT_CANDIDATES, "crawled_price_items.csv"),
                latest_snapshot_path(),
            ]
        )
    )

    details = outputs["details"]
    reviews = outputs["reviews"]
    negative = outputs["negative"]
    jd_checkpoint = outputs["jd_checkpoint"]
    price_history = outputs["price_history"]
    price_checkpoint = outputs["price_checkpoint"]
    latest_jd_log = latest_file("jd_cdp_review_scraper_*.out.log")
    latest_mmb_log = latest_file("mmb_price_history_batch_*.out.log")
    jd_tail = read_log_tail(latest_jd_log)
    mmb_tail = read_log_tail(latest_mmb_log)
    coverage = report.get("coverage", {}) if report else {}

    st.subheader("项目机制自查")
    st.caption("本页只读取本地 CSV、质量报告和日志，用来确认最新数据是否已经进入经营工作台。")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("统一 SKU", f"{len(data):,}")
    m2.metric("价格覆盖", pct_text(coverage.get("price", {}).get("coverage", data["price"].notna().mean())))
    m3.metric("单位价覆盖", pct_text(coverage.get("unit_price_valid", {}).get("coverage", data["unit_price"].notna().mean())))
    m4.metric("京东评论覆盖", pct_text(coverage.get("jd_reviews", {}).get("coverage", len(details) / max(len(data), 1))))
    m5.metric("历史价覆盖", pct_text(coverage.get("mmb_price_history", {}).get("coverage", 0)))

    st.info(
        f"最新质量报告：{report.get('generated_at', '-') if report else '-'}；"
        f"当前已应用 integrated_selection_products.csv、price_history.csv、京东评论补充表和快照趋势表。"
    )
    st.warning(
        "近期失败结论：京东详情/评论主要卡在验证码等待超时；慢慢买历史价主要卡在登录浮层遮挡查询按钮。"
        "已处理：京东与慢慢买分离到 9222/9223 两个 CDP 端口，慢慢买查询按钮新增 JS 触发兜底，守护进程保留断点并在连续风控时停机。"
    )

    jd_counts = status_counts(jd_checkpoint)
    mmb_counts = status_counts(price_history)
    mechanism_rows = [
        {
            "机制": "京东列表/主表整合",
            "当前状态": "已落地到 integrated_selection_products.csv",
            "最新进度": f"{len(data):,} 个唯一 SKU，0 个重复 SKU",
            "近期问题": "平台搜索/详情抓取存在验证码和访问限制，已改为本地快照整合为主",
            "解决方式": "保留本地 CSV 快照；增量脚本只补充缺口字段，不在页面加载时访问外站",
        },
        {
            "机制": "京东详情与评论补充",
            "当前状态": "断点续爬，遇风控自动停",
            "最新进度": f"详情 {len(details):,}；评论 {len(reviews):,}；差评 {len(negative):,}；断点 {len(jd_checkpoint):,}；状态 {jd_counts}",
            "近期问题": "最新日志显示验证码等待超时；另有早期运行被慢慢买页面串页打断",
            "解决方式": "京东固定使用 CDP 9222；慢慢买改用 9223；连续风控自动停止，人工验证后从断点重试",
        },
        {
            "机制": "慢慢买历史价补充",
            "当前状态": "分批限额爬取，成功/无结果都会写断点",
            "最新进度": f"记录 {len(price_history):,}；断点 {len(price_checkpoint):,}；状态 {mmb_counts}",
            "近期问题": "登录浮层 PClogin 挡住查询按钮，随后出现 TargetClosed 硬失败",
            "解决方式": "查询按钮增加 JS 触发兜底；守护脚本固定 CDP 9223、每日限额 50、活动锁防并发",
        },
        {
            "机制": "统一选品数据生成",
            "当前状态": f"质量报告时间 {report.get('generated_at', '-') if report else '-'}",
            "最新进度": f"主表 {report.get('row_count', len(data)) if report else len(data):,}；品类识别 {pct_text(coverage.get('category_recognized', {}).get('coverage', 0))}",
            "近期问题": "详情/评论/历史价属于增强层，覆盖率低于主表基础字段",
            "解决方式": "运行 integrate_selection_data.py 后，Streamlit 根据文件 mtime 自动刷新缓存",
        },
        {
            "机制": "快照与趋势基线",
            "当前状态": "可用本地快照对比周度变化",
            "最新进度": f"最新快照 {latest_snapshot_path() or '-'}；更新时间 {file_mtime_text(latest_snapshot_path())}",
            "近期问题": "趋势只反映已落地快照，不代表实时市场全量变化",
            "解决方式": "保持 snapshot_*.csv 周期化生成，趋势页读取最新快照和 trend_timeseries.csv",
        },
    ]
    st.dataframe(pd.DataFrame(mechanism_rows), width="stretch", hide_index=True)

    st.subheader("分层数据进度")
    layer_rows = [
        {"层级": "L0 商品主表", "指标": "统一 SKU / 品牌 / 三级分类", "进度": f"{len(data):,} / {data['brand'].nunique():,} / {data['category'].nunique():,}", "应用位置": "决策首页、机会预测、竞争格局"},
        {"层级": "L1 标准字段", "指标": "标题/品牌/品类/价格", "进度": f"{pct_text(coverage.get('title', {}).get('coverage', 1))} / {pct_text(coverage.get('brand', {}).get('coverage', 1))} / {pct_text(coverage.get('category', {}).get('coverage', 1))} / {pct_text(coverage.get('price', {}).get('coverage', 0))}", "应用位置": "全局筛选、价格带、品类机会"},
        {"层级": "L2 规格与单位价", "指标": "重量 / 单位价", "进度": f"{pct_text(coverage.get('weight', {}).get('coverage', 0))} / {pct_text(coverage.get('unit_price_valid', {}).get('coverage', 0))}", "应用位置": "单品性价比、价格竞争力"},
        {"层级": "L3 京东详情评论", "指标": "详情 / 评论明细 / 差评", "进度": f"{len(details):,} / {len(reviews):,} / {len(negative):,}", "应用位置": "差评归因、风险诊断"},
        {"层级": "L4 历史价", "指标": "成功 / 无结果 / 错误", "进度": f"{mmb_counts.get('success', 0):,} / {mmb_counts.get('no_result', 0):,} / {mmb_counts.get('error', 0):,}", "应用位置": "数据同步、价格趋势样本"},
        {"层级": "L5 快照趋势", "指标": "最新快照 / 时间序列", "进度": f"{file_mtime_text(latest_snapshot_path())} / {file_mtime_text(TREND_TIMESERIES_PATH)}", "应用位置": "趋势基线页"},
    ]
    st.dataframe(pd.DataFrame(layer_rows), width="stretch", hide_index=True)

    with st.expander("最近失败日志摘要", expanded=True):
        st.write("京东评论/详情")
        st.code(jd_tail[-1800:] if jd_tail else "未找到最新京东日志", language="text")
        st.write("慢慢买历史价")
        st.code(mmb_tail[-1800:] if mmb_tail else "未找到最新慢慢买日志", language="text")


def render_collection_sync(data: pd.DataFrame) -> None:
    outputs = load_collection_data(
        paths_cache_token(
            [
                best_existing(PRODUCT_DETAILS_CANDIDATES, "product_details.csv"),
                best_existing(PRODUCT_REVIEWS_CANDIDATES, "product_reviews.csv"),
                best_existing(REVIEWS_CANDIDATES, "negative_reviews.csv"),
                best_existing(JD_CHECKPOINT_CANDIDATES, "crawled_items.csv"),
                best_existing(PRICE_HISTORY_CANDIDATES, "price_history.csv"),
                best_existing(PRICE_CHECKPOINT_CANDIDATES, "crawled_price_items.csv"),
            ]
        )
    )
    details = outputs["details"]
    reviews = outputs["reviews"]
    negative = outputs["negative"]
    jd_checkpoint = outputs["jd_checkpoint"]
    price_history = outputs["price_history"]
    price_checkpoint = outputs["price_checkpoint"]

    st.subheader("最新本地数据同步状态")
    st.caption("这里只读取本地 CSV，不会访问京东或慢慢买。")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("商品主表", f"{len(data):,}")
    m2.metric("详情补充", f"{len(details):,}")
    m3.metric("评论明细", f"{len(reviews):,}")
    m4.metric("差评文本", f"{len(negative):,}")
    success_count = int(price_history.get("status", pd.Series(dtype=str)).astype(str).eq("success").sum()) if not price_history.empty else 0
    m5.metric("历史价成功", f"{success_count:,}")
    m6.metric("历史价断点", f"{len(price_checkpoint):,}")

    with st.expander("数据文件来源", expanded=True):
        source_rows = [
            {"数据": "商品主表", "文件": "merged_products.csv", "行数": len(data)},
            {"数据": "京东详情", "文件": outputs["details_path"], "行数": len(details)},
            {"数据": "京东评论", "文件": outputs["reviews_path"], "行数": len(reviews)},
            {"数据": "京东差评", "文件": outputs["negative_path"], "行数": len(negative)},
            {"数据": "京东断点", "文件": outputs["jd_checkpoint_path"], "行数": len(jd_checkpoint)},
            {"数据": "慢慢买历史价", "文件": outputs["price_history_path"], "行数": len(price_history)},
            {"数据": "慢慢买断点", "文件": outputs["price_checkpoint_path"], "行数": len(price_checkpoint)},
        ]
        st.dataframe(pd.DataFrame(source_rows), width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("京东详情/评论质量")
        quality_rows = pd.DataFrame(
            [
                {"指标": "详情页记录", "数值": len(details)},
                {"指标": "店铺非空", "数值": nonempty_count(details, "shop_name")},
                {"指标": "好评率非空", "数值": nonempty_count(details, "好评率")},
                {"指标": "评价标签非空", "数值": nonempty_count(details, "评价标签")},
                {"指标": "产地非空", "数值": nonempty_count(details, "产地")},
                {"指标": "保质期非空", "数值": nonempty_count(details, "保质期")},
                {"指标": "评论文本非空", "数值": nonempty_count(reviews, "content")},
                {"指标": "差评文本非空", "数值": nonempty_count(negative, "content") or nonempty_count(negative, "review_text")},
            ]
        )
        st.dataframe(quality_rows, width="stretch", hide_index=True)

        if not jd_checkpoint.empty and "status" in jd_checkpoint.columns:
            status_df = jd_checkpoint["status"].value_counts().rename_axis("状态").reset_index(name="数量")
            render_bar_chart(status_df, "状态", "数量", key="jd_checkpoint_status")

    with right:
        st.subheader("慢慢买历史价格质量")
        if price_history.empty:
            st.info("当前没有 price_history.csv 数据。")
        else:
            status_df = price_history["status"].value_counts().rename_axis("状态").reset_index(name="数量") if "status" in price_history.columns else pd.DataFrame()
            if not status_df.empty:
                render_bar_chart(status_df, "状态", "数量", key="price_history_status")
                st.dataframe(status_df, width="stretch", hide_index=True)
            trend_count = nonempty_count(price_history, "price_trend")
            price_metrics = pd.DataFrame(
                [
                    {"指标": "记录数", "数值": len(price_history)},
                    {"指标": "走势 JSON 非空", "数值": trend_count},
                    {"指标": "当前价非空", "数值": nonempty_count(price_history, "current_price")},
                    {"指标": "历史最低价非空", "数值": nonempty_count(price_history, "lowest_price")},
                    {"指标": "历史最高价非空", "数值": nonempty_count(price_history, "highest_price")},
                ]
            )
            st.dataframe(price_metrics, width="stretch", hide_index=True)

    st.subheader("历史价格样本")
    if not price_history.empty:
        sample_cols = [col for col in ["item_id", "title", "current_price", "lowest_price", "lowest_date", "highest_price", "status", "error_msg"] if col in price_history.columns]
        st.dataframe(price_history[sample_cols].head(50), width="stretch", hide_index=True)

    st.subheader("差评文本样本")
    if not negative.empty:
        if "review_text" not in negative.columns and "content" in negative.columns:
            negative = negative.rename(columns={"content": "review_text"})
        sample_cols = [col for col in ["item_id", "title", "review_text", "star_level", "crawl_time"] if col in negative.columns]
        st.dataframe(negative[sample_cols].head(50), width="stretch", hide_index=True)


def refresh_baseline_snapshot() -> None:
    import build_baseline_snapshot

    build_baseline_snapshot.main()
    load_snapshot_outputs.clear()


def render_baseline_trend() -> None:
    outputs = load_snapshot_outputs(
        paths_cache_token(
            [
                latest_snapshot_path(),
                BASELINE_STATS_PATH if BASELINE_STATS_PATH.exists() else None,
                TREND_TIMESERIES_PATH if TREND_TIMESERIES_PATH.exists() else None,
                BASELINE_REPORT_PATH if BASELINE_REPORT_PATH.exists() else None,
            ]
        )
    )
    snapshot = outputs["snapshot"]
    category_stats = outputs["category_stats"]
    timeseries = outputs["timeseries"]
    report = outputs["report"]
    snapshot_path = outputs["snapshot_path"]

    top_left, top_right = st.columns([1, 3])
    with top_left:
        if st.button("刷新快照", key="refresh_baseline_snapshot", type="primary"):
            with st.spinner("正在基于本地 merged_products.csv 重建快照..."):
                refresh_baseline_snapshot()
            st.rerun()
    with top_right:
        if snapshot_path:
            st.caption(f"当前快照：`{snapshot_path}`")
        else:
            st.warning("尚未生成快照文件。")

    if snapshot.empty:
        st.info("请先点击“刷新快照”生成基准文件。")
        return

    snapshot_date = snapshot["snapshot_date"].iloc[0] if "snapshot_date" in snapshot.columns else "-"
    price_count = int(pd.to_numeric(snapshot.get("price", pd.Series(dtype=float)), errors="coerce").notna().sum())
    review_count = int(pd.to_numeric(snapshot.get("review_count", pd.Series(dtype=float)), errors="coerce").notna().sum())
    category_col = "category_level3" if "category_level3" in snapshot.columns else "三级分类"
    category_count = snapshot[category_col].replace("", np.nan).dropna().nunique() if category_col in snapshot.columns else 0
    unresolved = int(snapshot[category_col].eq("未识别三级分类").sum()) if category_col in snapshot.columns else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("快照日期", snapshot_date)
    c2.metric("SKU 数", f"{len(snapshot):,}")
    c3.metric("三级分类数", f"{category_count:,}")
    c4.metric("价格覆盖率", f"{price_count / len(snapshot):.1%}" if len(snapshot) else "-")
    c5.metric("评论覆盖率", f"{review_count / len(snapshot):.1%}" if len(snapshot) else "-")

    if unresolved:
        st.info(f"未识别三级分类：{unresolved:,} 个 SKU，主要来自昨天新增爬取但缺少真实三级类目的商品。")

    if not category_stats.empty:
        st.subheader("基准分类统计")
        metric_options = [col for col in ["商品数量", "评论总量", "价格中位数", "CR3", "CR5"] if col in category_stats.columns]
        sort_metric = st.selectbox("排序指标", metric_options, key="baseline_sort_metric")
        top_n = st.slider("展示 Top N", min_value=5, max_value=30, value=15, step=5, key="baseline_top_n")
        sorted_stats = category_stats.sort_values(sort_metric, ascending=False).head(top_n)
        cat_col = category_stats.columns[0]
        render_bar_chart(sorted_stats, cat_col, sort_metric, key="baseline_category_chart")
        st.dataframe(
            category_stats.sort_values(sort_metric, ascending=False),
            width="stretch",
            hide_index=True,
        )

    st.subheader("趋势时间序列")
    if timeseries.empty:
        st.info("暂无趋势时间序列。")
    else:
        ts = timeseries.copy()
        if "snapshot_date" in ts.columns:
            date_counts = ts.groupby("snapshot_date").agg(SKU数量=("SKU", "count"), 平均价格=("price", "mean"), 平均评论=("review_count", "mean")).reset_index()
            if date_counts["snapshot_date"].nunique() > 1:
                trend_plot = date_counts.melt("snapshot_date", var_name="指标", value_name="数值")
                render_bar_chart(trend_plot, "snapshot_date", "数值", color="指标", key="baseline_trend_chart", sort=None)
            else:
                st.caption("当前只有一个快照日期，后续再次刷新后会形成跨日趋势。")
            st.dataframe(date_counts, width="stretch", hide_index=True)
        st.dataframe(ts.head(300), width="stretch", hide_index=True)

    downloads = st.columns(4)
    download_files = [
        ("快照 CSV", snapshot_path),
        ("分类统计 CSV", BASELINE_STATS_PATH),
        ("趋势 CSV", TREND_TIMESERIES_PATH),
        ("基准报告 MD", BASELINE_REPORT_PATH),
    ]
    for col, (label, path) in zip(downloads, download_files):
        with col:
            if path and Path(path).exists():
                st.download_button(label, Path(path).read_bytes(), file_name=Path(path).name, key=f"download_{label}")

    if report:
        with st.expander("基准报告全文", expanded=False):
            st.markdown(report)


def main() -> None:
    st.set_page_config(page_title="零食经营分析驾驶舱", layout="wide")
    st.title("AI 零食选品经营工作台")
    st.caption("基于现有本地 CSV 数据构建，不访问京东网页；从机会发现、策略制定到风险控制形成闭环。")

    data, meta = load_base_data(paths_cache_token([first_existing(DATA_CANDIDATES), first_existing(MERGED_CANDIDATES)]))
    page_options = [
        "自查总览｜机制与数据进度",
        "决策首页",
        "看机会｜选品趋势预测",
        "看机会｜品类竞争格局",
        "看机会｜价格带空白点",
        "定策略｜单品评估页",
        "定策略｜单品性价比",
        "定策略｜品牌组合推荐",
        "定策略｜促销策略效果",
        "控风险｜AI数据质量诊断",
        "控风险｜差评归因",
        "控风险｜数据同步与趋势",
    ]
    page_ids = {
        "audit": "自查总览｜机制与数据进度",
        "home": "决策首页",
        "forecast": "看机会｜选品趋势预测",
        "competition": "看机会｜品类竞争格局",
        "price_gap": "看机会｜价格带空白点",
        "single": "定策略｜单品评估页",
        "value": "定策略｜单品性价比",
        "brand": "定策略｜品牌组合推荐",
        "promotion": "定策略｜促销策略效果",
        "quality": "控风险｜AI数据质量诊断",
        "review": "控风险｜差评归因",
        "sync": "控风险｜数据同步与趋势",
    }
    page_to_id = {label: page_id for page_id, label in page_ids.items()}
    query_page = str(st.query_params.get("page", "audit"))
    default_page = page_ids.get(query_page, page_options[0])

    with st.sidebar:
        st.header("数据状态")
        for key, value in meta.items():
            st.write(f"{key}: `{value}`")
        st.metric("统一 SKU 数", f"{len(data):,}")
        st.metric("三级分类数", f"{data['category'].nunique():,}")
        st.metric("品牌数", f"{data['brand'].nunique():,}")
        st.divider()
        st.header("决策路径")
        st.write("1. 看机会：趋势、竞争、空白价格带")
        st.write("2. 定策略：单品、品牌、促销")
        st.write("3. 控风险：差评、质量、趋势追踪")
        if st.button("打开单品评估页", width="stretch", type="primary"):
            st.query_params["page"] = "single"
            st.rerun()

    nav_groups = [
        ["自查总览｜机制与数据进度"],
        ["决策首页"],
        ["看机会｜选品趋势预测", "看机会｜品类竞争格局", "看机会｜价格带空白点"],
        ["定策略｜单品评估页", "定策略｜单品性价比", "定策略｜品牌组合推荐", "定策略｜促销策略效果"],
        ["控风险｜AI数据质量诊断", "控风险｜差评归因", "控风险｜数据同步与趋势"],
    ]
    selected_page = default_page
    for idx, group in enumerate(nav_groups):
        cols = st.columns(len(group))
        for col, label in zip(cols, group):
            with col:
                if st.button(
                    label,
                    key=f"strategy_nav_btn_{idx}_{page_to_id[label]}",
                    type="primary" if default_page == label else "secondary",
                    width="stretch",
                ):
                    st.query_params["page"] = page_to_id[label]
                    st.rerun()
    selected_page_id = page_to_id.get(selected_page, "home")
    if selected_page_id != query_page:
        st.query_params["page"] = selected_page_id

    if selected_page == "自查总览｜机制与数据进度":
        render_mechanism_audit(data)
    elif selected_page == "决策首页":
        render_decision_home(data)
    elif selected_page == "看机会｜选品趋势预测":
        render_selection_forecast(data)
    elif selected_page == "看机会｜品类竞争格局":
        render_competition(data)
    elif selected_page == "看机会｜价格带空白点":
        render_price_gap(data)
    elif selected_page == "定策略｜单品评估页":
        render_single_product_assistant_embed()
    elif selected_page == "定策略｜单品性价比":
        render_value_score(data)
    elif selected_page == "定策略｜品牌组合推荐":
        render_brand_portfolio(data)
    elif selected_page == "定策略｜促销策略效果":
        render_promotion_effect(data)
    elif selected_page == "控风险｜AI数据质量诊断":
        render_quality(data)
    elif selected_page == "控风险｜差评归因":
        render_review_attribution()
    elif selected_page == "控风险｜数据同步与趋势":
        render_collection_sync(data)
        st.divider()
        render_baseline_trend()


if __name__ == "__main__":
    main()
