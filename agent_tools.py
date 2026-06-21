# -*- coding: utf-8 -*-
"""
Snack Selection Agent — 增强版工具集。

v2 新增:
- 多 LLM 后端（Claude 优先，OpenAI/DeepSeek 备用）
- 6 场景驱动 System Prompt
- 结构化返回（models.SelectionReport，不再只返回 UI 跳转字符串）
- 保留 v1 全部兼容性（现有 Streamlit 工具函数不变）

设计原则：Agent 推理和 Python 执行通过 models.py 数据结构解耦。
"""

from __future__ import annotations

import os
import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

import simple_price_compare as app
from models import (
    Evidence, RawProduct, SelectionAdvice, SelectionReport,
    make_evidence, make_advice,
)


# ── 路径常量 ──────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent
INTEGRATED_DATA = PROJECT_DIR / "integrated_selection_products.csv"
PRICE_HISTORY = PROJECT_DIR / "price_history.csv"
REVIEW_DIR = PROJECT_DIR / "数据" / "京东评论抓取"
QUALITY_REPORT = PROJECT_DIR / "selection_data_quality_report.json"


def get_data_age() -> dict:
    """返回数据文件的最新修改时间。"""
    ages = {}
    for label, path in [
        ("products", INTEGRATED_DATA),
        ("price_history", PRICE_HISTORY),
        ("reviews", REVIEW_DIR / "product_reviews.csv"),
        ("negative_reviews", REVIEW_DIR / "negative_reviews.csv"),
    ]:
        try:
            mtime = path.stat().st_mtime
            days = (datetime.now().timestamp() - mtime) / 86400
            ages[label] = {"mtime": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"), "days_ago": round(days)}
        except Exception:
            ages[label] = {"mtime": "未知", "days_ago": -1}
    return ages


def get_coverage() -> dict:
    """读取数据质量报告，返回覆盖率摘要。"""
    try:
        report = json.loads(QUALITY_REPORT.read_text(encoding="utf-8"))
        return {
            "jd_reviews": report.get("jd_reviews_coverage", 0.032),
            "mmb_price": report.get("mmb_price_history_coverage", 0.024),
            "total_products": report.get("total_products", 13400),
        }
    except Exception:
        return {"jd_reviews": 0.032, "mmb_price": 0.024, "total_products": 13400}


# ── v1 兼容层：Streamlit 工具函数（不改接口） ────────────────────

def build_tool_result(goto_tab, params, answer):
    """Streamlit 兼容：goto_tab 驱动页面跳转。"""
    return {"goto_tab": goto_tab, "params": params or {}, "answer": answer}


def tool_result_to_text(result):
    """LangChain Tool 兼容：dict → JSON 字符串。"""
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    return str(result)


def dataframe_preview(df, max_rows=5):
    """DataFrame → 简洁文本。"""
    if df is None or df.empty:
        return "暂无可展示的数据。"
    return df.head(max_rows).to_string(index=False)


def parse_agent_query_params(query, df=None):
    """从自然语言中正则抽取 价格上限/品类/品牌/关键词。"""
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


# ── v1 工具函数（保留，Streamlit 依赖） ──────────────────────────

def smart_selection(query=None, **kwargs):
    """选品推荐。"""
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
            f'未找到符合“{category}”且价格限制为 {max_price or "不限"} 的推荐商品。',
        )
    return build_tool_result(
        "高性价比选品",
        {"category": category, "max_price": max_price, "price_weight": 0.7, "top_n": 5},
        f"按性价比和销量综合推荐如下：\n{dataframe_preview(result, max_rows=5)}",
    )


def precise_price_compare(query=None, **kwargs):
    """精准比价。"""
    df = pd.read_csv(app.DATA_FILE)
    params = parse_agent_query_params(query or kwargs, df)
    brand = kwargs.get("brand") or params["brand"] or "良品铺子"
    category = kwargs.get("category") or params["category"] or params["keyword"] or "坚果"

    result, status = app.build_price_table(brand, category)
    if status != "ok" or result.empty:
        return build_tool_result(
            "精准比价", {"brand": brand, "category": category},
            f'未找到品牌“{brand}”和品类“{category}"的可比价商品。',
        )
    display_result = result.copy()
    display_result["unit_price"] = display_result["unit_price"].round(6)
    return build_tool_result(
        "精准比价", {"brand": brand, "category": category},
        f'品牌“{brand}”、品类“{category}”的低价结果：\n{dataframe_preview(display_result, max_rows=3)}',
    )


