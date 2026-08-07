"""Robust live scraper for Chinese supplier pages (1688, PDD, Taobao, Alibaba, JD).

Extracts titles, prices, image galleries, price tiers, and seller metadata from
live HTML and embedded JSON script tags without relying on dummy fallbacks.
"""
import json
import re

import httpx
from bs4 import BeautifulSoup

from app.china import extract_price_hint, extract_url_from_text, parse_china_url
from app.models import ChinaDeepAnalysisResult, PriceTier, SKUVariant, SupplierProfile


async def deep_extract_china_product(raw_text_or_url: str) -> ChinaDeepAnalysisResult:
    """Live network inspection for 1688, PDD, Taobao, Alibaba, and JD URLs."""
    clean_url = extract_url_from_text(raw_text_or_url)
    parse_basic = await parse_china_url(clean_url)
    platform = parse_basic.platform
    item_id = parse_basic.item_id
    canonical = parse_basic.canonical_url

    title_zh = parse_basic.extracted_title or f"Товар {platform} ({item_id or 'без ID'})"
    images: list[str] = []
    if parse_basic.extracted_image_url:
        images.append(parse_basic.extracted_image_url)

    # A price in a marketplace share message is useful even when the landing
    # page requires sign-in. It remains explicitly labelled as a hint below.
    price_cny = extract_price_hint(raw_text_or_url)
    price_from_page = False
    price_tiers: list[PriceTier] = []
    sku_variants: list[SKUVariant] = []
    supplier = SupplierProfile()
    data_notes: list[str] = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,ru;q=0.8,en;q=0.7",
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=12.0) as client:
            resp = await client.get(canonical)
            if resp.status_code == 200:
                html = resp.text
                soup = BeautifulSoup(html, "html.parser")

                # Strategy 1: Title from OG meta or HTML title
                og_title = (
                    soup.find("meta", property="og:title")
                    or soup.find("meta", attrs={"name": "title"})
                )
                if og_title and og_title.get("content"):
                    title_zh = og_title["content"].strip()
                    title_zh = re.sub(r"-1688\.com|-淘宝网|-Alibaba.com|-拼多多|-京东", "", title_zh).strip()

                # Strategy 2: High-res images from OG, img tags, script payloads
                img_matches = re.findall(r'https?://[^\s<>"\']+\.(?:jpg|png|jpeg|webp)', html, re.I)
                for img in img_matches:
                    if any(domain in img for domain in ["alicdn.com", "yangkeduo", "jd.com", "dewu"]):
                        if img not in images and len(images) < 6:
                            images.append(img)

                # Strategy 3: Price extraction from JSON / Regex / Script
                price_match = re.search(r'["\'](?:price|discountPrice|refPrice|salePrice)["\']\s*:\s*["\']?(\d+(?:\.\d{1,2})?)["\']?', html)
                if price_match:
                    try:
                        price_cny = float(price_match.group(1))
                        price_from_page = True
                    except ValueError:
                        pass

                if price_cny is None:
                    # Fallback regex for price in CNY symbol (￥15.5 или 15.5元)
                    m_cny = re.search(r'(?:￥|¥)\s*(\d+(?:\.\d{1,2})?)', html)
                    if m_cny:
                        try:
                            price_cny = float(m_cny.group(1))
                            price_from_page = True
                        except ValueError:
                            pass

                # Strategy 4: Supplier Company Name
                company_match = re.search(r'["\'](?:companyName|shopName|sellerName|supplierName)["\']\s*:\s*["\'](.*?)["\']', html)
                if company_match:
                    supplier.company_name = company_match.group(1).strip()
                    supplier.is_verified = True

                # Strategy 5: Price Tiers in JSON payloads
                tier_matches = re.findall(r'["\']beginAmount["\']\s*:\s*(\d+).*?["\']price["\']\s*:\s*["\']?(\d+(?:\.\d{1,2})?)["\']?', html)
                for min_q, p_val in tier_matches:
                    try:
                        price_tiers.append(PriceTier(min_quantity=int(min_q), price_cny=float(p_val)))
                    except ValueError:
                        pass
    except Exception:
        pass

    if price_cny is None:
        data_notes.append("Цена не извлечена: страница может требовать авторизации или перехода в приложение.")
    elif not price_from_page:
        data_notes.append("Цена взята из текста, которым поделились; подтвердите её на странице поставщика.")
    if not price_tiers:
        data_notes.append("Ступени MOQ не извлечены автоматически с публичной страницы.")
    if not supplier.company_name:
        data_notes.append("Имя компании поставщика не прочитано автоматически.")

    return ChinaDeepAnalysisResult(
        raw_url=raw_text_or_url,
        platform=platform,
        item_id=item_id,
        canonical_url=canonical,
        title_zh=title_zh,
        title_ru=parse_basic.extracted_title or title_zh,
        price_cny=price_cny,
        price_tiers=price_tiers,
        sku_variants=sku_variants,
        images=images,
        supplier=supplier,
        estimated_weight_kg=None,
        data_notes=data_notes,
    )
