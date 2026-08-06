"""Public Made-in-China search fallback for supplier discovery.

The integration reads only the publicly rendered search page. It does not sign
in, solve challenges, or attempt to work around access controls.
"""
from html import unescape
import re
from urllib.parse import quote

import httpx


def build_made_in_china_search_url(keywords: str) -> str:
    slug = re.sub(r"\s+", "_", keywords.strip())
    return f"https://www.made-in-china.com/products-search/hot-china-products/{quote(slug, safe='_')}.html"


def extract_made_in_china_items(page: str) -> list[dict]:
    """Parse visible product cards; do not infer absent prices or MOQ."""
    items: list[dict] = []
    for card in re.findall(r'<div class="products-item.*?(?=<div class="products-item|</div>\s*</div>\s*</div>\s*</body>)', page, re.S | re.I):
        link = re.search(r'<h2 class="product-name".*?<a title="([^"]+)"[^>]+href="([^"]+)"', card, re.S | re.I)
        price = re.search(r'class="price"[^>]*>\s*US\$<span>([\d.]+)</span>', card, re.S | re.I)
        moq = re.search(r'([\d,]+)\s+Pieces\b', card, re.S | re.I)
        company = re.search(r'<span title="([^"]+)">', card, re.S | re.I)
        if not link or not price:
            continue
        url = unescape(link.group(2))
        if url.startswith("//"):
            url = "https:" + url
        items.append({
            "title": unescape(link.group(1)).strip(),
            "price_amount": float(price.group(1)),
            "price_currency": "USD",
            "moq": int(moq.group(1).replace(",", "")) if moq else 1,
            "detail_url": url,
            "platform": "Made-in-China",
            "supplier_name": unescape(company.group(1)).strip() if company else None,
        })
        if len(items) == 5:
            break
    return items


async def search_made_in_china(keywords: str) -> tuple[list[dict], str]:
    url = build_made_in_china_search_url(keywords)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=8.0) as client:
            response = await client.get(url)
        if response.status_code != 200:
            return [], f"Made-in-China returned HTTP {response.status_code}"
        items = extract_made_in_china_items(response.text)
        return items, "Public Made-in-China search returned structured offers" if items else "Made-in-China returned no structured offers"
    except httpx.HTTPError as exc:
        return [], f"Made-in-China request failed: {exc.__class__.__name__}"
