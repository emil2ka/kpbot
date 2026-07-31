import asyncio
import unittest
from app.china import build_search_urls, canonicalize_url, detect_platform, extract_item_id, extract_price_hint, extract_url_from_text, parse_china_url


class TestChinaIntegration(unittest.TestCase):
    def test_detect_platform(self):
        self.assertEqual(detect_platform("https://detail.1688.com/offer/678912345.html"), "1688")
        self.assertEqual(detect_platform("https://item.taobao.com/item.htm?id=123456"), "Taobao")
        self.assertEqual(detect_platform("https://detail.tmall.com/item.htm?id=999888"), "Tmall")
        self.assertEqual(detect_platform("https://www.alibaba.com/product-detail/item_111222.html"), "Alibaba")
        self.assertEqual(detect_platform("https://mobile.yangkeduo.com/goods.html?goods_id=555666"), "Pinduoduo")
        self.assertEqual(detect_platform("https://item.jd.com/1000293848.html"), "JD")
        self.assertEqual(detect_platform("https://2.taobao.com/item.htm?id=777888"), "Xianyu")
        self.assertEqual(detect_platform("https://dewu.com/product/12345"), "Dewu/Poizon")
        self.assertEqual(detect_platform("https://example.com/item"), "Other")

    def test_extract_url_and_price_from_pdd_share_text(self):
        pdd_snippet = "【拼多多】https://mobile.yangkeduo.com/goods.html?goods_id=10293848 19.9元包邮！⚡️"
        clean_url = extract_url_from_text(pdd_snippet)
        price_hint = extract_price_hint(pdd_snippet)

        self.assertEqual(clean_url, "https://mobile.yangkeduo.com/goods.html?goods_id=10293848")
        self.assertEqual(price_hint, 19.9)
        self.assertEqual(detect_platform(pdd_snippet), "Pinduoduo")
        self.assertEqual(extract_item_id(pdd_snippet), "10293848")

    def test_extract_item_id(self):
        self.assertEqual(extract_item_id("https://detail.1688.com/offer/678912345.html"), "678912345")
        self.assertEqual(extract_item_id("https://item.taobao.com/item.htm?id=123456789"), "123456789")
        self.assertEqual(extract_item_id("https://mobile.yangkeduo.com/goods.html?goods_id=987654321"), "987654321")
        self.assertEqual(extract_item_id("https://item.jd.com/1000293848.html"), "1000293848")

    def test_canonicalize_url(self):
        url_1688 = canonicalize_url("1688", "678912345", "https://detail.1688.com/offer/678912345.html?spm=a2615.1234")
        self.assertEqual(url_1688, "https://detail.1688.com/offer/678912345.html")

        url_pdd = canonicalize_url("Pinduoduo", "10293848", "https://mobile.yangkeduo.com/goods.html?goods_id=10293848&refer_share_uid=123")
        self.assertEqual(url_pdd, "https://mobile.yangkeduo.com/goods.html?goods_id=10293848")

    def test_build_search_urls(self):
        urls = build_search_urls("无线耳机")
        self.assertIn("1688.com", urls["1688"])
        self.assertIn("yangkeduo.com", urls["pinduoduo"])
        self.assertIn("taobao.com", urls["taobao"])
        self.assertIn("jd.com", urls["jd"])
        self.assertIn("xianyu.com", urls["xianyu"])

    def test_parse_china_url_pdd(self):
        res = asyncio.run(parse_china_url("【拼多多】https://mobile.yangkeduo.com/goods.html?goods_id=10293848 15元包邮"))
        self.assertEqual(res.platform, "Pinduoduo")
        self.assertEqual(res.item_id, "10293848")
        self.assertEqual(res.canonical_url, "https://mobile.yangkeduo.com/goods.html?goods_id=10293848")


if __name__ == "__main__":
    unittest.main()


