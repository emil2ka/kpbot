"""Robust, multi-strategy live scraper for Kaspi.kz product pages.

Uses browser-like headers, JSON-LD, OpenGraph meta tags, embedded state extraction,
HTML selectors, and regex fallback parsing to guarantee maximum extraction success.
"""
import json
import re
from asyncio import gather
from datetime import datetime, timezone
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

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


def _is_kaspi_host(host: str | None) -> bool:
    """Accept kaspi.kz and its subdomains, never look-alike domains."""
    normalized = (host or "").lower().rstrip(".")
    return normalized == "kaspi.kz" or normalized.endswith(".kaspi.kz")


def _number(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def _extract_json_ld(soup: BeautifulSoup) -> dict:
    """Return the first Product schema, including products stored in @graph."""
    def find_product(value: object) -> dict | None:
        if isinstance(value, list):
            for item in value:
                product = find_product(item)
                if product:
                    return product
        elif isinstance(value, dict):
            schema_type = value.get("@type")
            types = schema_type if isinstance(schema_type, list) else [schema_type]
            if "Product" in types:
                return value
            return find_product(value.get("@graph", []))
        return None

    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(tag.string or "")
            product = find_product(payload)
            if product:
                return product
        except (json.JSONDecodeError, AttributeError):
            continue
    return {}


def _extract_meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return tag.get("content") if tag and tag.get("content") else None


async def fetch_product(url: str) -> KaspiProduct:
    """Fetch and deeply parse a Kaspi.kz product URL using 5 resilient fallback strategies."""
    try:
        parsed_url = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise KaspiExtractionError("Некорректная ссылка Kaspi") from exc
    if parsed_url.scheme != "https" or not _is_kaspi_host(parsed_url.host):
        raise KaspiExtractionError("Разрешены только HTTPS-ссылки kaspi.kz")

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
    # Missing data must not be reported as one seller: it would make a
    # potentially competitive listing look deceptively attractive.
    seller_count = _number(seller_match.group(1)) if seller_match else None

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


async def search_products(query: str, *, limit: int = 5) -> list[KaspiProduct]:
    """Find a small, public sample of Kaspi product pages and inspect each one.

    Kaspi's search listing is rendered client-side, so we use a public web-search
    result only to discover product URLs, then analyse the Kaspi pages directly.
    This is intentionally bounded and never attempts to bypass Kaspi protections.
    """
    cleaned = " ".join(query.split())[:120]
    if not cleaned:
        raise KaspiExtractionError("Напишите, какой товар или категорию искать")

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9"}
    html_text = ""
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=15.0) as client:
            resp = await client.post("https://html.duckduckgo.com/html/", data={"q": f"site:kaspi.kz/shop/p {cleaned}"})
            if resp.status_code == 200:
                html_text = resp.text
            else:
                search_url = "https://html.duckduckgo.com/html/?q=" + quote_plus(f"site:kaspi.kz/shop/p {cleaned}")
                resp2 = await client.get(search_url)
                html_text = resp2.text
    except Exception as exc:
        raise KaspiExtractionError("Не удалось найти открытые карточки Kaspi") from exc

    urls: list[str] = []
    # Extract URLs from HTML anchor tags and raw regex matches
    for candidate in re.findall(r"https?://(?:www\.)?kaspi\.kz/shop/p/[^?&#\"'\s]+", html_text):
        if candidate not in urls:
            urls.append(candidate)
        if len(urls) >= limit:
            break

    if not urls:
        for href in BeautifulSoup(html_text, "html.parser").select("a[href]"):
            candidate = unescape(href.get("href") or "")
            if "uddg=" in candidate:
                candidate = unquote(parse_qs(urlparse(candidate).query).get("uddg", [""])[0])
            match = re.search(r"https?://(?:www\.)?kaspi\.kz/shop/p/[^?&#\"']+", candidate)
            if match:
                url = match.group(0)
                if url not in urls:
                    urls.append(url)
            if len(urls) >= limit:
                break

    if not urls:
        raise KaspiExtractionError("По этому запросу не нашёл открытых карточек Kaspi")

    results = await gather(*(fetch_product(url) for url in urls), return_exceptions=True)
    products = [item for item in results if isinstance(item, KaspiProduct)]
    if not products:
        raise KaspiExtractionError("Карточки найдены, но Kaspi не отдал данные для анализа")
    return products
