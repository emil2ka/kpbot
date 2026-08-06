import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.tiktok import TikTokTrendSignal, extract_tiktok_hydration_data, fetch_tiktok_trend_signal


class TestTikTokTrends(unittest.TestCase):
    def test_extract_hydration_data(self):
        html = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{"__DEFAULT_SCOPE__": {"webapp.search-detail": {"data": []}}}</script>'
        data = extract_tiktok_hydration_data(html)
        self.assertIsNotNone(data)
        self.assertIn("__DEFAULT_SCOPE__", data)

    @patch("httpx.AsyncClient.get")
    def test_fetch_tiktok_trend_signal_mock(self, mock_get):
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
        {
            "__DEFAULT_SCOPE__": {
                "webapp.search-detail": {
                    "data": [
                        {
                            "item": {
                                "id": "7123456789012345678",
                                "desc": "Отличный товар #kaspi #рек",
                                "author": {"uniqueId": "seller_kz"},
                                "stats": {"playCount": 1500, "diggCount": 200}
                            }
                        }
                    ]
                }
            }
        }
        </script>
        """
        mock_get.return_value = mock_resp

        res = asyncio.run(fetch_tiktok_trend_signal("беспроводные наушники"))
        self.assertIsInstance(res, TikTokTrendSignal)
        self.assertEqual(res.status, "live")
        self.assertEqual(res.video_count, 1)
        self.assertEqual(res.total_views, 1500)
        self.assertIn("kaspi", res.top_hashtags)


if __name__ == "__main__":
    unittest.main()

