"""Public Telegram Channel and Product Mention Monitor.

Parses public Telegram web mirrors (t.me/s/) and channel feeds for product
mentions, trade discussions, and viral posts without needing official API keys.
"""
from datetime import datetime, timezone
import re
from urllib.parse import quote

import httpx
from pydantic import BaseModel


class TelegramPostInfo(BaseModel):
    channel: str
    message_id: int
    text: str
    views: str = "0"
    date: str = ""
    post_url: str = ""


class TelegramTrendSignal(BaseModel):
    query: str
    observed_at: datetime
    post_count: int = 0
    total_views_est: int = 0
    channels_found: list[str] = []
    status: str
    source_note: str
    top_posts: list[TelegramPostInfo] = []


# Popular Telegram public channels in Kazakhstan & CIS related to Kaspi and Sourcing
DEFAULT_SEARCH_CHANNELS = [
    "tovarka_kz",
    "wildberries_kz",
    "kaspiseller",
    "kaspikz_sellers",
]


async def fetch_telegram_channel_mentions(channel_username: str, query: str) -> list[TelegramPostInfo]:
    """Fetch public post mentions of query from t.me/s/<channel>."""
    url = f"https://t.me/s/{channel_username}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    posts: list[TelegramPostInfo] = []
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=6.0) as client:
            resp = await client.get(url)

        if resp.status_code == 200:
            html = resp.text
            # Extract post blocks split by tgme_widget_message
            blocks = html.split('<div class="tgme_widget_message ')
            query_lower = query.lower()

            for block in blocks[1:]:
                # Check for message text
                text_match = re.search(r'js-message_text[^>]*>(.*?)</div>', block, re.S) or re.search(r'<div class="tgme_widget_message_text\b[^">]*">(.*?)</div>', block, re.S)
                if not text_match:
                    continue
                raw_text = re.sub(r'<[^<]+?>', '', text_match.group(1)).strip()
                if query_lower not in raw_text.lower():
                    continue

                msg_id_match = re.search(r'data-post="[^/]+/(\d+)"', block)
                views_match = re.search(r'<span class="tgme_widget_message_views">(.*?)</span>', block)
                date_match = re.search(r'<time datetime="([^"]+)"', block)

                msg_id = int(msg_id_match.group(1)) if msg_id_match else 0
                views = views_match.group(1).strip() if views_match else "0"
                post_date = date_match.group(1) if date_match else ""

                posts.append(
                    TelegramPostInfo(
                        channel=channel_username,
                        message_id=msg_id,
                        text=raw_text[:200],
                        views=views,
                        date=post_date,
                        post_url=f"https://t.me/{channel_username}/{msg_id}" if msg_id else f"https://t.me/s/{channel_username}",
                    )
                )
    except Exception:
        pass
    return posts


async def fetch_telegram_trend_signal(query: str, channels: list[str] | None = None) -> TelegramTrendSignal:
    """Scan public Telegram trade channels for mentions of the target product."""
    now = datetime.now(timezone.utc)
    clean_query = " ".join(query.split())[:100]
    if not clean_query:
        return TelegramTrendSignal(
            query=query, observed_at=now, status="empty_query", source_note="Пустой запрос"
        )

    target_channels = channels or DEFAULT_SEARCH_CHANNELS
    all_posts: list[TelegramPostInfo] = []
    found_channels: set[str] = set()

    for ch in target_channels:
        posts = await fetch_telegram_channel_mentions(ch, clean_query)
        if posts:
            all_posts.extend(posts)
            found_channels.add(ch)

    total_est_views = 0
    for p in all_posts:
        v_str = p.views.upper().replace('K', '000').replace('M', '000000').replace('.', '')
        digits = ''.join(c for c in v_str if c.isdigit())
        if digits:
            total_est_views += int(digits)

    status = "live" if all_posts else "no_results"
    note = f"Проверено {len(target_channels)} публичных TG-каналов"

    return TelegramTrendSignal(
        query=clean_query,
        observed_at=now,
        post_count=len(all_posts),
        total_views_est=total_est_views,
        channels_found=list(found_channels),
        status=status,
        source_note=note,
        top_posts=all_posts[:5],
    )
