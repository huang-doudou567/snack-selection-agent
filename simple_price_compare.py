import re
import ast
import os
from io import BytesIO
from pathlib import Path

import pandas as pd

try:
    import matplotlib.pyplot as plt
    import wordcloud
except ImportError:
    plt = None
    wordcloud = None


# CSV 文件路径：脚本和 cleaned_snacks_data.csv 位于同一目录时可直接运行。
DATA_FILE = Path("cleaned_snacks_data.csv")

# 输出结果统一使用这些列，方便命令行和 Streamlit 复用。
RESULT_COLUMNS = ["店铺名称", "商品名称", "现价", "重量_g", "unit_price"]

# 预编译正则，避免在大数据集逐行 apply 时重复编译。
# 范围重量如 “500-1000g” 或 “1-1.5kg” 表示规格不确定，直接排除。
WEIGHT_RANGE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:-|~|～|至|到)\s*\d+(?:\.\d+)?\s*(?:g|G|克|公斤|千克|kg|KG|Kg|kG|斤)"
)

# 明确克重：支持 “750g”“750克”“30g/包”“500g*2袋”等，优先级最高。
GRAM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:g|G|克)")

# 明确公斤/千克：支持 “1.5kg”“2公斤”“1千克”。
KILOGRAM_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:公斤|千克|kg|KG|Kg|kG)"
)

# 明确斤：支持 “1斤装”“2.5斤”。注意必须在公斤之后使用。
JIN_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*斤")

# 纯计数或外包装单位：没有明确克重时无法换算。
UNCONVERTIBLE_UNIT_PATTERN = re.compile(r"箱|颗|粒|包")

# 温和数字兜底：极少数标题可能只有 “500”“1500” 这类疑似克重的 3-5 位数字。
NUMERIC_WEIGHT_FALLBACK_PATTERN = re.compile(r"(?<!\d)(\d{3,5})(?!\d)")


def extract_weight(text):
    """
    从商品名称中提取可换算为“克”的标准重量。

    规则：
    1. 优先匹配 g/克，例如 “500g”“750克” -> 500、750。
    2. 匹配 公斤/kg，例如 “2公斤”“1.5kg” -> 2000、1500。
       注意：“公斤”包含“斤”字，所以必须先于“斤”匹配。
    3. 匹配 斤，例如 “2斤” -> 1000。
    4. 如果只出现 箱/颗/粒/包 等无法确定克重的单位，返回 None。
    5. 其他情况默认返回 None。
    """
    try:
        if pd.isna(text):
            return None

        product_name = str(text).strip()
        if not product_name:
            return None

        # 范围重量不是确定规格，例如 “500-1000g”，不参与每克单价计算。
        if WEIGHT_RANGE_PATTERN.search(product_name):
            return None

        # 1. 优先匹配 g/克。
        # 只要标题里有明确克重，就提取数字，即使后面跟着 /包、/袋、/盒。
        # 示例：“750g/3包” -> 750.0，“30g/包” -> 30.0。
        gram_match = GRAM_PATTERN.search(product_name)
        if gram_match:
            # 一旦命中克重，立即返回，不再向下匹配斤/公斤，防止误判。
            return float(gram_match.group(1))

        # 2. 匹配公斤/千克/kg。
        # 必须放在“斤”之前，因为“公斤”本身包含“斤”。
        # 示例：“1.5kg” -> 1500.0。
        kilogram_match = KILOGRAM_PATTERN.search(product_name)
        if kilogram_match:
            return float(kilogram_match.group(1)) * 1000

        # 3. 匹配斤。
        # 示例：“1斤装” -> 500.0。
        jin_match = JIN_PATTERN.search(product_name)
        if jin_match:
            return float(jin_match.group(1)) * 500

        # 4. 只有无明确克重/公斤/斤，且只看到箱、颗、粒、包这类计数或包装单位时，
        # 才视为无法换算。示例：“30包/箱” -> None。
        if UNCONVERTIBLE_UNIT_PATTERN.search(product_name):
            return None

        # 5. 温和的数字兜底：如果标题中存在 3-5 位纯数字，假设其为克重。
        # 这段逻辑放在最后，确保不会覆盖前面明确单位的匹配结果。
        fallback_match = NUMERIC_WEIGHT_FALLBACK_PATTERN.search(product_name)
        if fallback_match:
            return float(fallback_match.group(1))

        return None
    except Exception:
        # 正则或类型转换异常时，不让单条脏数据中断整个比价流程。
        return None


def build_price_table(brand, category):
    """
    构建比价结果表。

    返回：
    - result: 最便宜前 3 条商品 DataFrame
    - status: 状态码
      - ok: 找到可比价商品
      - no_match: 品牌/分类关键词没有匹配到商品
      - no_standard_weight: 找到商品，但全部无标准克重，无法比价
      - no_valid_price: 有标准克重，但价格无效，无法比价
    """
    # 1. 读取 CSV 文件。
    df = pd.read_csv(DATA_FILE)

    # 2. 品牌模糊匹配。
    brand_mask = df["品牌"].astype(str).str.contains(str(brand), na=False, regex=False)

    # 3. 分类模糊匹配：同时查二级分类、三级分类和商品名称。
    # 这样可以处理三级分类为空、不精确，或分类词只出现在商品名中的情况。
    category_keyword = str(category)
    category_mask = (
        df["二级分类"].astype(str).str.contains(category_keyword, na=False, regex=False)
        | df["三级分类"].astype(str).str.contains(category_keyword, na=False, regex=False)
        | df["商品名称"].astype(str).str.contains(category_keyword, na=False, regex=False)
    )

    filtered = df[brand_mask & category_mask].copy()
    initial_count = len(filtered)
    if filtered.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS), "no_match"

    # 4. 调用新的重量提取函数，从商品名称重新计算标准克重。
    # 不直接依赖 CSV 里的 weight_g，是为了支持斤/公斤，并排除箱/颗/粒/包等无法换算商品。
    filtered["重量_g"] = filtered["商品名称"].apply(extract_weight)

    # 5. 跳过无法换算为标准克重的商品。
    with_weight = filtered[
        filtered["重量_g"].notna() & (pd.to_numeric(filtered["重量_g"], errors="coerce") > 0)
    ].copy()
    if with_weight.empty:
        print(f"Info: 过滤掉 {initial_count} 条无标准克重或无效价格的商品。")
        return pd.DataFrame(columns=RESULT_COLUMNS), "no_standard_weight"

    # 6. 清洗价格，并过滤掉现价 <= 0 的无效数据。
    with_weight["现价"] = pd.to_numeric(with_weight["现价"], errors="coerce")
    with_weight["重量_g"] = pd.to_numeric(with_weight["重量_g"], errors="coerce")
    valid = with_weight[
        with_weight["现价"].notna()
        & with_weight["重量_g"].notna()
        & (with_weight["现价"] > 0)
        & (with_weight["重量_g"] > 0)
    ].copy()
    print(f"Info: 过滤掉 {initial_count - len(valid)} 条无标准克重或无效价格的商品。")
    if valid.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS), "no_valid_price"

    # 7. 计算每克单价，并按单价升序排序。
    valid["unit_price"] = valid["现价"] / valid["重量_g"]
    result = valid.sort_values("unit_price", ascending=True).head(3)

    return result[RESULT_COLUMNS].copy(), "ok"


