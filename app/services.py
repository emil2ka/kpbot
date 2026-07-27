import json

from openai import AsyncOpenAI

from app.config import get_settings
from app.models import KaspiProduct, RiskAssessment


class XAIServiceError(RuntimeError):
    """Raised when xAI cannot produce a usable structured assessment."""


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
