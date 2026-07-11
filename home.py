# -*- coding: utf-8 -*-
"""智能选品AI Agent — 统一入口"""
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="智能选品AI Agent", page_icon="🛒", layout="centered")

BASE = Path(__file__).resolve().parent

def count_csv(path: Path) -> int:
    try:
        with open(path, encoding='utf-8-sig') as f:
            return sum(1 for _ in f) - 1
    except: return 0

JD_DIR = BASE / "数据" / "京东评论爬取"
all_p = count_csv(BASE / "merged_products.csv")
jd_r = count_csv(JD_DIR / "product_reviews.csv")
jd_p = count_csv(JD_DIR / "crawled_items.csv")
mmb_r = count_csv(BASE / "price_history.csv")
mmb_p = count_csv(BASE / "crawled_price_items.csv")

st.title("🛒 智能选品AI Agent")
st.caption("零食电商AI选品决策助手 — 品类竞争 · 价格空白点 · 选品推荐")

st.divider()

c1, c2, c3, c4 = st.columns(4)
c1.metric("商品总量", f"{all_p:,}")
c2.metric("京东评论", f"{jd_r:,} 条", f"{jd_p} 商品")
c3.metric("价格历史", f"{mmb_r:,} 条", f"{mmb_p} 商品")
c4.metric("评论覆盖率", f"{jd_p/all_p*100:.1f}%")

st.divider()
st.subheader("🚀 功能入口")

col1, col2 = st.columns(2)
with col1:
    st.markdown("""
    ## 📈 选品策略面板

    完整策略分析工具箱：
    - 品类竞争格局、品牌梯队
    - 单品性价比评分
    - 价格带空白点识别
    - 品牌组合推荐
    - 促销策略效果分析
    - 差评归因
    - 选品趋势预测
    - 数据质量诊断

    👉 **[打开策略面板](http://localhost:8501)**
    """)
with col2:
    st.markdown("""
    ## 🔍 单品智能分析

    粘贴京东/淘宝商品链接或手动输入：
    - 自动解析 SKU
    - 市场定位分析
    - 价格竞争力评分
    - 机会与风险评估
    - 同品类竞品对比
    - 语料洞察

    👉 **[打开单品分析](http://localhost:8502)**
    """)

st.divider()
st.subheader("🔧 工具 & 配置")

col3, col4, col5 = st.columns(3)
with col3:
    st.markdown("""
    ## ⚙️ Prompt 配置

    在线编辑 6 场景 System Prompt：
    - 选品 / 清仓 / 竞品对比
    - 促销策略 / 差评归因 / 月度进货
    - 保存即生效，无需重启

    👉 **[打开 Prompt 配置](http://localhost:8503)**
    """)
with col4:
    st.markdown("""
    ## 📋 决策追踪

    记录每次选品决策：
    - 建议 vs 实际选择
    - 预期 vs 实际效果
    - 3 个月后自动提醒回看
    - 偏差归因分析

    👉 **[打开决策追踪](http://localhost:8504)**
    """)
with col5:
    st.markdown("""
    ## 💬 AI 选品助手

    对话式选品决策：
    - 直接聊天提问
    - AI 实时分析品类数据
    - 流式回复体验
    - 基于真实 CSV 数据

    👉 **[打开 AI 助手](http://localhost:5173)**
    """)

st.divider()

import os, time as _t
def _m(p):
    try: return os.path.getmtime(p)
    except: return 0
latest = max(_m(BASE / "price_history.csv"), _m(JD_DIR / "product_reviews.csv"))
from datetime import datetime as _dt
st.caption(f"数据更新: {_dt.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M:%S')}")
