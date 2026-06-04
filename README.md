# 🛒 智能选品AI Agent

零食电商AI选品决策助手 — 品类竞争分析、价格带空白点识别、选品策略推荐。

## ✨ 核心能力

| 功能 | 说明 |
|------|------|
| 📊 品类竞争格局 | 品牌梯队分析、CR3/CR5 集中度、价格带热力图 |
| 🏷️ 单品性价比评分 | 基于单位价格、促销折扣、评论热度的综合评分 |
| 🎯 价格带空白点 | 品类内价格-需求分布，蓝海候选识别 |
| 🏗️ 品牌组合推荐 | 已有品牌覆盖分析 + 推荐引入品牌 |
| 💰 促销策略效果 | 优惠券/满减/特价效果对比 |
| 😡 差评归因 | 负面评价自动分类与根因分析 |
| 📈 选品趋势预测 | 需求热度 + 供给稀缺度 + 竞争度综合建模 |

## 🚀 快速启动

```bash
# 安装依赖
pip install streamlit pandas matplotlib numpy beautifulsoup4 requests DrissionPage playwright

# 启动数据看板
streamlit run home.py --server.port 8500          # 首页总览
streamlit run snack_strategy_app.py --server.port 8501   # 策略面板
streamlit run app.py --server.port 8502            # 单品分析
```

浏览器访问 `http://localhost:8500`

## 🕷️ 数据爬取

```bash
# 慢慢买历史价格
python mmb_cdp_price_history_crawler.py --limit 100

# 京东评论（需先登录）
python jd_login.py
python jd_cdp_review_scraper.py
```

## 📁 项目结构

```
├── home.py                    # 统一入口网页
├── snack_strategy_app.py      # 选品策略面板 (8501)
├── app.py                     # 单品智能分析 (8502)
├── product_assistant.py       # 选品分析引擎
├── agent_tools.py             # AI Agent 工具集
│
├── jd_cdp_review_scraper.py   # 京东评论爬虫 (DrissionPage)
├── jd_login.py                # 京东登录助手
├── jd_pw_crawler.py           # 京东评论 (Playwright)
├── mmb_cdp_price_history_crawler.py  # 慢慢买价格爬虫
├── mmb_manual_login.py        # 慢慢买登录助手
│
├── clean_snacks_data.py       # 数据清洗
├── integrate_selection_data.py # 数据整合
├── merge_jd_incremental.py    # 增量合并
│
├── merged_products.csv        # 主商品表 (~13K 商品)
├── integrated_selection_products.csv  # 选品筛选表
├── price_history.csv          # 历史价格数据
│
└── snapshots/                 # 周快照 + 趋势时序
```

## 🛠️ 技术栈

Streamlit · Matplotlib · Pandas · BeautifulSoup · DrissionPage · Playwright

## ⚠️ 注意事项

- 爬虫需消耗本机 Chrome 资源，建议夜间运行
- 京东有风控机制，高频访问可能触发 403
- 慢慢买查询间隔建议 ≥ 15 秒
