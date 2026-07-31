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


def _quick_actions(*actions: tuple[str, str]) -> dict[str, Any]:
    return {"inline_keyboard": [
        [{"text": label, "callback_data": callback} for label, callback in actions],
    ]}


async def _call(method: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.telegram_configured:
        return
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(TELEGRAM_API.format(token=settings.telegram_bot_token, method=method), json=payload)


async def _send_message(chat_id: int, text: str, *, actions: tuple[tuple[str, str], ...] = ()) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if actions:
        payload["reply_markup"] = _quick_actions(*actions)
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
        await _call("sendPhoto", {"chat_id": chat_id, "photo": str(product.image_url), "caption": text, "parse_mode": "HTML", "reply_markup": _quick_actions(("🇨🇳 Найти поставщика", "china"), ("💰 Посчитать прибыль", "profit"))})
    else:
        await _send_message(chat_id, text, actions=(("🇨🇳 Найти поставщика", "china"), ("💰 Посчитать прибыль", "profit")))


async def register_commands() -> None:
    """Expose the stable navigation in Telegram's native menu beside the composer."""
    await _call("setMyCommands", {"commands": [
        {"command": "start", "description": "Начать работу"},
        {"command": "ideas", "description": "Найти идеи товаров"},
        {"command": "check", "description": "Проверить товар Kaspi"},
        {"command": "china", "description": "Найти поставщика"},
        {"command": "cargo", "description": "Сравнить карго"},
        {"command": "profit", "description": "Посчитать прибыль"},
        {"command": "help", "description": "Как пользоваться ботом"},
    ]})


async def handle_update(update: dict[str, Any]) -> None:
    message = update.get("message") or update.get("callback_query", {}).get("message")
    if not message:
        return
    chat_id = message["chat"]["id"]
    callback = update.get("callback_query", {}).get("data")
    incoming = (update.get("message", {}).get("text") or "").strip()
    command = incoming.split(maxsplit=1)[0].lower() if incoming else ""
    if callback:
        await _call("answerCallbackQuery", {"callback_query_id": update["callback_query"]["id"]})
        prompts = {
            "ideas": "Напиши категорию, бюджет и желаемую маржу. Например: <i>товары для дома, 300 000 ₸, маржа от 40%</i>.",
            "check": "Пришли ссылку на товар Kaspi — я покажу карточку с фото и первичной оценкой.",
            "china": "Пришли ссылку 1688, Alibaba, Taobao или Pinduoduo. Я сохраню её для сравнения с товаром Kaspi; автоматический поиск добавим через разрешённый источник данных.",
            "cargo": "Для расчёта напиши: <i>вес кг, длина×ширина×высота см, количество, срочно/обычно</i>. Например: <i>12 кг, 40x30x25, 50, обычно</i>.",
            "profit": "Для расчёта прибыли используй API /api/v1/economics/calculate или пришли данные в формате: <i>продажа, цена CNY, количество, доставка KZT</i>.",
            "help": "Напиши задачу обычным текстом или пришли ссылку Kaspi. Постоянные действия находятся в меню рядом с полем ввода.",
        }
        await _send_message(chat_id, prompts.get(callback, "Выбери действие из меню."))
        return
    if command in {"/start", "/menu", "/help"}:
        await _send_message(
            chat_id,
            "<b>Kaspi Sourcing AI</b>\nНапиши задачу своими словами или пришли ссылку Kaspi. Все основные действия — в меню рядом с полем ввода.",
            actions=(("🔎 Проверить товар", "check"), ("🔥 Найти идею", "ideas")),
        )
        return
    command_callbacks = {"/ideas": "ideas", "/check": "check", "/china": "china", "/cargo": "cargo", "/profit": "profit"}
    if command in command_callbacks:
        await handle_update({"callback_query": {"id": update.get("update_id", "command"), "data": command_callbacks[command], "message": message}})
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
            actions=(("🔎 Проверить ссылку", "check"),),
        )
