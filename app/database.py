from app.config import get_settings
from uuid import UUID

from app.models import ScanResult
from app.models import KaspiProduct
from app.youtube_trends import YouTubeTrendSignal


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


def _client():
    s = get_settings()
    if not s.supabase_configured:
        raise DatabaseError("Supabase не настроен")
    from supabase import create_client
    return create_client(s.supabase_url, s.supabase_service_role_key)


def save_trend_observation(product: KaspiProduct, youtube: YouTubeTrendSignal) -> dict:
    """Persist one auditable Kaspi and YouTube observation."""
    try:
        client = _client()
        url = str(product.source_url)
        existing = client.table("trend_watches").select("id").eq("kaspi_url", url).limit(1).execute().data
        if existing:
            watch_id = existing[0]["id"]
            client.table("trend_watches").update({"title": product.title, "updated_at": product.scraped_at.isoformat()}).eq("id", watch_id).execute()
        else:
            watch_id = client.table("trend_watches").insert({"kaspi_url": url, "title": product.title}).execute().data[0]["id"]
        client.table("kaspi_trend_snapshots").insert({"watch_id": watch_id, "observed_at": product.scraped_at.isoformat(), "price_kzt": product.price_kzt, "review_count": product.review_count, "seller_count": product.seller_count, "rating": product.rating}).execute()
        if youtube.status == "live":
            client.table("youtube_trend_snapshots").insert({"query": youtube.query, "observed_at": youtube.observed_at.isoformat(), "video_count_30d": youtube.video_count_30d, "video_count_7d": youtube.video_count_7d, "total_views": youtube.total_views, "median_views_per_day": youtube.median_views_per_day, "source_note": youtube.source_note}).execute()
        return {"watch_id": watch_id}
    except Exception as exc:
        raise DatabaseError("Не удалось сохранить наблюдение тренда в Supabase; примените migration 004") from exc


def get_trend_history(kaspi_url: str) -> tuple[dict, list[dict]]:
    try:
        client = _client()
        watches = client.table("trend_watches").select("id,title,kaspi_url").eq("kaspi_url", kaspi_url).limit(1).execute().data
        if not watches:
            raise DatabaseError("Товар ещё не добавлен в мониторинг")
        watch = watches[0]
        snapshots = client.table("kaspi_trend_snapshots").select("*").eq("watch_id", watch["id"]).order("observed_at", desc=False).execute().data
        return watch, snapshots
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("Не удалось прочитать историю тренда из Supabase") from exc


def get_cached_youtube_signal(query: str) -> YouTubeTrendSignal | None:
    try:
        from datetime import datetime, timedelta, timezone
        rows = _client().table("youtube_trend_snapshots").select("*").eq("query", query).order("observed_at", desc=True).limit(1).execute().data
        if not rows:
            return None
        row = rows[0]
        observed_at = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - observed_at > timedelta(hours=24):
            return None
        return YouTubeTrendSignal(query=query, observed_at=observed_at, video_count_30d=row["video_count_30d"], video_count_7d=row["video_count_7d"], total_views=row["total_views"], median_views_per_day=row["median_views_per_day"], status="cached", source_note="Cached official YouTube observation (under 24 hours old)")
    except Exception:
        return None


def save_telegram_profile(telegram_id: int, profile: dict) -> bool:
    """Persist preferences; the Telegram UI still works when Supabase is absent."""
    if not get_settings().supabase_configured:
        return False
    try:
        _client().table("telegram_profiles").upsert({
            "telegram_id": telegram_id,
            "city": profile.get("city"),
            "test_budget_kzt": profile.get("test_budget_kzt"),
            "target_margin_percent": profile.get("target_margin_percent", 35),
            "excluded_categories": profile.get("excluded_categories", []),
            "goal": profile.get("goal"),
            "onboarded": profile.get("onboarded", False),
        }).execute()
        return True
    except Exception:
        return False


def get_telegram_profile(telegram_id: int) -> dict | None:
    if not get_settings().supabase_configured:
        return None
    try:
        rows = _client().table("telegram_profiles").select("*").eq("telegram_id", telegram_id).limit(1).execute().data
        return rows[0] if rows else None
    except Exception:
        return None


def save_sourcing_item(telegram_id: int, title: str, *, status: str = "idea", notes: str | None = None, kaspi_url: str | None = None, image_url: str | None = None, potential_score: int | None = None) -> str | None:
    if not get_settings().supabase_configured:
        return None
    try:
        result = _client().table("sourcing_items").insert({
            "owner_telegram_id": telegram_id, "title": title, "status": status,
            "notes": notes, "kaspi_url": kaspi_url, "image_url": image_url,
            "potential_score": potential_score,
        }).execute()
        return result.data[0]["id"] if result.data else None
    except Exception:
        return None


def list_sourcing_items(telegram_id: int, limit: int = 8) -> list[dict]:
    if not get_settings().supabase_configured:
        return []
    try:
        return _client().table("sourcing_items").select("id,title,status,potential_score,updated_at").eq("owner_telegram_id", telegram_id).order("updated_at", desc=True).limit(limit).execute().data
    except Exception:
        return []


def save_sourcing_offer(sourcing_item_id: str | None, platform: str, source_url: str, *, unit_price_cny: float | None = None, minimum_order_quantity: int | None = None, weight_kg: float | None = None, notes: str | None = None) -> bool:
    """Attach a supplier to the exact idea the user is currently evaluating."""
    if not sourcing_item_id or not get_settings().supabase_configured:
        return False
    try:
        _client().table("supplier_offers").insert({
            "sourcing_item_id": sourcing_item_id, "platform": platform,
            "source_url": source_url, "unit_price_cny": unit_price_cny,
            "minimum_order_quantity": minimum_order_quantity,
            "weight_kg": weight_kg, "notes": notes,
        }).execute()
        return True
    except Exception:
        return False
