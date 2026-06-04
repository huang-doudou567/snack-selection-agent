# 智能选品AI Agent

零食电商AI选品决策助手。核心能力：品类竞争分析、价格带空白点识别、选品策略推荐。

## 语言要求

与用户的所有互动都应使用中文，包括代码解释、错误消息、建议和计划输出。

## 技术栈

Claude Code + DeepSeek | DrissionPage（反检测内置） | 国内IP裸跑无代理 | CSV输出UTF-8 BOM

## 目录结构

```
C:\Users\HUAWEI\Documents\New project 2\
├── merged_products.csv              # 主商品表 13,396行 05-25
├── integrated_selection_products.csv # 筛选表 13,400行 05-27
├── snapshots/                       # 周快照 + trend_timeseries.csv
├── 数据/京东评论抓取/               # 评论CSV，覆盖率3%，crawled_items.csv断点
├── 数据/price_history.csv           # 慢慢买价格，覆盖率2.1%，crawled_price_items.csv断点
├── jd_login.py / jd_cdp_review_scraper.py / mmb_price_history_batch.py  # DrissionPage版爬虫
├── .jd_playwright_profile/          # 京东登录态
└── .mmb_playwright_profile/         # 慢慢买登录态
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
