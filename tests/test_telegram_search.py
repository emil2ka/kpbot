import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.telegram_search import TelegramTrendSignal, fetch_telegram_channel_mentions, fetch_telegram_trend_signal


class TestTelegramSearch(unittest.TestCase):
    @patch("httpx.AsyncClient.get")
    def test_fetch_telegram_channel_mentions(self, mock_get):
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <div class="tgme_widget_message " data-post="kaspiseller/123">
            <div class="tgme_widget_message_text">Ищем маржинальный товар смарт часы для закупа в Китае</div>
            <span class="tgme_widget_message_views">2.5K</span>
            <time datetime="2026-08-01T12:00:00Z"></time>
        </div>
        """
        mock_get.return_value = mock_resp

        posts = asyncio.run(fetch_telegram_channel_mentions("kaspiseller", "смарт часы"))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].channel, "kaspiseller")
        self.assertEqual(posts[0].message_id, 123)
        self.assertEqual(posts[0].views, "2.5K")

    @patch("app.telegram_search.fetch_telegram_channel_mentions")
    def test_fetch_telegram_trend_signal(self, mock_fetch):
        from app.telegram_search import TelegramPostInfo
        mock_fetch.return_value = [
            TelegramPostInfo(
                channel="kaspiseller",
                message_id=1,
                text="Качественные автотовары",
                views="1000",
            )
        ]
        res = asyncio.run(fetch_telegram_trend_signal("автотовары", channels=["kaspiseller"]))
        self.assertIsInstance(res, TelegramTrendSignal)
        self.assertEqual(res.status, "live")
        self.assertEqual(res.post_count, 1)
        self.assertIn("kaspiseller", res.channels_found)


if __name__ == "__main__":
    unittest.main()

