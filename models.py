# -*- coding: utf-8 -*-
"""
Snack Selection Agent — 结构化数据模型。

参照 InterviewRadar 的 RawPost → Question → FollowUpChain 体系，
建立 RawProduct → SelectionAdvice → Evidence 三级数据模型。
所有 Agent 工具返回这些 dataclass（而非字符串），
通过 JSON 磁盘文件解耦 Agent 推理层和 Python 执行层。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from datetime import datetime
from typing import Any


# ── 一级：原始商品（对应 InterviewRadar 的 RawPost） ──────────────

@dataclass
class Evidence:
    """一条可追溯的数据证据。"""
    source_file: str           # 来源文件名, 如 "price_history.csv"
    source_row: int | None = None   # 行号
    source_url: str = ""       # 商品链接
    crawled_at: str = ""       # 爬取时间 ISO
    freshness_days: int = 0    # 据今天数
    raw_value: str = ""        # 原始值

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class RawProduct:
    """一个原始商品记录（对应 InterviewRadar 的 RawPost）。"""
    source: str                # jd | taobao | pdd | mmb | ...
    url: str                   # 商品链接
    sku: str = ""              # 平台 SKU
    title: str = ""            # 商品名称
    price: float = 0.0         # 现价（元）
    original_price: float = 0.0  # 原价
    weight_g: float = 0.0      # 克重
    unit_price: float = 0.0    # 每克单价
    brand: str = ""            # 品牌
    category_l2: str = ""      # 二级分类
    category_l3: str = ""      # 三级分类
    store: str = ""            # 店铺名称
    sales_volume: int = 0      # 销量
    comments_count: int = 0    # 评论数
    good_rate: str = ""        # 好评率
    has_promotion: bool = False
    promotion_text: str = ""
    crawled_at: str = ""       # ISO 爬取时间
    price_history: list[dict] = field(default_factory=list)  # 历史价格点
    reviews: list[str] = field(default_factory=list)         # 评论文本
    negative_reviews: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RawProduct":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in allowed})


# ── 二级：选品建议（对应 InterviewRadar 的 FollowUpChain） ──────

@dataclass
class SelectionAdvice:
    """一条选品建议（对应 InterviewRadar 的 FollowUpChain）。"""
    title: str                 # 建议标题
    action: str                # 具体行动
    scenario: str = ""         # 场景 clearout|pick|benchmark|promotion|negative|sourcing
    priority: str = "P1"       # P0|P1|P2
    evidence: list[Evidence] = field(default_factory=list)
    is_grounded: bool = False  # 是否可追溯到真实数据
    confidence: float = 0.0    # 0-1
    caveats: list[str] = field(default_factory=list)     # 局限性
    alternatives: list[str] = field(default_factory=list)  # 替代方案

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SelectionAdvice":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in allowed})


# ── 三级：完整选品报告 ──────────────────────────────────────────

@dataclass
class SelectionReport:
    """一次完整的选品分析报告。"""
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    scenario: str = ""         # 场景
    scene_diagnosis: str = ""  # 一句话场景诊断
    user_input_summary: str = ""  # 用户需求摘要
    category: str = ""         # 目标品类
    brand: str = ""            # 目标品牌
    max_price: float | None = None

    # 数据源概况
    total_products: int = 0
    coverage_jd_reviews: float = 0.0  # 京东评论覆盖率
    coverage_mmb_price: float = 0.0   # 慢慢买价格覆盖率
    data_caveats: list[str] = field(default_factory=list)

    # 核心发现
    key_findings: list[dict] = field(default_factory=list)  # [{指标, 数值, 来源}]

    # 建议列表
    recommendations: list[SelectionAdvice] = field(default_factory=list)

    # 竞品对标
    competitor_comparison: list[dict] = field(default_factory=list)

    # 执行清单
    action_checklist: list[str] = field(default_factory=list)

    # 所有证据汇总
    all_evidence: list[Evidence] = field(default_factory=list)

    # Markdown 输出缓存
    markdown_output: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["recommendations"] = [r.to_dict() for r in self.recommendations]
        d["all_evidence"] = [e.to_dict() for e in self.all_evidence]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SelectionReport":
        data = dict(d)
        data["recommendations"] = [SelectionAdvice.from_dict(r) for r in data.get("recommendations", [])]
        data["all_evidence"] = [Evidence.from_dict(e) for e in data.get("all_evidence", [])]
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


# ── 工具函数 ────────────────────────────────────────────────────

def make_evidence(source_file: str, **kwargs) -> Evidence:
    """快速创建 Evidence 对象。"""
    return Evidence(source_file=source_file, **kwargs)


def make_advice(title: str, action: str, scenario: str = "",
                evidence: list[Evidence] | None = None,
                confidence: float = 0.0, is_grounded: bool = False,
                **kwargs) -> SelectionAdvice:
    """快速创建 SelectionAdvice 对象。"""
    return SelectionAdvice(
        title=title, action=action, scenario=scenario,
        evidence=evidence or [], confidence=confidence,
        is_grounded=is_grounded or bool(evidence), **kwargs,
    )