def find_cheapest(brand, category):
    """
    查找指定品牌、指定分类关键词下每克单价最低的前 3 个商品，并打印结果表格。
    """
    result, status = build_price_table(brand, category)

    if status == "no_match":
        print(f"未找到包含‘{brand}’且包含‘{category}’的商品，请尝试更换关键词。")
        return result

    if status == "no_standard_weight":
        print("抱歉，找到的商品均无标准克重（如按箱/颗售卖），暂不支持比价。")
        return result

    if status == "no_valid_price":
        print(f"包含‘{brand}’且包含‘{category}’的商品没有有效价格，暂不支持比价。")
        return result

    # 控制台打印时格式化每克单价，便于阅读。
    display_result = result.copy()
    display_result["unit_price"] = display_result["unit_price"].map(lambda x: f"{x:.6f}")
    print(display_result.to_string(index=False))
    return result


def normalize_brand_keyword(brand_text):
    """
    将混杂品牌字段整理为更适合下拉选择的品牌关键词。

    示例：
    - “良品铺子 - 坚果零食” -> “良品铺子”
    - “三只松鼠-休闲食品” -> “三只松鼠”
    """
    try:
        if pd.isna(brand_text):
            return ""

        brand_text = str(brand_text).strip()
        if not brand_text:
            return ""

        return re.split(r"\s*[-－—–]\s*", brand_text, maxsplit=1)[0].strip()
    except Exception:
        return ""


def build_comparable_keyword_table():
    """
    构建“能够参与精准比价”的候选数据。

    只有同时满足以下条件的商品才会进入下拉菜单：
    - 能从商品名称提取标准克重；
    - 现价有效且大于 0；
    - 品牌关键词、二级分类或三级分类非空。
    """
    df = pd.read_csv(DATA_FILE)
    df["现价"] = pd.to_numeric(df["现价"], errors="coerce")
    df["重量_g"] = df["商品名称"].apply(extract_weight)
    df["重量_g"] = pd.to_numeric(df["重量_g"], errors="coerce")
    df["品牌关键词"] = df["品牌"].apply(normalize_brand_keyword)

    comparable = df[
        df["品牌关键词"].ne("")
        & df["现价"].notna()
        & (df["现价"] > 0)
        & df["重量_g"].notna()
        & (df["重量_g"] > 0)
    ].copy()

    return comparable


def get_brand_options(comparable_df):
    """
    从可比价商品中提取品牌关键词下拉选项。
    """
    if comparable_df.empty:
        return []

    counts = comparable_df["品牌关键词"].value_counts()
    return counts.index.tolist()


def get_category_options(comparable_df, brand_keyword):
    """
    根据已选择的品牌，提取该品牌下可比价的品类关键词。

    品类来源同时包含二级分类和三级分类，按出现次数降序排列。
    """
    brand_df = comparable_df[comparable_df["品牌关键词"] == brand_keyword].copy()
    if brand_df.empty:
        return []

    categories = pd.concat(
        [
            brand_df["二级分类"].dropna().astype(str).str.strip(),
            brand_df["三级分类"].dropna().astype(str).str.strip(),
        ],
        ignore_index=True,
    )
    categories = categories[categories.ne("")]
    if categories.empty:
        return []

    return categories.value_counts().index.tolist()


def min_max_normalize(series):
    """
    Min-Max 归一化到 [0, 1]。

    如果最大值等于最小值，说明该维度没有区分度，统一给 1.0，避免除零。
    """
    series = pd.to_numeric(series, errors="coerce")
    min_value = series.min()
    max_value = series.max()

    if pd.isna(min_value) or pd.isna(max_value):
        return pd.Series(0.0, index=series.index)

    if max_value == min_value:
        return pd.Series(1.0, index=series.index)

    return (series - min_value) / (max_value - min_value)


def calculate_selection_score(df, price_weight=0.7):
    """
    计算高性价比选品综合得分。

    规则：
    - 过滤 unit_price <= 0 或 销售量 <= 0 的脏数据；
    - price_score = 1 / unit_price，单价越低分越高；
    - sales_score = 销售量，销量越高分越高；
    - 两个分数分别做 Min-Max 归一化；
    - final_score = price_score_norm * price_weight + sales_score_norm * (1 - price_weight)。
    """
    scored = df.copy()
    price_weight = min(max(float(price_weight), 0.0), 1.0)
    sales_weight = 1.0 - price_weight

    scored["unit_price"] = pd.to_numeric(scored["unit_price"], errors="coerce")
    scored["销售量"] = pd.to_numeric(scored["销售量"], errors="coerce")

    scored = scored[
        scored["unit_price"].notna()
        & scored["销售量"].notna()
        & (scored["unit_price"] > 0)
        & (scored["销售量"] > 0)
    ].copy()

    if scored.empty:
        scored["final_score"] = []
        return scored

    scored["price_score"] = 1 / scored["unit_price"]
    scored["sales_score"] = scored["销售量"]
    scored["price_score_norm"] = min_max_normalize(scored["price_score"])
    scored["sales_score_norm"] = min_max_normalize(scored["sales_score"])
    scored["final_score"] = (
        scored["price_score_norm"] * price_weight
        + scored["sales_score_norm"] * sales_weight
    )

    return scored


