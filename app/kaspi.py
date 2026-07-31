"""Robust, multi-strategy live scraper for Kaspi.kz product pages.

Uses browser-like headers, JSON-LD, OpenGraph meta tags, embedded state extraction,
HTML selectors, and regex fallback parsing to guarantee maximum extraction success.
"""
import json
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from app.models import KaspiProduct

# Realistic Chrome macOS browser User-Agent
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


class KaspiExtractionError(RuntimeError):
    pass


def _number(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def _extract_json_ld(soup: BeautifulSoup) -> dict:
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


def _extract_meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return tag.get("content") if tag and tag.get("content") else None


async def fetch_product(url: str) -> KaspiProduct:
    """Fetch and deeply parse a Kaspi.kz product URL using 5 resilient fallback strategies."""
    parsed_url = httpx.URL(url)
    if "kaspi.kz" not in parsed_url.host.lower():
        raise KaspiExtractionError("Разрешены только ссылки kaspi.kz")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "max-age=0",
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=15.0) as client:
            response = await client.get(url)
    except Exception as exc:
        raise KaspiExtractionError(f"Ошибка соединения с Kaspi: {exc}") from exc

    if response.status_code != 200:
        raise KaspiExtractionError(f"Kaspi вернул HTTP {response.status_code}")

    html_text = response.text
    soup = BeautifulSoup(html_text, "html.parser")

    # Strategy 1: JSON-LD
    json_ld = _extract_json_ld(soup)
    title = json_ld.get("name")

    # Strategy 2: OpenGraph Meta Tags
    if not title:
        title = _extract_meta(soup, "og:title") or _extract_meta(soup, "twitter:title")

    # Strategy 3: HTML Title tag
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
        # Clean common Kaspi title suffix
        title = re.sub(r"\s*–\s*купить\s*в\s*интернет-магазине\s*Kaspi\.kz.*$", "", title, flags=re.I).strip()

    if not title:
        raise KaspiExtractionError("Не удалось извлечь название товара Kaspi.")

    # Price extraction
    price: int | None = None
    offers = json_ld.get("offers") if isinstance(json_ld.get("offers"), dict) else {}
    if offers.get("price"):
        price = _number(str(offers.get("price")))

    if not price:
        price_meta = _extract_meta(soup, "product:price:amount") or _extract_meta(soup, "og:price:amount")
        if price_meta:
            price = _number(price_meta)

    if not price:
        # Regex search for price in HTML e.g. "price":8990 or 8 990 ₸
        m_price = re.search(r'["\']price["\']\s*:\s*(\d+)', html_text)
        if not m_price:
            m_price = re.search(r'(\d[\d\s]*)\s*(?:₸|тг|тенге|kzt)', html_text, re.I)
        if m_price:
            price = _number(m_price.group(1))

    # Rating and reviews
    rating: float | None = None
    review_count: int | None = None
    aggregate = json_ld.get("aggregateRating") if isinstance(json_ld.get("aggregateRating"), dict) else {}
    if aggregate.get("ratingValue"):
        try:
            rating = float(aggregate["ratingValue"])
        except ValueError:
            pass
    if aggregate.get("reviewCount"):
        review_count = _number(str(aggregate["reviewCount"]))

    if not review_count:
        m_rev = re.search(r'["\']reviewCount["\']\s*:\s*(\d+)', html_text)
        if m_rev:
            review_count = _number(m_rev.group(1))

    # Image URL
    image_url: str | None = None
    if json_ld.get("image"):
        img = json_ld["image"]
        image_url = img[0] if isinstance(img, list) and img else str(img)

    if not image_url:
        image_url = _extract_meta(soup, "og:image") or _extract_meta(soup, "twitter:image")

    # Sellers count
    page_text = soup.get_text(" ", strip=True)
    seller_match = re.search(r"(\d[\d\s]*)\s*(?:продавц|seller|магазин)", page_text, re.IGNORECASE)
    seller_count = _number(seller_match.group(1)) if seller_match else 1

    return KaspiProduct(
        source_url=url,
        title=title,
        price_kzt=price,
        review_count=review_count,
        seller_count=seller_count,
        rating=rating,
        image_url=image_url,
        scraped_at=datetime.now(timezone.utc),
    )
