# -*- coding: utf-8 -*-
"""Streamlit Web 界面：零食选品智能助手。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from product_assistant import ProductSelectionAssistant


st.set_page_config(page_title="零食选品智能助手", layout="wide")
ASSISTANT_CACHE_VERSION = "integrated-selection-corpus-v1"
QUALITY_REPORT_PATH = Path("selection_data_quality_report.json")
DATA_PATH_CANDIDATES = [
    Path("integrated_selection_products.csv"),
    Path.home() / "Desktop" / "integrated_selection_products.csv",
    Path("structured_snacks_data_with_random_sales.csv"),
    Path.home() / "Desktop" / "structured_snacks_data_with_random_sales.csv",
    Path("structured_snacks_data.csv"),
    Path.home() / "Desktop" / "structured_snacks_data.csv",
]


def file_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def resolve_selection_data_path() -> Path | None:
    for candidate in DATA_PATH_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


@st.cache_resource
def load_assistant(cache_version: str, data_mtime_ns: int) -> ProductSelectionAssistant:
    """加载核心助手。

    cache_version 用来在核心类新增能力后主动失效旧缓存，避免 Streamlit
    继续复用历史进程里的旧 ProductSelectionAssistant 实例。
    """
    _ = cache_version
    _ = data_mtime_ns
    return ProductSelectionAssistant()


def get_assistant() -> ProductSelectionAssistant:
    data_path = resolve_selection_data_path()
    assistant = load_assistant(ASSISTANT_CACHE_VERSION, file_mtime_ns(data_path) if data_path else 0)
    if not hasattr(assistant, "analyze_product_url"):
        load_assistant.clear()
        assistant = load_assistant(ASSISTANT_CACHE_VERSION, file_mtime_ns(data_path) if data_path else 0)
    return assistant


def parse_optional_float(value: str) -> float | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        number = float(value)
        return number if number > 0 else None
    except ValueError:
        return None


@st.cache_data(show_spinner=False)
def load_selection_quality_report(report_mtime_ns: int) -> dict:
    _ = report_mtime_ns
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


def render_selection_quality_summary(report: dict) -> None:
    if not report:
        st.info("尚未生成整合质量报告。可运行 `python integrate_selection_data.py` 后刷新页面。")
        return

    coverage = report.get("coverage", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("统一商品数", f"{report.get('row_count', 0):,}")
    c2.metric("价格覆盖", pct_text(coverage.get("price", {}).get("coverage")))
    c3.metric("单位价覆盖", pct_text(coverage.get("unit_price_valid", {}).get("coverage")))
    c4.metric("京东评论覆盖", pct_text(coverage.get("jd_reviews", {}).get("coverage")))
    c5.metric("历史价覆盖", pct_text(coverage.get("mmb_price_history", {}).get("coverage")))

    with st.expander("数据整合与质量检查", expanded=False):
        st.caption(f"报告生成时间：{report.get('generated_at', '-')}")
        source_rows = pd.DataFrame(
            [
                {"数据源": name, "行数": item.get("rows", 0), "文件": item.get("path", "")}
                for name, item in report.get("source_rows", {}).items()
            ]
        )
        if not source_rows.empty:
            st.dataframe(source_rows, width="stretch", hide_index=True)

        left, right = st.columns(2)
        with left:
            coverage_rows = pd.DataFrame(
                [
                    {
                        "指标": name,
                        "非空数量": item.get("nonempty", 0),
                        "覆盖率": pct_text(item.get("coverage")),
                    }
                    for name, item in coverage.items()
                ]
            )
            st.dataframe(coverage_rows, width="stretch", hide_index=True)
        with right:
            flags = pd.DataFrame(
                [{"质量项": name, "数量": value} for name, value in report.get("quality_flags", {}).items()]
            )
            st.dataframe(flags, width="stretch", hide_index=True)


def render_dict_block(data: dict) -> None:
    """通用字典展示，保留可解释字段。"""
    for key, value in data.items():
        if key in {"data_source", "method", "confidence", "limitation"}:
            continue
        if isinstance(value, list):
            st.write(f"**{key}**")
            for item in value:
                st.write(f"- {item}")
        elif isinstance(value, dict):
            st.write(f"**{key}**")
            st.json(value, expanded=False)
        else:
            st.write(f"**{key}**：{value}")


def render_explainability(data: dict) -> None:
    with st.container(border=True):
        st.caption("可解释性说明")
        if data.get("data_source"):
            st.write(f"数据来源：{data['data_source']}")
        if data.get("method"):
            st.write(f"计算方法：{data['method']}")
        if data.get("confidence"):
            st.write(f"置信度：{data['confidence']}")
        if data.get("limitation"):
            st.write(f"局限性：{data['limitation']}")


def render_parsed_product(results: dict) -> None:
    parsed = results.get("parsed_product")
    if not parsed:
        return

    with st.expander("链接解析结果", expanded=True):
        c1, c2, c3 = st.columns(3)
        c1.write(f"解析来源：{parsed.get('source') or '未知'}")
        c2.write(f"SKU：{parsed.get('sku') or '未识别'}")
        c3.write(f"标题：{parsed.get('title') or '未获取'}")
        st.write("解析出的分析字段")
        st.json(parsed.get("product_info", {}), expanded=False)
        for note in parsed.get("notes", []):
            st.caption(note)


def render_analysis(results: dict, assistant: ProductSelectionAssistant, category_for_recommend: str) -> None:
    if "error" in results:
        st.error(results["error"])
        render_parsed_product(results)
        if results.get("suggested_categories"):
            st.write("可选三级分类示例：")
            st.write("、".join(results["suggested_categories"]))
        return

    render_parsed_product(results)

    summary = results["input_summary"]
    st.subheader("输入与匹配")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("单位价格", summary["目标单位价格"])
    col2.metric("匹配范围", summary["匹配范围"])
    col3.metric("样本量", summary["用于分析的样本量"])
    col4.metric("品类输入", summary["品类输入"])

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["市场定位", "价格竞争力", "机会与风险", "竞品对比", "语料洞察"])

    with tab1:
        data = results["market_position"]
        if "info" in data:
            st.warning(data["info"])
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("市场定位", data["市场定位"])
            c2.metric("相对均价", data["相对均价"])
            c3.metric("价格百分位", data["价格百分位"])
            render_dict_block(data)
        render_explainability(data)

    with tab2:
        data = results["competitiveness"]
        if "info" in data:
            st.warning(data["info"])
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("竞争力评分", data["竞争力评分"])
            c2.metric("可比商品数量", data["可比商品数量"])
            c3.metric("竞争力排名", data["竞争力排名"])
            render_dict_block(data)
        render_explainability(data)

    with tab3:
        data = results["opportunities"]
        if "价格分布" in data:
            dist = pd.DataFrame(
                [{"价格带": key, "商品数": value} for key, value in data["价格分布"].items()]
            )
            st.bar_chart(dist.set_index("价格带"))
        render_dict_block(data)
        render_explainability(data)

    with tab4:
        competitors = pd.DataFrame(results["competitive_comparison"])
        if competitors.empty:
            st.warning("未找到可展示的竞品。")
        else:
            st.dataframe(competitors, width="stretch", hide_index=True)

    with tab5:
        data = results["corpus_insights"]
        left, right = st.columns(2)
        with left:
            st.write("常见品牌")
            st.json(data.get("常见品牌", {}), expanded=False)
            st.write("常见口味")
            st.json(data.get("常见口味", {}), expanded=False)
        with right:
            st.write("常见包装")
            st.json(data.get("常见包装", {}), expanded=False)
            st.write("高频关键词")
            st.json(data.get("高频关键词", {}), expanded=False)
        render_explainability(data)

    st.subheader("同范围选品参考")
    try:
        recommendation = assistant.recommend_by_category(category_for_recommend, top_n=10)
        if not recommendation.empty:
            st.dataframe(recommendation, width="stretch", hide_index=True)
    except Exception as exc:
        st.warning(f"推荐列表生成失败：{exc}")


def main() -> None:
    assistant = get_assistant()
    input_modes = ["商品链接自动解析", "手动输入商品信息"]
    query_mode = str(st.query_params.get("mode", ""))
    query_mode_map = {"link": input_modes[0], "manual": input_modes[1]}
    if query_mode in query_mode_map:
        st.session_state["single_product_input_mode"] = query_mode_map[query_mode]
    elif "single_product_input_mode" not in st.session_state:
        st.session_state["single_product_input_mode"] = input_modes[0]

    st.title("零食选品智能助手")
    st.caption(f"数据底座：{assistant.data_path}；有效结构化商品 {len(assistant._valid_market_df()):,} 条")

    st.subheader("选择输入方式")
    mode_left, mode_right = st.columns(2)
    with mode_left:
        if st.button(
            "粘贴商品链接自动解析",
            type="primary" if st.session_state["single_product_input_mode"] == input_modes[0] else "secondary",
            width="stretch",
        ):
            st.session_state["single_product_input_mode"] = input_modes[0]
            st.rerun()
        st.caption("适合直接粘贴京东/淘宝链接、分享文案或 SKU；系统会优先按 SKU 命中本地数据。")
    with mode_right:
        if st.button(
            "手动输入商品信息",
            type="primary" if st.session_state["single_product_input_mode"] == input_modes[1] else "secondary",
            width="stretch",
        ):
            st.session_state["single_product_input_mode"] = input_modes[1]
            st.rerun()
        st.caption("适合链接无法解析、没有链接，或需要直接评估一个设想中的商品方案。")

    render_selection_quality_summary(load_selection_quality_report(file_mtime_ns(QUALITY_REPORT_PATH)))
    if "随机销量" in assistant.df.columns:
        st.info(
            "当前语料已切换为整合版本：商品主表、结构化抽取、京东评论/差评与慢慢买历史价已按 SKU 汇总；"
            "其中“随机销量”仅作为相对热度代理，不代表真实精确销量。"
        )

    with st.sidebar:
        st.header("输入方式")
        sidebar_mode = st.radio(
            "选择分析入口",
            input_modes,
            index=input_modes.index(st.session_state["single_product_input_mode"]),
            horizontal=False,
            key="single_product_input_mode_sidebar",
        )
        if sidebar_mode != st.session_state["single_product_input_mode"]:
            st.session_state["single_product_input_mode"] = sidebar_mode
            st.rerun()
        input_mode = st.session_state["single_product_input_mode"]

        submitted = False
        product_url = ""
        uploaded_screenshot = None
        fallback_info: dict = {}
        product_info: dict = {}

        if input_mode == "商品链接自动解析":
            st.caption(
                "淘宝/京东可能要求登录或触发风控。系统会先用 Playwright 打开详情页并复用 Cookie；"
                "失败时会自动降级到手动标题、价格重量和截图 OCR 兜底。"
            )
            product_url = st.text_input(
                "商品链接 / 分享文案 / SKU",
                placeholder="例如：https://item.jd.com/100012345678.html，或粘贴淘宝/京东分享文案",
            )
            with st.expander("可选补充字段"):
                st.caption(
                    "网页价格、重量或标题解析失败时，这些字段会作为兜底。"
                    "建议至少补充：商品标题、售价、规格重量。"
                )
                title_fallback = st.text_area(
                    "商品标题",
                    value="",
                    placeholder="例如：三只松鼠零食大礼包 520节日送男女朋友礼物整箱解馋休闲食品小吃",
                    height=80,
                )
                category_fallback = st.text_input("品类/三级分类", value="")
                price_fallback = st.text_input("售价（元）", value="")
                weight_fallback = st.text_input("规格重量（克）", value="")
                brand_fallback = st.text_input("品牌", value="")
                flavor_fallback = st.text_input("口味", value="")
                package_fallback = st.text_input("包装", value="")
                uploaded_screenshot = st.file_uploader(
                    "商品截图 OCR（可选）",
                    type=["png", "jpg", "jpeg", "webp"],
                    help="上传详情页截图、商品主图或规格图。系统会用 Tesseract 尝试识别图片文字。",
                )

            fallback_info = {
                "title": title_fallback.strip() or None,
                "category": category_fallback.strip() or None,
                "price": parse_optional_float(price_fallback),
                "weight_g": parse_optional_float(weight_fallback),
                "brand": brand_fallback.strip() or None,
                "flavor": flavor_fallback.strip() or None,
                "package_type": package_fallback.strip() or None,
            }
            submitted = st.button("解析链接并分析", type="primary", width="stretch")
        else:
            categories = assistant.available_categories()
            category_mode = st.radio("品类输入方式", ["选择三级分类", "手动输入关键词"], horizontal=False)
            if category_mode == "选择三级分类":
                default_index = categories.index("腰果") if "腰果" in categories else 0
                category = st.selectbox("三级分类", categories, index=default_index)
            else:
                category = st.text_input("品类关键词", value="坚果")

            price = st.number_input("预期售价（元）", min_value=0.01, value=55.80, step=1.0)
            weight_g = st.number_input("规格重量（克）", min_value=1.0, value=300.0, step=10.0)
            brand = st.text_input("品牌（可选）", value="良品铺子")
            title = st.text_area("商品标题（可选）", value="", height=70)
            flavor = st.text_input("口味（可选）", value="蟹黄味")
            package_type = st.text_input("包装（可选）", value="袋装")
            product_info = {
                "category": category,
                "weight_g": weight_g,
                "price": price,
                "brand": brand or None,
                "title": title or None,
                "flavor": flavor or None,
                "package_type": package_type or None,
            }
            submitted = st.button("开始分析", type="primary", width="stretch")

    if not submitted:
        st.info(
            "默认使用链接/分享文案入口。若淘宝/京东要求登录，请在自动弹出的浏览器中登录一次；"
            "Cookie 会复用。若仍无法解析，请补充商品标题、售价、重量，或上传商品截图进行 OCR。"
        )
        with st.expander("使用说明", expanded=False):
            st.markdown(
                """
                1. **优先粘贴链接或分享文案**：系统会先识别 SKU、分享标题，并尝试读取网页。
                2. **遇到登录/风控**：点击解析后会弹出一个 Playwright 浏览器窗口，请手动登录淘宝或京东；登录态会保存在本机，下次自动复用。
                3. **自动抓取失败**：在“可选补充字段”里填写商品标题、售价、规格重量，或上传商品截图做 OCR 识别。
                4. **截图建议**：优先截商品标题、价格、规格参数区域，OCR 更容易识别出价格和重量。
                """
            )
        preview_cols = [
            "sku_text", "analysis_brand", "商品名称", "三级分类", "analysis_price",
            "analysis_weight_g", "unit_price", "flavor", "package_type", "keywords",
            "jd_review_nonempty", "jd_negative_nonempty", "mmb_lowest_price",
        ]
        preview = assistant.df[[col for col in preview_cols if col in assistant.df.columns]].head(20).rename(
            columns={
                "sku_text": "SKU",
                "analysis_brand": "品牌",
                "analysis_price": "现价",
                "analysis_weight_g": "重量_g",
                "unit_price": "单位价格_元每克",
                "flavor": "口味",
                "package_type": "包装",
                "jd_review_nonempty": "京东评论样本数",
                "jd_negative_nonempty": "京东差评样本数",
                "mmb_lowest_price": "历史低价",
            }
        )
        st.dataframe(preview, width="stretch", hide_index=True)
        return

    with st.spinner("正在解析并基于结构化语料分析..."):
        if input_mode == "商品链接自动解析":
            ocr_text = ""
            if uploaded_screenshot is not None:
                image_bytes = uploaded_screenshot.getvalue()
                ocr_text, ocr_note = assistant.extract_text_from_image_bytes(image_bytes)
                if ocr_text:
                    fallback_info["ocr_text"] = ocr_text
                st.caption(ocr_note)

            has_fallback = any(
                fallback_info.get(key)
                for key in ["title", "category", "price", "weight_g", "brand", "ocr_text"]
            )
            if not product_url.strip() and not has_fallback:
                st.error("请先输入商品链接/SKU，或至少补充商品标题、价格重量、截图 OCR 信息。")
                return
            results = assistant.analyze_product_url(product_url, fallback_info=fallback_info)
            parsed_info = results.get("parsed_product", {}).get("product_info", {})
            recommend_category = parsed_info.get("category") or fallback_info.get("category") or ""
        else:
            results = assistant.analyze_product(product_info)
            recommend_category = product_info["category"]

    render_analysis(results, assistant, recommend_category)


if __name__ == "__main__":
    main()