def get_top_selection(category, top_n=3, price_weight=0.7, source_df=None):
    """
    按品类关键词返回综合得分最高的 Top N 商品。

    category 会同时匹配二级分类、三级分类和商品名称。
    """
    if source_df is None:
        df = pd.read_csv(DATA_FILE)
    else:
        df = source_df.copy()

    category_keyword = str(category).strip()
    if not category_keyword:
        return pd.DataFrame()

    category_mask = (
        df["二级分类"].astype(str).str.contains(category_keyword, na=False, regex=False)
        | df["三级分类"].astype(str).str.contains(category_keyword, na=False, regex=False)
        | df["商品名称"].astype(str).str.contains(category_keyword, na=False, regex=False)
    )

    selected = df[category_mask].copy()
    if selected.empty:
        return pd.DataFrame()

    selected["现价"] = pd.to_numeric(selected["现价"], errors="coerce")
    selected["重量_g"] = selected["商品名称"].apply(extract_weight)
    selected["重量_g"] = pd.to_numeric(selected["重量_g"], errors="coerce")
    selected = selected[
        selected["现价"].notna()
        & selected["重量_g"].notna()
        & (selected["现价"] > 0)
        & (selected["重量_g"] > 0)
    ].copy()

    if selected.empty:
        return pd.DataFrame()

    selected["unit_price"] = selected["现价"] / selected["重量_g"]
    scored = calculate_selection_score(selected, price_weight=price_weight)
    if scored.empty:
        return pd.DataFrame()

    scored = scored.sort_values("final_score", ascending=False).head(top_n).copy()
    scored.insert(0, "排名", range(1, len(scored) + 1))

    result = scored[
        ["排名", "品牌", "商品名称", "现价", "重量_g", "unit_price", "销售量", "final_score"]
    ].copy()
    result = result.rename(
        columns={
            "unit_price": "unit_price(元/g)",
            "final_score": "综合得分",
        }
    )

    return result


def analyze_brand_strategy(df):
    """
    分析各品牌定价策略。

    指标：
    - 商品数量
    - 平均售价
    - 平均单位成本：AVG(unit_price)
    - 价格中位数

    返回按商品数量排序的 Top 10 品牌。
    """
    strategy_df = df.copy()

    strategy_df["现价"] = pd.to_numeric(strategy_df["现价"], errors="coerce")
    strategy_df["重量_g"] = strategy_df["商品名称"].apply(extract_weight)
    strategy_df["重量_g"] = pd.to_numeric(strategy_df["重量_g"], errors="coerce")
    strategy_df["品牌关键词"] = strategy_df["品牌"].apply(normalize_brand_keyword)

    strategy_df = strategy_df[
        strategy_df["品牌关键词"].ne("")
        & strategy_df["现价"].notna()
        & strategy_df["重量_g"].notna()
        & (strategy_df["现价"] > 0)
        & (strategy_df["重量_g"] > 0)
    ].copy()

    if strategy_df.empty:
        return pd.DataFrame(
            columns=["品牌", "商品数量", "平均售价", "平均单位成本", "价格中位数"]
        )

    strategy_df["unit_price"] = strategy_df["现价"] / strategy_df["重量_g"]
    strategy_df = strategy_df[strategy_df["unit_price"] > 0].copy()

    if strategy_df.empty:
        return pd.DataFrame(
            columns=["品牌", "商品数量", "平均售价", "平均单位成本", "价格中位数"]
        )

    brand_strategy = (
        strategy_df.groupby("品牌关键词")
        .agg(
            商品数量=("商品名称", "count"),
            平均售价=("现价", "mean"),
            平均单位成本=("unit_price", "mean"),
            价格中位数=("现价", "median"),
        )
        .reset_index()
        .rename(columns={"品牌关键词": "品牌"})
        .sort_values("商品数量", ascending=False)
        .head(10)
    )

    return brand_strategy


def parse_promotion_keywords(promo_value):
    """
    解析促销信息字段，返回促销关键词列表。

    兼容两种常见格式：
    - 列表字符串：['新品', '券满29减1', '包邮']
    - 普通字符串：满减 包邮 百亿补贴
    """
    if pd.isna(promo_value):
        return []

    text = str(promo_value).strip()
    if not text or text in ("[]", "nan", "None"):
        return []

    items = []
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, list):
            items = [str(item).strip() for item in parsed if str(item).strip()]
        else:
            items = [text]
    except Exception:
        items = re.split(r"[,，;；、\s]+", text)

    keywords = []
    for item in items:
        if not item:
            continue

        # 将具体促销文案归并为更稳定的促销类型。
        if "百亿补贴" in item:
            keywords.append("百亿补贴")
        elif "满减" in item or re.search(r"每\d+减\d+|满\d+减\d+", item):
            keywords.append("满减")
        elif "券" in item:
            keywords.append("优惠券")
        elif "包邮" in item:
            keywords.append("包邮")
        elif "京东物流" in item:
            keywords.append("京东物流")
        elif "新品" in item:
            keywords.append("新品")
        elif "免息" in item:
            keywords.append("免息")
        elif "秒杀" in item:
            keywords.append("秒杀")
        elif "赠" in item or "买一送一" in item:
            keywords.append("赠品/买赠")
        else:
            keywords.append(item)

    return list(dict.fromkeys(keywords))


def analyze_promotions(df):
    """
    分析促销信息对商品销量的影响。

    返回：
    - promo_summary: 每种促销类型的商品数量和平均销量
    - top_keywords: Top 10 促销关键词出现频次
    - promo_compare: 有促销/无促销商品的平均销量对比
    """
    promo_df = df.copy()
    promo_df["销售量"] = pd.to_numeric(promo_df["销售量"], errors="coerce").fillna(0)
    promo_df["促销关键词"] = promo_df["促销信息"].apply(parse_promotion_keywords)
    promo_df["是否有促销"] = promo_df["促销关键词"].apply(lambda keywords: len(keywords) > 0)

    exploded = promo_df.explode("促销关键词")
    exploded = exploded[exploded["促销关键词"].notna() & exploded["促销关键词"].astype(str).str.strip().ne("")]

    if exploded.empty:
        promo_summary = pd.DataFrame(columns=["促销类型", "商品数量", "平均销量"])
        top_keywords = pd.Series(dtype="int64")
    else:
        promo_summary = (
            exploded.groupby("促销关键词")
            .agg(
                商品数量=("商品名称", "count"),
                平均销量=("销售量", "mean"),
            )
            .reset_index()
            .rename(columns={"促销关键词": "促销类型"})
            .sort_values("商品数量", ascending=False)
        )
        top_keywords = exploded["促销关键词"].value_counts().head(10)

    promo_compare = (
        promo_df.groupby("是否有促销")["销售量"]
        .mean()
        .rename(index={True: "有促销商品", False: "无促销商品"})
    )

    return promo_summary, top_keywords, promo_compare


