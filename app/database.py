from app.config import get_settings
from uuid import UUID

from app.models import ScanResult


class DatabaseError(RuntimeError):
    """Raised when the configured Supabase persistence layer is unavailable."""


def save_scan(result: ScanResult) -> bool:
    s = get_settings()
    if not s.supabase_configured:
        return False
    from supabase import create_client

    client = create_client(s.supabase_url, s.supabase_service_role_key)
    record = {
        "source_url": str(result.product.source_url),
        "title": result.product.title,
        "price_kzt": result.product.price_kzt,
        "review_count": result.product.review_count,
        "seller_count": result.product.seller_count,
        "rating": result.product.rating,
        "image_url": str(result.product.image_url) if result.product.image_url else None,
        "scraped_at": result.product.scraped_at.isoformat(),
        "passes_hard_filters": result.passes_hard_filters,
        "filter_reasons": result.filter_reasons,
        "ai_assessment": result.ai_assessment.model_dump() if result.ai_assessment else None,
    }
    try:
        client.table("kaspi_scans").insert(record).execute()
    except Exception as exc:  # The SDK exposes several transport-specific exceptions.
        raise DatabaseError("Не удалось сохранить результат в Supabase") from exc
    return True


def save_supplier_link(
    platform: str,
    raw_url: str,
    canonical_url: str,
    item_id: str | None = None,
    unit_price_cny: float | None = None,
    minimum_order_quantity: int = 1,
    weight_kg: float | None = None,
    notes: str | None = None,
    scan_id: UUID | None = None,
) -> bool:
    s = get_settings()
    if not s.supabase_configured:
        return False
    from supabase import create_client

    client = create_client(s.supabase_url, s.supabase_service_role_key)
    record = {
        "platform": platform,
        "raw_url": raw_url,
        "canonical_url": canonical_url,
        "item_id": item_id,
        "unit_price_cny": unit_price_cny,
        "minimum_order_quantity": minimum_order_quantity,
        "weight_kg": weight_kg,
        "notes": notes,
        "scan_id": scan_id,
    }
    try:
        client.table("supplier_links").insert(record).execute()
    except Exception as exc:
        raise DatabaseError("Не удалось сохранить ссылку поставщика в Supabase") from exc
    return True
