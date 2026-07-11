# -*- coding: utf-8 -*-
"""第三遍：提取所有剩余未知品牌——从标题首词提取，孤例也保留"""
import csv, re

path = r'C:\Users\HUAWEI\Documents\New project 2\integrated_selection_products.csv'

with open(path, 'r', encoding='utf-8-sig') as f:
    rows = list(csv.reader(f))

header = rows[0]
ncols = len(header)
col_brand, col_title, col_status = 0, 2, 21

# 真的不应该当品牌的垃圾词
garbage = {
    '零食', '休闲', '小吃', '特产', '食品', '美味', '新鲜', '健康',
    '精选', '进口', '网红', '散装', '批发', '包邮', '现货', '热卖',
    '爆款', '促销', '特价', '新货', '年货', '节日', '送礼',
    '麻辣', '五香', '原味', '香辣', '烧烤', '炭烤', '盐焗', '卤味',
    '每日', '混合', '大礼包', '礼盒装', '儿童', '孕妇', '老年',
    '低脂', '无糖', '有机', '素食', '清真', '清真食品',
    '金榜', '步步高', '考试', '高考', '中考', '状元', '定胜', '逢考',
    '金榜题名', '步步', '步步高升', '好柿', '喜',
    '日本', '日本进口', '韩国', '泰国', '马来西亚', '越南', '台湾',
    '2025年', '2026年', '2024年', '2023年',
    '新日期', '日期', '新鲜', '新款', '新品', '新品上市',
    '特浓', '特惠', '超值', '实惠', '划算', '包邮送到',
    '买', '送', '赠', '限时', '限量', '秒杀', '抢购', '清仓',
    '满', '减', '折', '降', '券', '领券', '立减', '到手',
    '品牌', '官方', '正品', '正版', '授权', '旗舰', '直营',
    '批发价', '工厂', '直销', '代工', '代发', '一件代发',
    '试吃', '尝鲜', '上新', '首发', '预售', '预定', '定制',
    '节日送礼', '年货礼盒', '圣诞', '万圣', '情人节', '母亲节', '父亲节',
    '端午', '中秋', '元宵', '春节', '新年', '过年', '元旦',
    '庆典', '开幕', '周年', '店庆', '大促',
    '学生', '上班族', '办公室', '熬夜', '追剧', '出游', '旅行',
    '便携', '小包装', '独立', '即食', '开袋', '方便', '速食',
    '甜蜜', '幸福', '快乐', '好吃', '美味', '可口', '香醇',
    '脆', '酥', '软', 'Q弹', '筋道', '松软', '醇香', '鲜香',
    '高蛋白', '低卡', '零卡', '零脂', '零糖', '无添加',
    '真空', '充氮', '锁鲜', '保鲜', '新鲜直达', '冷链',
    '网红爆款', '抖音同款', '小红书推荐',
    '备考', '考前', '冲刺', '复习', '考试', '上岸', '录取',
    '百日', '百日誓师', '誓师', '毕业', '开学', '成人',
    '状元', '状元糕', '定胜糕', '金榜题名', '逢考必过',
    'MEMBER', 'WiFi', 'WiFi登录', '会员', '版本',
    '登录', '注册', '验证', '手机', '下载', '安装',
    '零食', '休闲零食', '办公室零食',
    '嘴馋你', '脆香居', '阿Q熊', '阿Q', '邵福斋', '巧鲜尝', '百宝库',
    '嘟赴', '鲜丰春', '万般宜', '零食宅域', '零食', '小Q',
    '山姆', '零食很忙', '好特卖', '赵一鸣',
}