def analyze_category_distribution(df):
    """
    分析二级分类的价格分布。

    过滤条件：
    - 能提取出有效重量；
    - 现价 > 0；
    - 重量_g > 0。

    返回：
    - category_summary: 各二级分类的商品数量、平均价格、价格标准差、最低价、最高价、价格极差
    - valid_df: 清洗后的有效明细数据，用于绘制箱线图
    """
    category_df = df.copy()
    category_df["现价"] = pd.to_numeric(category_df["现价"], errors="coerce")
    category_df["重量_g"] = category_df["商品名称"].apply(extract_weight)
    category_df["重量_g"] = pd.to_numeric(category_df["重量_g"], errors="coerce")

    valid_df = category_df[
        category_df["二级分类"].notna()
        & category_df["现价"].notna()
        & category_df["重量_g"].notna()
        & (category_df["现价"] > 0)
        & (category_df["重量_g"] > 0)
    ].copy()

    if valid_df.empty:
        empty_summary = pd.DataFrame(
            columns=["二级分类", "商品数量", "平均价格", "价格标准差", "最低价", "最高价", "价格极差"]
        )
        return empty_summary, valid_df

    valid_df["二级分类"] = valid_df["二级分类"].astype(str).str.strip()
    valid_df = valid_df[valid_df["二级分类"].ne("")].copy()

    category_summary = (
        valid_df.groupby("二级分类")
        .agg(
            商品数量=("商品名称", "count"),
            平均价格=("现价", "mean"),
            价格标准差=("现价", "std"),
            最低价=("现价", "min"),
            最高价=("现价", "max"),
        )
        .reset_index()
        .sort_values("商品数量", ascending=False)
    )
    category_summary["价格标准差"] = category_summary["价格标准差"].fillna(0)
    category_summary["价格极差"] = category_summary["最高价"] - category_summary["最低价"]

    return category_summary, valid_df


def dataframe_preview(df, max_rows=5):
    """
    将 DataFrame 转成简洁文本，供 Agent/聊天区展示。
    """
    if df is None or df.empty:
        return "暂无可展示的数据。"
    return df.head(max_rows).to_string(index=False)


def parse_agent_query_params(query, df=None):
    """
    从自然语言中粗略抽取价格上限、品类、关键词、品牌。

    输入解析规则：
    - 价格上限 -> max_price
    - 品类 -> category
    - 关键词 -> keyword
    - 品牌 -> brand
    """
    query = str(query or "").strip()
    if df is None:
        df = pd.read_csv(DATA_FILE)

    max_price = None
    price_match = re.search(r"(\d+(?:\.\d+)?)\s*元\s*(?:以内|以下|内)?", query)
    if price_match:
        max_price = float(price_match.group(1))

    brand = None
    brand_candidates = [
        item for item in df["品牌"].apply(normalize_brand_keyword).dropna().unique().tolist() if item
    ]
    for candidate in sorted(brand_candidates, key=len, reverse=True):
        if candidate and candidate in query:
            brand = candidate
            break

    category = None
    category_candidates = pd.concat(
        [df["二级分类"].dropna().astype(str), df["三级分类"].dropna().astype(str)],
        ignore_index=True,
    ).unique().tolist()
    for candidate in sorted(category_candidates, key=len, reverse=True):
        if candidate and candidate in query:
            category = candidate
            break

    if category is None:
        for candidate in ["坚果", "肉脯", "肉类", "巧克力", "饼干", "糖果", "膨化", "礼盒", "果干", "豆干"]:
            if candidate in query:
                category = candidate
                break

    keyword = category or ""
    return {"max_price": max_price, "category": category, "keyword": keyword, "brand": brand}


def smart_selection(query):
    """
    选品/推荐工具：按品类、价格上限、性价比与销量综合得分推荐商品。
    """
    df = pd.read_csv(DATA_FILE)
    params = parse_agent_query_params(query, df)
    category = params["category"] or params["keyword"] or "零食"
    max_price = params["max_price"]

    category_mask = (
        df["二级分类"].astype(str).str.contains(category, na=False, regex=False)
        | df["三级分类"].astype(str).str.contains(category, na=False, regex=False)
        | df["商品名称"].astype(str).str.contains(category, na=False, regex=False)
    )
    selected = df[category_mask].copy()
    if max_price is not None:
        selected["现价"] = pd.to_numeric(selected["现价"], errors="coerce")
        selected = selected[selected["现价"] <= max_price].copy()

    result = get_top_selection(category, top_n=5, price_weight=0.7, source_df=selected)
    if result.empty:
        return f"未找到符合“{category}”且价格限制为 {max_price or '不限'} 的推荐商品。"

    return f"按性价比和销量综合推荐如下：\n{dataframe_preview(result, max_rows=5)}"


def precise_price_compare(query):
    """
    比价工具：按品牌和品类找出每克单价最低商品。
    """
    df = pd.read_csv(DATA_FILE)
    params = parse_agent_query_params(query, df)
    brand = params["brand"] or "良品铺子"
    category = params["category"] or params["keyword"] or "坚果"

    result, status = build_price_table(brand, category)
    if status != "ok" or result.empty:
        return f"未找到品牌“{brand}”和品类“{category}”的可比价商品。"

    display_result = result.copy()
    display_result["unit_price"] = display_result["unit_price"].round(6)
    return f"品牌“{brand}”、品类“{category}”的低价结果：\n{dataframe_preview(display_result, max_rows=3)}"


def nonstandard_insight(query):
    """
    非标品/礼盒工具：分析无法换算标准克重的商品。
    """
    non_standard_df = build_non_standard_table()
    avg_price = pd.to_numeric(non_standard_df["现价"], errors="coerce").mean()
    top_words = get_top_words(non_standard_df, top_n=10)
    return (
        f"非标品总数：{len(non_standard_df)}\n"
        f"平均售价：{avg_price:.2f} 元\n"
        f"高频词 Top10：{top_words.to_dict() if not top_words.empty else {}}"
    )


