# 选品数据整合与质量报告

- 生成时间：2026-06-01 11:08:54
- 统一商品数：13,400
- 唯一 SKU 数：13,400
- 重复 SKU 数：0

## 数据源

- structured: 9,282 行；`C:\Users\HUAWEI\Documents\New project 2\structured_snacks_data_with_random_sales.csv`
- merged: 13,396 行；`C:\Users\HUAWEI\Documents\New project 2\merged_products.csv`
- details: 423 行；`C:\Users\HUAWEI\Documents\New project 2\数据\京东评论爬取\product_details.csv`
- reviews: 3,034 行；`C:\Users\HUAWEI\Documents\New project 2\数据\京东评论爬取\product_reviews.csv`
- negative: 1,227 行；`C:\Users\HUAWEI\Documents\New project 2\数据\京东评论爬取\negative_reviews.csv`
- checkpoint: 480 行；`C:\Users\HUAWEI\Documents\New project 2\数据\京东评论爬取\crawled_items.csv`
- price_history: 579 行；`C:\Users\HUAWEI\Documents\New project 2\price_history.csv`

## 覆盖率

- title: 13,400 / 13,400 (100.0%)
- brand: 13,400 / 13,400 (100.0%)
- category: 13,400 / 13,400 (100.0%)
- category_recognized: 13,400 / 13,400 (100.0%)
- price: 13,302 / 13,400 (99.3%)
- weight: 9,534 / 13,400 (71.2%)
- unit_price_valid: 9,432 / 13,400 (70.4%)
- flavor: 367 / 13,400 (2.7%)
- package_type: 78 / 13,400 (0.6%)
- jd_reviews: 423 / 13,400 (3.2%)
- jd_negative_reviews: 280 / 13,400 (2.1%)
- mmb_price_history: 319 / 13,400 (2.4%)

## 质量告警

- missing_sku: 0
- missing_title: 0
- missing_category: 0
- invalid_price: 98
- invalid_weight: 3,877
- extreme_price_over_1000: 31
- extreme_weight_over_10000g: 9
- duplicate_title_price_weight: 759

## 京东抓取状态

- success: 90
- access_blocked: 3
- captcha_timeout: 1

## 慢慢买历史价状态

- success: 339
- no_result: 220
- error: 20
