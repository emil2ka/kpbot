"""China sourcing integrations: URL parsing, share text extraction, canonicalization, and search link generation for 1688, Pinduoduo, Taobao, JD, Xianyu, Dewu, Vipshop, and Alibaba."""
import html
import re
from urllib.parse import parse_qs, quote, urlparse

import httpx

from app.models import ChinaParseResult

# Platform URL patterns
_PATTERNS = [
    (r"1688\.com", "1688"),
    (r"pinduoduo\.com|yangkeduo\.com|pdd\.com", "Pinduoduo"),
    (r"2\.taobao\.com|xianyu\.com", "Xianyu"),
    (r"tmall\.com", "Tmall"),
    (r"taobao\.com", "Taobao"),
    (r"jd\.com|jingdong\.com", "JD"),
    (r"vip\.com", "Vipshop"),
    (r"dewu\.com|poizon\.com", "Dewu/Poizon"),
    (r"alibaba\.com", "Alibaba"),
    (r"shein\.com|shein\.cn", "Shein"),
    (r"temu\.com", "Temu"),
]



def extract_url_from_text(text: str) -> str:
    """Extract clean URL from noisy mobile app share snippet (e.g. from PDD or 1688 app)."""
    match = re.search(r"https?://[^\s<>\"']+", text)
    return match.group(0) if match else text.strip()


def extract_price_hint(text: str) -> float | None:
    """Extract price in CNY from share text if mentioned (e.g., '19.9元', '￥25.0', '15元包邮')."""
    match = re.search(r"(?:￥|¥|\b)(\d+(?:\.\d{1,2})?)\s*(?:元|块|￥|¥)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def detect_platform(url: str) -> str:
    """Identify the Chinese e-commerce platform from a URL string."""
    clean_url = extract_url_from_text(url)
    lower_url = clean_url.lower()
    for pattern, platform in _PATTERNS:
        if re.search(pattern, lower_url):
            return platform
    return "Other"


def extract_item_id(url: str) -> str | None:
    """Extract item ID from various Chinese platform URL structures."""
    clean_url = extract_url_from_text(url)
    parsed = urlparse(clean_url)
    qs = parse_qs(parsed.query)

    # Standard query param IDs (id, offerId, productId, goods_id, etc.)
    for key in ("id", "offerId", "offer_id", "productId", "goods_id", "goodsId", "item_id"):
        if key in qs and qs[key]:
            return qs[key][0]

    # Path-based IDs, e.g. 1688 offer/678912345.html or detail.1688.com/offer/1234567.html or /item/12345.html
    match = re.search(r"/(?:offer|item|goods|product|detail)/(\d+)", parsed.path)
    if match:
        return match.group(1)

    # Direct digits filename, e.g. /123456789.html or /1000293848.html
    match_file = re.search(r"/(\d{6,20})\.(?:html|htm)", parsed.path)
    if match_file:
        return match_file.group(1)

    return None


def canonicalize_url(platform: str, item_id: str | None, raw_url: str) -> str:
    """Construct a clean, canonical desktop/mobile link without tracking params."""
    clean_url = extract_url_from_text(raw_url)
    if not item_id:
        return clean_url

    if platform == "1688":
        return f"https://detail.1688.com/offer/{item_id}.html"
    elif platform == "Pinduoduo":
        return f"https://mobile.yangkeduo.com/goods.html?goods_id={item_id}"
    elif platform == "Taobao":
        return f"https://item.taobao.com/item.htm?id={item_id}"
    elif platform == "Tmall":
        return f"https://detail.tmall.com/item.htm?id={item_id}"
    elif platform == "JD":
        return f"https://item.jd.com/{item_id}.html"
    elif platform == "Alibaba":
        return f"https://www.alibaba.com/product-detail/item_{item_id}.html"
    elif platform == "Xianyu":
        return f"https://2.taobao.com/item.htm?id={item_id}"
    return clean_url


def build_search_urls(chinese_keywords: str, max_price_cny: float | None = None) -> dict[str, str]:
    """Generate direct search URLs from a safe, readable China query."""
    clean_keywords = normalize_search_keywords(chinese_keywords)
    encoded = quote(clean_keywords)
    urls = {
        "1688": f"https://s.1688.com/selloffer/offer_search.htm?keywords={encoded}",
        "pinduoduo": f"https://mobile.yangkeduo.com/search_result.html?search_key={encoded}",
        "taobao": f"https://s.taobao.com/search?q={encoded}",
        "jd": f"https://search.jd.com/Search?keyword={encoded}",
        "xianyu": f"https://s.xianyu.com/search?q={encoded}",
        "dewu": f"https://www.dewu.com/search?k={encoded}",
        "alibaba": f"https://www.alibaba.com/trade/search?SearchText={encoded}",
    }
    if max_price_cny and max_price_cny > 0:
        price_str = f"{max_price_cny:.1f}"
        urls["1688"] += f"&priceFilter.endPrice={price_str}"
        urls["taobao"] += f"&end_price={price_str}"
        urls["pinduoduo"] += f"&max_price={price_str}"
        urls["jd"] += f"&ev=exprice_0-{price_str}"
    return urls


def normalize_search_keywords(value: str) -> str:
    """Remove broken HTML/entity output before it reaches a marketplace URL."""
    text = html.unescape(str(value or "")).strip()
    text = text.replace("\ufffd", " ")
    text = re.sub(r"&#(?:x[0-9a-fA-F]+|\d+);?", " ", text)
    text = re.sub(r"[<>\[\]{}|]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    han_count = len(re.findall(r"[\u3400-\u9fff]", text))
    # Do not emit an empty or corrupted search. This fallback is intentionally
    # broad but valid; the bot labels it as a query for the user to refine.
    return text if han_count >= 2 else "商品 批发"


def build_image_search_url(image_url: str | None) -> str | None:
    """Generate 1688 visual search URL for a Kaspi product image."""
    if not image_url:
        return None
    encoded_img = quote(str(image_url).strip())
    return f"https://s.1688.com/selloffer/image_search.htm?imageUrl={encoded_img}"



async def parse_china_url(raw_text_or_url: str) -> ChinaParseResult:
    """Parse raw URL or app share text, detect platform, clean canonical URL, and extract public meta information."""
    extracted_url = extract_url_from_text(raw_text_or_url)
    price_hint = extract_price_hint(raw_text_or_url)
    platform = detect_platform(extracted_url)
    item_id = extract_item_id(extracted_url)
    canonical = canonicalize_url(platform, item_id, extracted_url)

    title = None
    image_url = None

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
                title_match = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']', html, re.I)
                if not title_match:
                    title_match = re.search(r'<title>(.*?)</title>', html, re.I)
                if title_match:
                    title = title_match.group(1).strip()
                    title = re.sub(r"-1688\.com|-淘宝网|-Alibaba.com|-拼多多", "", title).strip()

                img_match = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\'](.*?)["\']', html, re.I)
                if img_match:
                    image_url = img_match.group(1).strip()
    except Exception:
        pass

    return ChinaParseResult(
        raw_url=raw_text_or_url,
        platform=platform,
        item_id=item_id,
        canonical_url=canonical,
        extracted_title=title,
        extracted_image_url=image_url,
    )