def brand_strategy_insight(query):
    """
    品牌分析工具：返回 Top 10 品牌的定价策略统计。
    """
    df = pd.read_csv(DATA_FILE)
    result = analyze_brand_strategy(df)
    if result.empty:
        return "暂无品牌定价策略数据。"
    display_result = result.copy()
    display_result["平均售价"] = display_result["平均售价"].round(2)
    display_result["平均单位成本"] = display_result["平均单位成本"].round(6)
    display_result["价格中位数"] = display_result["价格中位数"].round(2)
    return f"Top 10 品牌定价策略：\n{dataframe_preview(display_result, max_rows=10)}"


def promotion_insight(query):
    """
    促销分析工具：分析促销关键词频次和有/无促销销量差异。
    """
    df = pd.read_csv(DATA_FILE)
    promo_summary, top_keywords, promo_compare = analyze_promotions(df)
    promo_avg = promo_compare.get("有促销商品", 0)
    no_promo_avg = promo_compare.get("无促销商品", 0)
    return (
        f"促销关键词 Top10：{top_keywords.to_dict() if not top_keywords.empty else {}}\n"
        f"有促销商品平均销量：{promo_avg:,.0f}\n"
        f"无促销商品平均销量：{no_promo_avg:,.0f}\n"
        f"促销类型明细：\n{dataframe_preview(promo_summary, max_rows=10)}"
    )


def category_distribution_insight(query):
    """
    品类价格工具：分析二级分类价格分布。
    """
    df = pd.read_csv(DATA_FILE)
    params = parse_agent_query_params(query, df)
    category = params["category"] or params["keyword"]
    category_summary, _ = analyze_category_distribution(df)

    if category_summary.empty:
        return "暂无品类价格分布数据。"

    if category:
        matched = category_summary[
            category_summary["二级分类"].astype(str).str.contains(category, na=False, regex=False)
        ].copy()
        if not matched.empty:
            row = matched.iloc[0]
            return (
                f"{row['二级分类']} 的价格分布：商品数量 {int(row['商品数量'])}，"
                f"平均价格 {row['平均价格']:.2f} 元，最低价 {row['最低价']:.2f} 元，"
                f"最高价 {row['最高价']:.2f} 元，价格极差 {row['价格极差']:.2f} 元。"
            )

    return f"各二级分类价格分布概览：\n{dataframe_preview(category_summary, max_rows=10)}"


class PythonFunctionTool:
    """
    轻量 Python 函数工具适配器。

    用它统一声明工具，再转换为 LangChain Tool。
    """

    def __init__(self, name, description, func):
        self.name = name
        self.description = description
        self.func = func

    def to_langchain_tool(self, tool_cls):
        return tool_cls.from_function(name=self.name, description=self.description, func=self.func)


def build_python_function_tools():
    """
    Tool 映射关系：
    - 选品 / 推荐 -> smart_selection
    - 比价 -> precise_price_compare
    - 非标品 / 礼盒 -> nonstandard_insight
    - 品牌分析 -> analyze_brand_strategy
    - 促销分析 -> analyze_promotions
    - 品类价格 -> analyze_category_distribution
    """
    return [
        PythonFunctionTool("smart_selection", "用于选品、推荐商品、寻找高性价比商品。输入为用户自然语言需求。", smart_selection),
        PythonFunctionTool("precise_price_compare", "用于精准比价，按品牌和品类比较每克单价。输入为用户自然语言需求。", precise_price_compare),
        PythonFunctionTool("nonstandard_insight", "用于分析非标品、礼盒、按箱/颗/包售卖商品。输入为用户自然语言需求。", nonstandard_insight),
        PythonFunctionTool("analyze_brand_strategy", "用于品牌定价策略分析，比较各品牌平均售价和平均单位成本。输入为用户自然语言需求。", brand_strategy_insight),
        PythonFunctionTool("analyze_promotions", "用于促销效果分析，统计促销关键词和有无促销销量差异。输入为用户自然语言需求。", promotion_insight),
        PythonFunctionTool("analyze_category_distribution", "用于品类价格分布分析，包括平均价、极差、最高价、最低价。输入为用户自然语言需求。", category_distribution_insight),
    ]


def initialize_snack_agent():
    """
    初始化 LangChain ZERO_SHOT_REACT_DESCRIPTION Agent。

    优先使用题目要求的 langchain.agents.initialize_agent。
    当前环境若为 LangChain 1.x 且不再导出 initialize_agent，则返回错误信息，
    Streamlit 页面会自动使用本地规则路由兜底。
    """
    try:
        from langchain.agents import AgentType, initialize_agent
        from langchain.tools import Tool
    except Exception:
        try:
            from langchain_classic.agents import AgentType, initialize_agent
            from langchain_classic.tools import Tool
        except Exception as exc:
            return None, (
                "当前 LangChain 环境未提供 initialize_agent。"
                "请安装兼容版本：`pip install langchain-classic`。"
                f"原始错误：{exc}"
            )

    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        return None, f"未安装 ChatOpenAI 依赖，请安装 `langchain-openai`。原始错误：{exc}"

    if not os.getenv("OPENAI_API_KEY"):
        return None, "未检测到 OPENAI_API_KEY，已使用本地规则路由兜底。"

    tools = [tool.to_langchain_tool(Tool) for tool in build_python_function_tools()]
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = initialize_agent(
        tools,
        llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=False,
        handle_parsing_errors=True,
    )
    return agent, None


def local_agent_router(query):
    """
    无 LLM 或 LangChain 版本不兼容时的本地意图路由兜底。
    """
    query = str(query or "")
    if any(word in query for word in ["促销", "满减", "包邮", "优惠券", "补贴"]):
        return promotion_insight(query)
    if any(word in query for word in ["非标", "礼盒", "整箱", "按颗", "按箱"]):
        return nonstandard_insight(query)
    if any(word in query for word in ["品牌", "定价", "策略"]):
        return brand_strategy_insight(query)
    if any(word in query for word in ["分布", "箱线", "波动", "价格区间"]):
        return category_distribution_insight(query)
    if any(word in query for word in ["比价", "哪个店", "每克", "单价"]):
        return precise_price_compare(query)
    return smart_selection(query)


def load_jieba():
    """
    懒加载 jieba。

    如果运行环境没有安装 jieba，不中断页面，只在 Streamlit 中给出安装提示。
    """
    try:
        import jieba

        return jieba
    except ImportError:
        return None


