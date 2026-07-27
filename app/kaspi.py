"""Low-volume public-page extraction for Kaspi product pages.

This deliberately does not authenticate, bypass access controls, or attempt to
circumvent anti-bot systems. When a page cannot be read, it returns a clear
error for manual review rather than retrying aggressively.
"""
import json
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from app.models import KaspiProduct

USER_AGENT = "KaspiResearchMVP/0.1 (contact: configure-before-production)"


class KaspiExtractionError(RuntimeError):
    pass


def _number(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def _json_ld_product(soup: BeautifulSoup) -> dict:
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(tag.string or "")
            entries = payload if isinstance(payload, list) else [payload]
            for entry in entries:
                if entry.get("@type") == "Product":
                    return entry
        except (json.JSONDecodeError, AttributeError):
            continue
    return {}


async def fetch_product(url: str) -> KaspiProduct:
    if "kaspi.kz" not in httpx.URL(url).host.lower():
        raise KaspiExtractionError("Разрешены только ссылки kaspi.kz")

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise KaspiExtractionError(f"Kaspi вернул HTTP {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    data = _json_ld_product(soup)
    title = data.get("name") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    if not title:
        raise KaspiExtractionError("Не удалось извлечь название. Страница может требовать ручной проверки.")

    offers = data.get("offers") if isinstance(data.get("offers"), dict) else {}
    price = _number(str(offers.get("price", "")))
    aggregate = data.get("aggregateRating") if isinstance(data.get("aggregateRating"), dict) else {}
    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None

    page_text = soup.get_text(" ", strip=True)
    seller_match = re.search(r"(\d[\d\s]*)\s*(?:продавц|seller)", page_text, re.IGNORECASE)
    return KaspiProduct(
        source_url=url,
        title=title,
        price_kzt=price,
        review_count=_number(str(aggregate.get("reviewCount", ""))),
        seller_count=_number(seller_match.group(1)) if seller_match else None,
        rating=float(aggregate["ratingValue"]) if aggregate.get("ratingValue") else None,
        image_url=image,
        scraped_at=datetime.utcnow(),
    )

