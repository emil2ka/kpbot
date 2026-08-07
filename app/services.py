import json
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.china import normalize_search_keywords
from app.config import get_settings
from app.models import ChinaIdeaResearch, KaspiProduct, ProductInsight, RiskAssessment


class XAIServiceError(RuntimeError):
    """Raised when xAI cannot produce a usable structured assessment."""


class SourcingIntent(BaseModel):
    """A compact routing decision for a free-form Telegram message."""

    kind: Literal["product_search", "idea_discovery", "trend_discovery", "question"]
    query: str


def _fallback_sourcing_intent(message: str) -> SourcingIntent:
    normalized = message.lower()
    if any(word in normalized for word in ("тренд", "в тренде", "что сейчас прода", "популярн")):
        return SourcingIntent(kind="trend_discovery", query=message)
    if any(word in normalized for word in ("что-то", "что то", "подскажи", "посоветуй", "идею")):
        return SourcingIntent(kind="idea_discovery", query=message)
    return SourcingIntent(kind="product_search", query=message)


async def classify_sourcing_request(message: str) -> SourcingIntent:
    """Understand the user's goal before choosing a sourcing workflow.

    This keeps conversational requests such as "проверь, что в тренде" from
    being sent verbatim to a Kaspi product search.
    """
    s = get_settings()
    clean_message = " ".join(message.split())[:500]
    if not s.xai_configured:
        return _fallback_sourcing_intent(clean_message)
    prompt = (
        "Определи намерение пользователя для помощника по товарам Kaspi и закупкам из Китая. "
        "Верни строго JSON: {\"kind\":\"product_search|idea_discovery|trend_discovery|question\",\"query\":\"...\"}. "
        "product_search — пользователь назвал конкретный товар для поиска; "
        "idea_discovery — просит подобрать товар или направление; "
        "trend_discovery — просит сначала проверить, что сейчас в тренде/популярно, затем предложить товар; "
        "question — общий вопрос, не требующий поиска карточек. "
        "В query помести короткий поисковый запрос или исходную просьбу.\n\n"
        f"Пользователь: {clean_message}"
    )
    try:
        async with AsyncOpenAI(api_key=s.xai_api_key, base_url="https://api.x.ai/v1") as client:
            response = await client.chat.completions.create(
                model=s.xai_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
        result = SourcingIntent.model_validate_json(response.choices[0].message.content or "{}")
        return result.model_copy(update={"query": result.query.strip() or clean_message})
    except Exception:
        return _fallback_sourcing_intent(clean_message)


def evaluate_hard_filters(product: KaspiProduct) -> tuple[bool, list[str]]:
    s = get_settings()
    reasons: list[str] = []
    if product.price_kzt is None:
        reasons.append("Не удалось определить цену")
    elif product.price_kzt < s.min_kaspi_price_kzt:
        reasons.append(f"Цена ниже {s.min_kaspi_price_kzt:,} ₸")
    if product.review_count is None:
        reasons.append("Не удалось определить число отзывов")
    elif product.review_count < s.min_reviews:
        reasons.append(f"Отзывов меньше {s.min_reviews}")
    if product.seller_count is None:
        reasons.append("Не удалось определить число продавцов")
    elif product.seller_count >= s.max_sellers:
        reasons.append(f"Продавцов {s.max_sellers} или больше")
    return not reasons, reasons


def build_product_insight(product: KaspiProduct) -> ProductInsight:
    """Produce a deterministic, explainable first-pass recommendation."""
    score = 50
    strengths: list[str] = []
    concerns: list[str] = []
    if product.review_count is not None:
        if product.review_count >= 50:
            score += 20
            strengths.append("Есть заметный социальный сигнал: много отзывов.")
        elif product.review_count < 15:
            score -= 12
            concerns.append("Мало отзывов: спрос ещё не подтверждён.")
    else:
        concerns.append("Не удалось прочитать число отзывов.")
    if product.seller_count is not None:
        if product.seller_count <= 3:
            score += 15
            strengths.append("Конкуренция по числу продавцов выглядит умеренной.")
        elif product.seller_count >= 8:
            score -= 20
            concerns.append("Много продавцов: вероятно придётся конкурировать ценой.")
    else:
        concerns.append("Нужно вручную проверить число продавцов.")
    if product.rating is not None and product.rating >= 4.5:
        score += 10
        strengths.append("Высокий рейтинг помогает подтвердить интерес покупателей.")
    if product.price_kzt is not None and product.price_kzt >= 8000:
        score += 5
        strengths.append("Цена оставляет больше пространства для логистики и маржи.")
    elif product.price_kzt is not None and product.price_kzt < 4000:
        score -= 12
        concerns.append("Низкая цена может не покрыть логистику и комиссию.")
    score = max(0, min(100, score))
    if score >= 75:
        verdict, next_step = "Можно исследовать", "Найдите 3 поставщиков и рассчитайте тестовую партию."
    elif score >= 55:
        verdict, next_step = "Нужна проверка", "Проверьте поставщика, вес и себестоимость до решения."
    else:
        verdict, next_step = "Высокий риск", "Не закупайте, пока не появится сильное преимущество по цене или качеству."
    return ProductInsight(
        score=score, verdict=verdict,
        summary="Оценка построена по открытым сигналам карточки; это не оценка фактических продаж.",
        strengths=strengths or ["Нужно собрать больше рыночных данных."], concerns=concerns,
        next_step=next_step,
    )


async def assess_risk(product: KaspiProduct) -> RiskAssessment:
    s = get_settings()
    if not s.xai_configured:
        raise XAIServiceError("XAI_API_KEY не задан")
    prompt = (
        "Оцени товар для импорта и перепродажи в Казахстане. Верни строго JSON без Markdown: "
        '{"score":1-10,"verdict":"...","risks":["..."],"checks":["..."]}. '
        "score 10 означает наибольший риск. Не давай юридических гарантий. "
        f"Товар: {product.title}. Цена: {product.price_kzt} KZT."
    )
    try:
        async with AsyncOpenAI(api_key=s.xai_api_key, base_url="https://api.x.ai/v1") as client:
            response = await client.chat.completions.create(
                model=s.xai_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        return RiskAssessment.model_validate(json.loads(response.choices[0].message.content or "{}"))
    except Exception as exc:  # SDK, transport, invalid JSON, and schema failures.
        raise XAIServiceError("xAI не вернул корректную оценку рисков") from exc


async def answer_sourcing_question(question: str) -> str | None:
    """Give the Telegram bot a useful conversational layer without inventing market facts."""
    s = get_settings()
    if not s.xai_configured:
        return None
    prompt = (
        "Ты дружелюбный AI-помощник по закупкам товаров из Китая для продажи на Kaspi в Казахстане. "
        "Отвечай по-русски, коротко и конкретно. Не выдавай предположения за рыночные данные, "
        "не обещай юридическое соответствие и не советуй обходить правила площадок. "
        "Если для расчёта не хватает цифр, перечисли ровно какие. В конце предложи один следующий шаг.\n\n"
        f"Сообщение пользователя: {question}"
    )
    try:
        async with AsyncOpenAI(api_key=s.xai_api_key, base_url="https://api.x.ai/v1") as client:
            response = await client.chat.completions.create(
                model=s.xai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.35,
            )
        answer = response.choices[0].message.content
        return answer.strip() if answer else None
    except Exception:
        return None


async def generate_chinese_keywords(title_ru: str) -> str:
    """Translate Russian product title to Chinese e-commerce / B2B search keywords for 1688."""
    s = get_settings()
    if not s.xai_configured:
        return title_ru
    prompt = (
        "Переведи название товара на китайский язык для оптового поиска на 1688.com. "
        "Используй популярные китайские торговые термины и ключевые слова (B2B). "
        "Выдай ТОЛЬКО иероглифы (ключевые слова через пробел), без лишних знаков и объяснений.\n\n"
        f"Товар: {title_ru}"
    )
    try:
        async with AsyncOpenAI(api_key=s.xai_api_key, base_url="https://api.x.ai/v1") as client:
            response = await client.chat.completions.create(
                model=s.xai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
        result = response.choices[0].message.content
        return normalize_search_keywords(result) if result else title_ru
    except Exception:
        return title_ru


async def generate_global_search_keywords(title_ru: str) -> str:
    """Create a concise English B2B query for the public global fallback."""
    s = get_settings()
    if not s.xai_configured:
        return title_ru
    prompt = (
        "Translate this product name into a concise English B2B supplier search query. "
        "Return only 2-6 English keywords, no explanation or brand names.\n\n"
        f"Product: {title_ru}"
    )
    try:
        async with AsyncOpenAI(api_key=s.xai_api_key, base_url="https://api.x.ai/v1") as client:
            response = await client.chat.completions.create(
                model=s.xai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
        return (response.choices[0].message.content or title_ru).strip()
    except Exception:
        return title_ru


async def generate_china_ideas(request: str, count: int = 3) -> ChinaIdeaResearch | None:
    """Generate sourcing hypotheses and searchable Chinese queries (from 1 to 10 ideas)."""
    s = get_settings()
    if not s.xai_configured:
        return None
    num_ideas = max(1, min(10, count))
    prompt = (
        f"Ты исследователь товаров для перепродажи в Казахстане. Сформируй ровно {num_ideas} гипотез "
        "товара для поиска у китайских поставщиков. Пользователь может назвать категорию, бюджет, "
        "целевую маржу или попросить подумать самостоятельно. Выбирай небрандовые, компактные, "
        "неопасные товары; исключай лекарства, БАДы, детские товары, электронику с батареями и явные бренды. "
        "Не заявляй о реальном спросе, продажах, ценах или конкуренции: это гипотезы, которые нужно проверить. "
        "Верни строго JSON: {\"interpretation\":\"...\",\"ideas\":[{\"title_ru\":\"...\","
        "\"chinese_keywords\":\"только китайские ключевые слова\",\"why_interesting\":\"...\","
        "\"risk_to_check\":\"...\"}]}.\n\nЗапрос пользователя: " + request
    )
    try:
        async with AsyncOpenAI(api_key=s.xai_api_key, base_url="https://api.x.ai/v1") as client:
            response = await client.chat.completions.create(
                model=s.xai_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.45,
            )
        research = ChinaIdeaResearch.model_validate_json(response.choices[0].message.content or "{}")
        for idea in research.ideas:
            idea.chinese_keywords = normalize_search_keywords(idea.chinese_keywords)
        return research
    except Exception:
        return None
