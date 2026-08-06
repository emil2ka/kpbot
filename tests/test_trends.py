import unittest
from datetime import datetime, timezone

from app.telegram_search import TelegramTrendSignal
from app.tiktok import TikTokTrendSignal
from app.trends import build_trend_report
from app.youtube_trends import YouTubeTrendSignal


class TestTrendReports(unittest.TestCase):
    def test_early_history_is_labelled_as_hypothesis(self):
        signal = YouTubeTrendSignal(
            query="термос", observed_at=datetime.now(timezone.utc), video_count_30d=12,
            video_count_7d=5, total_views=1000, median_views_per_day=50,
            status="live", source_note="test",
        )
        report = build_trend_report(
            {"kaspi_url": "https://kaspi.kz/shop/p/test/", "title": "Термос"},
            [
                {"observed_at": "2026-08-01T00:00:00+00:00", "price_kzt": 10000, "review_count": 10, "seller_count": 2},
                {"observed_at": "2026-08-02T00:00:00+00:00", "price_kzt": 10000, "review_count": 18, "seller_count": 3},
            ],
            signal,
        )
        self.assertEqual(report.review_change, 8)
        self.assertEqual(report.confidence_label, "средняя")
        self.assertTrue(any("короче 7" in item for item in report.caveats))

    def test_missing_youtube_cannot_create_a_high_confidence_trend(self):
        signal = YouTubeTrendSignal(query="товар", observed_at=datetime.now(timezone.utc), status="not_configured", source_note="missing key")
        snapshots = [{"observed_at": f"2026-08-{day:02d}T00:00:00+00:00", "price_kzt": 10000, "review_count": day, "seller_count": 2} for day in range(1, 8)]
        report = build_trend_report({"kaspi_url": "https://kaspi.kz/shop/p/test/", "title": "Товар"}, snapshots, signal)
        self.assertLess(report.confidence_score, 70)
        self.assertTrue(any("YouTube" in item for item in report.caveats))

    def test_multiplatform_tiktok_and_telegram_boosts_score(self):
        yt_signal = YouTubeTrendSignal(query="товар", observed_at=datetime.now(timezone.utc), video_count_7d=3, status="live", source_note="test")
        tt_signal = TikTokTrendSignal(query="товар", observed_at=datetime.now(timezone.utc), video_count=5, total_views=15000, status="live", source_note="test")
        tg_signal = TelegramTrendSignal(query="товар", observed_at=datetime.now(timezone.utc), post_count=3, channels_found=["kaspiseller"], status="live", source_note="test")

        snapshots = [{"observed_at": f"2026-08-{day:02d}T00:00:00+00:00", "price_kzt": 10000, "review_count": day * 5, "seller_count": 1} for day in range(1, 8)]
        report = build_trend_report(
            {"kaspi_url": "https://kaspi.kz/shop/p/test/", "title": "Товар"},
            snapshots,
            yt_signal,
            tiktok=tt_signal,
            telegram=tg_signal,
        )
        self.assertGreaterEqual(report.confidence_score, 70)
        self.assertEqual(report.confidence_label, "высокая")
        self.assertTrue(any("TikTok" in item for item in report.evidence))
        self.assertTrue(any("Telegram" in item for item in report.evidence))

