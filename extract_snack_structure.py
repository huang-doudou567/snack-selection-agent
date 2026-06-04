# -*- coding: utf-8 -*-
"""
商品名称结构化关键词提取

默认读取桌面的 cleaned_snacks_data.csv，生成 structured_snacks_data.csv。
也可以通过命令行指定输入输出：
    python extract_snack_structure.py --input "C:\\path\\cleaned_snacks_data.csv" --output "C:\\path\\structured_snacks_data.csv"
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import jieba
import jieba.posseg as pseg
import pandas as pd


FLAVOR_WORDS = [
    "蟹黄味", "蟹黄",
    "盐焗味", "盐焗",
    "奶油味", "奶油",
    "五香味", "五香",
    "麻辣味", "麻辣",
    "原味",
    "蜂蜜味", "蜂蜜",
    "蒜香味", "蒜香",
    "烧烤味", "烧烤",
    "香辣味", "香辣",
    "甜辣味", "甜辣",
    "黑胡椒味", "黑胡椒",
    "海盐味", "海盐",
    "奶香味", "奶香",
    "巧克力味", "巧克力",
    "草莓味", "草莓",
    "抹茶味", "抹茶",
]

GIFT_WORDS = [
    "送礼", "礼盒", "礼包", "礼品", "送人", "礼物", "赠品", "年货", "春节",
    "中秋", "端午", "节日", "福利", "团购", "公司采购", "走亲戚", "长辈",
]

PACKAGE_PATTERNS = [
    ("礼盒", r"礼盒装|礼品盒|礼盒"),
    ("礼包", r"大礼包|礼包|礼袋"),
    ("独立包装", r"独立小包装|独立小包|独立包装|小包装"),
    ("罐装", r"罐装|听装|铁罐|塑料罐|[0-9一二两三四五六七八九十百千万]+罐"),
    ("袋装", r"袋装|[0-9一二两三四五六七八九十百千万]+袋"),
    ("桶装", r"桶装|[0-9一二两三四五六七八九十百千万]+桶|[0-9一二两三四五六七八九十百千万]+筒"),
    ("箱装", r"箱装|整箱|[0-9一二两三四五六七八九十百千万]+箱|盒装|[0-9一二两三四五六七八九十百千万]+盒"),
    ("小包装", r"[0-9一二两三四五六七八九十百千万]+包|小包"),
]

UNIT_PATTERN = r"(?:kg|KG|Kg|kG|公斤|千克|斤|g|G|克)"
QUANTITY_WORDS = "袋包罐盒箱桶筒听瓶枚粒个份条款"
CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}

STOP_WORDS = {
    "的", "了", "和", "与", "是", "在", "及", "或", "等", "新款", "官方", "旗舰",
    "旗舰店", "京东", "自营", "包邮", "满减", "券", "优惠", "促销", "特价", "热卖",
    "组合", "混合", "休闲", "食品", "零食", "小吃", "解馋", "健康", "早餐", "下午茶",
    "实发", "净重", "共", "约", "装", "买", "送", "款", "袋", "包", "罐", "盒",
    "箱", "桶", "筒", "克", "公斤", "千克", "斤", "g", "kg", "G", "KG",
}


def normalize_text(value: Any) -> str:
    """统一空格、全半角和常见标点，降低正则匹配难度。"""
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("×", "x").replace("X", "x")
    text = re.sub(r"[，、；;]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_csv_robust(path: Path) -> tuple[pd.DataFrame, str]:
    """自动尝试常见中文 CSV 编码。"""
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"无法识别 CSV 编码：{path}") from last_error


def cn_to_int(token: str) -> int | None:
    """支持一到数千级别的中文数字转换，失败返回 None。"""
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)

    total = 0
    section = 0
    number = 0
    seen = False
    for char in token:
        if char in CN_DIGITS:
            number = CN_DIGITS[char]
            seen = True
        elif char in CN_UNITS:
            unit = CN_UNITS[char]
            seen = True
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                if number == 0:
                    number = 1
                section += number * unit
            number = 0
        else:
            return None
    return total + section + number if seen else None


def normalize_spec_number(token: str) -> str:
    value = cn_to_int(token)
    return str(value) if value is not None else token


def unit_to_grams(value: str | float, unit: str) -> float:
    number = float(value)
    unit_lower = unit.lower()
    if unit_lower == "kg" or unit in {"公斤", "千克"}:
        return number * 1000
    if unit == "斤":
        return number * 500
    return number


def clean_weight_number(value: float | None) -> float | None:
    if value is None or math.isnan(value):
        return None
    return round(value, 2) if value % 1 else int(value)


def bracket_segments(text: str) -> list[str]:
    """优先返回括号、方括号和书名式括号内文本。"""
    segments = re.findall(r"[\(\[【](.*?)[\)\]】]", text)
    return [seg.strip() for seg in segments if seg.strip()]


def extract_weight_from_candidate(text: str) -> tuple[float | None, str | None]:
    """从单段文本中提取重量，按强信号、倍数、范围、普通重量的顺序处理。"""
    if not text:
        return None, None

    total_pattern = re.compile(
        rf"(?:共|合计|总重|净重|重量|规格|实发)\s*[:：]?\s*"
        rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})",
        re.I,
    )
    match = total_pattern.search(text)
    if match:
        return clean_weight_number(unit_to_grams(match.group(1), match.group(2))), "强信号重量"

    multi_pattern = re.compile(
        rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})\s*(?:\*|x|/)\s*"
        rf"(\d+(?:\.\d+)?)\s*(?:[{QUANTITY_WORDS}])?",
        re.I,
    )
    match = multi_pattern.search(text)
    if match and "*" in match.group(0) or match and "x" in match.group(0).lower():
        grams = unit_to_grams(match.group(1), match.group(2)) * float(match.group(3))
        return clean_weight_number(grams), "倍数重量"

    reverse_multi_pattern = re.compile(
        rf"(\d+(?:\.\d+)?)\s*(?:[{QUANTITY_WORDS}])\s*(?:\*|x)\s*"
        rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})",
        re.I,
    )
    match = reverse_multi_pattern.search(text)
    if match:
        grams = float(match.group(1)) * unit_to_grams(match.group(2), match.group(3))
        return clean_weight_number(grams), "反向倍数重量"

    range_pattern = re.compile(
        rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})?\s*(?:-|~|至|到)\s*"
        rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})",
        re.I,
    )
    match = range_pattern.search(text)
    if match:
        unit1 = match.group(2) or match.group(4)
        start = unit_to_grams(match.group(1), unit1)
        end = unit_to_grams(match.group(3), match.group(4))
        return clean_weight_number((start + end) / 2), "范围重量均值"

    simple_pattern = re.compile(rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})", re.I)
    match = simple_pattern.search(text)
    if match:
        return clean_weight_number(unit_to_grams(match.group(1), match.group(2))), "普通重量"

    return None, None


def extract_weight(text: str) -> tuple[float | None, str]:
    """括号内重量优先；括号无重量时再匹配完整标题。"""
    normalized = normalize_text(text)
    for segment in bracket_segments(normalized):
        value, source = extract_weight_from_candidate(segment)
        if value is not None:
            return value, f"括号优先-{source}"

    value, source = extract_weight_from_candidate(normalized)
    if value is not None:
        return value, source or "重量提取成功"
    return None, "未识别重量"


def normalize_brand_value(value: Any) -> str:
    """品牌字段常带分类后缀，如“良品铺子 - 坚果零食”，仅保留品牌主体。"""
    text = normalize_text(value)
    if not text:
        return ""
    text = re.split(r"\s*[-—–|/]\s*", text, maxsplit=1)[0]
    text = re.sub(r"(旗舰店|官方|自营|专营店|食品|零食|坚果炒货)$", "", text)
    return text.strip()


def build_brand_aliases(df: pd.DataFrame, brand_col: str | None) -> list[str]:
    aliases: set[str] = set()
    if brand_col and brand_col in df.columns:
        for value in df[brand_col].dropna().astype(str).unique():
            brand = normalize_brand_value(value)
            if len(brand) >= 2:
                aliases.add(brand)
    return sorted(aliases, key=len, reverse=True)


def extract_brand_from_name(text: str, row_brand: Any, brand_aliases: list[str]) -> str:
    name = normalize_text(text)
    own_brand = normalize_brand_value(row_brand)
    if own_brand and own_brand in name:
        return own_brand

    for alias in brand_aliases:
        if alias and alias in name:
            return alias

    # 兜底：标题开头连续 2-12 位中文/英文/数字通常是品牌词。
    match = re.match(r"^([A-Za-z0-9\u4e00-\u9fa5]{2,12})", name)
    return match.group(1) if match else ""


def extract_flavor(text: str) -> str:
    name = normalize_text(text)
    found: list[str] = []
    for word in sorted(FLAVOR_WORDS, key=len, reverse=True):
        if word in name and word not in found:
            found.append(word)
    # 去掉“蟹黄味”和“蟹黄”这种包含关系的重复项。
    deduped: list[str] = []
    for word in found:
        if not any(word != other and word in other for other in found):
            deduped.append(word)
    return ";".join(deduped)


def extract_package_type(text: str) -> str:
    name = normalize_text(text)
    packages: list[str] = []
    for label, pattern in PACKAGE_PATTERNS:
        if re.search(pattern, name) and label not in packages:
            packages.append(label)
    return ";".join(packages)


def extract_is_gift(text: str) -> bool:
    name = normalize_text(text)
    return any(word in name for word in GIFT_WORDS)


def extract_specification(text: str) -> str:
    name = normalize_text(text)
    specs: list[str] = []
    occupied_spans: list[tuple[int, int]] = []

    def span_overlaps(span: tuple[int, int]) -> bool:
        return any(max(span[0], old[0]) < min(span[1], old[1]) for old in occupied_spans)

    def add_spec(value: str, span: tuple[int, int] | None = None) -> None:
        value = re.sub(num, lambda m: normalize_spec_number(m.group(0)), value)
        value = re.sub(r"\s+", "", value)
        if value and value not in specs:
            specs.append(value)
        if span is not None:
            occupied_spans.append(span)

    # 提取不含重量的系列/版本说明。
    for segment in bracket_segments(name):
        if not re.search(UNIT_PATTERN, segment, re.I) and len(segment) <= 30:
            specs.append(f"系列:{segment}")

    num = r"[0-9一二两三四五六七八九十百千万]+"
    spec_patterns = [
        rf"共\s*{num}\s*款",
        rf"买\s*{num}\s*送\s*{num}",
        rf"{num}\s*[{QUANTITY_WORDS}]\s*装",
        rf"{num}\s*[{QUANTITY_WORDS}]",
    ]
    for pattern in spec_patterns:
        for match in re.finditer(pattern, name):
            if span_overlaps(match.span()):
                continue
            add_spec(match.group(0), match.span())

    return ";".join(specs)


def extract_keywords(
    text: str,
    brand: str,
    flavor: str,
    package_type: str,
    second_category: Any = "",
    third_category: Any = "",
) -> str:
    """使用 jieba 词性分词，并把已提取的品牌/口味/品类词补回关键词集合。"""
    name = normalize_text(text)
    extra_words: list[str] = []
    for value in [brand, flavor, package_type, normalize_text(second_category), normalize_text(third_category)]:
        if not value:
            continue
        extra_words.extend([item for item in re.split(r"[;,\s]+", value) if item])

    for word in extra_words + FLAVOR_WORDS:
        if word:
            jieba.add_word(word)

    keep_flags = ("n", "nr", "ns", "nt", "nz", "vn", "eng", "a")
    keywords: list[str] = []

    for word, flag in pseg.cut(name):
        word = word.strip()
        if not word or word in STOP_WORDS:
            continue
        if re.fullmatch(r"[\d.]+", word) or re.fullmatch(UNIT_PATTERN, word, re.I):
            continue
        if re.search(r"\d", word) and re.search(r"(g|kg|克|斤|袋|包|罐|盒|箱|桶|筒)", word, re.I):
            continue
        if len(word) == 1 and word not in FLAVOR_WORDS:
            continue
        if flag.startswith(keep_flags) or word in extra_words or word in FLAVOR_WORDS:
            if word not in keywords:
                keywords.append(word)

    for word in extra_words:
        if word and word not in STOP_WORDS and word not in keywords:
            keywords.append(word)

    return json.dumps(keywords, ensure_ascii=False)


def compare_brand(row_brand: Any, brand_from_name: str) -> str:
    expected = normalize_brand_value(row_brand)
    actual = normalize_brand_value(brand_from_name)
    if not expected and not actual:
        return "missing_both"
    if expected and not actual:
        return "missing_extracted"
    if actual and not expected:
        return "missing_original"
    if expected == actual or expected in actual or actual in expected:
        return "consistent"
    return "mismatch"


def compare_weight(original_weight: Any, weight_from_text: float | None) -> str:
    original = pd.to_numeric(pd.Series([original_weight]), errors="coerce").iloc[0]
    has_original = not pd.isna(original) and float(original) > 0
    has_text = weight_from_text is not None and not pd.isna(weight_from_text)

    if not has_original and not has_text:
        return "missing_both"
    if not has_original and has_text:
        return "filled_from_text"
    if has_original and not has_text:
        return "missing_extracted"

    tolerance = max(1.0, float(original) * 0.02)
    return "consistent" if abs(float(original) - float(weight_from_text)) <= tolerance else "mismatch"


def build_notes(
    brand_status: str,
    weight_status: str,
    flavor: str,
    package_type: str,
    weight_note: str,
) -> str:
    notes: list[str] = []
    notes.append("品牌一致" if brand_status == "consistent" else f"品牌{brand_status}")
    notes.append("重量一致" if weight_status == "consistent" else f"重量{weight_status}")
    notes.append(f"重量来源:{weight_note}")
    if not flavor:
        notes.append("未识别口味")
    if not package_type:
        notes.append("未识别包装")
    return ";".join(notes)


def structure_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    name_col = "商品名称"
    brand_col = "品牌" if "品牌" in df.columns else None
    weight_col = "重量_g" if "重量_g" in df.columns else ("weight_g" if "weight_g" in df.columns else None)
    second_col = "二级分类" if "二级分类" in df.columns else None
    third_col = "三级分类" if "三级分类" in df.columns else None

    if name_col not in df.columns:
        raise KeyError(f"缺少必要字段：{name_col}")

    result = df.copy()
    brand_aliases = build_brand_aliases(result, brand_col)

    rows: list[dict[str, Any]] = []
    for _, row in result.iterrows():
        name = row.get(name_col, "")
        brand_from_name = extract_brand_from_name(name, row.get(brand_col, "") if brand_col else "", brand_aliases)
        flavor = extract_flavor(name)
        weight_from_text, weight_note = extract_weight(name)
        package_type = extract_package_type(name)
        specification = extract_specification(name)
        is_gift = extract_is_gift(name)

        brand_status = compare_brand(row.get(brand_col, "") if brand_col else "", brand_from_name)
        weight_status = compare_weight(row.get(weight_col, "") if weight_col else "", weight_from_text)
        keywords = extract_keywords(
            name,
            brand_from_name,
            flavor,
            package_type,
            row.get(second_col, "") if second_col else "",
            row.get(third_col, "") if third_col else "",
        )

        rows.append({
            "brand_from_name": brand_from_name,
            "flavor": flavor,
            "weight_from_text": weight_from_text,
            "package_type": package_type,
            "specification": specification,
            "is_gift": bool(is_gift),
            "keywords": keywords,
            "brand_match_status": brand_status,
            "weight_match_status": weight_status,
            "extraction_notes": build_notes(brand_status, weight_status, flavor, package_type, weight_note),
        })

    extracted = pd.DataFrame(rows, index=result.index)
    return pd.concat([result, extracted], axis=1)


def print_statistics(df: pd.DataFrame) -> None:
    total = len(df)
    if total == 0:
        print("数据为空，未生成统计信息。")
        return

    def rate(mask: pd.Series) -> str:
        return f"{mask.sum() / total:.2%} ({mask.sum()}/{total})"

    print("\n处理统计信息")
    print("-" * 40)
    print(f"总记录数：{total}")
    print(f"品牌提取成功率：{rate(df['brand_from_name'].astype(str).str.len() > 0)}")
    print(f"口味提取成功率：{rate(df['flavor'].astype(str).str.len() > 0)}")
    print(f"重量提取成功率：{rate(df['weight_from_text'].notna())}")
    print(f"包装提取成功率：{rate(df['package_type'].astype(str).str.len() > 0)}")
    print(f"礼品装占比：{rate(df['is_gift'] == True)}")
    print(f"品牌不一致率：{rate(df['brand_match_status'] == 'mismatch')}")
    print(f"重量不一致率：{rate(df['weight_match_status'] == 'mismatch')}")
    print(f"重量字段可由文本补充：{rate(df['weight_match_status'] == 'filled_from_text')}")


def run_test_cases() -> None:
    test_cases = [
        "良品铺子坚果零食高端礼盒大礼包送人走亲戚年货送长辈健康礼物品 【龙跃凤鸣】买一送一共24款（实发2箱共1816g）",
        "良品铺子 蟹黄味腰果60g果仁坚果每日干果零食解馋小吃 蟹黄味腰果60g*5袋",
        "洽洽小黄袋每日坚果26g*10袋独立小包装混合坚果仁果干健康休闲零食",
        "三只松鼠 奶油味夏威夷果265gx2袋 坚果炒货 年货零食",
        "百草味 麻辣牛肉条100g 肉类零食 休闲小吃",
    ]
    test_df = pd.DataFrame({
        "品牌": ["良品铺子", "良品铺子", "洽洽", "三只松鼠", "百草味"],
        "商品名称": test_cases,
        "weight_g": [1816, 60, None, None, 100],
        "二级分类": ["坚果炒货"] * 4 + ["肉干肉脯"],
        "三级分类": ["坚果礼盒", "腰果", "每日坚果", "夏威夷果", "牛肉干"],
    })
    structured = structure_dataframe(test_df)
    columns = [
        "商品名称", "brand_from_name", "flavor", "weight_from_text",
        "package_type", "specification", "is_gift", "brand_match_status",
        "weight_match_status",
    ]
    print("\n测试用例结果")
    print("-" * 40)
    print(structured[columns].to_string(index=False))


def default_input_path() -> Path:
    desktop_path = Path.home() / "Desktop" / "cleaned_snacks_data.csv"
    local_path = Path.cwd() / "cleaned_snacks_data.csv"
    return desktop_path if desktop_path.exists() else local_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从中文零食商品名称中提取结构化关键词。")
    parser.add_argument("--input", default=str(default_input_path()), help="输入 CSV 路径")
    parser.add_argument("--output", default="", help="输出 CSV 路径，默认与输入文件同目录")
    parser.add_argument("--skip-tests", action="store_true", help="跳过内置测试用例打印")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve() if args.output else input_path.with_name("structured_snacks_data.csv")

    if not input_path.exists():
        raise FileNotFoundError(f"找不到输入文件：{input_path}")

    if not args.skip_tests:
        run_test_cases()

    df, encoding = read_csv_robust(input_path)
    print(f"\n已读取：{input_path}")
    print(f"识别编码：{encoding}")
    print(f"原始形状：{df.shape}")

    structured = structure_dataframe(df)
    structured.to_csv(output_path, index=False, encoding="utf-8-sig")
    print_statistics(structured)
    print(f"\n已保存：{output_path}")


if __name__ == "__main__":
    main()
