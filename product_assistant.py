# -*- coding: utf-8 -*-
"""
基于 structured_snacks_data.csv 的单平台零食选品分析助手。

设计目标：
1. 只使用本地静态快照数据，不依赖外部 API。
2. 分析结论必须带数据来源、计算方法、置信度和局限性。
3. 优先使用结构化抽取字段作为分析语料，例如 brand_from_name、flavor、package_type、keywords。
"""

from __future__ import annotations

import json
import math
import os
import re
from io import BytesIO
from http.client import InvalidURL
from html import unescape
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {"商品名称", "现价", "三级分类"}
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
PLAYWRIGHT_PROFILE_DIR = Path.home() / ".snack_selection_assistant" / "browser_profile"
try:
    PLAYWRIGHT_LOGIN_WAIT_SECONDS = int(os.getenv("SNACK_PLAYWRIGHT_LOGIN_WAIT_SECONDS", "60"))
except ValueError:
    PLAYWRIGHT_LOGIN_WAIT_SECONDS = 60


@dataclass(frozen=True)
class CategoryMatch:
    """品类匹配结果。"""

    query: str
    label: str
    scope: str
    sample_size: int


@dataclass(frozen=True)
class ParsedProduct:
    """从商品链接或网页标题解析出的商品信息。"""

    product_info: dict[str, Any]
    source: str
    sku: str = ""
    title: str = ""
    notes: tuple[str, ...] = ()


