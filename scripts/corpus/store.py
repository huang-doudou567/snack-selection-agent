# -*- coding: utf-8 -*-
"""
Snack Selection Agent — 磁盘持久化层（corpus/store）。

参照 InterviewRadar 的 store.py：通过 JSON 文件解耦 Agent 推理和 Python 执行。
Agent 推理结果落盘后可独立调试，无需重新执行数据查询。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from models import RawProduct, SelectionAdvice, SelectionReport, Evidence


CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "corpus_cache"
CACHE_DIR.mkdir(exist_ok=True)


def _now() -> str:
    return datetime.now().isoformat()


def save_raw_products(products: list[RawProduct], label: str = "raw_products") -> Path:
    """保存 RawProduct 列表到 JSON。"""
    path = CACHE_DIR / f"{label}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "saved_at": _now(),
        "count": len(products),
        "products": [p.to_dict() for p in products],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_raw_products(label: str = "raw_products") -> list[RawProduct]:
    """从 JSON 加载 RawProduct 列表。"""
    path = CACHE_DIR / f"{label}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [RawProduct.from_dict(p) for p in data.get("products", [])]


def save_report(report: SelectionReport, label: str = "latest_report") -> Path:
    """保存 SelectionReport 到 JSON。"""
    path = CACHE_DIR / f"{label}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_report(label: str = "latest_report") -> SelectionReport | None:
    """从 JSON 加载 SelectionReport。"""
    path = CACHE_DIR / f"{label}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SelectionReport.from_dict(data)


def save_markdown(markdown: str, scenario: str = "report") -> Path:
    """保存 Markdown 报告到文件。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CACHE_DIR / f"{scenario}_{timestamp}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def list_reports() -> list[Path]:
    """列出所有已保存的报告。"""
    return sorted(CACHE_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
