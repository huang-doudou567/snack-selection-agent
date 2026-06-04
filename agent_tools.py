import os
import json
import re

import pandas as pd

import simple_price_compare as app


def build_tool_result(goto_tab, params, answer):
    """
    统一工具返回结构，方便 Streamlit 根据 goto_tab 和 params 做页面跳转/参数填充。
    """
    return {
        "goto_tab": goto_tab,
        "params": params or {},
        "answer": answer,
    }


def tool_result_to_text(result):
    """
    LangChain Tool 通常更适合返回字符串，这里把结构化结果转成 JSON 字符串。
    """
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    return str(result)


def dataframe_preview(df, max_rows=5):
    """
    将 DataFrame 转成简洁文本，方便 Agent 返回自然语言结果。
    """
    if df is None or df.empty:
        return "暂无可展示的数据。"
    return df.head(max_rows).to_string(index=False)


def parse_agent_query_params(query, df=None):
    """
    从用户自然语言中抽取轻量参数。

    解析规则：
    - 价格上限 -> max_price
    - 品类 -> category
    - 关键词 -> keyword
    - 品牌 -> brand
    """
    query = str(query or "").strip()
    if df is None:
        df = pd.read_csv(app.DATA_FILE)

    max_price = None
    price_match = re.search(r"(\d+(?:\.\d+)?)\s*元\s*(?:以内|以下|内)?", query)
    if price_match:
        max_price = float(price_match.group(1))

    brand = None
    brand_candidates = [
        item for item in df["品牌"].apply(app.normalize_brand_keyword).dropna().unique().tolist() if item
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


def smart_selection(query=None, **kwargs):
    """
    选品/推荐工具：按品类、价格上限、性价比与销量综合得分推荐商品。
    """
    df = pd.read_csv(app.DATA_FILE)
    params = parse_agent_query_params(query or kwargs, df)
    category = kwargs.get("category") or params["category"] or params["keyword"] or "零食"
    max_price = kwargs.get("max_price", params["max_price"])

    category_mask = (
        df["二级分类"].astype(str).str.contains(category, na=False, regex=False)
        | df["三级分类"].astype(str).str.contains(category, na=False, regex=False)
        | df["商品名称"].astype(str).str.contains(category, na=False, regex=False)
    )
    selected = df[category_mask].copy()
    if max_price is not None:
        selected["现价"] = pd.to_numeric(selected["现价"], errors="coerce")
        selected = selected[selected["现价"] <= max_price].copy()

    result = app.get_top_selection(category, top_n=5, price_weight=0.7, source_df=selected)
    if result.empty:
        return build_tool_result(
            "高性价比选品",
            {"category": category, "max_price": max_price, "price_weight": 0.7, "top_n": 5},
            f"未找到符合“{category}”且价格限制为 {max_price or '不限'} 的推荐商品。",
        )

    return build_tool_result(
        "高性价比选品",
        {"category": category, "max_price": max_price, "price_weight": 0.7, "top_n": 5},
        f"按性价比和销量综合推荐如下：\n{dataframe_preview(result, max_rows=5)}",
    )


def precise_price_compare(query=None, **kwargs):
    """
    比价工具：按品牌和品类找出每克单价最低商品。
    """
    df = pd.read_csv(app.DATA_FILE)
    params = parse_agent_query_params(query or kwargs, df)
    brand = kwargs.get("brand") or params["brand"] or "良品铺子"
    category = kwargs.get("category") or params["category"] or params["keyword"] or "坚果"

    result, status = app.build_price_table(brand, category)
    if status != "ok" or result.empty:
        return build_tool_result(
            "精准比价",
            {"brand": brand, "category": category},
            f"未找到品牌“{brand}”和品类“{category}”的可比价商品。",
        )

    display_result = result.copy()
    display_result["unit_price"] = display_result["unit_price"].round(6)
    return build_tool_result(
        "精准比价",
        {"brand": brand, "category": category},
        f"品牌“{brand}”、品类“{category}”的低价结果：\n{dataframe_preview(display_result, max_rows=3)}",
    )


def nonstandard_insight(query=None, **kwargs):
    """
    非标品/礼盒工具：分析无法换算标准克重的商品。
    """
    non_standard_df = app.build_non_standard_table()
    avg_price = pd.to_numeric(non_standard_df["现价"], errors="coerce").mean()
    top_words = app.get_top_words(non_standard_df, top_n=10)

    answer = (
        f"非标品总数：{len(non_standard_df)}\n"
        f"平均售价：{avg_price:.2f} 元\n"
        f"高频词 Top10：{top_words.to_dict() if not top_words.empty else {}}"
    )
    return build_tool_result("非标品洞察", {}, answer)


def brand_strategy_insight(query=None, **kwargs):
    """
    品牌分析工具：返回 Top 10 品牌的定价策略统计。
    """
    df = pd.read_csv(app.DATA_FILE)
    result = app.analyze_brand_strategy(df)
    if result.empty:
        return build_tool_result("品牌定价策略", {}, "暂无品牌定价策略数据。")

    display_result = result.copy()
    display_result["平均售价"] = display_result["平均售价"].round(2)
    display_result["平均单位成本"] = display_result["平均单位成本"].round(6)
    display_result["价格中位数"] = display_result["价格中位数"].round(2)
    return build_tool_result(
        "品牌定价策略",
        {"top_n": 10},
        f"Top 10 品牌定价策略：\n{dataframe_preview(display_result, max_rows=10)}",
    )


def promotion_insight(query=None, **kwargs):
    """
    促销分析工具：分析促销关键词频次和有/无促销销量差异。
    """
    df = pd.read_csv(app.DATA_FILE)
    promo_summary, top_keywords, promo_compare = app.analyze_promotions(df)
    promo_avg = promo_compare.get("有促销商品", 0)
    no_promo_avg = promo_compare.get("无促销商品", 0)

    answer = (
        f"促销关键词 Top10：{top_keywords.to_dict() if not top_keywords.empty else {}}\n"
        f"有促销商品平均销量：{promo_avg:,.0f}\n"
        f"无促销商品平均销量：{no_promo_avg:,.0f}\n"
        f"促销类型明细：\n{dataframe_preview(promo_summary, max_rows=10)}"
    )
    return build_tool_result("促销效果分析", {"top_n": 10}, answer)


def category_distribution_insight(query=None, **kwargs):
    """
    品类价格工具：分析二级分类价格分布。
    """
    df = pd.read_csv(app.DATA_FILE)
    params = parse_agent_query_params(query or kwargs, df)
    category = kwargs.get("category") or params["category"] or params["keyword"]
    category_summary, _ = app.analyze_category_distribution(df)

    if category_summary.empty:
        return build_tool_result("品类价格分布", {"category": category}, "暂无品类价格分布数据。")

    if category:
        matched = category_summary[
            category_summary["二级分类"].astype(str).str.contains(category, na=False, regex=False)
        ].copy()
        if not matched.empty:
            row = matched.iloc[0]
            answer = (
                f"{row['二级分类']} 的价格分布：商品数量 {int(row['商品数量'])}，"
                f"平均价格 {row['平均价格']:.2f} 元，最低价 {row['最低价']:.2f} 元，"
                f"最高价 {row['最高价']:.2f} 元，价格极差 {row['价格极差']:.2f} 元。"
            )
            return build_tool_result("品类价格分布", {"category": row["二级分类"]}, answer)

    return build_tool_result(
        "品类价格分布",
        {"category": category},
        f"各二级分类价格分布概览：\n{dataframe_preview(category_summary, max_rows=10)}",
    )


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
        def wrapped_func(query):
            return tool_result_to_text(self.func(query=query))

        return tool_cls.from_function(name=self.name, description=self.description, func=wrapped_func)


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
    若当前环境使用 LangChain 1.x，则自动尝试 langchain_classic 兼容路径。
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
