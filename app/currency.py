"""Live exchange rate manager for CNY to KZT conversion."""
from datetime import datetime, timezone
import httpx

_CACHED_RATE: float = 72.0
_LAST_FETCHED: datetime | None = None
_CACHE_TTL_SECONDS = 3600  # 1 hour cache


async def get_cny_to_kzt_rate() -> float:
    """Fetch live CNY to KZT exchange rate with 1-hour in-memory cache and fallback."""
    global _CACHED_RATE, _LAST_FETCHED

    now = datetime.now(timezone.utc)
    if _LAST_FETCHED and (now - _LAST_FETCHED).total_seconds() < _CACHE_TTL_SECONDS:
        return _CACHED_RATE

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://open.er-api.com/v6/latest/CNY")
            if resp.status_code == 200:
                rates = resp.json().get("rates", {})
                kzt_rate = rates.get("KZT")
                if kzt_rate and float(kzt_rate) > 0:
                    _CACHED_RATE = round(float(kzt_rate), 2)
                    _LAST_FETCHED = now
                    return _CACHED_RATE
    except Exception:
        pass

    return _CACHED_RATE


def set_cached_cny_rate(rate: float) -> None:
    """Manually override or seed the cached exchange rate."""
    global _CACHED_RATE, _LAST_FETCHED
    if rate > 0:
        _CACHED_RATE = round(rate, 2)
        _LAST_FETCHED = datetime.now(timezone.utc)
