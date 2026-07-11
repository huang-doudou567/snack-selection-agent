# 智能选品AI Agent

零食电商AI选品决策助手。核心能力：品类竞争分析、价格带空白点识别、选品策略推荐。

## 语言要求

与用户的所有互动都应使用中文，包括代码解释、错误消息、建议和计划输出。

## 技术栈

Claude Code + DeepSeek | LangChain Agent | DrissionPage（反检测内置） | 国内IP裸跑无代理 | CSV输出UTF-8 BOM

## 架构

```
Agent 推理层（Claude Code / LLM）
    ↕ SKILL.md 编排 + models.py 数据结构
Python 执行层（确定性脚本）
    ↕ JSON 磁盘解耦（corpus_cache/）
数据层（CSV + 实时爬取）
```

## 常用命令

```bash
# 依赖
pip install -r requirements.txt
playwright install chromium              # Playwright 首次运行需装浏览器内核

# 测试（unittest，唯一测试文件）
python -m unittest test_product_assistant           # 全部
python -m unittest test_product_assistant.ProductAssistantTest.test_analyze_product_with_structured_corpus  # 单个

# Streamlit 面板（端口见下方表格）
streamlit run home.py --server.port 8500

# 对话式 AI 助手（web-chat/，前后端一起起）
cd web-chat && npm install && npm run dev   # tsx server/index.ts + vite，默认 5173；先 cp .env.example .env 填 DEEPSEEK_API_KEY
```

## 代码架构（关键模块依赖）

单一 Python 包，无框架，模块间直接 import。理解全局的最短路径是这条依赖链：

```
models.py                    ← 数据契约：Evidence / RawProduct / SelectionAdvice / SelectionReport（dataclass）
   ↑
simple_price_compare.py      ← 核心：CSV 加载 + 比价/统计脏活（在 agent_tools 里以别名 app 导入）
   ↑
agent_tools.py               ← 6 个 Agent 工具，返回 models 里的 dataclass（不是字符串）；多 LLM 后端 claude→openai→deepseek
product_assistant.py         ← ProductSelectionAssistant 单品分析引擎（被 app.py 和测试直接用）
   ↑
Streamlit 面板：home.py / snack_strategy_app.py(matplotlib) / app.py / prompt_config.py / decision_tracker.py
```

- **推理层/执行层解耦**：Agent（LLM）只做场景识别与策略文字；Python 脚本做确定性计算。二者只通过 `models.py` 的 dataclass 交换数据 —— 改数据结构就改 `models.py`，别在两侧各写一份。
- **场景编排在 `SKILL.md`**，不在 Python 里：6 场景→工具组合→`assets/templates/*.md` 的映射是 Skill 层职责；`scene_prompts.json` 存各场景 System Prompt，由 `prompt_config.py`(8503) 在线编辑。
- **爬虫是独立一层**：`jd_*` / `mmb_*` 脚本各自可单独运行，产物落 CSV，与分析层通过磁盘 CSV 解耦，不被 import。DrissionPage 与 Playwright 两套并存（部分脚本两者都引），不是二选一。
- **数据 fallback 链**：`integrated_selection_products.csv` → `merged_products.csv` → `final_products.csv`，读不到再报错，绝不编造。

## 目录结构

```
C:\Users\HUAWEI\Documents\New project 2\
├── SKILL.md                         ← Claude Code Skill 入口（v2 新增）
├── models.py                        ← 结构化数据模型（v2 新增）
├── agent_tools.py                   ← Agent 工具集（v2 增强）
│
├── scripts/connectors/              ← 数据源统一接口（v2 新增）
│   └── base.py                      ← Connector ABC + SearchResult
├── scripts/corpus/
│   └── store.py                     ← JSON 持久化层（v2 新增）
│
├── assets/templates/                ← 6场景输出模板（v2 新增）
│   ├── clearout.md                  ← 清仓决策
│   ├── pick.md                      ← 选品蓝海
│   ├── benchmark.md                 ← 竞品对标
│   ├── promotion.md                 ← 促销策略
│   ├── negative_review.md           ← 差评归因
│   └── sourcing.md                  ← 月度进货
│
├── corpus_cache/                    ← 运行时产物（gitignored）
│
├── home.py                          # Streamlit 统一入口
├── snack_strategy_app.py            # 选品策略面板
├── app.py                           # 单品智能分析
├── product_assistant.py             # 选品分析引擎
├── simple_price_compare.py          # 比价核心逻辑
│
├── integrated_selection_products.csv # 主商品表 13,400行
├── merged_products.csv               # 合并表 13,396行
├── price_history.csv                 # 慢慢买历史价格
│
├── jd_cdp_review_scraper.py         # 京东评论爬虫（DrissionPage）
├── mmb_cdp_price_history_crawler.py  # 慢慢买价格爬虫
├── crawler_quality_monitor.py        # 爬虫质量巡检
│
└── snapshots/                        # 周快照 + trend_timeseries.csv
```

## 爬取安全规则

- 间隔15-40秒随机（低频30-60秒），每30条休息15-20分钟
- 日上限：评论200条（20:00-23:00），价格100条（00:00-06:00），凌晨风控最松可同时补量
- 验证码→截图+暂停60秒→连续4次当天停止
- 断点续爬：crawled_items.csv / crawled_price_items.csv
- 慢慢买搜索间隔60-90秒，超时则切换接管浏览器模式
- 每商品最多100条评论

## DrissionPage要点

- 截图：`page.get_screenshot(path='x.png', full_page=True)` 不是 `screenshot`
- 启动：`ChromiumOptions().auto_port().set_user_data_path('./profile')`
- 加载：`page.get(url)` 不是 `goto` | 等待：`time.sleep()` 同步不是 async
- 不用CDP，不检测9222端口
- 反检测试：https://bot.sannysoft.com/

## Streamlit 面板端口

| 端口 | 面板 | 说明 |
|------|------|------|
| 8500 | home.py | 统一入口 + 数据仪表板 |
| 8501 | snack_strategy_app.py | 选品策略面板 |
| 8502 | app.py | 单品智能分析 |
| 8503 | prompt_config.py | 6场景 System Prompt 在线编辑 |
| 8504 | decision_tracker.py | 选品决策追踪 + 3月回看 |

## 对话式 AI 助手

`web-chat/` — SSE 流式聊天界面（基于 your-world-editor 架构复用）
```bash
cd web-chat
cp .env.example .env  # 填入 DEEPSEEK_API_KEY
npm run dev
```
浏览器访问 Vite 端口（默认 5173），直接对话做选品决策。

## 快照

每周一09:00自动执行，输出 snapshot + changes.md + 更新 trend_timeseries.csv

## 待办

- **P0**：慢慢买超时排查 | 验证DrissionPage反检测
- **P1**：去CDP依赖 | 京东验证码检测逻辑 | 评论→40% | 价格→20%
- **P2**：分类补全 | 评论去重 | 清理中间文件
- **v2**：补淘宝/拼多多 Connector | agent_tools 接入真实 LLM 测试 | templates 端到端跑通
