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

## 快照

每周一09:00自动执行，输出 snapshot + changes.md + 更新 trend_timeseries.csv

## 待办

- **P0**：慢慢买超时排查 | 验证DrissionPage反检测
- **P1**：去CDP依赖 | 京东验证码检测逻辑 | 评论→40% | 价格→20%
- **P2**：分类补全 | 评论去重 | 清理中间文件
- **v2**：补淘宝/拼多多 Connector | agent_tools 接入真实 LLM 测试 | templates 端到端跑通