class ProductSelectionAssistant:
    """零食选品分析助手核心类。"""

    def __init__(self, data_path: str | Path | None = None) -> None:
        self.data_path = self._resolve_data_path(data_path)
        self.df = self._load_csv(self.data_path)
        self._validate_columns()
        self.df = self._prepare_dataframe(self.df)
        self.category_stats = self._precompute_statistics()

    @staticmethod
    def _resolve_data_path(data_path: str | Path | None) -> Path:
        """寻找结构化数据文件。"""
        candidates = []
        if data_path:
            candidates.append(Path(data_path).expanduser())
        # 绝对路径：项目目录
        candidates.extend([
            Path(r"C:\Users\HUAWEI\Documents\New project 2") / "integrated_selection_products.csv",
            Path(r"C:\Users\HUAWEI\Documents\New project 2") / "structured_snacks_data_with_random_sales.csv",
            Path(r"C:\Users\HUAWEI\Documents\New project 2") / "structured_snacks_data.csv",
        ])
        # cwd fallback
        candidates.extend([
            Path.cwd() / "integrated_selection_products.csv",
            Path.home() / "Desktop" / "integrated_selection_products.csv",
            Path.cwd() / "structured_snacks_data_with_random_sales.csv",
        ])

        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        raise FileNotFoundError("未找到 integrated_selection_products.csv，请放在项目目录或桌面。")

    @staticmethod
    def _load_csv(path: Path) -> pd.DataFrame:
        """兼容 UTF-8-SIG、GB18030 等常见 CSV 编码。"""
        last_error: Exception | None = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                return pd.read_csv(path, encoding=encoding)
            except UnicodeDecodeError as exc:
                last_error = exc
        raise RuntimeError(f"无法读取 CSV 编码：{path}") from last_error

    def _validate_columns(self) -> None:
        missing = REQUIRED_COLUMNS - set(self.df.columns)
        if missing:
            raise KeyError(f"数据缺少必要字段：{', '.join(sorted(missing))}")

    @staticmethod
    def _clean_brand(value: Any) -> str:
        if pd.isna(value):
            return ""
        text = str(value).strip()
        return text.split(" - ")[0].strip()

    @staticmethod
    def _normalize_sku(value: Any) -> str:
        """把 CSV 中可能以数字、浮点或科学计数法存在的 SKU 统一成字符串。"""
        if pd.isna(value):
            return ""
        text = str(value).strip()
        if not text:
            return ""
        try:
            number = float(text)
            if math.isfinite(number):
                return str(int(number))
        except (TypeError, ValueError):
            pass
        digits = re.findall(r"\d+", text)
        return max(digits, key=len) if digits else text

    @staticmethod
    def _parse_keywords(value: Any) -> list[str]:
        if pd.isna(value) or value == "":
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        text = str(value).strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in text.replace(";", ",").split(",") if item.strip()]

    @staticmethod
    def _has_promotion(row: pd.Series) -> bool:
        if "has_coupon" in row and pd.notna(row["has_coupon"]):
            try:
                if int(row["has_coupon"]) == 1:
                    return True
            except (TypeError, ValueError):
                pass
        promo = str(row.get("促销信息", "") or "").strip()
        return bool(promo and promo not in {"[]", "nan", "None"})

    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """构造分析字段，优先使用结构化抽取结果。"""
        prepared = df.copy()
        weight_col = "weight_from_text" if "weight_from_text" in prepared.columns else "weight_g"
        fallback_weight_col = "weight_g" if "weight_g" in prepared.columns else weight_col

        prepared["analysis_price"] = pd.to_numeric(prepared["现价"], errors="coerce")
        prepared["analysis_weight_g"] = pd.to_numeric(prepared.get(weight_col), errors="coerce")
        fallback_weight = pd.to_numeric(prepared.get(fallback_weight_col), errors="coerce")
        prepared["analysis_weight_g"] = prepared["analysis_weight_g"].fillna(fallback_weight)

        prepared["unit_price"] = prepared["analysis_price"] / prepared["analysis_weight_g"]
        prepared.loc[
            (prepared["analysis_price"] <= 0)
            | (prepared["analysis_weight_g"] <= 0)
            | ~np.isfinite(prepared["unit_price"]),
            "unit_price",
        ] = np.nan

        # 新语料已删除原始“销售量”，优先使用“随机销量”作为热度指标。
        if "随机销量" in prepared.columns:
            sales_col = "随机销量"
        elif "sales_num" in prepared.columns:
            sales_col = "sales_num"
        else:
            sales_col = "销售量"
        prepared["sales_metric"] = pd.to_numeric(prepared.get(sales_col), errors="coerce").fillna(0)
        prepared["sales_metric_source"] = sales_col

        if "brand_from_name" in prepared.columns:
            prepared["analysis_brand"] = prepared["brand_from_name"].fillna("").astype(str)
            fallback_brand = prepared.get("品牌", "").apply(self._clean_brand)
            prepared.loc[prepared["analysis_brand"].str.strip() == "", "analysis_brand"] = fallback_brand
        else:
            prepared["analysis_brand"] = prepared.get("品牌", "").apply(self._clean_brand)

        for col in ["flavor", "package_type", "specification", "extraction_notes"]:
            if col not in prepared.columns:
                prepared[col] = ""
            prepared[col] = prepared[col].fillna("").astype(str)

        if "is_gift" not in prepared.columns:
            prepared["is_gift"] = False
        prepared["is_gift"] = prepared["is_gift"].fillna(False).astype(bool)

        if "keywords" not in prepared.columns:
            prepared["keywords"] = "[]"
        prepared["keyword_list"] = prepared["keywords"].apply(self._parse_keywords)
        prepared["keyword_text"] = prepared["keyword_list"].apply(lambda words: " ".join(words))
        prepared["has_promotion_flag"] = prepared.apply(self._has_promotion, axis=1)
        if "SKU" in prepared.columns:
            prepared["sku_text"] = prepared["SKU"].apply(self._normalize_sku)
        else:
            prepared["sku_text"] = ""

        return prepared

    def _valid_market_df(self) -> pd.DataFrame:
        return self.df[self.df["unit_price"].notna()].copy()

    def _precompute_statistics(self) -> dict[str, dict[str, Any]]:
        """预先计算三级品类统计，提高交互查询速度。"""
        stats: dict[str, dict[str, Any]] = {}
        valid = self._valid_market_df()
        for category, cat_data in valid.groupby("三级分类"):
            if pd.isna(category) or len(cat_data) < 5:
                continue
            stats[str(category)] = self._build_stats(cat_data)
        return stats

    @staticmethod
    def _build_stats(cat_data: pd.DataFrame) -> dict[str, Any]:
        prices = cat_data["unit_price"].dropna()
        return {
            "sample_size": int(len(cat_data)),
            "avg_unit_price": float(prices.mean()),
            "median_unit_price": float(prices.median()),
            "price_25th": float(prices.quantile(0.25)),
            "price_75th": float(prices.quantile(0.75)),
            "min_unit_price": float(prices.min()),
            "max_unit_price": float(prices.max()),
            "common_specs": cat_data["analysis_weight_g"].round(0).value_counts().head(5).index.astype(int).tolist(),
            "top_brands": cat_data["analysis_brand"].replace("", np.nan).dropna().value_counts().head(5).index.tolist(),
            "top_flavors": cat_data["flavor"].replace("", np.nan).dropna().value_counts().head(5).index.tolist(),
            "top_packages": cat_data["package_type"].replace("", np.nan).dropna().value_counts().head(5).index.tolist(),
            "promotion_rate": float(cat_data["has_promotion_flag"].mean()),
            "gift_rate": float(cat_data["is_gift"].mean()),
        }

    @staticmethod
    def _confidence(sample_size: int) -> str:
        if sample_size >= 80:
            return f"高（样本量 {sample_size}）"
        if sample_size >= 30:
            return f"中（样本量 {sample_size}）"
        if sample_size >= 10:
            return f"低（样本量 {sample_size}）"
        return f"不足（样本量 {sample_size}）"

    @staticmethod
    def _is_missing_value(value: Any) -> bool:
        if value in (None, "", 0, 0.0):
            return True
        try:
            return bool(pd.isna(value))
        except TypeError:
            return False

    def available_categories(self) -> list[str]:
        return sorted([str(item) for item in self.df["三级分类"].dropna().unique()])

    @staticmethod
    def _extract_url_candidate(raw_text: str) -> str:
        """
        从用户粘贴内容中提取真正的 URL 片段。

        京东分享文本常见格式类似：
        //3.cn/xxx?jkl=abc 「商品标题」 点击链接直接打开...

        这类输入不能整体交给 urlopen，否则空格、中文标题会触发
        http.client.InvalidURL。这里只取第一个 URL-like token。
        """
        text = str(raw_text or "").strip()
        if not text:
            return ""

        # 去掉不可见控制字符，保留正常空格用于分隔分享文案。
        text = re.sub(r"[\x00-\x1f\x7f]+", " ", text).strip()

        patterns = [
            r"https?://[^\s\"'<>，。；、]+",
            r"//[^\s\"'<>，。；、]+",
            r"(?:item\.jd\.com|item\.m\.jd\.com|3\.cn|u\.jd\.com|jd\.com|m\.jd\.com|item\.taobao\.com|detail\.tmall\.com|e\.tb\.cn)/[^\s\"'<>，。；、]+",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(0).strip()

        # 如果用户输入本身没有空白，可能就是裸域名或 SKU。
        return text if not re.search(r"\s", text) else ""

    @classmethod
    def clean_taobao_url(cls, url: str) -> str:
        """
        淘宝/天猫链接净化：删除追踪参数，只保留商品 ID。

        支持：
        - item.taobao.com/item.htm?id=...
        - detail.tmall.com/item.htm?id=...

        短链如 e.tb.cn 直接返回，不展开、不修改。
        """
        candidate = cls._extract_url_candidate(url)
        if not candidate:
            return ""

        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        elif not re.match(r"^https?://", candidate, re.I):
            candidate = f"https://{candidate}"

        parsed = urlparse(candidate)
        netloc = parsed.netloc.lower()
        if "taobao.com" in netloc or "tmall.com" in netloc:
            query = parse_qs(parsed.query)
            keep_params = {}
            if "id" in query and query["id"]:
                keep_params["id"] = query["id"][0]

            clean_query = urlencode(keep_params)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if clean_query:
                clean_url += f"?{clean_query}"
            return clean_url

        return candidate

    @classmethod
    def _normalize_url_for_fetch(cls, raw_url: str) -> str:
        """
        将用户输入标准化为可被 urllib 请求的 URL。

        - 从分享文案里提取真实链接；
        - 支持 //3.cn/... 这类 scheme-relative URL；
        - 对 path/query 做百分号编码，避免空格和中文等非法字符进入 http.client。
        """
        candidate = cls._extract_url_candidate(raw_url)
        if not candidate:
            return ""
        if re.fullmatch(r"\d{6,}", candidate):
            return ""

        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        elif not re.match(r"^https?://", candidate, re.I):
            candidate = f"https://{candidate}"

        candidate = cls.clean_taobao_url(candidate)
        if not candidate:
            return ""

        parts = urlsplit(candidate)
        if not parts.netloc:
            return ""

        safe_path = quote(parts.path, safe="/:@!$&'()*+,;=-._~%")
        safe_query = quote(parts.query, safe="=&?/:@!$,'()*+,;=-._~%")
        return urlunsplit((parts.scheme, parts.netloc, safe_path, safe_query, parts.fragment))

    @staticmethod
    def extract_sku_from_url(product_url: str) -> str:
        """从京东商品链接或纯 SKU 文本中提取 SKU。"""
        text = str(product_url or "").strip()
        if not text:
            return ""
        if re.fullmatch(r"\d{6,}", text):
            return text

        normalized_url = ProductSelectionAssistant._normalize_url_for_fetch(text)
        parse_text = normalized_url or text
        parsed = urlparse(parse_text if re.match(r"^https?://", parse_text, re.I) else f"https://{parse_text}")
        query = parse_qs(parsed.query)
        for key in ["sku", "skuId", "wareId", "itemId", "productId", "id"]:
            for value in query.get(key, []):
                match = re.search(r"\d{6,}", value)
                if match:
                    return match.group(0)

        path_patterns = [
            r"/(\d{6,})\.html",
            r"/product/(\d{6,})",
            r"/item/(\d{6,})",
            r"/(\d{6,})(?:/|$)",
        ]
        for pattern in path_patterns:
            match = re.search(pattern, parsed.path)
            if match:
                return match.group(1)

        match = re.search(r"(?:skuIds=J_|skuId=|sku=)?(\d{6,})", text)
        return match.group(1) if match else ""

    @staticmethod
    def _fetch_url_text(url: str, timeout: int = 8) -> str:
        fetch_url = ProductSelectionAssistant._normalize_url_for_fetch(url)
        if not fetch_url:
            raise ValueError("未识别到可抓取的有效 URL，请粘贴商品链接或京东分享文本。")

        request = Request(
            fetch_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="ignore")

    @staticmethod
    def _extract_shared_title(raw_text: str) -> str:
        """
        从分享文案中提取「商品标题」。
        """
        text = str(raw_text or "")
        match = re.search(r"「([^」]+)」", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _clean_page_title(title: str) -> str:
        title = unescape(re.sub(r"\s+", " ", title or "")).strip()
        title = re.sub(r"[-_]\s*京东.*$", "", title)
        title = re.sub(r"【图片.*?】", "", title)
        return title.strip()

    @classmethod
    def _extract_title_from_html(cls, html_text: str) -> str:
        patterns = [
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']title["\'][^>]+content=["\'](.*?)["\']',
            r'"skuName"\s*:\s*"(.*?)"',
            r"<title[^>]*>(.*?)</title>",
        ]
        for pattern in patterns:
            match = re.search(pattern, html_text, re.I | re.S)
            if match:
                return cls._clean_page_title(match.group(1))
        return ""

    @staticmethod
    def _extract_price_from_html(html_text: str) -> float | None:
        patterns = [
            r'"p"\s*:\s*"(\d+(?:\.\d+)?)"',
            r'"price"\s*:\s*"(\d+(?:\.\d+)?)"',
            r'"jdPrice"\s*:\s*"(\d+(?:\.\d+)?)"',
            r"￥\s*(\d+(?:\.\d+)?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, html_text)
            if match:
                try:
                    price = float(match.group(1))
                    if price > 0:
                        return price
                except ValueError:
                    continue
        return None

    @staticmethod
    def _extract_price_from_text(text: str) -> float | None:
        """
        从可见文本或 OCR 文本中提取价格。

        相比 HTML JSON 价格字段，这里更保守：优先匹配带货币符号或“价”的价格，
        避免把 520、1000g 这类数字误当成售价。
        """
        text = re.sub(r"\s+", " ", str(text or ""))
        patterns = [
            r"(?:到手价|券后价|促销价|秒杀价|京东价|售价|价格|价)\D{0,8}([1-9]\d{0,4}(?:\.\d{1,2})?)",
            r"[￥¥]\s*([1-9]\d{0,4}(?:\.\d{1,2})?)",
            r"([1-9]\d{0,4}(?:\.\d{1,2})?)\s*元",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.I):
                try:
                    price = float(match.group(1))
                    if 0 < price < 100000:
                        return price
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _ocr_image_bytes(image_bytes: bytes) -> tuple[str, str]:
        """
        对截图做 OCR。

        依赖：
        - pytesseract Python 包
        - 系统已安装 Tesseract OCR 可执行程序

        缺任一依赖时返回空文本和说明，不影响主流程。
        """
        if not image_bytes:
            return "", "OCR 跳过：截图为空。"
        try:
            import pytesseract
            from PIL import Image

            if Path(TESSERACT_CMD).exists():
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

            image = Image.open(BytesIO(image_bytes))
            text = pytesseract.image_to_string(image, lang="chi_sim+eng")
            text = re.sub(r"\s+", " ", text or "").strip()
            return text, "已尝试对详情页截图进行 OCR。"
        except Exception as exc:
            return "", f"OCR 不可用或识别失败：{exc}"

    @classmethod
    def extract_text_from_image_bytes(cls, image_bytes: bytes) -> tuple[str, str]:
        """
        公开 OCR 方法，供 Streamlit 上传商品截图时调用。
        """
        return cls._ocr_image_bytes(image_bytes)

    @classmethod
    def _render_product_page(cls, raw_url: str, timeout_ms: int = 15000) -> dict[str, Any]:
        """
        使用 Playwright 真实浏览器渲染商品详情页，提取标题、可见文本、截图 OCR 文本。

        注意：淘宝/京东存在登录态、验证码和风控，本方法是增强解析能力，
        不是保证一定能抓到价格/规格。
        """
        fetch_url = cls._normalize_url_for_fetch(raw_url)
        if not fetch_url:
            return {"notes": ["浏览器渲染跳过：未识别到有效 URL。"]}

        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return {"notes": [f"浏览器渲染跳过：未安装 Playwright（{exc}）。"]}

        notes: list[str] = []
        title = ""
        visible_text = ""
        ocr_text = ""

        try:
            with sync_playwright() as p:
                context = None
                launch_errors: list[str] = []
                headless = os.getenv("SNACK_PLAYWRIGHT_HEADLESS", "0").strip().lower() in {"1", "true", "yes"}
                PLAYWRIGHT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                for launch_kwargs in (
                    {"channel": "msedge", "headless": headless},
                    {"channel": "chrome", "headless": headless},
                    {"headless": headless},
                ):
                    try:
                        context = p.chromium.launch_persistent_context(
                            user_data_dir=str(PLAYWRIGHT_PROFILE_DIR),
                            viewport={"width": 1366, "height": 1600},
                            user_agent=(
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                            ),
                            locale="zh-CN",
                            **launch_kwargs,
                        )
                        if "channel" in launch_kwargs:
                            notes.append(f"已使用系统浏览器 {launch_kwargs['channel']} 持久化会话渲染页面。")
                        notes.append(f"Cookie 复用目录：{PLAYWRIGHT_PROFILE_DIR}")
                        if not headless:
                            notes.append("如页面要求登录，请在弹出的浏览器窗口中完成登录；Cookie 会被保存供下次复用。")
                        break
                    except Exception as exc:
                        launch_errors.append(str(exc).splitlines()[0])

                if context is None:
                    raise RuntimeError("；".join(launch_errors))

                page = context.pages[0] if context.pages else context.new_page()
                page.goto(fetch_url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    notes.append("浏览器渲染提示：networkidle 等待超时，继续读取已加载内容。")

                title = cls._clean_page_title(page.title())
                try:
                    visible_text = page.locator("body").inner_text(timeout=5000)
                    visible_text = re.sub(r"\s+", " ", visible_text or "").strip()
                except Exception as exc:
                    notes.append(f"浏览器可见文本读取失败：{exc}")

                login_hint_text = f"{title}\n{visible_text}".lower()
                login_required = any(
                    word in login_hint_text
                    for word in ["登录", "登陆", "扫码登录", "账户登录", "login", "sign in"]
                )
                if login_required and not headless and PLAYWRIGHT_LOGIN_WAIT_SECONDS > 0:
                    # 淘宝/京东经常要求用户手动登录或扫码；这里暂停窗口，等用户完成后再回到详情页读取一次。
                    notes.append(
                        f"检测到疑似登录页，已等待 {PLAYWRIGHT_LOGIN_WAIT_SECONDS} 秒供手动登录；"
                        "登录成功后 Cookie 会保存在本机并在后续请求复用。"
                    )
                    page.wait_for_timeout(PLAYWRIGHT_LOGIN_WAIT_SECONDS * 1000)
                    try:
                        page.goto(fetch_url, wait_until="domcontentloaded", timeout=timeout_ms)
                        try:
                            page.wait_for_load_state("networkidle", timeout=5000)
                        except Exception:
                            pass
                        title = cls._clean_page_title(page.title())
                        visible_text = page.locator("body").inner_text(timeout=5000)
                        visible_text = re.sub(r"\s+", " ", visible_text or "").strip()
                    except Exception as exc:
                        notes.append(f"登录等待后重新读取详情页失败：{exc}")

                try:
                    screenshot = page.get_screenshot(as_bytes="png", full_page=False)
                    ocr_text, ocr_note = cls._ocr_image_bytes(screenshot)
                    notes.append(ocr_note)
                except Exception as exc:
                    notes.append(f"截图 OCR 阶段失败：{exc}")

                context.close()
                notes.append("已使用 Playwright 渲染商品详情页。")
        except Exception as exc:
            notes.append(f"浏览器渲染失败：{exc}")

        combined_text = "\n".join([title, visible_text, ocr_text])
        return {
            "title": title,
            "visible_text": visible_text,
            "ocr_text": ocr_text,
            "combined_text": combined_text,
            "price": cls._extract_price_from_text(combined_text),
            "notes": notes,
        }

    def _fetch_jd_price(self, sku: str) -> float | None:
        if not sku:
            return None
        try:
            text = self._fetch_url_text(f"https://p.3.cn/prices/mgets?skuIds=J_{sku}", timeout=5)
            payload = json.loads(text)
            if isinstance(payload, list) and payload:
                for key in ["p", "op", "m"]:
                    value = payload[0].get(key)
                    try:
                        price = float(value)
                        if price > 0:
                            return price
                    except (TypeError, ValueError):
                        pass
        except (URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError, InvalidURL):
            return None
        return None

    @staticmethod
    def _extract_weight_from_title(title: str) -> float | None:
        """轻量级标题重量解析，作为结构化语料未命中时的兜底。"""
        try:
            from extract_snack_structure import extract_weight

            value, _ = extract_weight(title)
            return float(value) if value is not None else None
        except Exception:
            match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|KG|公斤|千克|斤|g|G|克)", title)
            if not match:
                return None
            value = float(match.group(1))
            unit = match.group(2).lower()
            if unit == "kg" or match.group(2) in {"公斤", "千克"}:
                return value * 1000
            if match.group(2) == "斤":
                return value * 500
            return value

    def _infer_brand_from_title(self, title: str) -> str:
        brands = self.df["analysis_brand"].replace("", np.nan).dropna().value_counts().index.tolist()
        for brand in sorted(brands, key=len, reverse=True):
            if brand and str(brand) in title:
                return str(brand)
        return ""

    def _infer_tag_from_title(self, title: str, column: str) -> str:
        values: set[str] = set()
        for value in self.df[column].dropna().astype(str):
            for item in value.split(";"):
                item = item.strip()
                if item:
                    values.add(item)
        found = [value for value in sorted(values, key=len, reverse=True) if value in title]
        return ";".join(found[:3])

    def _infer_category_from_title(self, title: str) -> str:
        categories = [str(item) for item in self.df["三级分类"].dropna().unique()]
        for category in sorted(categories, key=len, reverse=True):
            if category and category in title:
                return category

        best_category = ""
        best_score = 0
        for category, group in self.df.groupby("三级分类"):
            tokens: set[str] = {str(category)}
            for words in group["keyword_list"].head(80):
                tokens.update(str(word) for word in words if len(str(word)) >= 2)
            score = sum(len(token) for token in tokens if token and token in title)
            if score > best_score:
                best_category = str(category)
                best_score = score
        return best_category if best_score > 0 else ""

    def _product_info_from_row(self, row: pd.Series) -> dict[str, Any]:
        return {
            "category": row.get("三级分类", ""),
            "weight_g": float(row.get("analysis_weight_g", 0) or 0),
            "price": float(row.get("analysis_price", 0) or 0),
            "brand": row.get("analysis_brand", ""),
            "flavor": row.get("flavor", ""),
            "package_type": row.get("package_type", ""),
        }

    def parse_product_url(self, product_url: str, fallback_info: dict[str, Any] | None = None) -> ParsedProduct:
        """解析商品链接，优先从本地结构化语料按 SKU 命中。"""
        fallback_info = fallback_info or {}
        notes: list[str] = []
        sku = self.extract_sku_from_url(product_url)

        if sku:
            matched = self.df[self.df["sku_text"] == sku]
            if not matched.empty:
                row = matched.iloc[0]
                notes.append("已通过链接 SKU 命中本地选品数据，直接使用整合后的结构化字段。")
                return ParsedProduct(
                    product_info=self._product_info_from_row(row),
                    source="sku_matched_structured_corpus",
                    sku=sku,
                    title=str(row.get("商品名称", "")),
                    notes=tuple(notes),
                )
            notes.append("链接 SKU 未在结构化语料中命中，转为网页标题解析。")
        else:
            notes.append("未能从链接中识别 SKU，转为网页标题解析。")

        html_text = ""
        title = ""
        analysis_text = ""
        price = None
        try:
            fetch_url = self._normalize_url_for_fetch(product_url)
            if not fetch_url:
                raise ValueError("未识别到可抓取的有效 URL。")
            html_text = self._fetch_url_text(fetch_url)
            title = self._extract_title_from_html(html_text)
            price = self._extract_price_from_html(html_text)
            analysis_text = "\n".join([title, html_text[:5000]])
            notes.append("已尝试抓取商品页 HTML 并解析标题。")
        except (URLError, TimeoutError, OSError, ValueError, InvalidURL) as exc:
            notes.append(f"网页抓取失败：{exc}")

        if not title:
            shared_title = self._extract_shared_title(product_url)
            if shared_title:
                title = shared_title
                notes.append("已从分享文案中提取商品标题。")
                analysis_text = "\n".join([analysis_text, title])

        fallback_title = str(fallback_info.get("title") or "").strip()
        if fallback_title:
            if not title:
                title = fallback_title
            analysis_text = "\n".join([analysis_text, fallback_title])
            notes.append("已使用手动输入商品标题作为兜底。")

        fallback_ocr_text = str(fallback_info.get("ocr_text") or "").strip()
        if fallback_ocr_text:
            analysis_text = "\n".join([analysis_text, fallback_ocr_text])
            notes.append("已使用上传截图 OCR 文本作为兜底。")

        has_manual_price = fallback_info.get("price") not in (None, "", 0, 0.0)
        should_render = (
            bool(self._normalize_url_for_fetch(product_url))
            and (not title or (price is None and not has_manual_price))
        )
        if should_render:
            rendered = self._render_product_page(product_url)
            notes.extend(rendered.get("notes", []))
            if not title and rendered.get("title"):
                title = str(rendered["title"])
            if price is None and rendered.get("price") is not None:
                price = rendered["price"]
            rendered_text = str(rendered.get("combined_text") or "")
            if rendered_text:
                analysis_text = "\n".join([analysis_text, rendered_text])

        if price is None and sku:
            price = self._fetch_jd_price(sku)
            if price is not None:
                notes.append("已通过京东公开价格端点解析价格。")

        if price is None and analysis_text:
            # 上传截图 OCR 或网页可见文本中如果包含“￥/售价/到手价”，也可作为价格兜底。
            price = self._extract_price_from_text(analysis_text)
            if price is not None:
                notes.append("已从网页可见文本或 OCR 文本中解析价格。")

        product_info = {
            "category": self._infer_category_from_title(analysis_text or title) if (analysis_text or title) else "",
            "weight_g": self._extract_weight_from_title(analysis_text or title) if (analysis_text or title) else None,
            "price": price,
            "brand": self._infer_brand_from_title(analysis_text or title) if (analysis_text or title) else "",
            "flavor": self._infer_tag_from_title(analysis_text or title, "flavor") if (analysis_text or title) else "",
            "package_type": self._infer_tag_from_title(analysis_text or title, "package_type") if (analysis_text or title) else "",
        }

        allowed_product_keys = {"category", "weight_g", "price", "brand", "flavor", "package_type"}
        for key, value in fallback_info.items():
            if key not in allowed_product_keys:
                continue
            if value not in (None, "", 0, 0.0):
                product_info[key] = value

        return ParsedProduct(
            product_info=product_info,
            source="web_title_inference",
            sku=sku,
            title=title,
            notes=tuple(notes),
        )

    def analyze_product_url(self, product_url: str, fallback_info: dict[str, Any] | None = None) -> dict[str, Any]:
        """从商品链接自动解析信息并执行分析。"""
        parsed = self.parse_product_url(product_url, fallback_info=fallback_info)
        info = parsed.product_info
        missing = [
            label
            for key, label in [("category", "品类"), ("weight_g", "重量"), ("price", "价格")]
            if self._is_missing_value(info.get(key))
        ]
        parsed_payload = {
            "source": parsed.source,
            "sku": parsed.sku,
            "title": parsed.title,
            "product_info": info,
            "notes": list(parsed.notes),
        }
        if missing:
            return {
                "error": f"链接解析未获得必要字段：{', '.join(missing)}。请补充后再分析。",
                "parsed_product": parsed_payload,
            }

        result = self.analyze_product(info)
        result["parsed_product"] = parsed_payload
        return result

    def resolve_category(self, category_query: str) -> CategoryMatch:
        """支持三级分类精确匹配，也支持二级分类、商品名、关键词模糊匹配。"""
        query = str(category_query or "").strip()
        if not query:
            raise ValueError("品类不能为空。")

        valid = self._valid_market_df()
        exact = valid[valid["三级分类"].astype(str) == query]
        if len(exact) > 0:
            return CategoryMatch(query=query, label=query, scope="三级分类精确匹配", sample_size=len(exact))

        contains_third = valid[valid["三级分类"].astype(str).str.contains(query, na=False, regex=False)]
        if len(contains_third) > 0:
            label = str(contains_third["三级分类"].value_counts().index[0])
            return CategoryMatch(query=query, label=label, scope="三级分类模糊匹配", sample_size=len(contains_third))

        mask = (
            valid["二级分类"].astype(str).str.contains(query, na=False, regex=False)
            | valid["商品名称"].astype(str).str.contains(query, na=False, regex=False)
            | valid["keyword_text"].astype(str).str.contains(query, na=False, regex=False)
        )
        fuzzy = valid[mask]
        if len(fuzzy) > 0:
            label = query
            return CategoryMatch(query=query, label=label, scope="二级分类/商品名/关键词模糊匹配", sample_size=len(fuzzy))

        raise ValueError(f"未在结构化语料中找到品类：{query}")

    def _category_data(self, match: CategoryMatch) -> pd.DataFrame:
        valid = self._valid_market_df()
        if match.scope == "三级分类精确匹配":
            return valid[valid["三级分类"].astype(str) == match.label].copy()
        if match.scope == "三级分类模糊匹配":
            return valid[valid["三级分类"].astype(str).str.contains(match.query, na=False, regex=False)].copy()
        mask = (
            valid["二级分类"].astype(str).str.contains(match.query, na=False, regex=False)
            | valid["商品名称"].astype(str).str.contains(match.query, na=False, regex=False)
            | valid["keyword_text"].astype(str).str.contains(match.query, na=False, regex=False)
        )
        return valid[mask].copy()

    @staticmethod
    def _price_band(price: float) -> str:
        bins = [0, 20, 50, 100, 200, 500, 1000, math.inf]
        labels = ["0-20元", "20-50元", "50-100元", "100-200元", "200-500元", "500-1000元", "1000元以上"]
        for low, high, label in zip(bins[:-1], bins[1:], labels):
            if low <= price < high:
                return label
        return "未知"

    def analyze_product(self, product_info: dict[str, Any]) -> dict[str, Any]:
        """主分析函数。product_info 至少包含 category、weight_g、price。"""
        category = str(product_info.get("category", "")).strip()
        brand = str(product_info.get("brand", "") or "").strip()
        flavor = str(product_info.get("flavor", "") or "").strip()
        package_type = str(product_info.get("package_type", "") or "").strip()

        try:
            weight_g = float(product_info.get("weight_g", 0))
            price = float(product_info.get("price", 0))
        except (TypeError, ValueError):
            return {"error": "价格和重量必须是数字。"}

        if not category or not math.isfinite(weight_g) or not math.isfinite(price) or weight_g <= 0 or price <= 0:
            return {"error": "缺少必要信息：品类、重量或价格。"}

        try:
            match = self.resolve_category(category)
        except ValueError as exc:
            return {
                "error": str(exc),
                "suggested_categories": self.available_categories()[:30],
            }

        cat_data = self._category_data(match)
        unit_price = price / weight_g
        context = {
            "category_match": match,
            "cat_data": cat_data,
            "unit_price": unit_price,
            "price": price,
            "weight_g": weight_g,
            "brand": brand,
            "flavor": flavor,
            "package_type": package_type,
        }

        return {
            "input_summary": {
                "品类输入": category,
                "匹配范围": match.scope,
                "用于分析的样本量": len(cat_data),
                "目标售价": f"{price:.2f}元",
                "目标规格": f"{weight_g:.0f}g",
                "目标单位价格": f"{unit_price:.4f}元/克",
                "品牌": brand or "未填写",
                "口味": flavor or "未填写",
                "包装": package_type or "未填写",
            },
            "market_position": self._analyze_market_position(context),
            "competitiveness": self._evaluate_competitiveness(context),
            "opportunities": self._identify_opportunities(context),
            "competitive_comparison": self._find_similar_products(context, limit=5),
            "corpus_insights": self._corpus_insights(context),
        }

    def _analyze_market_position(self, context: dict[str, Any]) -> dict[str, Any]:
        cat_data = context["cat_data"]
        unit_price = context["unit_price"]
        prices = cat_data["unit_price"].dropna()
        sample_size = len(prices)
        if sample_size < 5:
            return {"info": "样本不足，无法可靠判断市场定位。", "confidence": self._confidence(sample_size)}

        avg_price = float(prices.mean())
        q25 = float(prices.quantile(0.25))
        q50 = float(prices.quantile(0.50))
        q75 = float(prices.quantile(0.75))
        percentile = float((prices <= unit_price).mean() * 100)

        if percentile < 25:
            position = "低价/性价比定位"
        elif percentile > 75:
            position = "高端/高溢价定位"
        else:
            position = "主流价格带"

        ratio = unit_price / avg_price if avg_price > 0 else np.nan
        return {
            "市场定位": position,
            "价格百分位": f"高于该范围 {percentile:.1f}% 的商品",
            "目标单位价格": f"{unit_price:.4f}元/克",
            "市场均价": f"{avg_price:.4f}元/克",
            "市场中位数": f"{q50:.4f}元/克",
            "四分位区间": f"{q25:.4f}-{q75:.4f}元/克",
            "相对均价": f"{ratio:.2f}倍",
            "data_source": f"{self.data_path.name}；{context['category_match'].scope}；有效样本 {sample_size} 条",
            "method": "使用结构化重量字段 weight_from_text/weight_g 计算单位价格，并与同范围商品单位价格分布比较。",
            "confidence": self._confidence(sample_size),
            "limitation": "静态快照无法反映价格波动、真实利润和平台流量变化。",
        }

    def _evaluate_competitiveness(self, context: dict[str, Any]) -> dict[str, Any]:
        similar = self._similar_products_df(context, limit=20)
        unit_price = context["unit_price"]
        sample_size = len(similar)
        if sample_size < 3:
            return {"info": "可比商品不足，竞争力评分仅供参考。", "confidence": self._confidence(sample_size)}

        cheaper_than_count = int((similar["unit_price"] > unit_price).sum())
        beat_rate = cheaper_than_count / sample_size
        stars = max(1, min(5, int(round(beat_rate * 4)) + 1))

        brand = context["brand"]
        same_brand = similar[similar["analysis_brand"].astype(str).str.contains(brand, na=False, regex=False)] if brand else pd.DataFrame()
        promo_rate = float(similar["has_promotion_flag"].mean()) if sample_size else 0

        advantages: list[str] = []
        risks: list[str] = []
        if beat_rate >= 0.6:
            advantages.append(f"单位价格低于多数可比商品，优于约 {beat_rate:.0%} 的竞品。")
        else:
            risks.append(f"单位价格优势不明显，仅优于约 {beat_rate:.0%} 的竞品。")
        if brand and len(same_brand) >= 3:
            brand_median = float(same_brand["unit_price"].median())
            if unit_price <= brand_median:
                advantages.append(f"低于同品牌可比商品单位价格中位数 {brand_median:.4f} 元/克。")
            else:
                risks.append(f"高于同品牌可比商品单位价格中位数 {brand_median:.4f} 元/克。")
        if promo_rate >= 0.5:
            risks.append("可比商品促销占比较高，实际成交价可能低于页面现价。")

        return {
            "可比商品数量": sample_size,
            "竞争力排名": f"单位价格优于 {beat_rate:.0%} 的可比商品",
            "竞争力评分": "★" * stars + "☆" * (5 - stars),
            "优势": advantages or ["暂未发现明显价格优势。"],
            "风险": risks or ["未发现突出的结构性风险。"],
            "主要竞争品牌": similar["analysis_brand"].replace("", np.nan).dropna().value_counts().head(3).index.tolist(),
            "data_source": f"从 {self.data_path.name} 中按品类、规格接近度、口味/包装标签筛选可比商品。",
            "method": "以单位价格越低越有竞争力为基础，并结合促销占比、同品牌中位价做解释。",
            "confidence": self._confidence(sample_size),
            "limitation": "缺少成本、券后价和转化率，因此评分代表价格相对竞争力，不代表利润率。",
        }

    def _identify_opportunities(self, context: dict[str, Any]) -> dict[str, Any]:
        cat_data = context["cat_data"]
        price = context["price"]
        sample_size = len(cat_data)
        if sample_size < 10:
            return {"info": "该范围样本较少，机会分析可能不稳定。", "confidence": self._confidence(sample_size)}

        bins = [0, 20, 50, 100, 200, 500, 1000, math.inf]
        labels = ["0-20元", "20-50元", "50-100元", "100-200元", "200-500元", "500-1000元", "1000元以上"]
        cat_data = cat_data.copy()
        cat_data["price_band"] = pd.cut(cat_data["analysis_price"], bins=bins, labels=labels, right=False)
        distribution = cat_data["price_band"].value_counts().reindex(labels, fill_value=0)

        opportunities: list[str] = []
        risks: list[str] = []
        total = int(distribution.sum())
        for band, count in distribution.items():
            share = count / total if total else 0
            band_data = cat_data[cat_data["price_band"] == band]
            avg_sales = float(band_data["sales_metric"].mean()) if len(band_data) else 0
            if 0 < share < 0.10 and avg_sales >= cat_data["sales_metric"].median():
                opportunities.append(f"{band} 商品密度低且平均随机销量不低，可能存在细分机会。")
            elif share > 0.30:
                risks.append(f"{band} 商品集中度高，竞争更拥挤。")

        target_band = self._price_band(price)
        return {
            "价格分布": {str(k): int(v) for k, v in distribution.items()},
            "您的价格区间": target_band,
            "机会点": opportunities[:3] or ["未发现明显低密度且高销售的价格空白带。"],
            "风险提示": risks[:3] or ["各价格带未出现特别集中的竞争风险。"],
            "data_source": f"{self.data_path.name} 中匹配范围内 {sample_size} 条商品的现价与随机销量。",
            "method": "按页面现价分桶，寻找商品数量占比低但平均随机销量不低的价格带。",
            "confidence": self._confidence(sample_size),
            "limitation": "机会判断是供选品讨论的相对分布信号，不等同于需求预测。",
        }

    def _corpus_insights(self, context: dict[str, Any]) -> dict[str, Any]:
        cat_data = context["cat_data"]
        sample_size = len(cat_data)
        top_keywords = (
            pd.Series([word for words in cat_data["keyword_list"] for word in words])
            .value_counts()
            .head(12)
            .to_dict()
        )
        return {
            "常见品牌": cat_data["analysis_brand"].replace("", np.nan).dropna().value_counts().head(5).to_dict(),
            "常见口味": cat_data["flavor"].replace("", np.nan).dropna().value_counts().head(5).to_dict(),
            "常见包装": cat_data["package_type"].replace("", np.nan).dropna().value_counts().head(5).to_dict(),
            "高频关键词": top_keywords,
            "礼品装占比": f"{cat_data['is_gift'].mean():.1%}" if sample_size else "未知",
            "促销商品占比": f"{cat_data['has_promotion_flag'].mean():.1%}" if sample_size else "未知",
            "data_source": f"直接来自 {self.data_path.name} 的结构化字段 flavor、package_type、keywords、is_gift、has_coupon。",
            "method": "对结构化抽取标签和关键词做频次统计，用于解释该品类的主流卖点表达。",
            "confidence": self._confidence(sample_size),
        }

    def _similar_products_df(self, context: dict[str, Any], limit: int = 10) -> pd.DataFrame:
        cat_data = context["cat_data"].copy()
        cat_data = cat_data.drop_duplicates(subset=["商品名称", "analysis_price", "analysis_weight_g"])
        target_weight = context["weight_g"]
        target_unit_price = context["unit_price"]
        target_flavor = context["flavor"]
        target_package = context["package_type"]

        cat_data["weight_gap_ratio"] = (cat_data["analysis_weight_g"] - target_weight).abs() / target_weight
        cat_data["unit_price_gap"] = (cat_data["unit_price"] - target_unit_price).abs()
        cat_data["tag_bonus"] = 0.0
        if target_flavor:
            cat_data.loc[cat_data["flavor"].str.contains(target_flavor, na=False, regex=False), "tag_bonus"] -= 0.20
        if target_package:
            cat_data.loc[cat_data["package_type"].str.contains(target_package, na=False, regex=False), "tag_bonus"] -= 0.10

        comparable = cat_data[cat_data["weight_gap_ratio"] <= 1.0].copy()
        if len(comparable) < min(5, len(cat_data)):
            comparable = cat_data.copy()
        comparable["similarity_score"] = comparable["weight_gap_ratio"] + comparable["unit_price_gap"] + comparable["tag_bonus"]
        return comparable.sort_values(["similarity_score", "unit_price"]).head(limit)

    def _find_similar_products(self, context: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
        similar = self._similar_products_df(context, limit=limit)
        rows: list[dict[str, Any]] = []
        for _, row in similar.iterrows():
            rows.append(
                {
                    "品牌": row.get("analysis_brand", ""),
                    "商品名称": row.get("商品名称", ""),
                    "现价": round(float(row.get("analysis_price", 0)), 2),
                    "重量_g": round(float(row.get("analysis_weight_g", 0)), 0),
                    "单位价格_元每克": round(float(row.get("unit_price", 0)), 4),
                    "口味": row.get("flavor", ""),
                    "包装": row.get("package_type", ""),
                    "规格": row.get("specification", ""),
                    "促销": bool(row.get("has_promotion_flag", False)),
                }
            )
        return rows

    def recommend_by_category(self, category: str, top_n: int = 10) -> pd.DataFrame:
        """按价格、随机销量和结构化质量给出可解释的参考商品列表。"""
        match = self.resolve_category(category)
        cat_data = self._category_data(match).copy()
        if cat_data.empty:
            return pd.DataFrame()
        cat_data = cat_data.drop_duplicates(subset=["商品名称", "analysis_price", "analysis_weight_g"])

        cat_data["price_score"] = 1 - cat_data["unit_price"].rank(pct=True)
        cat_data["sales_score"] = cat_data["sales_metric"].rank(pct=True)
        cat_data["structure_score"] = (
            cat_data["brand_match_status"].eq("consistent").astype(float) * 0.4
            + cat_data["weight_match_status"].eq("consistent").astype(float) * 0.4
            + cat_data["keyword_list"].apply(lambda words: min(len(words), 8) / 8) * 0.2
        )
        cat_data["selection_score"] = (
            cat_data["price_score"] * 0.45
            + cat_data["sales_score"] * 0.35
            + cat_data["structure_score"] * 0.20
        )
        columns = [
            "analysis_brand", "商品名称", "analysis_price", "analysis_weight_g", "unit_price",
            "sales_metric", "flavor", "package_type", "specification", "selection_score",
        ]
        optional_columns = [
            "jd_review_nonempty",
            "jd_negative_nonempty",
            "mmb_lowest_price",
            "mmb_lowest_date",
            "mmb_status",
        ]
        columns.extend([column for column in optional_columns if column in cat_data.columns])
        result = cat_data.sort_values("selection_score", ascending=False).head(top_n)[columns].copy()
        return result.rename(
            columns={
                "analysis_brand": "品牌",
                "analysis_price": "现价",
                "analysis_weight_g": "重量_g",
                "unit_price": "单位价格_元每克",
                "sales_metric": "随机销量",
                "flavor": "口味",
                "package_type": "包装",
                "specification": "规格",
                "selection_score": "选品参考分",
                "jd_review_nonempty": "京东评论样本数",
                "jd_negative_nonempty": "京东差评样本数",
                "mmb_lowest_price": "历史低价",
                "mmb_lowest_date": "历史低价日期",
                "mmb_status": "历史价状态",
            }
        )


def demo() -> None:
    """命令行示例，便于快速验收。"""
    assistant = ProductSelectionAssistant()
    product = {"category": "腰果", "weight_g": 300, "price": 55.8, "brand": "良品铺子", "flavor": "蟹黄味", "package_type": "袋装"}
    result = assistant.analyze_product(product)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    demo()
