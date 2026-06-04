import re
from pathlib import Path

import numpy as np
import pandas as pd


# =========================
# 基础配置
# =========================
# 原始 Excel 文件路径：如需迁移脚本，只需要修改这里即可。
INPUT_FILE = Path(r"C:\Users\HUAWEI\Desktop\导出_中文分类.xlsx")

# 需要读取的工作表名称。
SHEET_NAME = "分类信息清理后"

# 清洗后 CSV 输出路径：默认保存到当前项目目录。
OUTPUT_FILE = Path("cleaned_snacks_data.csv")


def extract_first_float(value):
    """
    从混乱的价格字段中提取第一个浮点数。

    示例：
    - '110.1 110.1 100+' -> 110.1
    - '￥1,299.00' -> 1299.0
    - 空值或无法解析 -> np.nan
    """
    try:
        if pd.isna(value):
            return np.nan

        text = str(value).replace(",", "").strip()
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not match:
            return np.nan

        return float(match.group(0))
    except Exception:
        return np.nan


def extract_weight_g(product_name):
    """
    从商品名称中提取第一个重量规格，并统一转换为克。

    支持格式：
    - 500g / 500G
    - 750克
    - 1kg / 1KG
    - 1千克 / 1公斤

    提取不到时返回 None。
    """
    try:
        if pd.isna(product_name):
            return None

        text = str(product_name)
        pattern = r"(\d+(?:\.\d+)?)\s*(kg|千克|公斤|g|克)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            return None

        number = float(match.group(1))
        unit = match.group(2).lower()

        if unit in ("kg", "千克", "公斤"):
            return number * 1000

        return number
    except Exception:
        return None


def detect_coupon(promo_text):
    """
    判断促销信息中是否包含优惠券/满减/百亿补贴等信号。

    包含任一关键词则返回 1，否则返回 0。
    """
    try:
        if pd.isna(promo_text):
            return 0

        text = str(promo_text)
        return 1 if re.search(r"券|满减|百亿补贴", text) else 0
    except Exception:
        return 0


def normalize_sales(sales_value):
    """
    将销量字段标准化为整数。

    示例：
    - '100+' -> 100
    - '1万+' -> 10000
    - '1.5万+' -> 15000
    - '5000+' -> 5000
    - 空值或无法解析 -> np.nan
    """
    try:
        if pd.isna(sales_value):
            return np.nan

        text = str(sales_value).replace(",", "").strip()
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if not match:
            return np.nan

        number = float(match.group(1))
        multiplier = 10000 if "万" in text else 1

        return int(number * multiplier)
    except Exception:
        return np.nan


def main():
    """
    主清洗流程：
    1. 读取 Excel 指定工作表
    2. 删除全空行列并重置索引
    3. 清洗价格字段
    4. 提取重量规格
    5. 结构化促销信息
    6. 标准化销量
    7. 打印质量信息并导出 CSV
    """
    try:
        df = pd.read_excel(INPUT_FILE, sheet_name=SHEET_NAME)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"未找到 Excel 文件：{INPUT_FILE}") from exc
    except ValueError as exc:
        raise ValueError(f"未找到工作表：{SHEET_NAME}") from exc

    # 删除所有全为空的列和行，避免后续统计被空白区域干扰。
    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="all")

    # 重置索引，drop=True 表示不保留原索引列。
    df = df.reset_index(drop=True)

    # 价格字段清洗：提取第一个浮点数，并强制转换为 float 类型。
    price_columns = ["原价", "现价"]
    for col in price_columns:
        if col not in df.columns:
            raise KeyError(f"缺少必要价格列：{col}")
        df[col] = df[col].apply(extract_first_float).astype(float)

    # 商品重量规格提取：统一转换为克。
    if "商品名称" not in df.columns:
        raise KeyError("缺少必要列：商品名称")
    df["weight_g"] = df["商品名称"].apply(extract_weight_g)

    # 促销信息结构化：判断是否存在优惠相关关键词。
    if "促销信息" not in df.columns:
        raise KeyError("缺少必要列：促销信息")
    df["has_coupon"] = df["促销信息"].apply(detect_coupon).astype(int)

    # 销量标准化：使用 Pandas 可空整数类型 Int64，兼容无法解析的空值。
    if "销售量" not in df.columns:
        raise KeyError("缺少必要列：销售量")
    df["sales_num"] = df["销售量"].apply(normalize_sales).astype("Int64")

    # 打印 DataFrame 基本信息。
    print("========== 清洗后 DataFrame 基本信息 ==========")
    df.info()

    # 统计 weight_g 成功提取率：以非空商品名称行作为分母。
    valid_name_count = df["商品名称"].notna().sum()
    extracted_weight_count = df["weight_g"].notna().sum()
    weight_success_rate = (
        extracted_weight_count / valid_name_count if valid_name_count else 0
    )
    print("\n========== weight_g 提取统计 ==========")
    print(f"商品名称非空行数：{valid_name_count}")
    print(f"weight_g 成功提取行数：{extracted_weight_count}")
    print(f"weight_g 成功提取率：{weight_success_rate:.2%}")

    # 导出为 CSV，使用 utf-8-sig 便于 Excel 直接打开时正确显示中文。
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n清洗后的数据已保存为：{OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