def build_non_standard_table():
    """
    构建非标品数据集。

    非标品定义：
    - 使用当前 extract_weight 逻辑无法提取标准克重；
    - 或提取出的重量 <= 0。

    这里不直接依赖 CSV 中旧的 weight_g，而是复用当前脚本的重量提取逻辑，
    确保“精准比价”和“非标品洞察”的口径一致。
    """
    df = pd.read_csv(DATA_FILE)
    df["现价"] = pd.to_numeric(df["现价"], errors="coerce")
    df["重量_g"] = df["商品名称"].apply(extract_weight)
    df["重量_g"] = pd.to_numeric(df["重量_g"], errors="coerce")

    non_standard = df[df["重量_g"].isna() | (df["重量_g"] <= 0)].copy()
    return non_standard


def get_top_words(non_standard_df, top_n=10):
    """
    对非标品商品名称进行 jieba 分词，返回 TopN 高频词。
    """
    jieba = load_jieba()
    if jieba is None or non_standard_df.empty:
        return pd.Series(dtype="int64")

    # 轻量停用词：去掉品牌/促销/单位/纯数字等对洞察价值较弱的词。
    stop_words = {
        "良品",
        "铺子",
        "良品铺子",
        "三只",
        "松鼠",
        "百草味",
        "京东",
        "零食",
        "食品",
        "商品",
        "官方",
        "旗舰店",
        "包",
        "袋",
        "盒",
        "箱",
        "颗",
        "粒",
        "g",
        "G",
        "克",
        "kg",
        "KG",
    }

    words = []
    for name in non_standard_df["商品名称"].dropna().astype(str):
        for word in jieba.lcut(name):
            word = word.strip()
            if len(word) < 2:
                continue
            if word in stop_words:
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?", word):
                continue
            words.append(word)

    if not words:
        return pd.Series(dtype="int64")

    return pd.Series(words).value_counts().head(top_n)


def get_price_distribution(non_standard_df):
    """
    统计非标品现价区间分布。
    """
    prices = pd.to_numeric(non_standard_df["现价"], errors="coerce").dropna()
    prices = prices[prices >= 0]
    if prices.empty:
        return pd.Series(dtype="int64")

    bins = [0, 50, 100, float("inf")]
    labels = ["0-50元", "50-100元", "100元以上"]
    return pd.cut(prices, bins=bins, labels=labels, right=False).value_counts().sort_index()


