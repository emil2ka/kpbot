"""Minimal Telegram Bot API adapter without a framework dependency."""
from html import escape
from typing import Any
import re

import httpx

from app.china import build_search_urls, detect_platform, parse_china_url
from app.config import get_settings
from app.database import save_supplier_link
from app.economics import calculate_economics
from app.kaspi import KaspiExtractionError, fetch_product
from app.models import EconomicsRequest
from app.services import answer_sourcing_question, build_product_insight, generate_china_ideas, generate_chinese_keywords

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _quick_actions(*actions: tuple[str, str]) -> dict[str, Any]:
    return {"inline_keyboard": [
        [{"text": label, "callback_data": callback} for label, callback in actions],
    ]}


def _link_button(label: str, url: str) -> dict[str, Any]:
    return {"inline_keyboard": [
        [{"text": label, "url": url}],
    ]}


async def _call(method: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.telegram_configured:
        return
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(TELEGRAM_API.format(token=settings.telegram_bot_token, method=method), json=payload)


async def _send_message(chat_id: int, text: str, *, actions: tuple[tuple[str, str], ...] = (), reply_markup: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    elif actions:
        payload["reply_markup"] = _quick_actions(*actions)
    await _call("sendMessage", payload)


async def _send_product(chat_id: int, product: Any) -> None:
    insight = build_product_insight(product)
    price = f"{product.price_kzt:,} ₸" if product.price_kzt else "не прочитана"

    keywords_zh = await generate_chinese_keywords(product.title)
    search_urls = build_search_urls(keywords_zh)

    text = (
        f"<b>{escape(product.title)}</b>\n\n"
        f"Потенциал: <b>{insight.score}/100 · {insight.verdict}</b>\n"
        f"Цена Kaspi: <b>{price}</b>\n"
        f"Отзывы: {product.review_count or 'нет данных'} · Продавцы: {product.seller_count or 'нет данных'}\n\n"
        f"<b>Поиск 1688 (CN):</b> <code>{escape(keywords_zh)}</code>\n"
        f"<b>Что вижу:</b> {insight.summary}\n"
        f"<b>Следующий шаг:</b> {insight.next_step}"
    )
    markup = {
        "inline_keyboard": [
            [{"text": "🔎 Искать на 1688", "url": search_urls["1688"]}, {"text": "💰 Посчитать прибыль", "callback_data": "profit"}],
            [{"text": "🇨🇳 Добавить ссылку поставщика", "callback_data": "china"}],
        ]
    }
    if product.image_url:
        await _call("sendPhoto", {"chat_id": chat_id, "photo": str(product.image_url), "caption": text, "parse_mode": "HTML", "reply_markup": markup})
    else:
        await _send_message(chat_id, text, reply_markup=markup)


async def _send_china_ideas(chat_id: int, request: str) -> bool:
    research = await generate_china_ideas(request)
    if not research:
        return False
    await _send_message(
        chat_id,
        f"<b>Ищу со стороны Китая</b>\n{escape(research.interpretation)}\n\n"
        "Это 3 гипотезы. Открой поиск — там уже готовый китайский запрос; после выбора ссылки я сравню её с Kaspi и прибылью.",
    )
    for index, idea in enumerate(research.ideas, start=1):
        urls = build_search_urls(idea.chinese_keywords)
        text = (
            f"<b>{index}. {escape(idea.title_ru)}</b>\n"
            f"<b>Запрос для Китая:</b> <code>{escape(idea.chinese_keywords)}</code>\n"
            f"<b>Почему смотреть:</b> {escape(idea.why_interesting)}\n"
            f"<b>Проверить:</b> {escape(idea.risk_to_check)}"
        )
        markup = {"inline_keyboard": [
            [{"text": "🔎 1688", "url": urls["1688"]}, {"text": "🌐 Alibaba", "url": urls["alibaba"]}],
            [{"text": "🛍 Taobao", "url": urls["taobao"]}, {"text": "📦 Проверить Kaspi", "callback_data": "check"}],
        ]}
        await _send_message(chat_id, text, reply_markup=markup)
    return True


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
        if callback == "ideas":
            await _send_message(chat_id, "Подбираю 3 товарные гипотезы со стороны Китая…")
            if await _send_china_ideas(chat_id, "Самостоятельно найди компактные небрандовые товары для перепродажи на Kaspi."):
                return
        prompts = {
            "check": "Пришли ссылку на товар Kaspi — я покажу карточку с фото, ключевыми словами на китайском для 1688 и первичной оценкой.",
            "china": "Пришли ссылку на 1688, Alibaba, Taobao, Pinduoduo или Tmall. Я распознаю платформу, содам чистую ссылку и сохраню для расчёта юнит-экономики.",
            "cargo": "Для расчёта напиши: <i>вес кг, длина×ширина×высота см, количество, срочно/обычно</i>. Например: <i>12 кг, 40x30x25, 50, обычно</i>.",
            "profit": "Для расчёта прибыли используй API /api/v1/economics/calculate или пришли данные в формате: <i>продажа, цена CNY, количество, доставка KZT</i>.",
            "help": "Напиши задачу обычным текстом, пришли ссылку Kaspi или ссылку на 1688. Все действия доступны в меню.",
        }
        await _send_message(chat_id, prompts.get(callback, "Выбери действие из меню."))
        return

    if command in {"/start", "/menu", "/help"}:
        await _send_message(
            chat_id,
            "<b>Kaspi Sourcing AI</b>\nНапиши задачу своими словами, пришли ссылку Kaspi или ссылку 1688/Taobao/Alibaba. Все действия — в меню рядом с полем ввода.",
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
            await _send_message(chat_id, f"Не смог прочитать карточку: {exc}")
        return

    # Check if incoming text is a Chinese platform link (1688, taobao, alibaba, pinduoduo, tmall, dewu)
    platform = detect_platform(incoming)
    if platform != "Other":
        parsed = await parse_china_url(incoming)
        try:
            save_supplier_link(
                platform=parsed.platform,
                raw_url=parsed.raw_url,
                canonical_url=parsed.canonical_url,
                item_id=parsed.item_id,
            )
        except Exception:
            pass

        title_info = f"\n<b>Название:</b> {escape(parsed.extracted_title)}" if parsed.extracted_title else ""
        item_id_info = f"\n<b>ID товара:</b> <code>{parsed.item_id}</code>" if parsed.item_id else ""
        reply_text = (
            f"🇨🇳 <b>Ссылка поставщика распознана!</b>\n"
            f"<b>Платформа:</b> {parsed.platform}{title_info}{item_id_info}\n"
            f"<b>Чистая ссылка:</b> {parsed.canonical_url}\n\n"
            f"Для расчёта маржи отправь данные закупки: <i>цена закупки CNY, количество, стоимость карго KZT</i>."
        )
        await _send_message(
            chat_id,
            reply_text,
            actions=(("💰 Посчитать прибыль", "profit"), ("🔎 Проверить Kaspi", "check")),
        )
        return

    if incoming:
        if await _send_china_ideas(chat_id, incoming):
            return
        answer = await answer_sourcing_question(incoming)
        await _send_message(
            chat_id,
            escape(answer) if answer else "Понял задачу. Пришли ссылку Kaspi или ссылку на 1688/Taobao — я покажу аналитику и помогу посчитать прибыль.",
            actions=(("🔎 Проверить ссылку", "check"),),
        )
