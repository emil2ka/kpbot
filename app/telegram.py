"""Conversation-first Telegram interface for the sourcing workspace."""
from __future__ import annotations

from html import escape
import re
from typing import Any

import httpx

from app.china import build_image_search_url, build_search_urls, detect_platform
from app.china_scraper import deep_extract_china_product
from app.config import get_settings
from app.database import (
    get_telegram_profile, list_sourcing_items, save_sourcing_item,
    save_sourcing_offer, save_supplier_link, save_telegram_profile,
)
from app.economics import calculate_economics, calculate_target_cny_price, compare_cargo
from app.models import CargoQuoteRequest, EconomicsRequest
from app.services import build_product_insight, generate_china_ideas, generate_chinese_keywords
from app.kaspi import KaspiExtractionError, fetch_product, search_products

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# A live conversation must have context. Supabase persists workspace data; this
# tiny cache holds only the unfinished dialog and lets local/demo deployments work.
_sessions: dict[int, dict[str, Any]] = {}
_local_items: dict[int, list[dict[str, Any]]] = {}


def _session(chat_id: int) -> dict[str, Any]:
    return _sessions.setdefault(chat_id, {"stage": None, "profile": {}, "ideas": [], "context": {}})


def _keyboard(rows: list[list[tuple[str, str]]]) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": label, "callback_data": value} for label, value in row] for row in rows]}


def _url_keyboard(rows: list[list[dict[str, str]]]) -> dict[str, Any]:
    return {"inline_keyboard": rows}