# 品牌候选词（从第一二遍提取的真实品牌中补充）
# 同时做一次全文品牌匹配（非前缀，标题任意位置含已知品牌）
KNOWN_BRANDS_IN_TITLE = [
    '良品铺子', '三只松鼠', '百草味', '洽洽', '来伊份', '华味亨',
    '费列罗', '德芙', '好时', '不二家', '溜溜梅', '周黑鸭',
    '好丽友', '卡乐比', '达利园', '五芳斋', '天喔', '卫龙',
    '麻辣王子', '盼盼', '有友', '徐福记', '上好佳', '盐津铺子',
    '甘源', '口水娃', '沃隆', '雀巢', '格力高', '乐事', '旺旺',
    '喜之郎', '亲亲', '无穷', '劲仔', '双汇', '金锣', '雨润',
    '煌上煌', '科尔沁', '棒棒娃', '老川东', '蒙牛', '伊利', '光明',
    '君乐宝', '妙可蓝多', '稻香村', '知味观', '沈大成', '广州酒家',
    '奥利奥', '趣多多', '闲趣', '达能', '百醇', '百力滋', '百奇',
    '好时', '不二家', '奇多', '张飞牛肉', '康师傅', '统一', '今麦郎',
    '良品铺子', '三只松鼠', '百草味', '来伊份', '盐津铺子',
    '煌上煌', '绝味', '久久丫', '费列罗', '健达', '好时',
    '卡乐比', '洽洽', '华味亨', '溜溜梅', '天喔', '有友',
    '德芙', '雀巢', '格力高', '乐事', '奇多',
    '西域美农', '楼兰蜜语', '果园老农', '真心', '黄飞红',
    '旺旺', '喜之郎', '亲亲', '徽记', '口水娃', '甘源',
    '沃隆', '劲仔', '无穷', '良品铺子', '卫龙', '麻辣王子',
    '唐饼家', '杏花楼', '元朗', '嘉顿', '盼盼',
    '妙可蓝多', '百吉福', '达利园', '好丽友', '徐福记',
    '双汇', '金锣', '雨润', '科尔沁', '棒棒娃', '老川东', '蒙牛', '伊利',
    '康师傅', '统一', '今麦郎',
]

KNOWN_BRANDS_IN_TITLE = sorted(set(KNOWN_BRANDS_IN_TITLE), key=len, reverse=True)

updated = 0
p3_brand = 0
p3_unknown = 0

for i in range(1, len(rows)):
    row = rows[i]
    while len(row) < ncols: row.append('')

    brand = row[col_brand].strip()
    title = row[col_title].strip() if col_title < len(row) else ''
    if brand != '未知品牌':
        continue

    found = None

    # Strategy 1: 全文搜索已知品牌（不限前缀）
    for b in KNOWN_BRANDS_IN_TITLE:
        if b in title:
            found = b
            break

    # Strategy 2: 标题首词提取
    if not found and title:
        m = re.match(r'^([一-鿿A-Za-z0-9·]+)', title)
        if m:
            token = m.group(1)
            if (len(token) >= 2 and len(token) <= 15
                and token not in garbage
                and not re.match(r'^\d{4}', token)  # 不以年份开头
                and not re.match(r'^[A-F0-9]{6,}', token)  # 不是纯HEX
                ):
                found = token

    if found:
        row[col_brand] = found
        row[col_status] = 'brand_from_title_p3'
        updated += 1
    else:
        p3_unknown += 1

with open(path, 'w', encoding='utf-8-sig', newline='') as f:
    csv.writer(f).writerows(rows)

total = len(rows) - 1
remaining = sum(1 for row in rows[1:] if row[col_brand].strip() == '未知品牌')
covered = total - remaining

print(f'第三轮提取: {updated}')
print(f'剩余未知: {remaining}')
print(f'总覆盖率: {covered}/{total} = {covered/total*100:.1f}%')

# Show sample of what became brands
new_brands = {}
for row in rows[1:]:
    b = row[col_brand].strip()
    if row[col_status] == 'brand_from_title_p3':
        new_brands[b] = new_brands.get(b, 0) + 1

print(f'\n第三轮新增品牌数: {len(new_brands)}')
for b, c in sorted(new_brands.items(), key=lambda x: -x[1])[:30]:
    print(f'  [{c:4d}] {b}')

# Show what's still unknown (sample)
unknown_samples = []
for row in rows[1:]:
    if row[col_brand].strip() == '未知品牌' and len(unknown_samples) < 10:
        unknown_samples.append(row[col_title][:60])
print(f'\n仍为未知品牌 样本:')
for t in unknown_samples:
    print(f'  {t}')
