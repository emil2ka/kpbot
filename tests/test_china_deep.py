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


if __name__ == "__main__":
    unittest.main()
