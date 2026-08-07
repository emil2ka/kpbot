import asyncio
import unittest

from bs4 import BeautifulSoup

from app.kaspi import KaspiExtractionError, _extract_json_ld, _is_kaspi_host, _number, fetch_product


class TestKaspiSafetyAndParsing(unittest.TestCase):
    def test_accepts_only_exact_kaspi_hosts(self):
        self.assertTrue(_is_kaspi_host("kaspi.kz"))
        self.assertTrue(_is_kaspi_host("shop.kaspi.kz"))
        self.assertFalse(_is_kaspi_host("kaspi.kz.evil.example"))
        self.assertFalse(_is_kaspi_host("notkaspi.kz"))
        self.assertFalse(_is_kaspi_host(None))

    def test_rejects_lookalike_and_insecure_urls_before_request(self):
        for url in ("https://kaspi.kz.evil.example/item", "http://kaspi.kz/shop/p/item"):
            with self.assertRaises(KaspiExtractionError):
                asyncio.run(fetch_product(url))

    def test_extracts_product_json_ld_among_other_schema_blocks(self):
        soup = BeautifulSoup(
            '''<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>
            <script type="application/ld+json">{"@type":"Product","name":"Термос","offers":{"price":"8990"},"aggregateRating":{"ratingValue":"4.8","reviewCount":"123"}}</script>''',
            "html.parser",
        )
        product = _extract_json_ld(soup)
        self.assertEqual(product["name"], "Термос")
        self.assertEqual(_number(str(product["offers"]["price"])), 8990)
        self.assertEqual(_number(str(product["aggregateRating"]["reviewCount"])), 123)

    def test_extracts_product_json_ld_from_graph(self):
        soup = BeautifulSoup(
            '''<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
            {"@type":"WebPage"},{"@type":["Product","Thing"],"name":"Термокружка"}]}</script>''',
            "html.parser",
        )
        self.assertEqual(_extract_json_ld(soup)["name"], "Термокружка")

    def test_number_parser_handles_kaspi_formatting(self):
        self.assertEqual(_number("8 990 ₸"), 8990)
        self.assertIsNone(_number("нет данных"))


if __name__ == "__main__":
    unittest.main()
