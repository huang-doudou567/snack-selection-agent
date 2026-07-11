# -*- coding: utf-8 -*-
"""场景 System Prompt 配置页 — streamlit run prompt_config.py --server.port 8503"""
import json
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Prompt 配置", page_icon="⚙️", layout="wide")

BASE = Path(__file__).resolve().parent
PROMPTS_FILE = BASE / "scene_prompts.json"

# ── 加载 ──
def load_prompts():
    if PROMPTS_FILE.exists():
        return json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
    return {}

def save_prompts(data):
    PROMPTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    load_prompts()

st.title("⚙️ 场景 System Prompt 配置")
st.caption("编辑完毕后点击保存即生效，无需重启。")

prompts = load_prompts()

tabs = st.tabs([
    "🎯 选品 pick",
    "📦 清仓 clearout",
    "📊 竞品对标 benchmark",
    "💰 促销 promotion",
    "😡 差评归因 negative_review",
    "🛒 月度进货 sourcing",
])

scene_ids = ["pick", "clearout", "benchmark", "promotion", "negative_review", "sourcing"]

for i, scene_id in enumerate(scene_ids):
    with tabs[i]:
        data = prompts.get(scene_id, {"name": scene_id, "description": "", "prompt": ""})
        st.text_input("场景名", value=data.get("name", scene_id), key=f"{scene_id}_name")
        st.text_input("描述", value=data.get("description", ""), key=f"{scene_id}_desc")
        new_prompt = st.text_area(
            "System Prompt",
            value=data.get("prompt", ""),
            height=300,
            key=f"{scene_id}_prompt",
            help="编辑 System Prompt。保存后立即生效。",
        )
        if st.button(f"💾 保存「{data.get('name', scene_id)}」", key=f"save_{scene_id}"):
            if scene_id not in prompts:
                prompts[scene_id] = {}
            prompts[scene_id]["name"] = st.session_state[f"{scene_id}_name"]
            prompts[scene_id]["description"] = st.session_state[f"{scene_id}_desc"]
            prompts[scene_id]["prompt"] = new_prompt
            save_prompts(prompts)
            st.success(f"「{data.get('name', scene_id)}」已保存 ✅")
            st.rerun()
