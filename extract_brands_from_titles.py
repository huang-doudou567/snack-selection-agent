# -*- coding: utf-8 -*-
"""从商品标题提取品牌名，填充 integrated_selection_products.csv 的品牌列"""
import csv, re, shutil
from collections import Counter

path = r'C:\Users\HUAWEI\Documents\New project 2\integrated_selection_products.csv'
bak = path + '.bak_20260701'

shutil.copy2(path, bak)
print('backup:', bak)

BRANDS = sorted(set([
    '良品铺子', '三只松鼠', '百草味', '洽洽', '来伊份', '华味亨',
    '费列罗', '德芙', '好时', '不二家', '溜溜梅', '周黑鸭',
    '好丽友', '卡乐比', '达利园', '奇多', '五芳斋', '天喔',
    '张飞牛肉', '健达', '麻辣王子', '卫龙', '盼盼', '有友',
    '徐福记', '上好佳', '盐津铺子', '甘源', '口水娃', '沃隆',
    '雀巢', '格力高', '乐事', '旺旺', '喜之郎', '亲亲',
    '无穷', '劲仔', '金锣', '双汇', '雨润', '煌上煌',
    '科尔沁', '棒棒娃', '老川东', '牛头牌', '蒙牛', '伊利',
    '光明', '君乐宝', '妙可蓝多', '百吉福',
    '稻香村', '知味观', '沈大成', '杏花楼', '广州酒家', '唐饼家',
    '元朗', '嘉顿', '康师傅', '统一', '今麦郎',
    '奥利奥', '趣多多', '闲趣', '太平', '达能',
    '百醇', '百力滋', '百奇', '脆脆鲨', '闲趣',
    '果园老农', '楼兰蜜语', '西域美农', '真心', '徽记', '黄飞红',
    '绝味', '久久丫', '步-步', '万般宜', '果园老农',
    '德芙', '费列罗', '好时', '不二家', '健达',
    '乐事', '格力高', '上好佳', '卡乐比', '奇多',
    '旺旺', '达利园', '好丽友', '盼盼', '亲亲', '喜之郎',
    '无穷', '劲仔', '有友', '味巴哥',
    '张飞牛肉', '棒棒娃', '科尔沁', '牛头牌', '蒙牛', '伊利', '光明',
    '沈大成', '知味观', '五芳斋', '稻香村', '杏花楼',
    '百草味', '洽洽', '三只松鼠', '良品铺子', '来伊份',
    '华味亨', '溜溜梅', '天喔', '周黑鸭', '盐津铺子', '甘源',
    '口水娃', '沃隆', '味巴哥', '百宝库', '嘟赴', '鲜丰春', '巧鲜尝',
    '邵福斋', '楼兰蜜语', '西域美农', '果园老农', '徽记',
    '广州酒家', '唐饼家', '元朗', '嘉顿',
    '妙可蓝多', '百吉福', '君乐宝', '新希望',
    '趣多多', '奥利奥', '百醇', '百力滋', '百奇', '脆脆鲨',
    '康师傅', '统一', '今麦郎', '双汇', '金锣', '雨润',
    '科尔沁', '煌上煌', '绝味', '久久丫',
    '老川东', '棒棒娃', '牛头牌',
    '劲仔', '无穷', '有友', '周黑鸭',
    '卫龙', '麻辣王子',
    '黄飞红', '真心', '徽记', '果园老农',
]), key=len, reverse=True)
print(f'dict: {len(BRANDS)} brands')

def extract_brand(title):
    if not title: return None
    m = re.search(r'「(.+?)」', title)
    if m: return m.group(1)
    m = re.search(r'[（(](.+?)[）)]', title)
    if m:
        inner = m.group(1)
        if len(inner) <= 10 and not re.search(r'\d', inner):
            return inner
    for b in BRANDS:
        if title.startswith(b):
            return b
    for b in BRANDS:
        if b in title[:20]:
            return b
    for b in BRANDS:
        if b in title:
            return b
    return None

with open(path, 'r', encoding='utf-8-sig') as f:
    rows = list(csv.reader(f))

header = rows[0]
ncols = len(header)
col_brand, col_title, col_brand_from, col_status = 0, 2, 14, 21

updated = 0
stats = Counter()

for i in range(1, len(rows)):
    row = rows[i]
    while len(row) < ncols: row.append('')

    brand = row[col_brand].strip()
    title = row[col_title].strip() if col_title < len(row) else ''

    if brand and brand != '未知品牌' and '页面的连接' not in brand and '版本:' not in brand and 'screenshot=' not in brand:
        stats['already_has_brand'] += 1
        continue

    ext = extract_brand(title)
    if ext:
        row[col_brand] = ext
        row[col_brand_from] = ext
        row[col_status] = 'brand_from_title'
        updated += 1
        stats['extracted'] += 1
    else:
        stats['failed'] += 1

with open(path, 'w', encoding='utf-8-sig', newline='') as f:
    csv.writer(f).writerows(rows)

total = len(rows) - 1
covered = stats['already_has_brand'] + updated
print(f'total: {total}')
print(f'already: {stats["already_has_brand"]}')
print(f'extracted: {updated}')
print(f'failed: {stats["failed"]}')
print(f'coverage: {covered}/{total} = {covered/total*100:.1f}%')