def nonstandard_insight(query=None, **kwargs):
    """非标品/礼盒分析。"""
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
    """品牌定价策略。"""
    df = pd.read_csv(app.DATA_FILE)
    result = app.analyze_brand_strategy(df)
    if result.empty:
        return build_tool_result("品牌定价策略", {}, "暂无品牌定价策略数据。")
    display_result = result.copy()
    display_result["平均售价"] = display_result["平均售价"].round(2)
    display_result["平均单位成本"] = display_result["平均单位成本"].round(6)
    display_result["价格中位数"] = display_result["价格中位数"].round(2)
    return build_tool_result(
        "品牌定价策略", {"top_n": 10},
        f"Top 10 品牌定价策略：\n{dataframe_preview(display_result, max_rows=10)}",
    )


def promotion_insight(query=None, **kwargs):
    """促销效果分析。"""
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
    """品类价格分布。"""
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
        "品类价格分布", {"category": category},
        f"各二级分类价格分布概览：\n{dataframe_preview(category_summary, max_rows=10)}",
    )


# ── v2 新增：场景驱动 System Prompts ─────────────────────────────

SCENE_SYSTEM_PROMPTS = {
    "clearout": """你是一个帮零食电商用户以最小亏损清理库存的选品 Agent。
用户场景：仓库压货，需要快速出清。
你的任务：
1. 分析同品类竞品价格分布，确定该品类的市场底价
2. 计算降价到不同区间的清仓速度预估（基于销量数据）
3. 给出 3 档降价方案（激进/平衡/保守），每档标注预期毛利损失和清仓周期
4. 建议搭配促销手段（满减/优惠券/组合销售）
5. 每条建议标注数据来源和置信度。
输出语言：中文。数据不足时明确写出局限性。""",

    "pick": """你是一个帮零食电商用户发现蓝海选品机会的 Agent。
用户场景：想在某品类找到价格带空白并上架新品。
你的任务：
1. 分析品类价格-需求分布，找到供给不足的价格区间（空白带）
2. 推荐 3-5 个能填补空白的具体商品（含品名/品牌/价格/净重/预计利润率）
3. 分析空白带的竞争强度（现有品牌数量和集中度）
4. 给出上架优先级排序和理由
5. 每条建议标注数据来源和置信度。
输出语言：中文。数据不足时明确写出局限性。""",

    "benchmark": """你是一个帮零食电商用户做竞品对标的 Agent。
用户场景：手上有一个商品，想知道能不能跟竞品打、怎么差异化。
你的任务：
1. 对竞品做全维度拆解：价格、克重、每克单价、促销策略、好评率、差评归因
2. 在同品类中找出价格/规格最接近的 5 个替代品
3. 给出 3 种差异化定位方案（价格战/品质升级/规格错位）
4. 每条建议标注数据来源和置信度。
输出语言：中文。数据不足时明确写出局限性。""",

    "promotion": """你是一个帮零食电商用户制定促销策略的 Agent。
用户场景：大促在即，需要确定折扣力度和促销形式。
你的任务：
1. 分析历史促销效果（满减 vs 直降 vs 优惠券 vs 包邮）
2. 给出该品类最优促销形式和力度建议
3. 预估促销 ROI（基于历史有/无促销的销量对比）
4. 建议促销组合（组合销售/加价购/赠品）
5. 每条建议标注数据来源和置信度。
输出语言：中文。数据不足时明确写出局限性。""",

    "negative_review": """你是一个帮零食电商用户做差评归因和改品建议的 Agent。
用户场景：商品差评集中爆发，需要找到根因并给出改品方案。
你的任务：
1. 分类差评根因（口味/包装破损/保质期短/规格不符/物流/其他）
2. 统计各类差评占比
3. 给出针对性改品建议（配方/包装/规格/供应链）
4. 提供客服话术模板（用于回复差评）
5. 每条建议标注数据来源和置信度。
输出语言：中文。数据不足时明确写出局限性。""",

    "sourcing": """你是一个帮零食电商用户做月度进货决策的 Agent。
用户场景：月底要定下个月的进货清单，有预算约束。
你的任务：
1. 分析各品类近期销量趋势，找出上升/下降品类
2. 基于预算和品类趋势给出进货清单（品名/数量/预计进价/建议售价/预期周转天数）
3. 建议品牌组合（引流款+利润款+形象款）
4. 标注安全库存建议
5. 每条建议标注数据来源和置信度。
输出语言：中文。数据不足时明确写出局限性。""",
}


