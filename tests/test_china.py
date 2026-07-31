import asyncio
import unittest
from app.china import build_image_search_url, build_search_urls, canonicalize_url, detect_platform, extract_item_id, extract_price_hint, extract_url_from_text, normalize_search_keywords, parse_china_url
from app.china_api import get_china_data_provider
from app.economics import calculate_target_cny_price


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

    def test_calculate_target_cny_price(self):
        target_cny = calculate_target_cny_price(8990.0, target_margin_percent=35.0)
        self.assertGreater(target_cny, 0.0)
        # 8990 * 0.35 = 3146.5 profit. Marketplace 12% = 1078.8. Reserve 5% = 449.5. Cargo = 1200. Pack = 150.
        # Max purchase = (8990 - 3146.5 - 1078.8 - 449.5 - 1200 - 150) / 72 = 2965.2 / 72 = 41.18 CNY

    def test_build_search_urls_with_max_price(self):
        urls = build_search_urls("无线耳机", max_price_cny=42.0)
        self.assertIn("priceFilter.endPrice=42.0", urls["1688"])
        self.assertIn("max_price=42.0", urls["pinduoduo"])

    def test_build_image_search_url(self):
        img_url = build_image_search_url("https://resources.cdn-kaspi.kz/img/m/p/h88/h55/12345.jpg")
        self.assertIn("image_search.htm?imageUrl=", img_url)

    def test_normalize_broken_chinese_query(self):
        self.assertEqual(normalize_search_keywords("&#65533;\ufffd"), "商品 批发")
        self.assertEqual(normalize_search_keywords("  数据线   批发 "), "数据线 批发")

    def test_china_data_provider(self):
        provider = get_china_data_provider()
        res = asyncio.run(
            provider.search_suppliers(
                title_ru="Детский термос 500мл",
                keywords_zh="儿童保温杯 500ml",
                sale_price_kzt=8990.0,
                image_url="https://kaspi.kz/image.jpg",
            )
        )
        self.assertGreater(res.target_cny_price, 0.0)
        self.assertIn("1688.com", res.search_urls["1688"])
        self.assertIsNotNone(res.image_search_url)


if __name__ == "__main__":
    unittest.main()
