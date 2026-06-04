# -*- coding: utf-8 -*-
"""Fill remaining unknown brands while skipping generic gift/snack bundle titles."""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


CSV_PATH = Path("integrated_selection_products.csv")
DETAIL_PATH = Path("remaining_unknown_brand_fill_report.csv")


def u(value: str) -> str:
    return value.encode("ascii").decode("unicode_escape")


COL_BRAND = u(r"\u54c1\u724c")
COL_NAME = u(r"\u5546\u54c1\u540d\u79f0")
COL_SKU = "SKU"
UNKNOWN_BRAND = u(r"\u672a\u77e5\u54c1\u724c")

ALIASES = [
    (u(r"\u963fQ\u718a"), u(r"\u963fQ\u718a")),
    (u(r"\u80dc\u724c"), u(r"\u80dc\u724c")),
    (u(r"\u5947\u591a"), u(r"\u5947\u591a")),
    (u(r"\u5149\u5408\u661f\u7403"), u(r"\u5149\u5408\u661f\u7403")),
    ("FINUTE", "FINUTE"),
    ("Calbee", u(r"\u5361\u4e50\u6bd4")),
    (u(r"\u5361\u4e50\u6bd4"), u(r"\u5361\u4e50\u6bd4")),
    (u(r"\u8c46MM"), u(r"\u8c46MM")),
    (u(r"\u5c0f\u7231\u679c\u812f"), u(r"\u5c0f\u7231\u679c\u812f")),
    (u(r"\u8106\u8c37\u4e50"), u(r"\u8106\u8c37\u4e50")),
    (u(r"\u706b\uff088\uff09"), u(r"\u706b\uff088\uff09")),
    (u(r"\u7ef4C\u8fa3\u4e1d"), u(r"\u7ef4C\u8fa3\u4e1d")),
    (u(r"\u4e09\u89d2\u9aa8"), u(r"\u4e09\u89d2\u9aa8")),
    (u(r"\u5c71\u59c6"), u(r"\u5c71\u59c6")),
    (u(r"\u8089\u94fa"), u(r"1\u53f7\u8089\u94fa")),
    (u(r"1 \u53f7\u8089\u94fa"), u(r"1\u53f7\u8089\u94fa")),
    (u(r"1\u53f7\u8089\u94fa"), u(r"1\u53f7\u8089\u94fa")),
]

GENERIC_CANDIDATE_TERMS = [
    u(r"\u96f6\u98df\u5927\u793c\u5305"),
    u(r"\u4f11\u95f2\u96f6\u98df"),
    u(r"\u4f11\u95f2\u98df\u54c1"),
    u(r"\u96f6\u98df\u4e00\u6574\u7bb1"),
    u(r"\u5927\u793c\u5305"),
    u(r"\u793c\u5305"),
    u(r"\u793c\u76d2"),
    u(r"\u9001\u5973\u751f"),
    u(r"\u9001\u5b69\u5b50"),
    u(r"\u7f51\u7ea2\u96f6\u98df"),
    u(r"\u591a\u79cd\u96f6\u98df"),
    u(r"\u7cd6\u679c\u793c\u76d2"),
]

STRIP_PREFIXES = [
    u(r"\u4ee3\u8d2d"),
    "2026",
    "2025",
    "2024",
    "61",
    "8090",
]


def strip_leading_tags(text: str) -> str:
    text = str(text or "").strip()
    left = u(r"\u3010")
    right = u(r"\u3011")
    while text.startswith(left) and right in text[:20]:
        text = text.split(right, 1)[1].strip()
    return text


def normalize_for_prefix(text: str) -> str:
    text = strip_leading_tags(text)
    text = re.sub(r"\s+", " ", text).strip()
    changed = True
    while changed:
        changed = False
        for prefix in STRIP_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                changed = True
    if text.startswith(u(r"\u5e74")):
        text = text[1:].strip()
    return text


def alias_brand(name: str) -> str:
    lower = name.lower()
    for pattern, brand in sorted(ALIASES, key=lambda item: len(item[0]), reverse=True):
        if pattern.lower() in lower:
            return brand
    return ""


def prefix_candidate(name: str) -> str:
    text = normalize_for_prefix(name)
    match = re.match(r"([A-Za-z][A-Za-z0-9&'.-]{1,18})", text)
    if match:
        return match.group(1)

    match = re.match(r"([\u4e00-\u9fffA-Za-z0-9]{2,8})", text)
    if not match:
        return ""
    token = match.group(1)
    return token[:6] if len(token) > 6 else token


def is_generic(candidate: str, name: str) -> bool:
    text = normalize_for_prefix(name)
    merged = f"{candidate} {text}"
    return any(term in merged for term in GENERIC_CANDIDATE_TERMS)


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(CSV_PATH)

    df = pd.read_csv(CSV_PATH, dtype=str, encoding="utf-8-sig").fillna("")
    unknown_mask = df[COL_BRAND].astype(str).str.strip().eq(UNKNOWN_BRAND)
    before_unknown = int(unknown_mask.sum())

    rows = []
    updated = 0
    skipped_generic = 0
    skipped_empty = 0

    for idx in df.index[unknown_mask]:
        name = str(df.at[idx, COL_NAME])
        brand = alias_brand(name)
        method = "alias"
        if not brand:
            brand = prefix_candidate(name)
            method = "prefix"

        if not brand:
            skipped_empty += 1
            rows.append({"row_index": idx, "sku": df.at[idx, COL_SKU], "name": name, "action": "skip_empty", "brand": ""})
            continue

        if method == "prefix" and is_generic(brand, name):
            skipped_generic += 1
            rows.append({"row_index": idx, "sku": df.at[idx, COL_SKU], "name": name, "action": "skip_generic", "brand": brand})
            continue

        df.at[idx, COL_BRAND] = brand
        updated += 1
        rows.append({"row_index": idx, "sku": df.at[idx, COL_SKU], "name": name, "action": f"updated_{method}", "brand": brand})

    backup = CSV_PATH.with_name(f"{CSV_PATH.stem}.before_remaining_brand_fill_{datetime.now():%Y%m%d_%H%M%S}.csv")
    shutil.copy2(CSV_PATH, backup)
    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")

    report = pd.DataFrame(rows)
    report.to_csv(DETAIL_PATH, index=False, encoding="utf-8-sig")

    after_unknown = int(df[COL_BRAND].astype(str).str.strip().eq(UNKNOWN_BRAND).sum())
    print(f"file={CSV_PATH}")
    print(f"backup={backup}")
    print(f"report={DETAIL_PATH}")
    print(f"unknown_before={before_unknown}")
    print(f"updated={updated}")
    print(f"skipped_generic={skipped_generic}")
    print(f"skipped_empty={skipped_empty}")
    print(f"unknown_after={after_unknown}")
    if not report.empty:
        print(report["action"].value_counts().to_string())
        print(report.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