def get_chinese_font_path():
    """
    查找可用于词云和 Matplotlib 的中文字体。

    优先使用当前目录下的 simhei.ttf；如果不存在，则尝试 Windows 常见字体目录。
    """
    candidates = [
        Path("simhei.ttf"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]
    for font_path in candidates:
        if font_path.exists():
            return str(font_path)
    return None


def generate_wordcloud(words_freq_dict):
    """
    使用 wordcloud 生成真正的词云图片，并返回 BytesIO 图像流。

    参数：
    - words_freq_dict: 高频词及其频次，可以是 dict 或 pandas Series。

    返回：
    - BytesIO: PNG 图片流，可直接传给 st.image()
    - None: 依赖缺失、字体缺失或数据为空时返回 None
    """
    if wordcloud is None or plt is None:
        return None

    if hasattr(words_freq_dict, "to_dict"):
        words_freq_dict = words_freq_dict.to_dict()

    words_freq_dict = {
        str(word): int(freq)
        for word, freq in words_freq_dict.items()
        if pd.notna(word) and pd.notna(freq) and int(freq) > 0
    }
    if not words_freq_dict:
        return None

    font_path = get_chinese_font_path()
    if font_path is None:
        return None

    # 设置 Matplotlib 中文字体，避免图像标题或中文内容乱码。
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "SimSun", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False

    wc = wordcloud.WordCloud(
        width=800,
        height=400,
        background_color="white",
        font_path=font_path,
        collocations=False,
        random_state=42,
    ).generate_from_frequencies(words_freq_dict)

    fig, ax = plt.subplots(figsize=(10, 5), dpi=100)
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")

    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    image_buffer.seek(0)
    return image_buffer


def build_pie_chart(series, name_column, value_column):
    """
    将词频或价格区间 Series 转为 Altair 扇形图。
    """
    import altair as alt

    chart_df = series.reset_index()
    chart_df.columns = [name_column, value_column]
    chart_df[value_column] = pd.to_numeric(chart_df[value_column], errors="coerce")

    return (
        alt.Chart(chart_df)
        .mark_arc()
        .encode(
            theta=alt.Theta(field=value_column, type="quantitative"),
            color=alt.Color(field=name_column, type="nominal", legend=alt.Legend(title=name_column)),
            tooltip=[
                alt.Tooltip(field=name_column, type="nominal", title=name_column),
                alt.Tooltip(field=value_column, type="quantitative", title=value_column),
            ],
        )
        .properties(height=320)
    )


def is_streamlit_runtime():
    """
    判断当前脚本是否由 Streamlit 启动。

    这样同一个文件既可以：
    - python simple_price_compare.py
    - streamlit run simple_price_compare.py
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def run_streamlit_app():
    """
    Streamlit 网页界面。
    """
    import streamlit as st

    @st.cache_data
    def load_cached_data(csv_path, file_mtime):
        """
        缓存读取 CSV。

        file_mtime 作为缓存键的一部分，数据文件更新后会自动刷新缓存。
        """
        return pd.read_csv(csv_path)

    raw_df = load_cached_data(str(DATA_FILE.resolve()), DATA_FILE.stat().st_mtime)

    st.title("零食智能比价")

    @st.cache_resource
    def load_snack_agent():
        """
        缓存 LangChain Agent，避免每次页面刷新都重新初始化。
        """
        from agent_tools import initialize_snack_agent as initialize_external_snack_agent

        return initialize_external_snack_agent()

    def format_agent_response(agent_result):
        """
        兼容 agent_tools 的结构化返回：
        {
          "goto_tab": "...",
          "params": {...},
          "answer": "..."
        }
        """
        if isinstance(agent_result, dict):
            goto_tab = agent_result.get("goto_tab", "")
            params = agent_result.get("params", {})
            answer = agent_result.get("answer", "")
            route_hint = f"\n\n建议查看 Tab：{goto_tab}" if goto_tab else ""
            params_hint = f"\n参数：{params}" if params else ""
            return f"{answer}{route_hint}{params_hint}"
        return str(agent_result)

    st.subheader("智能分析助手")
    if "agent_messages" not in st.session_state:
        st.session_state["agent_messages"] = []

    for message in st.session_state["agent_messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_query = st.chat_input("请输入你的需求，例如：帮我选50元以内的健康坚果")
    if user_query:
        st.session_state["agent_messages"].append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        agent, agent_error = load_snack_agent()
        from agent_tools import local_agent_router as external_local_agent_router

        with st.chat_message("assistant"):
            if agent is not None:
                try:
                    agent_answer = agent.run(user_query)
                except Exception as exc:
                    fallback_result = external_local_agent_router(user_query)
                    agent_answer = f"Agent 调用失败，已切换本地分析：{exc}\n\n{format_agent_response(fallback_result)}"
            else:
                fallback_result = external_local_agent_router(user_query)
                agent_answer = f"{agent_error}\n\n{format_agent_response(fallback_result)}"

            st.markdown(f"```text\n{agent_answer}\n```")
        st.session_state["agent_messages"].append({"role": "assistant", "content": f"```text\n{agent_answer}\n```"})

    (
        price_tab,
        non_standard_tab,
        selection_tab,
        brand_strategy_tab,
        promotion_tab,
        category_distribution_tab,
    ) = st.tabs(
        [
            "精准比价",
            "非标品/礼盒洞察",
            "高性价比选品",
            "品牌定价策略",
            "促销效果分析",
            "品类价格分布",
        ]
    )

    with price_tab:
        comparable_df = build_comparable_keyword_table()
        brand_options = get_brand_options(comparable_df)

        if not brand_options:
            st.warning("当前数据中没有可参与每克单价计算的品牌。")
            brand = ""
            category = ""
        else:
            default_brand_index = brand_options.index("良品铺子") if "良品铺子" in brand_options else 0
            selected_brand = st.selectbox(
                "品牌关键词",
                brand_options,
                index=default_brand_index,
                help="仅展示当前数据中存在可比价商品的品牌。",
            )

            category_options = get_category_options(comparable_df, selected_brand)
            if not category_options:
                st.warning("该品牌下暂无可参与比价的品类。")
                selected_category = ""
            else:
                preferred_categories = ["坚果礼盒", "坚果炒货", "每日坚果", "坚果"]
                default_category_index = 0
                for preferred_category in preferred_categories:
                    if preferred_category in category_options:
                        default_category_index = category_options.index(preferred_category)
                        break

                selected_category = st.selectbox(
                    "品类关键词",
                    category_options,
                    index=default_category_index,
                    help="品类来自可比价商品的二级分类和三级分类，会随品牌自动联动。",
                )

            brand = selected_brand
            category = selected_category

        with st.expander("手动输入关键词"):
            use_custom_keywords = st.checkbox("启用手动输入", value=False)
            if use_custom_keywords:
                brand = st.text_input("自定义品牌关键词", value=brand)
                category = st.text_input("自定义品类关键词", value=category)

        if st.button("开始比价", disabled=not brand or not category):
            result, status = build_price_table(brand, category)

            if status == "no_match":
                st.warning(f"未找到包含‘{brand}’且包含‘{category}’的商品，请尝试更换关键词。")
            elif status == "no_standard_weight":
                st.info("抱歉，找到的商品均无标准克重（如按箱/颗售卖），暂不支持比价。")
            elif status == "no_valid_price":
                st.warning(f"包含‘{brand}’且包含‘{category}’的商品没有有效价格，暂不支持比价。")
            else:
                display_result = result.copy()
                display_result["unit_price"] = display_result["unit_price"].round(6)
                st.dataframe(display_result, width="stretch")

    with non_standard_tab:
        st.info("注：此类商品无标准克重，不参与每克单价计算，通常属于礼盒或批发场景。")

        non_standard_df = build_non_standard_table()

        metric_col_1, metric_col_2 = st.columns(2)
        metric_col_1.metric("非标品总数", f"{len(non_standard_df):,}")

        avg_price = pd.to_numeric(non_standard_df["现价"], errors="coerce").mean()
        avg_price_text = "暂无数据" if pd.isna(avg_price) else f"{avg_price:.2f} 元"
        metric_col_2.metric("平均售价", avg_price_text)

        st.subheader("高频词分析")
        wordcloud_words = get_top_words(non_standard_df, top_n=30)
        top_words = get_top_words(non_standard_df, top_n=10)
        if wordcloud_words.empty and top_words.empty:
            st.warning("未检测到 jieba 分词结果。请先安装 jieba：`pip install jieba`")
        else:
            word_cloud_col, word_pie_col = st.columns(2)
            with word_cloud_col:
                st.caption("词云（Top 30）")
                wordcloud_image = generate_wordcloud(wordcloud_words)
                if wordcloud_image is None:
                    st.warning(
                        "词云依赖或中文字体不可用。请安装：`pip install wordcloud matplotlib`，"
                        "并确保系统存在 `simhei.ttf` 或微软雅黑字体。"
                    )
                else:
                    st.image(wordcloud_image, width="stretch")
            with word_pie_col:
                st.caption("高频词占比")
                st.altair_chart(
                    build_pie_chart(top_words, "关键词", "出现次数"),
                    width="stretch",
                )

        st.subheader("价格区间分布")
        price_distribution = get_price_distribution(non_standard_df)
        if price_distribution.empty:
            st.warning("暂无有效价格数据可用于价格区间分析。")
        else:
            st.altair_chart(
                build_pie_chart(price_distribution, "价格区间", "商品数"),
                width="stretch",
            )

        st.subheader("非标品样例")
        sample_columns = ["品牌", "商品名称", "店铺名称", "现价", "二级分类", "三级分类"]
        available_columns = [col for col in sample_columns if col in non_standard_df.columns]
        st.dataframe(non_standard_df[available_columns].head(20), width="stretch")

    with selection_tab:
        st.subheader("高性价比选品")

        select_category = st.text_input("输入品类关键词（如：坚果、肉脯）", value="坚果", key="select_category")
        weight_col, explain_col = st.columns([1, 2])
        with weight_col:
            price_weight = st.slider("性价比权重", 0.0, 1.0, 0.7, 0.1)
        with explain_col:
            st.caption(
                "这个滑块决定系统更看重什么：数值越高，越优先推荐每克更便宜的商品；"
                "数值越低，越优先参考销量高、大家更常买的商品。默认 0.7 表示主要看划算程度，也兼顾热度。"
            )

        if not select_category.strip():
            st.warning("请输入品类关键词")
        else:
            top_selection = get_top_selection(
                select_category,
                top_n=3,
                price_weight=price_weight,
                source_df=raw_df,
            )

            if top_selection.empty:
                st.warning("未找到相关商品")
            else:
                display_selection = top_selection.copy()
                display_selection["现价"] = display_selection["现价"].round(2)
                display_selection["重量_g"] = display_selection["重量_g"].round(1)
                display_selection["unit_price(元/g)"] = display_selection["unit_price(元/g)"].round(6)
                display_selection["综合得分"] = display_selection["综合得分"].round(4)

                st.dataframe(display_selection, width="stretch")

    with brand_strategy_tab:
        st.subheader("品牌定价策略")

        brand_strategy = analyze_brand_strategy(raw_df)
        if brand_strategy.empty:
            st.warning("暂无可用于品牌定价策略分析的数据。")
        else:
            display_strategy = brand_strategy.copy()
            display_strategy["平均售价"] = display_strategy["平均售价"].round(2)
            display_strategy["平均单位成本"] = display_strategy["平均单位成本"].round(6)
            display_strategy["价格中位数"] = display_strategy["价格中位数"].round(2)

            st.dataframe(display_strategy, width="stretch")

            st.subheader("各品牌平均单位成本对比")
            import altair as alt

            unit_price_chart = (
                alt.Chart(display_strategy)
                .mark_bar()
                .encode(
                    x=alt.X(
                        "品牌:N",
                        title="品牌",
                        sort=None,
                        axis=alt.Axis(labelAngle=0, labelLimit=120),
                    ),
                    y=alt.Y("平均单位成本:Q", title="平均单位成本（元/g）"),
                    tooltip=[
                        alt.Tooltip("品牌:N", title="品牌"),
                        alt.Tooltip("平均单位成本:Q", title="平均单位成本", format=".6f"),
                        alt.Tooltip("商品数量:Q", title="商品数量"),
                    ],
                )
                .properties(height=380)
            )
            st.altair_chart(unit_price_chart, width="stretch")

    with promotion_tab:
        st.subheader("促销效果分析")

        promo_summary, top_keywords, promo_compare = analyze_promotions(raw_df)

        st.subheader("Top 10 促销关键词频次")
        if top_keywords.empty:
            st.warning("暂无可解析的促销关键词。")
        else:
            st.bar_chart(top_keywords)

        st.subheader("有促销 vs 无促销：平均销量对比")
        promo_col, no_promo_col = st.columns(2)
        promo_avg = promo_compare.get("有促销商品", 0)
        no_promo_avg = promo_compare.get("无促销商品", 0)
        promo_col.metric("有促销商品平均销量", f"{promo_avg:,.0f}")
        no_promo_col.metric("无促销商品平均销量", f"{no_promo_avg:,.0f}")

        st.subheader("促销类型明细")
        if promo_summary.empty:
            st.warning("暂无促销类型明细。")
        else:
            display_promo_summary = promo_summary.head(10).copy()
            display_promo_summary["平均销量"] = display_promo_summary["平均销量"].round(0).astype(int)
            st.dataframe(display_promo_summary, width="stretch")

    with category_distribution_tab:
        st.subheader("品类价格分布")

        category_summary, category_detail = analyze_category_distribution(raw_df)
        if category_summary.empty or category_detail.empty:
            st.warning("暂无可用于品类价格分布分析的数据。")
        else:
            category_options = category_summary["二级分类"].tolist()
            selected_category = st.selectbox("选择二级分类", category_options)

            selected_summary = category_summary[
                category_summary["二级分类"] == selected_category
            ].iloc[0]
            selected_detail = category_detail[
                category_detail["二级分类"] == selected_category
            ].copy()

            metric_col_1, metric_col_2 = st.columns(2)
            metric_col_1.metric("平均价", f"{selected_summary['平均价格']:.2f} 元")
            metric_col_2.metric("价格极差", f"{selected_summary['价格极差']:.2f} 元")

            st.caption(
                f"样本数：{int(selected_summary['商品数量'])}，"
                f"最低价：{selected_summary['最低价']:.2f} 元，"
                f"最高价：{selected_summary['最高价']:.2f} 元。"
            )

            if plt is None:
                st.warning("Matplotlib 不可用，请安装：`pip install matplotlib`。")
            else:
                plt.rcParams["font.sans-serif"] = [
                    "SimHei",
                    "Microsoft YaHei",
                    "SimSun",
                    "Arial Unicode MS",
                ]
                plt.rcParams["axes.unicode_minus"] = False

                fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
                ax.boxplot(
                    selected_detail["现价"].dropna(),
                    vert=True,
                    patch_artist=True,
                    boxprops={"facecolor": "#93c5fd", "color": "#2563eb"},
                    medianprops={"color": "#dc2626", "linewidth": 2},
                    whiskerprops={"color": "#2563eb"},
                    capprops={"color": "#2563eb"},
                    flierprops={
                        "marker": "o",
                        "markerfacecolor": "#f97316",
                        "markeredgecolor": "#f97316",
                        "markersize": 4,
                        "alpha": 0.55,
                    },
                )
                ax.set_title(f"{selected_category} 价格分布箱线图")
                ax.set_ylabel("现价（元）")
                ax.set_xticks([1])
                ax.set_xticklabels([selected_category])
                ax.grid(axis="y", linestyle="--", alpha=0.3)
                st.pyplot(fig)
                plt.close(fig)

                st.markdown(
                    """
                    **怎么看箱线图**

                    - 箱子中间的红线：这个品类的价格中位数，一半商品比它便宜，一半商品比它贵。
                    - 箱子的上下边：大多数商品集中的价格范围，箱子越高，说明价格差异越大。
                    - 上下延伸的线：常规价格的低端和高端。
                    - 单独的小圆点：价格特别低或特别高的商品，通常是异常低价、礼盒装或大规格商品。
                    """
                )


if __name__ == "__main__":
    if is_streamlit_runtime():
        run_streamlit_app()
    else:
        # 命令行测试：查找“良品铺子”中与“坚果”相关的最便宜商品。
        find_cheapest("良品铺子", "坚果")