# ── v2 新增：场景识别 ───────────────────────────────────────────

def identify_scene(query: str) -> tuple[str, float]:
    """从用户自然语言中识别经营场景。

    返回 (场景名, 置信度)。
    不只用关键词——也考虑语义。Agent 可以覆写此结果。
    """
    query = str(query or "")

    # 词袋 + 权重
    scene_keywords = {
        "clearout": ["清仓", "滞销", "压货", "库存", "清掉", "甩卖", "降价清", "卖不动", "积压", "出清"],
        "pick": ["选品", "上架", "空白", "蓝海", "推荐", "哪个品", "什么品", "新品", "进货选", "品类分析"],
        "benchmark": ["竞品", "对标", "跟价", "替代", "能不能打", "差异化", "对比", "竞品分析", "同款"],
        "promotion": ["促销", "满减", "折扣", "优惠券", "大促", "双11", "618", "活动", "降价", "打折"],
        "negative_review": ["差评", "投诉", "口碑", "改品", "品控", "质量", "差评分析", "负面评价"],
        "sourcing": ["进货", "采购", "进货单", "补货", "备货", "囤货", "进什么", "预算", "月度"],
    }

    scores = {}
    for scene, keywords in scene_keywords.items():
        score = sum(1 for kw in keywords if kw in query)
        if score > 0:
            scores[scene] = score

    if not scores:
        return ("pick", 0.3)  # 默认选品场景

    best = max(scores, key=scores.get)
    total = sum(scores.values())
    confidence = scores[best] / total if total > 0 else 0.3
    return (best, min(confidence, 1.0))


# ── v2 新增：结构化查询工具 ─────────────────────────────────────

def query_category_structure(category: str) -> dict:
    """查询品类的完整结构化数据。

    返回 dict 包含 价格分布/品牌集中度/TOP 商品/证据列表。
    这是 v2 的核心查询函数——Agent 用此结果做推理。
    """
    df = pd.read_csv(app.DATA_FILE)
    params = {"category": category}

    # 品类分布
    category_summary, _ = app.analyze_category_distribution(df)
    cat_row = None
    if not category_summary.empty:
        matched = category_summary[
            category_summary["二级分类"].astype(str).str.contains(category, na=False, regex=False)
        ]
        if not matched.empty:
            cat_row = matched.iloc[0].to_dict()

    # 品牌策略
    brand_strategy = app.analyze_brand_strategy(df)
    cat_brands = pd.DataFrame()
    if not brand_strategy.empty and "品牌" in brand_strategy.columns:
        # 筛选该品类的品牌
        cat_products = df[
            df["二级分类"].astype(str).str.contains(category, na=False, regex=False)
        ]
        cat_brands_set = cat_products["品牌"].dropna().unique()
        cat_brands = brand_strategy[brand_strategy["品牌"].isin(cat_brands_set)]

    # TOP 性价比商品
    top_products = app.get_top_selection(category, top_n=10, price_weight=0.7, source_df=df)

    data_age = get_data_age()
    coverage = get_coverage()

    return {
        "category": category,
        "distribution": cat_row,
        "brand_strategy": cat_brands.head(10).to_dict(orient="records") if not cat_brands.empty else [],
        "top_products": top_products.head(10).to_dict(orient="records") if not top_products.empty else [],
        "data_age": data_age,
        "coverage": coverage,
        "query_at": datetime.now().isoformat(),
    }


def query_price_compare_structured(brand: str, category: str) -> dict:
    """精准比价的结构化版本。"""
    result, status = app.build_price_table(brand, category)
    if status != "ok" or result.empty:
        return {"status": status, "brand": brand, "category": category, "products": []}

    display = result.copy()
    if "unit_price" in display.columns:
        display["unit_price"] = display["unit_price"].round(6)
    return {
        "status": status,
        "brand": brand,
        "category": category,
        "products": display.head(10).to_dict(orient="records"),
        "cheapest": display.iloc[0].to_dict() if len(display) > 0 else None,
        "most_expensive": display.iloc[-1].to_dict() if len(display) > 0 else None,
    }


