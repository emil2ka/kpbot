"""Minimal Telegram Bot API adapter without a framework dependency."""
from html import escape
from typing import Any
import re

import httpx

from app.china import build_image_search_url, build_search_urls, detect_platform, parse_china_url
from app.china_scraper import deep_extract_china_product
from app.config import get_settings
from app.database import save_supplier_link
from app.economics import calculate_economics, calculate_target_cny_price
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

    target_cny = calculate_target_cny_price(product.price_kzt) if product.price_kzt else 0.0
    target_info = f"\n🎯 <b>Цель закупки (маржа 35%):</b> до <b>{target_cny} CNY</b> (~{int(target_cny * 72):,} ₸)\n" if target_cny > 0 else ""

    keywords_zh = await generate_chinese_keywords(product.title)
    search_urls = build_search_urls(keywords_zh, max_price_cny=target_cny if target_cny > 0 else None)
    img_search_url = build_image_search_url(str(product.image_url)) if product.image_url else None

    text = (
        f"<b>{escape(product.title)}</b>\n\n"
        f"Потенциал: <b>{insight.score}/100 · {insight.verdict}</b>\n"
        f"Цена Kaspi: <b>{price}</b>{target_info}\n"
        f"Отзывы: {product.review_count or 'нет данных'} · Продавцы: {product.seller_count or 'нет данных'}\n\n"
        f"<b>Запрос 1688 (CN):</b> <code>{escape(keywords_zh)}</code>\n"
        f"<b>Что вижу:</b> {insight.summary}\n"
        f"<b>Следующий шаг:</b> {insight.next_step}"
    )

    first_row = [{"text": f"🔎 1688 (до {target_cny}￥)" if target_cny > 0 else "🔎 1688", "url": search_urls["1688"]}]
    if img_search_url:
        first_row.append({"text": "🖼 По фото 1688", "url": img_search_url})
    else:
        first_row.append({"text": "🛍 Pinduoduo", "url": search_urls["pinduoduo"]})

    markup = {
        "inline_keyboard": [
            first_row,
            [{"text": "🛍 Pinduoduo", "url": search_urls["pinduoduo"]} if img_search_url else {"text": "💰 Посчитать прибыль", "callback_data": "profit"}, {"text": "💰 Посчитать прибыль", "callback_data": "profit"}] if img_search_url else [{"text": "🇨🇳 Добавить ссылку поставщика", "callback_data": "china"}],
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
        deep_res = await deep_extract_china_product(incoming)
        try:
            save_supplier_link(
                platform=deep_res.platform,
                raw_url=deep_res.raw_url,
                canonical_url=deep_res.canonical_url,
                item_id=deep_res.item_id,
                unit_price_cny=deep_res.price_cny,
            )
        except Exception:
            pass

        # Build price tiers text
        tiers_text = ""
        if deep_res.price_tiers:
            tiers_list = []
            for t in deep_res.price_tiers:
                max_str = f"–{t.max_quantity}" if t.max_quantity else "+"
                tiers_list.append(f"• {t.min_quantity}{max_str} шт: <b>{t.price_cny} ¥</b>")
            tiers_text = "\n<b>Оптовые цены (MOQ):</b>\n" + "\n".join(tiers_list) + "\n"

        # Build SKU text
        sku_text = ""
        if deep_res.sku_variants:
            variants_list = [f"• {v.name_ru or v.name_zh} ({v.price_cny} ¥)" for v in deep_res.sku_variants[:3]]
            sku_text = "\n<b>Варианты (SKU):</b>\n" + "\n".join(variants_list) + "\n"

        supplier_info = ""
        if deep_res.supplier.company_name:
            supplier_info = f"\n🏭 <b>Поставщик:</b> {escape(deep_res.supplier.company_name)}"
            if deep_res.supplier.location:
                supplier_info += f" ({escape(deep_res.supplier.location)})"
        price_info = f"<b>Базовая цена:</b> <b>{deep_res.price_cny} CNY</b> (~{int(deep_res.price_cny * 72):,} ₸)\n" if deep_res.price_cny is not None else "<b>Цена:</b> не извлечена — проверь на карточке поставщика.\n"
        notes = "\n".join(f"• {escape(note)}" for note in deep_res.data_notes)

        reply_text = (
            f"🇨🇳 <b>Глубокий анализ поставщика ({deep_res.platform})</b>\n"
            f"<b>Товар:</b> {escape(deep_res.title_ru)}\n"
            f"{price_info}{tiers_text}{sku_text}{supplier_info}\n"
            f"<b>Чистая ссылка:</b> {deep_res.canonical_url}\n\n"
            f"{notes}\n\nОтправь ссылку Kaspi для полного сопоставления маржинальности."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "💰 Расчёт прибыли", "callback_data": "profit"}, {"text": "📦 Проверить Kaspi", "callback_data": "check"}],
                [{"text": "📄 Бланк закупки для Карго", "callback_data": "profit"}],
            ]
        }
        if deep_res.images:
            await _call("sendPhoto", {"chat_id": chat_id, "photo": deep_res.images[0], "caption": reply_text, "parse_mode": "HTML", "reply_markup": markup})
        else:
            await _send_message(chat_id, reply_text, reply_markup=markup)
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
