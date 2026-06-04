from pathlib import Path

import numpy as np
import pandas as pd

try:
    from tqdm import tqdm
except ImportError:  # 兼容没有安装 tqdm 的环境，脚本仍可运行。
    tqdm = None


# =========================
# 基础配置
# =========================
# 清洗后的数据文件路径。
DATA_FILE = Path("cleaned_snacks_data.csv")

# 默认报告输出路径。
REPORT_FILE = Path("price_comparison_report.md")


def load_clean_data(csv_path=DATA_FILE):
    """
    读取清洗后的零食数据，并校验比价模块需要的关键列。
    """
    required_columns = ["品牌", "商品名称", "店铺名称", "现价", "weight_g", "二级分类", "三级分类"]

    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"未找到数据文件：{Path(csv_path).resolve()}") from exc

    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise KeyError(f"数据缺少必要列：{missing_columns}")

    return df


def calculate_price_per_g(df):
    """
    过滤 weight_g 为空或为 0 的脏数据，并计算每克单价。

    price_per_g = 现价 / weight_g
    """
    clean_df = df.copy()

    # 将关键数值列统一转为数值类型，无法转换的值会变为 NaN，方便后续过滤。
    clean_df["现价"] = pd.to_numeric(clean_df["现价"], errors="coerce")
    clean_df["weight_g"] = pd.to_numeric(clean_df["weight_g"], errors="coerce")

    # 过滤 weight_g 为空、为 0、价格为空或价格异常的数据。
    clean_df = clean_df[
        clean_df["weight_g"].notna()
        & (clean_df["weight_g"] > 0)
        & clean_df["现价"].notna()
        & (clean_df["现价"] >= 0)
    ].copy()

    # 使用 tqdm 展示逐行计算进度；数据量较小时也方便确认脚本在工作。
    if tqdm is not None:
        tqdm.pandas(desc="计算每克单价")
        clean_df["price_per_g"] = clean_df.progress_apply(
            lambda row: row["现价"] / row["weight_g"], axis=1
        )
    else:
        clean_df["price_per_g"] = clean_df["现价"] / clean_df["weight_g"]

    clean_df = clean_df.replace([np.inf, -np.inf], np.nan)
    clean_df = clean_df[clean_df["price_per_g"].notna()].copy()

    return clean_df


def dataframe_to_markdown(df):
    """
    将 DataFrame 转成 Markdown 表格。

    不依赖 tabulate，避免 pandas.to_markdown 在缺少可选依赖时失败。
    """
    if df.empty:
        return "未找到符合条件的数据。"

    string_df = df.fillna("").astype(str)
    headers = list(string_df.columns)

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for _, row in string_df.iterrows():
        values = [row[col].replace("\n", " ").replace("|", "/") for col in headers]
        lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines)


def compare_price(brand, category):
    """
    按品牌和分类进行智能比价，输出 Markdown 表格。

    参数：
    - brand：品牌关键词，例如 '良品铺子'、'三只松鼠'
    - category：分类关键词，可匹配二级分类或三级分类，例如 '坚果炒货'、'坚果礼盒'

    返回：
    - markdown_table：Markdown 表格字符串
    - detail_df：该品牌/分类下按每克单价排序后的明细数据
    """
    try:
        df = load_clean_data(DATA_FILE)
        df = calculate_price_per_g(df)

        brand_text = str(brand).strip()
        category_text = str(category).strip()
        if not brand_text:
            raise ValueError("brand 不能为空")
        if not category_text:
            raise ValueError("category 不能为空")

        # 品牌使用包含匹配，兼容 '良品铺子 - 坚果零食' 这种组合品牌字段。
        brand_mask = df["品牌"].astype(str).str.contains(brand_text, case=False, na=False)

        # 分类同时匹配二级分类和三级分类，兼容实际数据中 '坚果礼盒' 位于三级分类的情况。
        category_mask = (
            df["二级分类"].astype(str).str.contains(category_text, case=False, na=False)
            | df["三级分类"].astype(str).str.contains(category_text, case=False, na=False)
        )

        result = df[brand_mask & category_mask].copy()
        if result.empty:
            markdown_table = (
                f"未找到品牌 `{brand}` 且分类 `{category}` 的有效比价数据。"
            )
            return markdown_table, result

        result = result.sort_values("price_per_g", ascending=True).reset_index(drop=True)

        cheapest = result.iloc[0]
        most_expensive = result.iloc[-1]
        price_gap = most_expensive["price_per_g"] - cheapest["price_per_g"]
        gap_rate = price_gap / cheapest["price_per_g"] if cheapest["price_per_g"] else np.nan

        # 汇总层：展示该品牌/分类下最便宜与最贵店铺，以及差价幅度。
        summary_df = pd.DataFrame(
            [
                {
                    "品牌": brand,
                    "分类": category,
                    "有效商品数": len(result),
                    "最便宜店铺": cheapest["店铺名称"],
                    "最低每克单价": f"{cheapest['price_per_g']:.4f}",
                    "最低价商品": cheapest["商品名称"],
                    "最贵店铺": most_expensive["店铺名称"],
                    "最高每克单价": f"{most_expensive['price_per_g']:.4f}",
                    "最高价商品": most_expensive["商品名称"],
                    "差价/克": f"{price_gap:.4f}",
                    "差价幅度": f"{gap_rate:.2%}" if pd.notna(gap_rate) else "",
                }
            ]
        )

        # 明细层：展示前 10 个最便宜店铺/商品，方便观察价格战况。
        detail_df = result[
            ["品牌", "二级分类", "三级分类", "店铺名称", "商品名称", "现价", "weight_g", "price_per_g"]
        ].head(10).copy()
        detail_df["现价"] = detail_df["现价"].map(lambda x: f"{x:.2f}")
        detail_df["weight_g"] = detail_df["weight_g"].map(lambda x: f"{x:.1f}")
        detail_df["price_per_g"] = detail_df["price_per_g"].map(lambda x: f"{x:.4f}")

        markdown_table = "\n".join(
            [
                f"## {brand} - {category} 同品类不同店铺价格战况",
                "",
                "### 价格极值对比",
                dataframe_to_markdown(summary_df),
                "",
                "### 每克单价最低 TOP 10",
                dataframe_to_markdown(detail_df),
            ]
        )

        return markdown_table, result
    except Exception as exc:
        raise RuntimeError(f"比价分析失败：{exc}") from exc


def main():
    """
    示例入口：默认分析 '良品铺子' 在 '坚果礼盒' 分类下的比价情况。
    """
    markdown_table, _ = compare_price("良品铺子", "坚果礼盒")

    print(markdown_table)
    REPORT_FILE.write_text(markdown_table, encoding="utf-8")
    print(f"\nMarkdown 报告已保存为：{REPORT_FILE.resolve()}")


if __name__ == "__main__":
    main()
