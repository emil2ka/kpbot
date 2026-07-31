"""Minimal Telegram Bot API adapter without a framework dependency."""
from html import escape
from typing import Any

import httpx

from app.config import get_settings
from app.economics import calculate_economics
from app.kaspi import KaspiExtractionError, fetch_product
from app.models import EconomicsRequest
from app.services import answer_sourcing_question, build_product_insight

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _main_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [
        [{"text": "🔥 Найти товары", "callback_data": "ideas"}, {"text": "🔎 Проверить товар", "callback_data": "check"}],
        [{"text": "🇨🇳 Найти в Китае", "callback_data": "china"}, {"text": "📦 Карго", "callback_data": "cargo"}],
        [{"text": "💰 Прибыль", "callback_data": "profit"}, {"text": "❓ Помощь", "callback_data": "help"}],
    ]}


async def _call(method: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.telegram_configured:
        return
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(TELEGRAM_API.format(token=settings.telegram_bot_token, method=method), json=payload)


async def _send_message(chat_id: int, text: str, *, keyboard: bool = False) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = _main_keyboard()
    await _call("sendMessage", payload)


async def _send_product(chat_id: int, product: Any) -> None:
    insight = build_product_insight(product)
    price = f"{product.price_kzt:,} ₸" if product.price_kzt else "не прочитана"
    text = (
        f"<b>{escape(product.title)}</b>\n\n"
        f"Потенциал: <b>{insight.score}/100 · {insight.verdict}</b>\n"
        f"Цена Kaspi: <b>{price}</b>\n"
        f"Отзывы: {product.review_count or 'нет данных'} · Продавцы: {product.seller_count or 'нет данных'}\n\n"
        f"<b>Что вижу:</b> {insight.summary}\n"
        f"<b>Следующий шаг:</b> {insight.next_step}"
    )
    if product.image_url:
        await _call("sendPhoto", {"chat_id": chat_id, "photo": str(product.image_url), "caption": text, "parse_mode": "HTML", "reply_markup": _main_keyboard()})
    else:
        await _send_message(chat_id, text, keyboard=True)


async def handle_update(update: dict[str, Any]) -> None:
    message = update.get("message") or update.get("callback_query", {}).get("message")
    if not message:
        return
    chat_id = message["chat"]["id"]
    callback = update.get("callback_query", {}).get("data")
    incoming = (update.get("message", {}).get("text") or "").strip()
    if callback:
        await _call("answerCallbackQuery", {"callback_query_id": update["callback_query"]["id"]})
        prompts = {
            "ideas": "Напиши категорию, бюджет и желаемую маржу. Например: <i>товары для дома, 300 000 ₸, маржа от 40%</i>.",
            "check": "Пришли ссылку на товар Kaspi — я покажу карточку с фото и первичной оценкой.",
            "china": "Пришли ссылку 1688, Alibaba, Taobao или Pinduoduo. Я сохраню её для сравнения с товаром Kaspi; автоматический поиск добавим через разрешённый источник данных.",
            "cargo": "Для расчёта напиши: <i>вес кг, длина×ширина×высота см, количество, срочно/обычно</i>. Например: <i>12 кг, 40x30x25, 50, обычно</i>.",
            "profit": "Для расчёта прибыли используй API /api/v1/economics/calculate или пришли данные в формате: <i>продажа, цена CNY, количество, доставка KZT</i>.",
            "help": "Я умею проверить ссылку Kaspi, показать фото и первичную оценку. Дальше добавим поиск поставщиков, карго и закупки.",
        }
        await _send_message(chat_id, prompts.get(callback, "Выбери действие из меню."), keyboard=True)
        return
    if incoming in {"/start", "/menu", "/help"}:
        await _send_message(chat_id, "<b>Kaspi Sourcing AI</b>\nПришли ссылку Kaspi, фото или расскажи, что хочешь найти.", keyboard=True)
        return
    if "kaspi.kz" in incoming.lower():
        try:
            await _send_product(chat_id, await fetch_product(incoming))
        except KaspiExtractionError as exc:
            await _send_message(chat_id, f"Не смог прочитать карточку: {exc}", keyboard=True)
        return
    if incoming:
        answer = await answer_sourcing_question(incoming)
        await _send_message(
            chat_id,
            escape(answer) if answer else "Понял задачу. Для первого запуска пришли ссылку Kaspi — я покажу товар с фото и оценкой. Поиск идей и поставщиков будет следующим шагом.",
            keyboard=True,
        )
