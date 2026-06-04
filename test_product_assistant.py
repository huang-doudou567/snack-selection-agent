# -*- coding: utf-8 -*-
"""ProductSelectionAssistant 的轻量测试用例。"""

import unittest
from product_assistant import ProductSelectionAssistant


class ProductAssistantTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant = ProductSelectionAssistant()

    def test_analyze_product_with_structured_corpus(self) -> None:
        result = self.assistant.analyze_product(
            {
                "category": "腰果",
                "weight_g": 300,
                "price": 55.8,
                "brand": "良品铺子",
                "flavor": "蟹黄味",
                "package_type": "袋装",
            }
        )

        self.assertNotIn("error", result)
        self.assertGreater(result["input_summary"]["用于分析的样本量"], 0)
        self.assertIn("market_position", result)
        self.assertIn("competitiveness", result)
        self.assertIn("competitive_comparison", result)
        self.assertIsInstance(result["competitive_comparison"], list)

    def test_recommend_by_category_returns_rows(self) -> None:
        result = self.assistant.recommend_by_category("腰果", top_n=3)

        self.assertGreater(len(result), 0)
        self.assertIn("单位价格_元每克", result.columns)
        self.assertIn("选品参考分", result.columns)

    def test_analyze_product_url_matches_structured_sku(self) -> None:
        sample = self.assistant.df[self.assistant.df["sku_text"].astype(str).str.len() > 0].iloc[0]
        sku = sample["sku_text"]
        result = self.assistant.analyze_product_url(f"https://item.jd.com/{sku}.html")

        self.assertNotIn("error", result)
        self.assertEqual(result["parsed_product"]["source"], "sku_matched_structured_corpus")
        self.assertEqual(result["parsed_product"]["sku"], sku)

    def test_jd_share_text_extracts_clean_short_url(self) -> None:
        share_text = (
            "//3.cn/2-ObrTbe?jkl=@U5OlD6VEhxs0@ MF8335 "
            "「三只松鼠巨型零食大礼包送女友」 点击链接直接打开 或者复制文案打开京东"
        )

        self.assertEqual(
            ProductSelectionAssistant._extract_url_candidate(share_text),
            "//3.cn/2-ObrTbe?jkl=@U5OlD6VEhxs0@",
        )
        self.assertEqual(
            ProductSelectionAssistant._normalize_url_for_fetch(share_text),
            "https://3.cn/2-ObrTbe?jkl=@U5OlD6VEhxs0@",
        )

    def test_dirty_share_text_does_not_crash_url_parser(self) -> None:
        share_text = (
            "//3.cn/2-ObrTbe?jkl=@U5OlD6VEhxs0@ MF8335 "
            "「三只松鼠巨型零食大礼包送女友」 点击链接直接打开 或者复制文案打开京东"
        )
        parsed = self.assistant.parse_product_url(share_text)

        self.assertEqual(parsed.source, "web_title_inference")
        self.assertIsInstance(parsed.notes, tuple)

    def test_taobao_url_keeps_only_item_id(self) -> None:
        taobao_url = (
            "https://item.taobao.com/item.htm?id=123456789012"
            "&spm=a21n57.1.hoverItem.2&ut_sk=abc&foo=bar"
        )

        self.assertEqual(
            ProductSelectionAssistant.clean_taobao_url(taobao_url),
            "https://item.taobao.com/item.htm?id=123456789012",
        )
        self.assertEqual(
            ProductSelectionAssistant._normalize_url_for_fetch(taobao_url),
            "https://item.taobao.com/item.htm?id=123456789012",
        )

    def test_tmall_url_keeps_only_item_id(self) -> None:
        tmall_url = "https://detail.tmall.com/item.htm?id=998877665544&abbucket=1&skuId=123"

        self.assertEqual(
            ProductSelectionAssistant.clean_taobao_url(tmall_url),
            "https://detail.tmall.com/item.htm?id=998877665544",
        )

    def test_taobao_share_text_extracts_title_and_clean_url(self) -> None:
        share_text = (
            "复制这段内容后打开淘宝 https://item.taobao.com/item.htm?id=123456789012"
            "&spm=a21n57.1.hoverItem.2 「三只松鼠巨型零食大礼包送女友」"
        )

        self.assertEqual(
            ProductSelectionAssistant._normalize_url_for_fetch(share_text),
            "https://item.taobao.com/item.htm?id=123456789012",
        )
        self.assertEqual(
            ProductSelectionAssistant._extract_shared_title(share_text),
            "三只松鼠巨型零食大礼包送女友",
        )

    def test_extract_price_from_visible_text(self) -> None:
        text = "商品促销信息 到手价 ￥59.90 规格 750g"
        self.assertEqual(ProductSelectionAssistant._extract_price_from_text(text), 59.9)

    def test_browser_render_missing_dependency_does_not_crash(self) -> None:
        result = ProductSelectionAssistant._render_product_page("不是一个链接")
        self.assertIn("notes", result)


if __name__ == "__main__":
    unittest.main()
