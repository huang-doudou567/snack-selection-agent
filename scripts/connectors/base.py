# -*- coding: utf-8 -*-
"""
Snack Selection Agent — Connector 抽象基类。

参照 InterviewRadar 的 Connector ABC 模式统一所有数据源接口：
- 每个爬虫实现 search(queries) -> SearchResult
- 降级不可崩溃：返回 degraded 状态 + 提示消息
- 统一返回 RawProduct（models.py）而非零散格式
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
from models import RawProduct


@dataclass
class SearchResult:
    """Connector 统一返回结构。"""
    products: list[RawProduct] = field(default_factory=list)
    status: str = "ok"         # ok | degraded | error
    message: str = ""          # 降级或错误时的提示
    total_matched: int = 0     # 源里匹配到的总数
    source_name: str = ""      # 源名称

    @classmethod
    def degraded(cls, source_name: str, message: str) -> "SearchResult":
        return cls(
            products=[], status="degraded", message=f"[{source_name}] {message}",
            source_name=source_name,
        )

    @classmethod
    def ok(cls, products: list[RawProduct], source_name: str,
           total_matched: int = 0) -> "SearchResult":
        return cls(
            products=products, status="ok", source_name=source_name,
            total_matched=total_matched or len(products),
        )


class Connector(ABC):
    """数据源连接器抽象基类。

    所有京东/淘宝/拼多多/慢慢买爬虫都应实现此接口。
    未实现时返回 degraded 即可，不阻塞管线。
    """

    name: str = "base"

    @abstractmethod
    def search(self, queries: list[str]) -> SearchResult:
        """按查询词列表搜索，返回归一化的 RawProduct 列表。"""
        raise NotImplementedError

    def health(self) -> dict:
        """返回连接器健康状态。"""
        return {"name": self.name, "status": "unknown"}
