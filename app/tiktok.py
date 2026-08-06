"""Quota-free TikTok trend signals and hashtag scraping for product research.

Parses public TikTok search signals, view counts, and engagement metrics
without official API keys.
"""
from datetime import datetime, timezone
import json
import re
from urllib.parse import quote

import httpx
from pydantic import BaseModel


class TikTokVideoInfo(BaseModel):
    video_id: str
    desc: str
    views: int = 0
    likes: int = 0
    author: str = ""
    created_at: str = ""
    video_url: str = ""


class TikTokTrendSignal(BaseModel):
    query: str
    observed_at: datetime
    video_count: int = 0
    total_views: int = 0
    total_likes: int = 0
    status: str
    source_note: str
    top_hashtags: list[str] = []
    top_videos: list[TikTokVideoInfo] = []


def extract_tiktok_hydration_data(html: str) -> dict | None:
    """Extract embedded JSON state from TikTok web pages."""
    match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        match = re.search(r'<script id="SIGI_STATE" type="application/json">(.*?)</script>', html, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return None


async def fetch_tiktok_trend_signal(query: str) -> TikTokTrendSignal:
    """Fetch recent public TikTok videos and metrics for product search query."""
    now = datetime.now(timezone.utc)
    clean_query = " ".join(query.split())[:100]
    if not clean_query:
        return TikTokTrendSignal(
            query=query, observed_at=now, status="empty_query", source_note="Пустой запрос"
        )

    search_url = f"https://www.tiktok.com/search?q={quote(clean_query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=8.0) as client:
            resp = await client.get(search_url)

        if resp.status_code != 200:
            return TikTokTrendSignal(
                query=clean_query,
                observed_at=now,
                status="unavailable",
                source_note=f"TikTok returned HTTP {resp.status_code}",
            )

        html = resp.text
        data = extract_tiktok_hydration_data(html)
        videos: list[TikTokVideoInfo] = []
        hashtags: set[str] = set()

        if data:
            default_scope = data.get("__DEFAULT_SCOPE__", {})
            search_item_list = default_scope.get("webapp.search-detail", {}).get("data", [])
            if not search_item_list:
                item_module = data.get("ItemModule", {})
                search_item_list = list(item_module.values())

            for item in search_item_list:
                if not isinstance(item, dict):
                    continue
                item_struct = item.get("item", item)
                stats = item_struct.get("stats", {}) or item_struct.get("statsV2", {})
                author = item_struct.get("author", {}).get("uniqueId", "")
                desc = item_struct.get("desc", "")
                v_id = item_struct.get("id", "")
                if not v_id:
                    continue

                views = int(stats.get("playCount", 0) or stats.get("views", 0))
                likes = int(stats.get("diggCount", 0) or stats.get("likes", 0))

                for tag in re.findall(r"#(\w+)", desc):
                    hashtags.add(tag.lower())

                videos.append(
                    TikTokVideoInfo(
                        video_id=v_id,
                        desc=desc[:150],
                        views=views,
                        likes=likes,
                        author=author,
                        video_url=f"https://www.tiktok.com/@{author}/video/{v_id}" if author else f"https://www.tiktok.com/video/{v_id}",
                    )
                )

        if not videos:
            play_counts = [int(m) for m in re.findall(r'"playCount":(\d+)', html)]
            digg_counts = [int(m) for m in re.findall(r'"diggCount":(\d+)', html)]
            video_ids = re.findall(r'"id":"(\d{15,20})"', html)

            for i, vid in enumerate(video_ids[:10]):
                views = play_counts[i] if i < len(play_counts) else 0
                likes = digg_counts[i] if i < len(digg_counts) else 0
                videos.append(
                    TikTokVideoInfo(
                        video_id=vid,
                        desc=clean_query,
                        views=views,
                        likes=likes,
                        video_url=f"https://www.tiktok.com/video/{vid}",
                    )
                )

        total_views = sum(v.views for v in videos)
        total_likes = sum(v.likes for v in videos)

        return TikTokTrendSignal(
            query=clean_query,
            observed_at=now,
            video_count=len(videos),
            total_views=total_views,
            total_likes=total_likes,
            status="live" if videos else "no_results",
            source_note="Публичный поиск TikTok (без ключа API)",
            top_hashtags=list(hashtags)[:8],
            top_videos=videos[:5],
        )

    except httpx.TimeoutException:
        return TikTokTrendSignal(
            query=clean_query, observed_at=now, status="unavailable", source_note="Таймаут запроса к TikTok"
        )
    except Exception as exc:
        return TikTokTrendSignal(
            query=clean_query, observed_at=now, status="unavailable", source_note=f"Ошибка TikTok: {exc.__class__.__name__}"
        )
