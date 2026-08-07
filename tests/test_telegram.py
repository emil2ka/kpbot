import unittest
from unittest.mock import AsyncMock, patch

from app.models import ChinaIdea, ChinaIdeaResearch, KaspiProduct
from app.services import SourcingIntent
from app import telegram


def message_update(chat_id: int, text: str) -> dict:
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def callback_update(chat_id: int, value: str) -> dict:
    return {"callback_query": {"id": f"cb-{value}", "data": value, "message": {"chat": {"id": chat_id}}}}


class TestTelegramUserJourneys(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        telegram._sessions.clear()
        telegram._local_items.clear()
        telegram._processed_updates.clear()
        self.messages = []

    async def capture_call(self, method, payload):
        if method == "sendMessage":
            self.messages.append(payload)

    async def test_start_prioritizes_idea_discovery(self):
        with patch("app.telegram._call", new=self.capture_call):
            await telegram.handle_update(message_update(42, "/start"))
        markup = self.messages[-1]["reply_markup"]["inline_keyboard"]
        labels = [button["text"] for row in markup for button in row]
        self.assertIn("🔍 Найти товар", labels)
        self.assertIn("🔗 Проверить Kaspi", labels)

    async def test_plain_product_text_starts_market_analysis_without_menu_choice(self):
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram._run_market_scan", new=AsyncMock()) as scan:
            await telegram.handle_update(message_update(42, "органайзер для кухни"))
        scan.assert_awaited_once_with(42, "органайзер для кухни")

    async def test_broad_request_gets_an_ai_hypothesis_instead_of_a_failed_kaspi_search(self):
        research = ChinaIdeaResearch(
            interpretation="Подходит для теста.",
            ideas=[
                ChinaIdea(title_ru="Органайзер для ящиков", chinese_keywords="抽屉收纳盒", why_interesting="Компактный", risk_to_check="Размер"),
                ChinaIdea(title_ru="Крючки", chinese_keywords="挂钩", why_interesting="Лёгкие", risk_to_check="Клей"),
                ChinaIdea(title_ru="Контейнеры", chinese_keywords="收纳盒", why_interesting="Понятные", risk_to_check="Материал"),
            ],
        )
        product = KaspiProduct(source_url="https://kaspi.kz/shop/p/test-1/", title="Органайзер", price_kzt=8990, review_count=42, seller_count=2, rating=4.7)
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram.classify_sourcing_request", new=AsyncMock(return_value=SourcingIntent(kind="idea_discovery", query="что то для дома"))), patch("app.telegram.generate_china_ideas", new=AsyncMock(return_value=research)), patch("app.telegram.search_products", new=AsyncMock(return_value=[product])) as search, patch("app.telegram._send_supplier_leads", new=AsyncMock()) as supplier_leads:
            await telegram.handle_update(message_update(42, "что то для дома"))
        self.assertEqual(search.await_count, 3)
        self.assertEqual(telegram._sessions[42]["context"]["idea"]["title_ru"], "Органайзер для ящиков")
        self.assertIsNone(telegram._sessions[42]["stage"])
        self.assertTrue(any("Рекомендация для первичной проверки" in message["text"] for message in self.messages))
        supplier_leads.assert_awaited_once_with(42, telegram._sessions[42]["context"]["idea"], 8990)

    async def test_yes_after_hypothesis_searches_the_suggested_product(self):
        telegram._sessions[42] = {
            "stage": "suggested_idea_confirmation", "profile": {}, "ideas": [],
            "context": {"idea": {"title_ru": "Органайзер для ящиков"}},
        }
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram._run_market_scan", new=AsyncMock()) as scan:
            await telegram.handle_update(message_update(42, "давай"))
        scan.assert_awaited_once_with(42, "Органайзер для ящиков")

    async def test_another_product_after_hypothesis_is_understood_as_a_new_query(self):
        telegram._sessions[42] = {
            "stage": "suggested_idea_confirmation", "profile": {}, "ideas": [],
            "context": {"idea": {"title_ru": "Органайзер для ящиков"}},
        }
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram._run_market_scan", new=AsyncMock()) as scan:
            await telegram.handle_update(message_update(42, "держатель для телефона"))
        scan.assert_awaited_once_with(42, "держатель для телефона")

    async def test_trend_request_is_routed_to_trend_flow_not_kaspi_search(self):
        with patch("app.telegram._call", new=self.capture_call), patch(
            "app.telegram.classify_sourcing_request",
            new=AsyncMock(return_value=SourcingIntent(kind="trend_discovery", query="проверь что в тренде")),
        ), patch("app.telegram._handle_trend_request", new=AsyncMock()) as trend, patch("app.telegram._run_market_scan", new=AsyncMock()) as scan:
            await telegram.handle_update(message_update(42, "ну проверь реально что в тренде потом предложи что-нибудь"))
        trend.assert_awaited_once()
        scan.assert_not_awaited()

    async def test_yes_after_trend_hypothesis_starts_social_signal_check(self):
        telegram._sessions[42] = {
            "stage": "suggested_idea_confirmation", "profile": {}, "ideas": [],
            "context": {"idea": {"title_ru": "Органайзер для ящиков"}, "trend_requested": True},
        }
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram._run_trend_product_check", new=AsyncMock()) as trend_check:
            await telegram.handle_update(message_update(42, "да"))
        trend_check.assert_awaited_once_with(42, "Органайзер для ящиков")

    async def test_duplicate_telegram_update_is_ignored(self):
        update = message_update(42, "/start") | {"update_id": 999}
        with patch("app.telegram._call", new=self.capture_call):
            await telegram.handle_update(update)
            await telegram.handle_update(update)
        self.assertEqual(len(self.messages), 1)

    async def test_profile_margin_accepts_a_plain_number(self):
        telegram._sessions[42] = {"stage": "profile_margin", "profile": {"target_margin_percent": 35}, "ideas": [], "context": {}}
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram.save_telegram_profile"):
            await telegram.handle_update(message_update(42, "42"))
        self.assertEqual(telegram._sessions[42]["profile"]["target_margin_percent"], 42)

    async def test_find_asks_for_a_product_instead_of_running_a_profile_wizard(self):
        with patch("app.telegram._call", new=self.capture_call):
            await telegram.handle_update(callback_update(42, "find"))
        self.assertEqual(telegram._sessions[42]["stage"], "market_scan")
        self.assertIn("Напиши товар", self.messages[-1]["text"])

    async def test_profit_text_is_calculated_not_sent_to_general_chat(self):
        telegram._sessions[42] = {"stage": "profit_manual", "profile": {}, "ideas": [], "context": {}}
        with patch("app.telegram._call", new=self.capture_call):
            await telegram.handle_update(message_update(42, "8990, 18, 50, 60000"))
        self.assertIn("Экономика тестовой партии", self.messages[-1]["text"])
        self.assertIsNone(telegram._sessions[42]["stage"])

    async def test_cargo_text_returns_quotes(self):
        telegram._sessions[42] = {"stage": "cargo", "profile": {}, "ideas": [], "context": {}}
        with patch("app.telegram._call", new=self.capture_call):
            await telegram.handle_update(message_update(42, "12, 40, 30, 25, 50"))
        self.assertIn("Сравнение карго", self.messages[-1]["text"])

    async def test_market_scan_searches_and_ranks_kaspi_cards(self):
        products = [
            KaspiProduct(source_url="https://kaspi.kz/shop/p/test-a-1/", title="Тест А", price_kzt=8990, review_count=60, seller_count=2, rating=4.8),
            KaspiProduct(source_url="https://kaspi.kz/shop/p/test-b-2/", title="Тест Б", price_kzt=4990, review_count=5, seller_count=12),
        ]
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram.search_products", new=AsyncMock(return_value=products)):
            await telegram.handle_update(callback_update(42, "market_scan"))
            await telegram.handle_update(message_update(42, "органайзеры"))
        self.assertTrue(any("Анализ Kaspi" in payload["text"] for payload in self.messages))
        self.assertTrue(any("Тест А" in payload["text"] for payload in self.messages))

    async def test_idea_can_be_selected_by_number(self):
        telegram._sessions[42] = {"stage": "idea_select", "profile": {}, "context": {}, "ideas": [
            {"title_ru": "Органайзер", "chinese_keywords": "收纳盒", "why_interesting": "Компактный", "risk_to_check": "Материал"},
        ]}
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram._open_idea", new=AsyncMock()) as open_idea:
            await telegram.handle_update(message_update(42, "1"))
        open_idea.assert_awaited_once_with(42, 0)