# ── v2 新增：LLM 后端抽象 ────────────────────────────────────────

def create_llm(backend: str = "claude", temperature: float = 0):
    """创建 LLM 实例——Claude 优先。

    支持的后端：
    - claude: Anthropic Claude（通过 langchain_anthropic）
    - openai: OpenAI GPT-4o-mini
    - deepseek: DeepSeek（兼容 OpenAI API）
    - auto: 自动探测可用的 LLM
    """
    if backend == "auto":
        for candidate in ["claude", "openai", "deepseek"]:
            try:
                return create_llm(candidate, temperature)
            except Exception:
                continue
        raise RuntimeError("无可用 LLM 后端。请设置 ANTHROPIC_API_KEY 或 OPENAI_API_KEY 或 DEEPSEEK_API_KEY。")

    if backend == "claude":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError("请安装 langchain-anthropic：pip install langchain-anthropic")
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise ValueError("未设置 ANTHROPIC_API_KEY")
        return ChatAnthropic(model="claude-sonnet-4-6", temperature=temperature)

    if backend == "openai":
        from langchain_openai import ChatOpenAI
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("未设置 OPENAI_API_KEY")
        return ChatOpenAI(model="gpt-4o-mini", temperature=temperature)

    if backend == "deepseek":
        from langchain_openai import ChatOpenAI
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("未设置 DEEPSEEK_API_KEY")
        return ChatOpenAI(
            model="deepseek-chat", temperature=temperature,
            openai_api_key=api_key, openai_api_base="https://api.deepseek.com",
        )

    raise ValueError(f"未知 LLM 后端: {backend}")


def get_system_prompt(scene: str) -> str:
    """获取场景对应的 System Prompt。"""
    return SCENE_SYSTEM_PROMPTS.get(
        scene,
        SCENE_SYSTEM_PROMPTS["pick"],  # 默认选品
    )


# ── v2 新增：Agent 初始化（多 LLM） ──────────────────────────────

class PythonFunctionTool:
    """轻量 Python 函数工具适配器。"""

    def __init__(self, name, description, func):
        self.name = name
        self.description = description
        self.func = func

    def to_langchain_tool(self, tool_cls):
        def wrapped_func(query):
            return tool_result_to_text(self.func(query=query))
        return tool_cls.from_function(name=self.name, description=self.description, func=wrapped_func)


def build_python_function_tools():
    """构建 6 个 Agent 工具。"""
    return [
        PythonFunctionTool("smart_selection", "选品推荐/寻找高性价比商品。输入自然语言需求。", smart_selection),
        PythonFunctionTool("precise_price_compare", "精准比价，按品牌+品类比较每克单价。输入自然语言需求。", precise_price_compare),
        PythonFunctionTool("nonstandard_insight", "分析非标品/礼盒/按箱颗包售卖商品。输入自然语言需求。", nonstandard_insight),
        PythonFunctionTool("analyze_brand_strategy", "品牌定价策略分析。输入自然语言需求。", brand_strategy_insight),
        PythonFunctionTool("analyze_promotions", "促销效果分析，统计促销关键词和效果差异。输入自然语言需求。", promotion_insight),
        PythonFunctionTool("analyze_category_distribution", "品类价格分布分析。输入自然语言需求。", category_distribution_insight),
    ]


def initialize_snack_agent(backend: str = "auto", scene: str = ""):
    """初始化 LangChain Agent（增强版）。

    Args:
        backend: LLM 后端 claude|openai|deepseek|auto
        scene: 场景 clearout|pick|benchmark|promotion|negative_review|sourcing
    """
    try:
        from langchain.agents import AgentType, initialize_agent
        from langchain.tools import Tool
        from langchain.memory import ConversationBufferMemory
    except Exception:
        try:
            from langchain_classic.agents import AgentType, initialize_agent
            from langchain_classic.tools import Tool
            from langchain_classic.memory import ConversationBufferMemory
        except Exception as exc:
            return None, (
                "当前 LangChain 环境未提供 initialize_agent。"
                "请安装兼容版本：pip install langchain-classic。"
                f"原始错误：{exc}"
            )

    try:
        llm = create_llm(backend)
    except Exception as exc:
        return None, f"LLM 初始化失败：{exc}"

    tools = [tool.to_langchain_tool(Tool) for tool in build_python_function_tools()]
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

    system_prompt = get_system_prompt(scene) if scene else ""

    agent = initialize_agent(
        tools,
        llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=False,
        handle_parsing_errors=True,
        memory=memory,
        agent_kwargs={"system_message": system_prompt} if system_prompt else {},
    )
    return agent, None


