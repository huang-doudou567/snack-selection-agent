# -*- coding: utf-8 -*-
"""第二遍：从仍为"未知品牌"的商品标题首词提取品牌名"""
import csv, re

path = r'C:\Users\HUAWEI\Documents\New project 2\integrated_selection_products.csv'

with open(path, 'r', encoding='utf-8-sig') as f:
    rows = list(csv.reader(f))

header = rows[0]
ncols = len(header)
col_brand, col_title, col_status = 0, 2, 21

# Pass 1: collect candidate brands from first token of unknown-brand titles
candidates = {}
for row in rows[1:]:
    while len(row) < ncols: row.append('')
    brand = row[col_brand].strip()
    title = row[col_title].strip() if col_title < len(row) else ''
    if brand != '未知品牌': continue
    if not title: continue
    # First token: chars before first space or digit or special char
    m = re.match(r'^([一-鿿\w]{2,8})', title)
    if m:
        token = m.group(1)
        candidates[token] = candidates.get(token, 0) + 1

# Filter: token must appear >= 3 times, not be a generic word
generic_words = {'零食', '休闲', '小吃', '特产', '食品', '美味', '新鲜', '健康', '精选',
                 '进口', '网红', '儿童', '孕妇', '老年', '低脂', '无糖', '有机',
                 '每日', '混合', '大礼包', '礼盒装', '散装', '批发', '包邮', '现货',
                 '热卖', '爆款', '促销', '特价', '新货', '年货', '节日', '送礼',
                 '麻辣', '五香', '原味', '香辣', '烧烤', '炭烤', '盐焗', '卤味',
                 '金榜', '步步高', '考试', '高考', '中考', '状元', '定胜', '逢考'}

new_brands = {}
for token, cnt in sorted(candidates.items(), key=lambda x: -x[1]):
    if cnt >= 3 and token not in generic_words and len(token) >= 2:
        new_brands[token] = cnt

print(f'发现候选品牌: {len(new_brands)} 个')
for t, c in sorted(new_brands.items(), key=lambda x: -x[1])[:30]:
    print(f'  [{c:4d}] {t}')

# Pass 2: apply new brands
new_brand_list = sorted(new_brands.keys(), key=len, reverse=True)
updated = 0
for i in range(1, len(rows)):
    row = rows[i]
    while len(row) < ncols: row.append('')
    brand = row[col_brand].strip()
    title = row[col_title].strip() if col_title < len(row) else ''
    if brand != '未知品牌': continue
    found = None
    for b in new_brand_list:
        if title.startswith(b):
            found = b
            break
    if found:
        row[col_brand] = found
        row[col_status] = 'brand_from_title_p2'
        updated += 1

# Count remaining unknown
remaining = sum(1 for row in rows[1:] if row[col_brand].strip() == '未知品牌')
total = len(rows) - 1
covered = total - remaining

with open(path, 'w', encoding='utf-8-sig', newline='') as f:
    csv.writer(f).writerows(rows)

print(f'')
print(f'=== 第二轮结果 ===')
print(f'本次提取: {updated}')
print(f'剩余未知: {remaining}')
print(f'总覆盖率: {covered}/{total} = {covered/total*100:.1f}%')
