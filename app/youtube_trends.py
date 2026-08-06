"""Quota-aware public YouTube signals for product research."""
from datetime import datetime, timedelta, timezone
from statistics import median

import httpx
from pydantic import BaseModel

from app.config import get_settings


class YouTubeTrendSignal(BaseModel):
    query: str
    observed_at: datetime
    video_count_30d: int = 0
    video_count_7d: int = 0
    total_views: int = 0
    median_views_per_day: float | None = None
    status: str
    source_note: str


async def fetch_youtube_trend_signal(query: str) -> YouTubeTrendSignal:
    """Read recent public videos and statistics using the official API only."""
    now = datetime.now(timezone.utc)
    clean_query = " ".join(query.split())[:120]
    api_key = get_settings().youtube_api_key
    if not api_key:
        return YouTubeTrendSignal(query=clean_query, observed_at=now, status="not_configured", source_note="YOUTUBE_API_KEY не задан")
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            search = await client.get("https://www.googleapis.com/youtube/v3/search", params={
                "key": api_key, "part": "snippet", "type": "video", "order": "date",
                "q": clean_query, "maxResults": 25, "regionCode": "KZ",
                "relevanceLanguage": "ru", "publishedAfter": (now - timedelta(days=30)).isoformat(),
            })
            if search.status_code != 200:
                return YouTubeTrendSignal(query=clean_query, observed_at=now, status="unavailable", source_note=f"YouTube returned HTTP {search.status_code}")
            videos = search.json().get("items", [])
            ids = [item.get("id", {}).get("videoId") for item in videos if item.get("id", {}).get("videoId")]
            stats_by_id: dict[str, dict] = {}
            if ids:
                details = await client.get("https://www.googleapis.com/youtube/v3/videos", params={
                    "key": api_key, "part": "statistics", "id": ",".join(ids),
                })
                if details.status_code == 200:
                    stats_by_id = {item["id"]: item.get("statistics", {}) for item in details.json().get("items", [])}
        ages_and_views: list[tuple[float, int]] = []
        week_count = 0
        for item in videos:
            video_id = item.get("id", {}).get("videoId")
            published = item.get("snippet", {}).get("publishedAt")
            if not video_id or not published:
                continue
            published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
            age_days = max((now - published_at).total_seconds() / 86400, 1 / 24)
            if age_days <= 7:
                week_count += 1
            ages_and_views.append((age_days, int(stats_by_id.get(video_id, {}).get("viewCount", 0))))
        velocities = [views / age for age, views in ages_and_views]
        return YouTubeTrendSignal(
            query=clean_query, observed_at=now, video_count_30d=len(ages_and_views), video_count_7d=week_count,
            total_views=sum(views for _, views in ages_and_views),
            median_views_per_day=round(float(median(velocities)), 2) if velocities else None,
            status="live", source_note="Official YouTube Data API: recent public videos in region KZ",
        )
    except httpx.HTTPError as exc:
        return YouTubeTrendSignal(query=clean_query, observed_at=now, status="unavailable", source_note=f"YouTube request failed: {exc.__class__.__name__}")
