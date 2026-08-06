import asyncio
import unittest

from app.china_scraper import deep_extract_china_product
from app.currency import get_cny_to_kzt_rate, set_cached_cny_rate
from app.models import ProcurementItem
from app.procurement import generate_procurement_sheet


class TestChinaDeepFeatures(unittest.TestCase):
    def test_currency_rate_cache(self):
        set_cached_cny_rate(73.5)
        rate = asyncio.run(get_cny_to_kzt_rate())
        self.assertEqual(rate, 73.5)

    def test_deep_extract_china_product(self):
        url = "https://detail.1688.com/offer/678912345.html"
        res = asyncio.run(deep_extract_china_product(url))

        self.assertEqual(res.platform, "1688")
        self.assertEqual(res.item_id, "678912345")
        self.assertIsInstance(res.price_tiers, list)
        self.assertIsInstance(res.sku_variants, list)
        self.assertTrue(res.data_notes)

    def test_generate_procurement_sheet(self):
        items = [
            ProcurementItem(
                product_title_ru="Детский термос 500мл",
                product_title_zh="儿童保温杯 500ml",
                supplier_url="https://detail.1688.com/offer/678912345.html",
                platform="1688",
                sku_name="Черный стандарт / 500мл",
                quantity=100,
                target_price_cny=15.0,
                total_cny=1500.0,
                notes="Проверить гравировку",
            ),
            ProcurementItem(
                product_title_ru="Беспроводные наушники",
                product_title_zh="无线蓝牙耳机",
                supplier_url="https://mobile.yangkeduo.com/goods.html?goods_id=10293848",
                platform="Pinduoduo",
                sku_name="Белый глянец",
                quantity=50,
                target_price_cny=20.0,
                total_cny=1000.0,
            ),
        ]

        sheet = asyncio.run(generate_procurement_sheet(items, custom_cny_rate=72.0))

        self.assertEqual(sheet.total_items_count, 2)
        self.assertEqual(sheet.total_quantity, 150)
        self.assertEqual(sheet.total_amount_cny, 2500.0)
        self.assertEqual(sheet.total_amount_kzt, 180000.0)  # 2500 * 72
        self.assertIn("\ufeff", sheet.csv_content)  # Check UTF-8 BOM
        self.assertIn("Бланк закупки", sheet.html_preview)


    def test_live_search_urls(self):
        from app.china_live import build_live_1688_image_search_url, build_live_1688_search_url, build_live_pdd_search_url

        url_1688 = build_live_1688_search_url("保温杯", max_price_cny=30.0, factory_only=True)
        url_pdd = build_live_pdd_search_url("保温杯", max_price_cny=30.0)
        url_img = build_live_1688_image_search_url("https://kaspi.kz/photo.jpg")

        self.assertIn("s.1688.com/selloffer/offer_search.htm", url_1688)
        self.assertIn("feature=gongying", url_1688)
        self.assertIn("priceFilter.endPrice=30.0", url_1688)
        self.assertIn("mobile.yangkeduo.com/search_result.html", url_pdd)
        self.assertIn("max_price=30.0", url_pdd)
        self.assertIn("image_search.htm?imageUrl=", url_img)


    def test_cargo_label_generation(self):
        from app.cargo_label import CargoLabelRequest, generate_cargo_label

        req = CargoLabelRequest(
            consignee_name="Асан Алиев",
            city="Алматы",
            cargo_code="KZ-ALM-7788",
            product_title_zh="儿童保温杯 500ml",
            carton_number=1,
            total_cartons=3,
            quantity_per_carton=50,
            weight_kg=18.5,
            is_fragile=True,
        )
        res = generate_cargo_label(req)
        self.assertIn("KAZAKHSTAN CARGO SHIPPING MARK (箱唛)", res.label_text_cn_ru)
        self.assertIn("KZ-ALM-7788", res.label_text_cn_ru)
        self.assertIn("易碎物品", res.label_text_cn_ru)
        self.assertIn("<html", res.html_printable)

    def test_niche_trends_finder(self):
        from app.niche_finder import find_trending_sourcing_niches

        res = asyncio.run(find_trending_sourcing_niches())
        self.assertEqual(len(res.opportunities), 3)
        self.assertGreater(res.opportunities[0].estimated_margin_percent, 30.0)
        self.assertIn("1688.com", res.opportunities[0].direct_1688_url)
        self.assertIn("гипотезы", res.summary_ru.lower())

    def test_cargo_quotes_are_marked_as_estimates(self):
        from app.economics import compare_cargo
        from app.models import CargoQuoteRequest

        quotes = compare_cargo(CargoQuoteRequest(
            actual_weight_kg=10, length_cm=30, width_cm=30, height_cm=30,
        ))
        self.assertTrue(all(quote.is_estimate for quote in quotes))
        self.assertTrue(all(quote.pricing_note for quote in quotes))


if __name__ == "__main__":
    unittest.main()

