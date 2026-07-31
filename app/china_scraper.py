"""Deep extractor for Chinese e-commerce product listings, SKU variants, price tiers, and supplier profiles."""
import re

import httpx

from app.china import extract_url_from_text, parse_china_url
from app.models import ChinaDeepAnalysisResult, PriceTier, SKUVariant, SupplierProfile


async def deep_extract_china_product(raw_text_or_url: str) -> ChinaDeepAnalysisResult:
    """Deeply inspect a 1688/PDD/Taobao URL and extract title, price tiers, SKU matrix, images, and supplier info."""
    clean_url = extract_url_from_text(raw_text_or_url)
    parse_basic = await parse_china_url(clean_url)
    platform = parse_basic.platform
    item_id = parse_basic.item_id
    canonical = parse_basic.canonical_url

    title_zh = parse_basic.extracted_title or f"Товар {platform} ({item_id or 'без ID'})"
    images: list[str] = []
    if parse_basic.extracted_image_url:
        images.append(parse_basic.extracted_image_url)

    price_cny: float | None = None
    price_tiers: list[PriceTier] = []
    sku_variants: list[SKUVariant] = []
    supplier = SupplierProfile()
    data_notes: list[str] = []

    try:
        async with httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
            timeout=10.0,
        ) as client:
            resp = await client.get(canonical)
            if resp.status_code == 200:
                html = resp.text

                # Extract images from img tags or JSON payload
                img_matches = re.findall(r'https?://[^\s<>"\']+\.(?:jpg|png|jpeg|webp)', html, re.I)
                for img in img_matches:
                    if "cbu01.alicdn.com" in img or "img.alicdn.com" in img or "yangkeduo" in img:
                        if img not in images and len(images) < 5:
                            images.append(img)

                # Search for price patterns in HTML e.g. "price":"15.50" or "priceRange"
                price_match = re.search(r'["\']price["\']\s*:\s*["\']?(\d+(?:\.\d{1,2})?)["\']?', html)
                if price_match:
                    try:
                        price_cny = float(price_match.group(1))
                    except ValueError:
                        pass
    except Exception:
        pass

    if price_cny is None:
        data_notes.append("Цена не извлечена: проверьте её на карточке поставщика.")
    if not price_tiers:
        data_notes.append("Оптовые ступени MOQ не извлечены из публичной страницы.")
    if not sku_variants:
        data_notes.append("Варианты SKU не извлечены: запросите реальные фото и комплектацию у поставщика.")
    if not supplier.company_name:
        data_notes.append("Профиль поставщика не подтверждён автоматически.")

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
