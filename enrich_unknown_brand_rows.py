# -*- coding: utf-8 -*-
"""Enrich unknown-brand rows in the integrated product table."""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


CSV_PATH = Path("integrated_selection_products.csv")

BRAND_ALIASES = [
    ("北京稻香村", "北京稻香村"),
    ("稻香村", "北京稻香村"),
    ("麻辣王子", "麻辣王子"),
    ("鲍师傅", "鲍师傅"),
    ("五芳斋", "五芳斋"),
    ("爸爸糖", "爸爸糖"),
    ("不二家", "不二家"),
    ("悠哈", "悠哈"),
    ("UHA", "悠哈"),
    ("乐事", "乐事"),
    ("Lay's", "乐事"),
    ("Lays", "乐事"),
    ("奥利奥", "奥利奥"),
    ("OREO", "奥利奥"),
    ("良品铺子", "良品铺子"),
    ("百草味", "百草味"),
    ("三只松鼠", "三只松鼠"),
    ("盐津铺子", "盐津铺子"),
    ("洽洽", "洽洽"),
    ("徐福记", "徐福记"),
    ("旺旺", "旺旺"),
    ("盼盼", "盼盼"),
    ("好丽友", "好丽友"),
    ("ORION", "好丽友"),
    ("德芙", "德芙"),
    ("Dove", "德芙"),
    ("士力架", "士力架"),
    ("费列罗", "费列罗"),
    ("Ferrero", "费列罗"),
    ("瑞士莲", "瑞士莲"),
    ("Lindt", "瑞士莲"),
    ("雀巢", "雀巢"),
    ("Nestle", "雀巢"),
    ("嘉士利", "嘉士利"),
    ("达利园", "达利园"),
    ("口水娃", "口水娃"),
    ("甘源", "甘源"),
    ("卫龙", "卫龙"),
    ("可比克", "可比克"),
    ("上好佳", "上好佳"),
    ("好想你", "好想你"),
    ("来伊份", "来伊份"),
    ("周黑鸭", "周黑鸭"),
    ("绝味", "绝味"),
    ("阿尔卑斯", "阿尔卑斯"),
    ("曼妥思", "曼妥思"),
    ("益达", "益达"),
    ("炫迈", "炫迈"),
    ("波力", "波力"),
    ("太平", "太平"),
    ("康师傅", "康师傅"),
    ("统一", "统一"),
    ("格力高", "格力高"),
    ("Glico", "格力高"),
    ("明治", "明治"),
    ("Meiji", "明治"),
    ("趣多多", "趣多多"),
    ("妙可蓝多", "妙可蓝多"),
    ("皇冠", "皇冠"),
    ("比比赞", "比比赞"),
    ("豪士", "豪士"),
    ("桃李", "桃李"),
    ("泓一", "泓一"),
    ("法丽兹", "法丽兹"),
    ("豪氏", "豪氏"),
]

FLAVOR_KEYWORDS = [
    "咸蛋黄", "得克萨斯烧烤", "奥尔良", "黑胡椒", "麻辣", "香辣", "甜辣", "辣卤", "烧烤", "番茄",
    "芝士", "抹茶", "巧克力", "牛奶", "奶油", "海盐", "蟹黄", "藤椒", "黑椒", "五香", "蜂蜜",
    "黄油", "椰香", "椰蓉", "草莓", "蓝莓", "芒果", "榴莲", "香草", "柠檬", "青柠", "酸奶",
    "红枣", "玫瑰", "桂花", "肉松", "卤味", "孜然", "蒜香", "山楂", "乌梅", "盐焗", "炭烤",
    "碳烤", "酱香", "原味",
]

SUBCATEGORY_PATTERNS = [
    ("夏威夷果", "坚果"),
    ("开心果", "坚果"),
    ("碧根果", "坚果"),
    ("巴旦木", "坚果"),
    ("腰果", "坚果"),
    ("核桃", "坚果"),
    ("混合坚果", "坚果"),
    ("每日坚果", "坚果"),
    ("坚果", "坚果"),
    ("夹心饼干", "饼干"),
    ("曲奇", "饼干"),
    ("威化", "饼干"),
    ("饼干", "饼干"),
    ("棒棒糖", "糖果"),
    ("软糖", "糖果"),
    ("奶糖", "糖果"),
    ("糖果", "糖果"),
    ("牛肉干", "肉干"),
    ("猪肉脯", "肉干"),
    ("肉脯", "肉干"),
    ("肉干", "肉干"),
    ("薯片", "薯片"),
    ("薯条", "薯片"),
    ("果冻布丁", "果冻"),
    ("果冻", "果冻"),
    ("布丁", "果冻"),
    ("蜜饯", "蜜饯"),
    ("梅子", "蜜饯"),
    ("话梅", "蜜饯"),
    ("果干", "蜜饯"),
    ("海苔", "海苔"),
    ("巧克力", "巧克力"),
    ("蛋糕", "糕点"),
    ("糕点", "糕点"),
    ("点心", "糕点"),
    ("蛋黄酥", "糕点"),
    ("凤梨酥", "糕点"),
    ("沙琪玛", "糕点"),
    ("粽子", "粽子"),
    ("月饼", "月饼"),
    ("辣条", "辣条/面筋"),
    ("面筋", "辣条/面筋"),
    ("豆干", "豆干"),
    ("鸭脖", "卤味肉类"),
    ("鸭肉", "卤味肉类"),
    ("鸡肉", "卤味肉类"),
    ("鱿鱼", "海味零食"),
    ("鱼干", "海味零食"),
    ("瓜子", "炒货"),
    ("花生", "炒货"),
    ("麦片", "麦片"),
    ("爆米花", "膨化食品"),
]

