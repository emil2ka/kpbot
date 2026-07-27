from app.config import get_settings
from app.models import ScanResult


def save_scan(result: ScanResult) -> None:
    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        return
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
    client.table("kaspi_scans").insert(record).execute()

