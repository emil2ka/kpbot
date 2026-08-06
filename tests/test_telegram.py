import unittest
from unittest.mock import AsyncMock, patch

from app.models import ChinaIdea, ChinaIdeaResearch, KaspiProduct
from app import telegram


def message_update(chat_id: int, text: str) -> dict:
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def callback_update(chat_id: int, value: str) -> dict:
    return {"callback_query": {"id": f"cb-{value}", "data": value, "message": {"chat": {"id": chat_id}}}}


class TestTelegramUserJourneys(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        telegram._sessions.clear()
        telegram._local_items.clear()
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

    async def test_idea_wizard_keeps_selected_idea_as_context(self):
        research = ChinaIdeaResearch(
            interpretation="Подходит под компактную тестовую закупку.",
            ideas=[
                ChinaIdea(title_ru="Органайзер", chinese_keywords="抽屉 收纳盒", why_interesting="Компактный", risk_to_check="Пластик"),
                ChinaIdea(title_ru="Крючок", chinese_keywords="挂钩", why_interesting="Лёгкий", risk_to_check="Клей"),
                ChinaIdea(title_ru="Контейнер", chinese_keywords="收纳箱", why_interesting="Понятный", risk_to_check="Размер"),
            ],
        )
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram.generate_china_ideas", new=AsyncMock(return_value=research)):
            await telegram.handle_update(callback_update(42, "find"))
            await telegram.handle_update(callback_update(42, "category:дом"))
            await telegram.handle_update(callback_update(42, "type:utility"))
            await telegram.handle_update(callback_update(42, "budget:50000"))
            await telegram.handle_update(callback_update(42, "exclude:none"))
            await telegram.handle_update(callback_update(42, "idea:0"))
        context = telegram._sessions[42]["context"]
        self.assertEqual(context["idea"]["title_ru"], "Органайзер")
        self.assertEqual(telegram._sessions[42]["profile"]["test_budget_kzt"], 50000)
        self.assertTrue(any("Работаем с идеей" in payload["text"] for payload in self.messages))

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
        with patch("app.telegram._call", new=self.capture_call), patch("app.telegram._run_market_scan", new=AsyncMock()):
            await telegram.handle_update(message_update(42, "1"))
        self.assertEqual(telegram._sessions[42]["context"]["idea"]["title_ru"], "Органайзер")
