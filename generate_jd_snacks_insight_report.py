from __future__ import annotations

import math
import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


INPUT_PATH = Path(r"C:\Users\HUAWEI\Desktop\cleaned_snacks_data.csv")
OUTPUT_DIR = Path("jd_snacks_market_insight")
REPORT_PATH = OUTPUT_DIR / "京东零食市场选品洞察报告.md"


def read_csv_with_fallback(path: Path) -> tuple[pd.DataFrame, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding), encoding
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path), "default"


def clean_brand(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if not text:
        return "未知品牌"
    return re.split(r"\s*[-－—]\s*", text, maxsplit=1)[0].strip() or text


def classify_store_type(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    self_keywords = ("京东自营", "自营旗舰店", "自营店", "京东超市", "京东生鲜")
    return "京东自营" if any(keyword in text for keyword in self_keywords) else "第三方店铺"


def price_band(price: float) -> str:
    if pd.isna(price):
        return "未知"
    bands = [
        (0, 10, "0-10元"),
        (10, 20, "10-20元"),
        (20, 30, "20-30元"),
        (30, 50, "30-50元"),
        (50, 80, "50-80元"),
        (80, 100, "80-100元"),
        (100, 200, "100-200元"),
    ]
    for low, high, label in bands:
        if low <= price < high:
            return label
    return "200元以上"


def weighted_avg(group: pd.DataFrame, value_col: str, weight_col: str) -> float:
    weights = group[weight_col].fillna(0)
    if weights.sum() <= 0:
        return float(group[value_col].mean())
    return float((group[value_col] * weights).sum() / weights.sum())


def pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def cn_int(value: float | int) -> str:
    if pd.isna(value):
        return "-"
    return f"{int(round(value)):,}"


def money(value: float | int) -> str:
    if pd.isna(value):
        return "-"
    return f"{float(value):.2f}"


def save_table(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")


def add_bar_labels(ax, values) -> None:
    max_value = max(values) if len(values) else 0
    for i, value in enumerate(values):
        ax.text(value + max_value * 0.01, i, f"{int(value):,}", va="center", fontsize=9)


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    charts_dir = OUTPUT_DIR / "charts"
    charts_dir.mkdir(exist_ok=True)

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    df, encoding = read_csv_with_fallback(INPUT_PATH)
    df = df.copy()

    numeric_cols = ["原价", "现价", "销售量", "评论", "weight_g", "has_coupon"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["品牌_clean"] = df["品牌"].map(clean_brand)
    df["店铺类型"] = df["店铺名称"].map(classify_store_type)
    df["价格带"] = df["现价"].map(price_band)

    total_items = len(df)
    total_sales = df["销售量"].sum()
    avg_price = df["现价"].mean()
    median_price = df["现价"].median()
    avg_sales = df["销售量"].mean()
    sales_median = df["销售量"].median()

    category_counts = (
        df["三级分类"]
        .value_counts(dropna=False)
        .rename_axis("三级分类")
        .reset_index(name="商品数量")
    )
    category_counts["商品数量占比"] = category_counts["商品数量"] / total_items
    category_sales = (
        df.groupby("三级分类", dropna=False)
        .agg(
            商品数量=("SKU", "count"),
            总销量=("销售量", "sum"),
            平均销量=("销售量", "mean"),
            中位销量=("销售量", "median"),
            均价=("现价", "mean"),
        )
        .reset_index()
        .sort_values("商品数量", ascending=False)
    )
    category_distribution = category_counts.merge(
        category_sales[["三级分类", "总销量", "平均销量", "中位销量", "均价"]],
        on="三级分类",
        how="left",
    )
    save_table(category_distribution, OUTPUT_DIR / "品类分布汇总.csv")

    top10_categories = category_distribution.head(10).copy()
    red_ocean = top10_categories.copy()
    blue_ocean = category_distribution[category_distribution["商品数量"] <= max(20, math.ceil(total_items * 0.005))].copy()
    if blue_ocean.empty:
        blue_ocean = category_distribution.tail(10).copy()
    else:
        blue_ocean = blue_ocean.sort_values(["商品数量", "平均销量"], ascending=[True, False]).head(10)

    price_order = ["0-10元", "10-20元", "20-30元", "30-50元", "50-80元", "80-100元", "100-200元", "200元以上"]
    price_band_distribution = (
        df["价格带"]
        .value_counts()
        .reindex(price_order, fill_value=0)
        .rename_axis("价格带")
        .reset_index(name="商品数量")
    )
    price_band_distribution["商品数量占比"] = price_band_distribution["商品数量"] / total_items
    price_sales = (
        df.groupby("价格带")
        .agg(总销量=("销售量", "sum"), 平均销量=("销售量", "mean"), 均价=("现价", "mean"))
        .reindex(price_order)
        .reset_index()
    )
    price_band_distribution = price_band_distribution.merge(price_sales, on="价格带", how="left")
    save_table(price_band_distribution, OUTPUT_DIR / "价格带分布汇总.csv")
    mainstream_price_band = price_band_distribution.sort_values("商品数量", ascending=False).iloc[0]
    high_price_items = int((df["现价"] >= 100).sum())
    high_price_share = high_price_items / total_items

    brand_counts = (
        df["品牌_clean"]
        .value_counts()
        .rename_axis("品牌")
        .reset_index(name="商品数量")
    )
    brand_counts["商品数量占比"] = brand_counts["商品数量"] / total_items
    brand_sales = (
        df.groupby("品牌_clean")
        .agg(总销量=("销售量", "sum"), 平均销量=("销售量", "mean"), 均价=("现价", "mean"))
        .reset_index()
        .rename(columns={"品牌_clean": "品牌"})
    )
    brand_summary = brand_counts.merge(brand_sales, on="品牌", how="left")
    save_table(brand_summary, OUTPUT_DIR / "品牌集中度汇总.csv")
    top10_brand_share = brand_summary.head(10)["商品数量"].sum() / total_items

    sales_by_cat_price = (
        df.groupby(["三级分类", "价格带"], dropna=False)
        .agg(
            商品数量=("SKU", "count"),
            总销量=("销售量", "sum"),
            平均销量=("销售量", "mean"),
            均价=("现价", "mean"),
        )
        .reset_index()
        .sort_values(["总销量", "商品数量"], ascending=False)
    )
    save_table(sales_by_cat_price, OUTPUT_DIR / "销量_品类_价格带交叉汇总.csv")

    top_sales_products = (
        df.sort_values("销售量", ascending=False)
        .loc[:, ["品牌_clean", "商品名称", "店铺名称", "店铺类型", "现价", "价格带", "销售量", "评论", "二级分类", "三级分类", "has_coupon"]]
        .head(30)
        .rename(columns={"品牌_clean": "品牌"})
    )
    save_table(top_sales_products, OUTPUT_DIR / "高销量商品Top30.csv")

    sales_threshold = df["销售量"].quantile(0.9)
    hot_products = df[df["销售量"] >= sales_threshold].copy()
    hot_features = {
        "threshold": sales_threshold,
        "count": len(hot_products),
        "top_category": hot_products["三级分类"].value_counts().idxmax(),
        "top_category_count": int(hot_products["三级分类"].value_counts().max()),
        "top_price_band": hot_products["价格带"].value_counts().idxmax(),
        "top_price_band_count": int(hot_products["价格带"].value_counts().max()),
        "avg_price": hot_products["现价"].mean(),
        "median_price": hot_products["现价"].median(),
        "self_share": (hot_products["店铺类型"] == "京东自营").mean(),
        "coupon_share": (hot_products["has_coupon"] == 1).mean(),
    }

    store_summary = (
        df.groupby("店铺类型")
        .apply(
            lambda g: pd.Series(
                {
                    "商品数量": len(g),
                    "商品数量占比": len(g) / total_items,
                    "均价": g["现价"].mean(),
                    "中位价": g["现价"].median(),
                    "平均销量": g["销售量"].mean(),
                    "中位销量": g["销售量"].median(),
                    "总销量": g["销售量"].sum(),
                    "销售量占比": g["销售量"].sum() / total_sales if total_sales else 0,
                    "销量加权均价": weighted_avg(g, "现价", "销售量"),
                    "平均评论数": g["评论"].mean(),
                    "优惠券商品占比": (g["has_coupon"] == 1).mean(),
                }
            ),
            include_groups=False,
        )
        .reset_index()
        .sort_values("商品数量", ascending=False)
    )
    save_table(store_summary, OUTPUT_DIR / "店铺类型分析汇总.csv")

    # Charts
    fig, ax = plt.subplots(figsize=(11, 6))
    plot_df = top10_categories.sort_values("商品数量")
    ax.barh(plot_df["三级分类"], plot_df["商品数量"], color="#4C78A8")
    add_bar_labels(ax, plot_df["商品数量"].tolist())
    ax.set_title("商品数最多的前10个三级分类")
    ax.set_xlabel("商品数量")
    ax.set_ylabel("")
    fig.tight_layout()
    fig.savefig(charts_dir / "top10_categories.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6))
    prices = df["现价"].dropna()
    ax.hist(prices, bins=[0, 10, 20, 30, 50, 80, 100, 150, 200, 300, 500, max(600, prices.max())], color="#59A14F", edgecolor="white")
    ax.axvline(100, color="#E15759", linestyle="--", linewidth=1.6, label="100元高客单价线")
    ax.set_title("现价分布直方图")
    ax.set_xlabel("现价（元）")
    ax.set_ylabel("商品数量")
    ax.legend()
    fig.tight_layout()
    fig.savefig(charts_dir / "price_histogram.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6))
    brand_plot = brand_summary.head(10).sort_values("商品数量")
    ax.barh(brand_plot["品牌"], brand_plot["商品数量"], color="#F28E2B")
    add_bar_labels(ax, brand_plot["商品数量"].tolist())
    ax.set_title("前10大品牌商品数量")
    ax.set_xlabel("商品数量")
    ax.set_ylabel("")
    fig.tight_layout()
    fig.savefig(charts_dir / "top10_brands.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6))
    store_plot = store_summary.set_index("店铺类型").loc[:, ["均价", "平均销量"]]
    store_plot.plot(kind="bar", secondary_y="平均销量", ax=ax, color=["#76B7B2", "#E15759"])
    ax.set_title("京东自营 vs 第三方店铺：均价与平均销量")
    ax.set_xlabel("")
    ax.set_ylabel("均价（元）")
    ax.right_ax.set_ylabel("平均销量")
    fig.tight_layout()
    fig.savefig(charts_dir / "store_type_price_sales.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 7))
    heat_data = sales_by_cat_price.pivot_table(index="三级分类", columns="价格带", values="总销量", aggfunc="sum").fillna(0)
    top_heat_categories = category_sales.sort_values("总销量", ascending=False).head(12)["三级分类"]
    heat_data = heat_data.reindex(index=top_heat_categories, columns=price_order, fill_value=0)
    im = ax.imshow(heat_data.values, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(len(price_order)))
    ax.set_xticklabels(price_order, rotation=35, ha="right")
    ax.set_yticks(range(len(heat_data.index)))
    ax.set_yticklabels(heat_data.index)
    ax.set_title("高销量品类在价格带上的分布（总销量）")
    fig.colorbar(im, ax=ax, label="总销量")
    fig.tight_layout()
    fig.savefig(charts_dir / "sales_category_price_heatmap.png", dpi=180)
    plt.close(fig)

    def md_table(data: pd.DataFrame, columns: list[str], formatters: dict[str, callable] | None = None) -> str:
        formatters = formatters or {}
        subset = data.loc[:, columns].copy()
        for col, fn in formatters.items():
            if col in subset.columns:
                subset[col] = subset[col].map(fn)
        rows = [[str(col) for col in subset.columns]]
        rows.extend([[str(value) for value in row] for row in subset.itertuples(index=False, name=None)])
        widths = [max(len(row[i]) for row in rows) for i in range(len(columns))]

        def render_row(row: list[str]) -> str:
            return "| " + " | ".join(value.ljust(widths[i]) for i, value in enumerate(row)) + " |"

        header = render_row(rows[0])
        separator = "| " + " | ".join("-" * width for width in widths) + " |"
        body = "\n".join(render_row(row) for row in rows[1:])
        return "\n".join([header, separator, body])

    red_signal = "红海强"
    blue_signal = "蓝海/长尾"
    concentration_signal = "分散竞争，未被头部品牌垄断" if top10_brand_share < 0.5 else "头部集中度较高"

    report = f"""# 京东零食市场选品洞察报告

数据来源：`{INPUT_PATH}`  
样本量：{cn_int(total_items)} 个商品；CSV 编码识别为 `{encoding}`。  
分析口径：以“三级分类”代表细分类目；品牌字段按第一个分隔符前的品牌名归并；店铺名包含“京东自营 / 自营旗舰店 / 自营店 / 京东超市 / 京东生鲜”判为京东自营，其余判为第三方店铺。

## 一、核心结论

1. **供给最拥挤的红海类目**集中在梅子干、薯片、鸡肉类、夹心饼干、鸭肉类等。Top10 三级分类共 {cn_int(top10_categories["商品数量"].sum())} 个商品，占全样本 {pct(top10_categories["商品数量"].sum() / total_items)}，说明供给竞争主要聚集在少数大众口味和高频零食品类。
2. **主流价格带**是 {mainstream_price_band["价格带"]}，共 {cn_int(mainstream_price_band["商品数量"])} 个商品，占 {pct(mainstream_price_band["商品数量占比"])}；100 元以上高客单价商品有 {cn_int(high_price_items)} 个，占 {pct(high_price_share)}，主要适合礼盒、坚果组合、肉类礼包等场景化选品。
3. **品牌集中度不高**：前10大品牌商品数占比 {pct(top10_brand_share)}，判断为“{concentration_signal}”。市场更像多品牌、多 SKU 竞争，而不是单一头部垄断。
4. **爆款特征**：销量前10%商品门槛约为 {cn_int(hot_features["threshold"])}；高销量商品最集中在“{hot_features["top_category"]}”和“{hot_features["top_price_band"]}”，高销量组中位价 {money(hot_features["median_price"])} 元，自营占比 {pct(hot_features["self_share"])}，带券占比 {pct(hot_features["coupon_share"])}。
5. **店铺类型差异明显**：京东自营商品占比见店铺类型表。可用“自营做信任和履约，第三方做长尾差异化”的策略拆分选品。

## 二、品类分布：红海与蓝海

### 商品数最多的前10个细分类目

![商品数最多的前10个三级分类](charts/top10_categories.png)

{md_table(top10_categories, ["三级分类", "商品数量", "商品数量占比", "平均销量", "均价"], {
    "商品数量": cn_int,
    "商品数量占比": pct,
    "平均销量": lambda x: f"{x:.1f}",
    "均价": money,
})}

**判断：**上述类目可视为“{red_signal}”区域，供给密集、竞品多，选品需要依靠品牌心智、规格组合、口味差异、价格效率或履约服务突破。

### 商品较少的蓝海/长尾类目

{md_table(blue_ocean, ["三级分类", "商品数量", "商品数量占比", "平均销量", "均价"], {
    "商品数量": cn_int,
    "商品数量占比": pct,
    "平均销量": lambda x: f"{x:.1f}",
    "均价": money,
})}

**判断：**这些类目供给较少，可能存在差异化机会；但需结合搜索热度、复购率和供应链稳定性进一步验证，避免把“低需求”误判为“蓝海”。

## 三、价格带分析

![现价分布直方图](charts/price_histogram.png)

{md_table(price_band_distribution, ["价格带", "商品数量", "商品数量占比", "平均销量", "均价"], {
    "商品数量": cn_int,
    "商品数量占比": pct,
    "平均销量": lambda x: "-" if pd.isna(x) else f"{x:.1f}",
    "均价": money,
})}

**解读：**均价为 {money(avg_price)} 元，中位价为 {money(median_price)} 元。主流价格带在 {mainstream_price_band["价格带"]}，适合做日常零食、尝鲜装、家庭囤货款；100 元以上的 {cn_int(high_price_items)} 个商品更适合礼盒、组合装、节庆送礼和高规格坚果肉脯等高客单价场景。

## 四、品牌集中度

![前10大品牌商品数量](charts/top10_brands.png)

{md_table(brand_summary.head(10), ["品牌", "商品数量", "商品数量占比", "总销量", "平均销量", "均价"], {
    "商品数量": cn_int,
    "商品数量占比": pct,
    "总销量": cn_int,
    "平均销量": lambda x: f"{x:.1f}",
    "均价": money,
})}

**结论：**前10大品牌商品数量占比为 {pct(top10_brand_share)}。从 SKU 供给看，市场并未呈现强垄断，头部品牌多但份额分散；新品牌或渠道品牌仍可通过细分类目、规格包装和促销机制切入。

## 五、销量分布与爆款特征

销量字段可用。本报告将销售量前10%商品定义为“高销量组”，门槛约为 {cn_int(hot_features["threshold"])}。

![高销量品类在价格带上的分布](charts/sales_category_price_heatmap.png)

### 销量最高的品类 x 价格带组合

{md_table(sales_by_cat_price.head(12), ["三级分类", "价格带", "商品数量", "总销量", "平均销量", "均价"], {
    "商品数量": cn_int,
    "总销量": cn_int,
    "平均销量": lambda x: f"{x:.1f}",
    "均价": money,
})}

**爆款画像：**高销量商品更偏向“{hot_features["top_category"]}”类目和“{hot_features["top_price_band"]}”价格带；价格并非越低越好，爆款更像是在大众口味、明确规格、可囤货和有促销感之间取得平衡。

## 六、店铺类型分析：京东自营 vs 第三方店铺

![京东自营 vs 第三方店铺](charts/store_type_price_sales.png)

{md_table(store_summary, ["店铺类型", "商品数量", "商品数量占比", "均价", "中位价", "平均销量", "中位销量", "销售量占比", "销量加权均价", "优惠券商品占比"], {
    "商品数量": cn_int,
    "商品数量占比": pct,
    "均价": money,
    "中位价": money,
    "平均销量": lambda x: f"{x:.1f}",
    "中位销量": lambda x: f"{x:.1f}",
    "销售量占比": pct,
    "销量加权均价": money,
    "优惠券商品占比": pct,
})}

**解读：**自营商品通常承担平台信任、物流体验和标准化供给；第三方店铺商品数量更多时，往往意味着细分口味、组合规格和长尾品牌更丰富。若要做选品，建议把自营同款作为价格和服务基准，再在第三方长尾里寻找差异化切口。

## 七、选品建议

1. **谨慎进入红海大类**：梅子干、薯片、鸡肉类、夹心饼干、鸭肉类等供给密集，除非有品牌、价格、规格或供应链优势，否则容易陷入同质化竞争。
2. **优先测试中低客单价高频款**：主流价格带最能代表当前供给重心，可围绕小包装、多口味组合、家庭分享装和办公室场景设计商品。
3. **高客单价适合场景化**：100 元以上不要只拼重量，应突出礼盒质感、健康属性、节庆送礼和企业团购。
4. **品牌不垄断，差异化仍有空间**：前10品牌份额未过半，细分口味、地方特色、低糖低脂、儿童/健身人群等方向有切入价值。
5. **对标自营，突破第三方**：自营适合作为履约和价格标杆；第三方适合寻找长尾机会，但要重点评估评论质量、复购潜力和供应稳定性。

## 八、附录文件

- `品类分布汇总.csv`
- `价格带分布汇总.csv`
- `品牌集中度汇总.csv`
- `销量_品类_价格带交叉汇总.csv`
- `店铺类型分析汇总.csv`
- `高销量商品Top30.csv`
"""

    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Report written: {REPORT_PATH.resolve()}")
    print(f"Output directory: {OUTPUT_DIR.resolve()}")
    print(f"Total items: {total_items}")
    print(f"Top 10 brand share: {top10_brand_share:.4f}")
    print(f"High price items >=100: {high_price_items}")


if __name__ == "__main__":
    main()