GENERIC_PREFIXES = [
    "京东超市", "京东", "进口", "国产", "新货", "新品", "正宗", "休闲零食", "休闲食品",
    "零食", "食品", "送礼", "端午", "中秋", "年货", "礼盒装", "礼盒", "大礼包",
]


def clean_title(title: str) -> str:
    title = str(title or "").strip()
    title = re.sub(r"^[\s【\[]*(京东超市|京东自营|自营|官方旗舰店)[\s】\]]*", "", title)
    for prefix in GENERIC_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
    return title


def extract_brand(title: str) -> tuple[str, str]:
    text = clean_title(title)
    lower = text.lower()
    for pattern, brand in sorted(BRAND_ALIASES, key=lambda item: len(item[0]), reverse=True):
        if pattern.lower() in lower:
            return brand, "brand_dictionary"

    match = re.match(r"([A-Za-z][A-Za-z0-9'&.-]{1,18})", text)
    if match:
        return match.group(1), "leading_token"

    chinese = re.match(r"([\u4e00-\u9fff]{2,8})", text)
    if not chinese:
        return "", ""

    token = chinese.group(1)
    stop_words = [
        "休闲", "零食", "食品", "礼盒", "礼包", "混合", "坚果", "饼干", "糖果", "蜜饯",
        "薯片", "果冻", "蛋糕", "糕点", "肉干", "新鲜", "散装", "整箱",
    ]
    for stop in stop_words:
        pos = token.find(stop)
        if 0 < pos:
            token = token[:pos]
            break
    token = token[:4] if len(token) >= 4 else token
    return (token, "leading_feature") if len(token) >= 2 else ("", "")


def extract_flavor(title: str) -> str:
    found = []
    for keyword in FLAVOR_KEYWORDS:
        if keyword in title and keyword not in found:
            found.append(keyword)
    return "|".join(found[:4])


def extract_subcategory(title: str) -> str:
    for keyword, subcategory in SUBCATEGORY_PATTERNS:
        if keyword in title:
            return subcategory
    return ""


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(CSV_PATH)

    df = pd.read_csv(CSV_PATH, dtype=str, encoding="utf-8-sig").fillna("")
    if "子品类" not in df.columns:
        insert_at = df.columns.get_loc("三级分类") + 1 if "三级分类" in df.columns else len(df.columns)
        df.insert(insert_at, "子品类", "")
    if "口味" not in df.columns:
        insert_at = df.columns.get_loc("flavor") + 1 if "flavor" in df.columns else len(df.columns)
        df.insert(insert_at, "口味", "")

    unknown = df["品牌"].astype(str).str.strip().eq("未知品牌")
    before_unknown = int(unknown.sum())
    brand_updates = 0
    flavor_updates = 0
    subcategory_updates = 0
    method_counts: dict[str, int] = {}

    for idx, row in df.loc[unknown].iterrows():
        title = str(row.get("商品名称", ""))
        brand, method = extract_brand(title)
        flavor = extract_flavor(title)
        subcategory = extract_subcategory(title)

        if brand:
            df.at[idx, "品牌"] = brand
            if "brand_from_name" in df.columns and not str(df.at[idx, "brand_from_name"]).strip():
                df.at[idx, "brand_from_name"] = brand
            brand_updates += 1
            method_counts[method] = method_counts.get(method, 0) + 1
        if flavor:
            df.at[idx, "flavor"] = flavor
            df.at[idx, "口味"] = flavor
            flavor_updates += 1
        elif str(row.get("flavor", "")).strip() and not str(row.get("口味", "")).strip():
            df.at[idx, "口味"] = row.get("flavor", "")
        if subcategory:
            df.at[idx, "子品类"] = subcategory
            subcategory_updates += 1

    backup = CSV_PATH.with_name(f"{CSV_PATH.stem}.before_brand_enrich_{datetime.now():%Y%m%d_%H%M%S}.csv")
    shutil.copy2(CSV_PATH, backup)
    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")

    after_unknown = int(df["品牌"].astype(str).str.strip().eq("未知品牌").sum())
    print(f"file={CSV_PATH}")
    print(f"backup={backup}")
    print(f"rows={len(df)}")
    print(f"unknown_brand_before={before_unknown}")
    print(f"unknown_brand_after={after_unknown}")
    print(f"brand_updates={brand_updates}")
    print(f"brand_method_counts={method_counts}")
    print(f"flavor_updates={flavor_updates}")
    print(f"subcategory_updates={subcategory_updates}")
    print(df.loc[df["品牌"].astype(str).str.strip().ne("未知品牌"), ["品牌", "商品名称", "口味", "子品类"]].tail(12).to_string(index=False))


if __name__ == "__main__":
    main()