# ── v2 新增：本地路由（无 LLM 兜底） ─────────────────────────────

def local_agent_router(query):
    """无 LLM 时的本地意图路由兜底。"""
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


# ── v2 新增：完整选品分析流程（供 Claude Code SKILL.md 调用） ──

def run_full_analysis(query: str, scene: str = "") -> SelectionReport:
    """执行完整的选品分析流程。

    这是供 Claude Code SKILL.md 调用的主入口。
    返回 SelectionReport，Agent 再基于此写 Markdown 建议书。
    """
    if not scene:
        scene, confidence = identify_scene(query)

    params = parse_agent_query_params(query)
    category = params.get("category") or params.get("keyword") or "零食"
    brand = params.get("brand", "")
    max_price = params.get("max_price")

    # 并行查询
    struct_data = query_category_structure(category)
    brand_data = query_price_compare_structured(brand or "良品铺子", category) if brand else None

    # 构建报告
    coverage = get_coverage()
    data_age = get_data_age()

    report = SelectionReport(
        generated_at=datetime.now().isoformat(),
        scenario=scene,
        scene_diagnosis=f"用户场景: {scene} | 品类: {category} | {'品牌: ' + brand if brand else '不限品牌'}",
        user_input_summary=query,
        category=category,
        brand=brand,
        max_price=max_price,
        total_products=coverage.get("total_products", 0),
        coverage_jd_reviews=coverage.get("jd_reviews", 0),
        coverage_mmb_price=coverage.get("mmb_price", 0),
        data_caveats=(
            [f"京东评论覆盖率仅 {coverage.get('jd_reviews', 0)*100:.1f}%"]
            if coverage.get("jd_reviews", 0) < 0.1 else []
        ) + (
            [f"慢慢买价格覆盖率仅 {coverage.get('mmb_price', 0)*100:.1f}%"]
            if coverage.get("mmb_price", 0) < 0.1 else []
        ),
    )

    # 价格分布发现
    dist = struct_data.get("distribution")
    if dist:
        report.key_findings.append({
            "指标": "品类价格分布",
            "数值": f"均价{dist.get('平均价格', 0):.2f}元, 最低{dist.get('最低价', 0):.2f}元, 最高{dist.get('最高价', 0):.2f}元",
            "来源": "integrated_selection_products.csv",
            "商品数": int(dist.get("商品数量", 0)),
        })

    # TOP 商品
    top_products = struct_data.get("top_products", [])
    if top_products:
        report.key_findings.append({
            "指标": "性价比 TOP5",
            "数值": "\n".join(
                f"{i+1}. {p.get('商品名称', '?')[:60]} — {p.get('现价', 0)}元"
                for i, p in enumerate(top_products[:5])
            ),
            "来源": "simple_price_compare.get_top_selection",
        })

    # 品牌策略
    brand_data_list = struct_data.get("brand_strategy", [])
    if brand_data_list:
        top_brands = brand_data_list[:5]
        report.key_findings.append({
            "指标": "品牌集中度",
            "数值": f"Top 5 品牌: {', '.join(b.get('品牌', '?') for b in top_brands)}",
            "来源": "simple_price_compare.analyze_brand_strategy",
        })

    # 数据时效
    for key, info in data_age.items():
        if info["days_ago"] >= 0:
            report.key_findings.append({
                "指标": f"{key} 数据时效",
                "数值": f"{info['mtime']} ({info['days_ago']}天前)",
                "来源": key,
            })

    # 组装证据
    for i, finding in enumerate(report.key_findings):
        report.all_evidence.append(make_evidence(
            source_file=finding.get("来源", ""),
            raw_value=str(finding.get("数值", ""))[:200],
        ))

    return report
