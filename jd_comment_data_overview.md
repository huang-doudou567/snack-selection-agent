# 京东评论数据总览

生成时间: 2026-05-22 15:16:47 +08:00

## 运行状态

- `jd_cdp_review_scraper.py` 当前未运行
- `http://127.0.0.1:9222` 已不可达
- Windows 启动文件夹和任务计划中未发现京东爬虫相关残留入口
- 仓库内未发现会自动拉起京东评论爬虫的独立定时任务配置

## 数据文件汇总

| 文件 | 行数 | 主要字段 | 备注 |
| --- | ---: | --- | --- |
| `数据/京东评论爬取/product_details.csv` | 299 | `item_id`, `title`, `shop_name`, `category`, `review_count`, `好评率`, `评价标签`, `产地`, `保质期`, `配料表`, `规格`, `crawl_time` | 商品详情表，`item_id` 去重后 299 条 |
| `数据/京东评论爬取/product_reviews.csv` | 1851 | `item_id`, `title`, `nickname`, `score`, `date`, `sku`, `content`, `like_count`, `crawl_time` | 评论表，`item_id` 去重后 297 个商品，评论内容去重后约 905 条 |
| `数据/京东评论爬取/negative_reviews.csv` | 739 | `item_id`, `title`, `content`, `star_level`, `crawl_time` | 差评表，`item_id` 去重后 175 个商品，评论内容去重后约 432 条 |
| `数据/京东评论爬取/crawled_items.csv` | 339 | `item_id`, `title`, `detail_url`, `status`, `review_count`, `reviews_count`, `negative_reviews_count`, `comment_card_count`, `comment_selector`, `has_bad_filter_text`, `has_good_rate_text`, `error`, `crawl_time` | 抓取检查点，`item_id` 去重后 339 条 |

## 现状判断

- 数据是可续跑的，当前 resume 依据仍是 `数据/京东评论爬取/crawled_items.csv`
- 这次已主动停止 Chrome 9222 会话，因此不会继续自动抓取
- 代码里保留的是手动启动 CDP 的爬虫入口，不是系统级自动启动

