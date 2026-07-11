# -*- coding: utf-8 -*-
"""选品决策追踪器 — 记录每次选品决策，标记三个月后回看。

运行: streamlit run decision_tracker.py --server.port 8504
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="决策记录", page_icon="📋", layout="wide")

BASE = Path(__file__).resolve().parent
DECISIONS_FILE = BASE / "selection_decisions.csv"

COLUMNS = [
    "决策时间", "场景", "品类", "品牌", "建议摘要",
    "用户选择", "置信度", "预期效果", "实际结果",
    "偏差分析", "回看日期", "已回看",
]

# ── 读写 ──
def load_decisions():
    if not DECISIONS_FILE.exists():
        return []
    rows = []
    with open(DECISIONS_FILE, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def save_decisions(rows):
    with open(DECISIONS_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            cleaned = {k: row.get(k, "") for k in COLUMNS}
            writer.writerow(cleaned)

# ── UI ──
st.title("📋 选品决策追踪")
st.caption("记录每次选品决策，三个月后回看——实际结果是否和预期一致？")

decisions = load_decisions()

# 统计
total = len(decisions)
reviewed = sum(1 for d in decisions if d.get("已回看") == "是")
pending_review = sum(
    1 for d in decisions
    if d.get("已回看") != "是"
    and d.get("回看日期")
    and d["回看日期"] <= datetime.now().strftime("%Y-%m-%d")
)

c1, c2, c3 = st.columns(3)
c1.metric("总决策", total)
c2.metric("待回看（已到期）", pending_review, delta=None if pending_review == 0 else f"⚠️ {pending_review}条需关注")
c3.metric("已回看", reviewed, delta=None if total == 0 else f"{reviewed/total*100:.0f}%" if total > 0 else "")

st.divider()

# ── 新增决策表单 ──
with st.expander("➕ 新增决策记录", expanded=False):
    with st.form("new_decision"):
        c1, c2, c3 = st.columns(3)
        with c1:
            scene = st.selectbox("场景", ["选品", "清仓", "竞品对标", "促销策略", "差评归因", "月度进货"])
            category = st.text_input("品类", placeholder="坚果")
            brand = st.text_input("品牌", placeholder="良品铺子")
        with c2:
            advice = st.text_area("建议摘要", placeholder="Agent 给出的核心建议", height=100)
            choice = st.text_input("用户选择", placeholder="采纳 / 部分采纳 / 拒绝")
        with c3:
            expected = st.text_area("预期效果", placeholder="预期的销量/利润变化", height=100)
            confidence = st.select_slider("置信度", options=["低", "中", "高"])

        review_date = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")
        submitted = st.form_submit_button("💾 保存决策")
        if submitted:
            decisions.append({
                "决策时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "场景": scene,
                "品类": category,
                "品牌": brand,
                "建议摘要": advice,
                "用户选择": choice,
                "置信度": confidence,
                "预期效果": expected,
                "实际结果": "",
                "偏差分析": "",
                "回看日期": review_date,
                "已回看": "否",
            })
            save_decisions(decisions)
            st.success(f"决策已记录。回看日期：{review_date}（3个月后）")
            st.rerun()

# ── 决策列表 ──
st.subheader(f"📋 所有决策记录")

if not decisions:
    st.info("暂无决策记录。使用上方表单记录第一条。")
else:
    for i, d in enumerate(reversed(decisions)):
        idx = len(decisions) - 1 - i
        is_overdue = (
            d.get("已回看") != "是"
            and d.get("回看日期")
            and d["回看日期"] <= datetime.now().strftime("%Y-%m-%d")
        )
        bg = "#fff8e1" if is_overdue else "#fff"

        with st.container():
            cols = st.columns([3, 1, 1, 1])
            with cols[0]:
                st.markdown(
                    f"{'⚠️ ' if is_overdue else ''}**{d.get('品类', '?')}** · {d.get('品牌', '?')} · {d.get('场景', '?')}  "
                    f"<small style='color:#999'>{d.get('决策时间', '?')}</small>",
                    unsafe_allow_html=True,
                )
                if d.get("建议摘要"):
                    st.caption(f"建议：{d['建议摘要'][:120]}")
                if d.get("用户选择"):
                    st.caption(f"选择：{d['用户选择']}")
            with cols[1]:
                st.metric("置信度", d.get("置信度", "?"))
                if d.get("回看日期"):
                    st.caption(f"回看：{d['回看日期']}")
            with cols[2]:
                if d.get("已回看") == "是":
                    st.success("✅ 已回看")
                elif is_overdue:
                    st.warning("⚠️ 待回看")
                else:
                    st.info("📅 等待中")

            # 回看表单
            if d.get("已回看") != "是" and is_overdue:
                with st.expander("🔍 回看此决策", expanded=False):
                    with st.form(f"review_{idx}"):
                        actual = st.text_area("实际结果", value=d.get("实际结果", ""), placeholder="实际发生了什么？", key=f"actual_{idx}")
                        deviation = st.text_area("偏差分析", value=d.get("偏差分析", ""), placeholder="为什么和预期不同？什么因素没考虑到？", key=f"dev_{idx}")
                        if st.form_submit_button("✅ 标记已回看"):
                            decisions[idx]["实际结果"] = actual
                            decisions[idx]["偏差分析"] = deviation
                            decisions[idx]["已回看"] = "是"
                            save_decisions(decisions)
                            st.success("回看完成 ✅")
                            st.rerun()

        st.divider()