async def _call(method: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.telegram_configured:
        return
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(TELEGRAM_API.format(token=settings.telegram_bot_token, method=method), json=payload)


async def _send(chat_id: int, text: str, markup: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    await _call("sendMessage", payload)


async def _home(chat_id: int) -> None:
    _session(chat_id)["stage"] = None
    await _send(chat_id, "<b>Kaspi Sourcing AI</b>\n\nПомогу найти товар, проверить спрос на Kaspi, подобрать поставщика и посчитать тестовую закупку.\n\nС чего начнём?", _keyboard([
        [("🔍 Найти товар", "find"), ("🧠 Анализ рынка Kaspi", "market_scan")],
        [("🔗 Проверить Kaspi", "check")],
        [("🇨🇳 Проверить поставщика", "supplier"), ("💰 Рассчитать прибыль", "profit")],
        [("📁 Мои идеи", "workspace"), ("👤 Профиль", "profile")],
    ]))


async def _run_market_scan(chat_id: int, query: str) -> None:
    """Search a bounded public sample and turn it into an evidence-based shortlist."""
    await _send(chat_id, f"Ищу до 5 открытых карточек Kaspi по запросу <b>{escape(query)}</b> и считаю конкуренцию, цену и потенциал…")
    try:
        products = await search_products(query)
    except KaspiExtractionError as exc:
        await _send(chat_id, f"Не смог провести анализ: {escape(str(exc))}")
        return
    ranked = sorted(((build_product_insight(product), product) for product in products), key=lambda pair: pair[0].score, reverse=True)
    prices = [product.price_kzt for _, product in ranked if product.price_kzt]
    reviews = [product.review_count for _, product in ranked if product.review_count is not None]
    sellers = [product.seller_count for _, product in ranked if product.seller_count is not None]
    summary = [f"<b>🧠 Анализ Kaspi: {escape(query)}</b>", f"Проверено карточек: <b>{len(ranked)}</b>"]
    if prices:
        summary.append(f"Диапазон цен: <b>{min(prices):,}–{max(prices):,} ₸</b>")
    if reviews:
        summary.append(f"Отзывы в выборке: <b>{min(reviews)}–{max(reviews)}</b>")
    if sellers:
        summary.append(f"Продавцы в карточках: <b>{min(sellers)}–{max(sellers)}</b>")
    await _send(chat_id, "\n".join(summary) + "\n\nЭто выборка открытых карточек, не полный объём продаж Kaspi.")
    for index, (insight, product) in enumerate(ranked[:3], start=1):
        target = calculate_target_cny_price(product.price_kzt) if product.price_kzt else 0
        await _send(chat_id,
            f"<b>{index}. {escape(product.title)}</b>\n"
            f"Оценка: <b>{insight.score}/100 · {insight.verdict}</b>\n"
            f"Цена: <b>{product.price_kzt:,.0f} ₸</b> · отзывы: {product.review_count or 'нет данных'} · продавцы: {product.seller_count or 'нет данных'}\n"
            f"Ориентир закупки для маржи 35%: <b>до {target} ¥</b>\n"
            f"Риск: {escape((insight.concerns or ['Нужно проверить поставщика и характеристики товара.'])[0])}\nСледующий шаг: {escape(insight.next_step)}",
            {"inline_keyboard": [[{"text": "Открыть Kaspi", "url": str(product.source_url)}], [{"text": "🔗 Разобрать эту карточку", "callback_data": "check"}]]})
    _session(chat_id)["stage"] = None


def _profile(chat_id: int) -> dict[str, Any]:
    session = _session(chat_id)
    if not session["profile"]:
        session["profile"] = get_telegram_profile(chat_id) or {
            "target_margin_percent": 35, "excluded_categories": [],
        }
    return session["profile"]


async def _show_profile(chat_id: int) -> None:
    profile = _profile(chat_id)
    excluded = ", ".join(profile.get("excluded_categories") or []) or "ничего"
    budget = profile.get("test_budget_kzt")
    budget_text = f"<b>{budget:,.0f} ₸</b>" if budget else "не задан"
    await _send(chat_id,
        "<b>👤 Профиль закупщика</b>\n"
        f"Бюджет теста: {budget_text}\n"
        f"Целевая маржа: <b>{profile.get('target_margin_percent', 35)}%</b>\n"
        f"Исключить: {escape(excluded)}\n\nНастройки используются при подборе и расчётах.",
        _keyboard([[("💳 Изменить бюджет", "profile_budget"), ("🎯 Маржа 35%", "profile_margin")], [("⬅️ В меню", "home")]]))


async def _start_idea_flow(chat_id: int) -> None:
    session = _session(chat_id)
    session["stage"] = "idea_budget"
    await _send(chat_id, "<b>Найдём товар для теста.</b>\nКакой бюджет на первую закупку? Это помогает отсечь неподходящие идеи.", _keyboard([
        [("до 50 000 ₸", "budget:50000"), ("50–150 тыс. ₸", "budget:150000")],
        [("150–300 тыс. ₸", "budget:300000"), ("Не знаю", "budget:0")],
        [("⬅️ В меню", "home")],
    ]))


async def _ask_category(chat_id: int) -> None:
    _session(chat_id)["stage"] = "idea_category"
    await _send(chat_id, "Что тебе ближе? Можно нажать вариант или написать свою категорию.", _keyboard([
        [("🏠 Дом", "category:дом"), ("🚗 Авто", "category:авто")],
        [("✨ Красота", "category:красота"), ("🏃 Спорт", "category:спорт")],
        [("🤷 Не знаю", "category:любая")],
    ]))


async def _ask_exclusions(chat_id: int) -> None:
    _session(chat_id)["stage"] = "idea_exclusions"
    await _send(chat_id, "Что лучше исключить?", _keyboard([
        [("Без электроники", "exclude:electronics"), ("Без хрупкого", "exclude:fragile")],
        [("Без одежды", "exclude:clothing"), ("Ничего", "exclude:none")],
    ]))


async def _generate_ideas(chat_id: int) -> None:
    session, profile = _session(chat_id), _profile(chat_id)
    context = session["context"]
    request = (
        f"Подбери товары для категории: {context.get('category', 'любая')}. "
        f"Бюджет тестовой закупки: {profile.get('test_budget_kzt') or 'не задан'} KZT. "
        f"Исключить: {', '.join(profile.get('excluded_categories') or ['ничего'])}. "
        "Покажи только безопасные небрандовые гипотезы для ручной проверки."
    )
    await _send(chat_id, "Подбираю гипотезы под твои условия…")
    research = await generate_china_ideas(request)
    if not research:
        await _send(chat_id, "Не смог подготовить персональные гипотезы сейчас. Попробуй ещё раз чуть позже или пришли название категории.", _keyboard([[("🔄 Попробовать снова", "find"), ("⬅️ В меню", "home")]]))
        return
    session["ideas"] = [idea.model_dump() for idea in research.ideas]
    session["stage"] = None
    await _send(chat_id, f"<b>Идеи для проверки</b>\n{escape(research.interpretation)}\n\nЭто гипотезы, а не подтверждённые тренды. Выбери ту, которую хочешь развить:")
    for index, idea in enumerate(session["ideas"]):
        await _send(chat_id,
            f"<b>{index + 1}. {escape(idea['title_ru'])}</b>\n"
            f"Почему подходит: {escape(idea['why_interesting'])}\n"
            f"Проверить: {escape(idea['risk_to_check'])}",
            _keyboard([[("Открыть эту идею", f"idea:{index}")]]))


async def _open_idea(chat_id: int, index: int) -> None:
    session = _session(chat_id)
    if index >= len(session["ideas"]):
        await _home(chat_id)
        return
    idea = session["ideas"][index]
    item_id = save_sourcing_item(chat_id, idea["title_ru"], notes=idea["why_interesting"])
    local = {"title": idea["title_ru"], "status": "idea", "potential_score": None}
    _local_items.setdefault(chat_id, []).insert(0, local)
    session["context"] = {"idea": idea, "item_id": item_id}
    urls = build_search_urls(idea["chinese_keywords"])
    await _send(chat_id,
        f"<b>Работаем с идеей: {escape(idea['title_ru'])}</b>\n"
        f"Китайский запрос: <code>{escape(idea['chinese_keywords'])}</code>\n\n"
        "Сначала посмотри похожие товары на Kaspi и варианты на 1688. Затем пришли любую найденную ссылку — я сохраню её в эту идею.",
        _url_keyboard([
            [{"text": "🔎 Искать на 1688", "url": urls["1688"]}, {"text": "🌐 Искать на Alibaba", "url": urls["alibaba"]}],
            [{"text": "📊 Проверить Kaspi", "callback_data": "check"}],
            [{"text": "📁 Мои идеи", "callback_data": "workspace"}],
        ]))


async def _send_kaspi_product(chat_id: int, product: Any) -> None:
    session = _session(chat_id)
    insight = build_product_insight(product)
    context = session["context"]
    context["kaspi"] = product
    target = calculate_target_cny_price(product.price_kzt) if product.price_kzt else 0
    keywords = await generate_chinese_keywords(product.title)
    urls = build_search_urls(keywords, max_price_cny=target or None)
    image_search = build_image_search_url(str(product.image_url)) if product.image_url else None
    item_id = save_sourcing_item(chat_id, product.title, status="researching", kaspi_url=str(product.source_url), image_url=str(product.image_url) if product.image_url else None, potential_score=insight.score)
    context["item_id"] = context.get("item_id") or item_id
    title = escape(product.title)
    text = (
        f"<b>{title}</b>\n\n"
        f"Оценка: <b>{insight.score}/100 · {insight.verdict}</b>\n"
        f"Цена Kaspi: <b>{product.price_kzt:,.0f} ₸</b>\n" if product.price_kzt else f"<b>{title}</b>\n\nЦена Kaspi не прочитана.\n"
    ) + (
        f"Отзывы: {product.review_count or 'нет данных'} · Продавцы: {product.seller_count or 'нет данных'}\n"
        f"Цель закупки для маржи 35%: <b>до {target} ¥</b>\n\n"
        f"{escape(insight.summary)}\nСледующий шаг: {escape(insight.next_step)}"
    )
    rows: list[list[dict[str, str]]] = [[{"text": "🔎 Найти на 1688", "url": urls["1688"]}]]
    if image_search:
        rows[0].append({"text": "🖼 По фото", "url": image_search})
    rows.append([{"text": "🇨🇳 Добавить поставщика", "callback_data": "supplier"}])
    if context.get("supplier"):
        rows.append([{"text": "💰 Сравнить с поставщиком", "callback_data": "compare"}])
    rows.append([{"text": "📁 Сохранено в мои идеи", "callback_data": "workspace"}])
    if product.image_url:
        await _call("sendPhoto", {"chat_id": chat_id, "photo": str(product.image_url), "caption": text, "parse_mode": "HTML", "reply_markup": _url_keyboard(rows)})
    else:
        await _send(chat_id, text, _url_keyboard(rows))


async def _send_supplier(chat_id: int, raw: str) -> None:
    try:
        supplier = await deep_extract_china_product(raw)
    except Exception:
        await _send(chat_id, "Не смог прочитать ссылку поставщика. Открой карточку в браузере и пришли полную ссылку ещё раз.")
        return
    session = _session(chat_id)
    session["context"]["supplier"] = supplier
    try:
        save_supplier_link(supplier.platform, supplier.raw_url, supplier.canonical_url, supplier.item_id, supplier.price_cny)
        save_sourcing_offer(
            session["context"].get("item_id"), supplier.platform, supplier.canonical_url,
            unit_price_cny=supplier.price_cny, weight_kg=supplier.estimated_weight_kg,
            notes="; ".join(supplier.data_notes),
        )
    except Exception:
        pass
    price = f"<b>{supplier.price_cny:g} ¥</b>" if supplier.price_cny is not None else "не извлечена"
    notes = "\n".join(f"• {escape(note)}" for note in supplier.data_notes[:2])
    await _send(chat_id,
        f"<b>🇨🇳 Поставщик: {escape(supplier.platform)}</b>\n"
        f"Товар: {escape(supplier.title_ru or supplier.title_zh)}\n"
        f"Цена: {price}\n{notes}\n\n"
        "Ссылка добавлена к текущей идее. Теперь сравни её с товаром Kaspi или посчитай экономику.",
        _keyboard([[("🔗 Добавить Kaspi-ссылку", "check"), ("💰 Рассчитать прибыль", "compare")], [("📁 Мои идеи", "workspace")]]))


def _render_economics(data: EconomicsRequest) -> str:
    result = calculate_economics(data)
    return (
        "<b>💰 Экономика тестовой партии</b>\n"
        f"Себестоимость 1 шт.: <b>{result.unit_cost_kzt:,.0f} ₸</b>\n"
        f"Прибыль 1 шт.: <b>{result.profit_per_unit_kzt:,.0f} ₸</b>\n"
        f"Маржа: <b>{result.margin_percent}%</b> · ROI: <b>{result.roi_percent}%</b>\n"
        f"Прибыль партии: <b>{result.total_profit_kzt:,.0f} ₸</b>\n"
        f"Максимальная закупочная цена: <b>{result.maximum_purchase_price_cny} ¥</b>\n\n"
        f"{escape(result.recommendation)}\n<i>В расчёте: комиссия Kaspi 12%, резерв возвратов 5%, упаковка 150 ₸. Проверь реальную ставку карго перед оплатой.</i>"
    )


async def _compare_current(chat_id: int) -> None:
    context = _session(chat_id)["context"]
    product, supplier = context.get("kaspi"), context.get("supplier")
    if not product:
        await _send(chat_id, "Сначала пришли ссылку на аналогичный товар Kaspi — тогда сравню цену продажи с поставщиком.", _keyboard([[("🔗 Добавить Kaspi", "check")]]))
        return
    if not supplier or supplier.price_cny is None:
        _session(chat_id)["stage"] = "profit_price"
        await _send(chat_id, "Не вижу точную цену поставщика. Напиши цену за 1 штуку в CNY, например: <code>18.5</code>.")
        return
    data = EconomicsRequest(sale_price_kzt=product.price_kzt or 1, unit_price_cny=supplier.price_cny, quantity=20, cargo_cost_kzt=24000)
    await _send(chat_id, _render_economics(data), _keyboard([[("✏️ Изменить параметры", "profit"), ("📦 Сравнить карго", "cargo")], [("📁 К моим идеям", "workspace")]]))


async def _show_workspace(chat_id: int) -> None:
    remote = list_sourcing_items(chat_id)
    items = remote or _local_items.get(chat_id, [])
    if not items:
        await _send(chat_id, "<b>📁 Мои идеи</b>\nПока пусто. Начни с подбора — сохраню выбранную гипотезу здесь.", _keyboard([[("🔍 Найти товар", "find"), ("⬅️ В меню", "home")]]))
        return
    labels = {"idea": "идея", "researching": "изучаю", "sample": "тестирую", "ordered": "заказано", "rejected": "не подошло"}
    lines = [f"• <b>{escape(str(item['title']))}</b> — {labels.get(item.get('status'), item.get('status', 'идея'))}" for item in items]
    await _send(chat_id, "<b>📁 Мои идеи</b>\n" + "\n".join(lines) + "\n\nИстория сохраняется в Supabase, если он подключён. В этой сессии выбранная идея также не потеряется.", _keyboard([[("🔍 Найти ещё товар", "find"), ("⬅️ В меню", "home")]]))


def _number(text: str) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", text.replace(" ", ""))
    return float(match.group(0).replace(",", ".")) if match else None


async def _handle_text_stage(chat_id: int, incoming: str) -> bool:
    session = _session(chat_id)
    stage = session.get("stage")
    if stage == "idea_budget":
        value = _number(incoming)
        if value is None:
            await _send(chat_id, "Напиши сумму цифрами, например <code>120000</code>, или выбери вариант кнопкой.")
            return True
        _profile(chat_id)["test_budget_kzt"] = value
        save_telegram_profile(chat_id, _profile(chat_id))
        await _ask_category(chat_id)
        return True
    if stage == "idea_category":
        session["context"]["category"] = incoming[:80]
        await _ask_exclusions(chat_id)
        return True
    if stage == "profit_price":
        price = _number(incoming)
        product = session["context"].get("kaspi")
        if price is None or not product or not product.price_kzt:
            await _send(chat_id, "Нужна цена в CNY и сохранённая Kaspi-ссылка. Начни с проверки товара Kaspi.")
            return True
        await _send(chat_id, _render_economics(EconomicsRequest(sale_price_kzt=product.price_kzt, unit_price_cny=price, quantity=20, cargo_cost_kzt=24000)))
        session["stage"] = None
        return True
    if stage == "profit_manual":
        # Commas are the documented field separator. Decimal values can use a dot.
        values = re.findall(r"\d+(?:\.\d+)?", incoming.replace(",", " "))
        if len(values) < 4:
            await _send(chat_id, "Нужно 4 значения: <code>продажа KZT, цена CNY, количество, доставка KZT</code>. Например: <code>8990, 18, 50, 60000</code>")
            return True
        sale, cny, quantity, cargo = [float(value) for value in values[:4]]
        await _send(chat_id, _render_economics(EconomicsRequest(sale_price_kzt=sale, unit_price_cny=cny, quantity=int(quantity), cargo_cost_kzt=cargo)))
        session["stage"] = None
        return True
    if stage == "cargo":
        values = re.findall(r"\d+(?:\.\d+)?", incoming.replace(",", " "))
        if len(values) < 5:
            await _send(chat_id, "Нужно: <code>вес кг, длина, ширина, высота см, количество</code>. Например: <code>12, 40, 30, 25, 50</code>")
            return True
        weight, length, width, height, quantity = [float(value) for value in values[:5]]
        quotes = compare_cargo(CargoQuoteRequest(actual_weight_kg=weight, length_cm=length, width_cm=width, height_cm=height, quantity=int(quantity)))
        text = "<b>📦 Сравнение карго</b>\n" + "\n".join(f"• <b>{q.method}</b>: {q.total_cost_kzt:,.0f} ₸, {q.delivery_days}, {q.cost_per_unit_kzt:,.0f} ₸/шт." for q in quotes)
        await _send(chat_id, text + "\n\n<i>Это ориентировочные тарифы. Подтверди стоимость у своего карго-партнёра.</i>")
        session["stage"] = None
        return True
    if stage == "profile_budget":
        value = _number(incoming)
        if value is None:
            await _send(chat_id, "Напиши бюджет цифрами, например <code>150000</code>.")
            return True
        _profile(chat_id)["test_budget_kzt"] = value
        save_telegram_profile(chat_id, _profile(chat_id))
        session["stage"] = None
        await _show_profile(chat_id)
        return True
    return False


async def register_commands() -> None:
    await _call("setMyCommands", {"commands": [
        {"command": "start", "description": "Открыть меню"},
        {"command": "find", "description": "Найти товар"},
        {"command": "analyze", "description": "Полный анализ Kaspi"},
        {"command": "check", "description": "Проверить товар Kaspi"},
        {"command": "ideas", "description": "Мои идеи"},
        {"command": "profit", "description": "Рассчитать прибыль"},
        {"command": "cargo", "description": "Сравнить карго"},
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
        if callback == "home": await _home(chat_id)
        elif callback == "find": await _start_idea_flow(chat_id)
        elif callback == "check":
            _session(chat_id)["stage"] = "await_kaspi"; await _send(chat_id, "Пришли ссылку на товар Kaspi. Я покажу конкуренцию, ориентир закупки и следующий шаг.")
        elif callback == "market_scan":
            _session(chat_id)["stage"] = "market_scan"; await _send(chat_id, "Что искать на Kaspi? Например: <code>органайзеры для кухни</code> или <code>авто держатели для телефона</code>.")
        elif callback == "supplier":
            _session(chat_id)["stage"] = "await_supplier"; await _send(chat_id, "Пришли ссылку на 1688, Taobao, Alibaba, Pinduoduo или Tmall. Добавлю её к текущей идее.")
        elif callback == "workspace": await _show_workspace(chat_id)
        elif callback == "profile": await _show_profile(chat_id)
        elif callback == "profile_budget": _session(chat_id)["stage"] = "profile_budget"; await _send(chat_id, "Напиши комфортный бюджет на тестовую закупку в тенге.")
        elif callback == "profile_margin":
            profile = _profile(chat_id); profile["target_margin_percent"] = 35; save_telegram_profile(chat_id, profile); await _show_profile(chat_id)
        elif callback == "profit": _session(chat_id)["stage"] = "profit_manual"; await _send(chat_id, "Напиши: <code>продажа KZT, цена CNY, количество, доставка KZT</code>.\nНапример: <code>8990, 18, 50, 60000</code>")
        elif callback == "compare": await _compare_current(chat_id)
        elif callback == "cargo": _session(chat_id)["stage"] = "cargo"; await _send(chat_id, "Напиши: <code>вес кг, длина, ширина, высота см, количество</code>.\nНапример: <code>12, 40, 30, 25, 50</code>")
        elif callback.startswith("budget:"):
            _profile(chat_id)["test_budget_kzt"] = int(callback.split(":", 1)[1]); save_telegram_profile(chat_id, _profile(chat_id)); await _ask_category(chat_id)
        elif callback.startswith("category:"):
            _session(chat_id)["context"]["category"] = callback.split(":", 1)[1]; await _ask_exclusions(chat_id)
        elif callback.startswith("exclude:"):
            value = callback.split(":", 1)[1]; _profile(chat_id)["excluded_categories"] = [] if value == "none" else [value]; save_telegram_profile(chat_id, _profile(chat_id)); await _generate_ideas(chat_id)
        elif callback.startswith("idea:"): await _open_idea(chat_id, int(callback.split(":", 1)[1]))
        return
    if command in {"/start", "/menu", "/help"}: await _home(chat_id); return
    command_actions = {"/find": "find", "/check": "check", "/analyze": "market_scan", "/ideas": "workspace", "/profit": "profit", "/cargo": "cargo"}
    if command in command_actions:
        await handle_update({"callback_query": {"id": str(update.get("update_id", "command")), "data": command_actions[command], "message": message}}); return
    if "kaspi.kz" in incoming.lower():
        try: await _send_kaspi_product(chat_id, await fetch_product(incoming))
        except KaspiExtractionError as exc: await _send(chat_id, f"Не смог прочитать карточку Kaspi: {escape(str(exc))}")
        return
    if detect_platform(incoming) != "Other": await _send_supplier(chat_id, incoming); return
    if _session(chat_id).get("stage") == "market_scan":
        await _run_market_scan(chat_id, incoming)
        return
    if incoming and await _handle_text_stage(chat_id, incoming): return
    await _send(chat_id, "Я могу помочь найти товар или проверить уже найденный. Выбери сценарий — так дам точный следующий шаг.", _keyboard([[("🔍 Найти товар", "find"), ("🔗 Проверить Kaspi", "check")], [("⬅️ В меню", "home")]]))
