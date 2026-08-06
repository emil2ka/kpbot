"""Plug-and-play provider architecture for fetching or searching China suppliers (1688, PDD, Taobao)."""
from abc import ABC, abstractmethod
import asyncio

import httpx
from pydantic import BaseModel, Field


from app.china import build_image_search_url, build_search_urls
from app.config import get_settings
from app.economics import calculate_target_cny_price
from app.made_in_china import build_made_in_china_search_url, search_made_in_china
from app.services import generate_global_search_keywords


class ChinaSupplierItem(BaseModel):
    title: str
    price_cny: float | None = None
    price_amount: float | None = None
    price_currency: str = "CNY"
    moq: int = 1
    image_url: str | None = None
    detail_url: str
    platform: str = "1688"
    supplier_name: str | None = None
    rating_score: float | None = None


class ChinaSearchResult(BaseModel):
    target_cny_price: float
    keywords_chinese: str
    search_urls: dict[str, str]
    image_search_url: str | None = None
    live_items: list[ChinaSupplierItem] = Field(default_factory=list)
    live_data_available: bool = False
    source_status: str = "not_configured"
    data_note: str = ""


class ChinaDataProvider(ABC):
    @abstractmethod
    async def search_suppliers(
        self,
        title_ru: str,
        keywords_zh: str,
        sale_price_kzt: float | None = None,
        image_url: str | None = None,
    ) -> ChinaSearchResult:
        pass


class LinkSearchProvider(ChinaDataProvider):
    """Default high-reliability provider generating targeted search links and price ceilings."""

    async def search_suppliers(
        self,
        title_ru: str,
        keywords_zh: str,
        sale_price_kzt: float | None = None,
        image_url: str | None = None,
    ) -> ChinaSearchResult:
        target_cny = calculate_target_cny_price(sale_price_kzt) if sale_price_kzt else 0.0
        search_urls = build_search_urls(keywords_zh, max_price_cny=target_cny if target_cny > 0 else None)
        img_url = build_image_search_url(image_url)

        return ChinaSearchResult(
            target_cny_price=target_cny,
            keywords_chinese=keywords_zh,
            search_urls=search_urls,
            image_search_url=img_url,
                live_items=[],
                live_data_available=False,
                source_status="not_configured",
            data_note=(
                "Каталожные цены не получены: подключите официальный или лицензированный "
                "провайдер данных, чтобы бот мог сравнивать реальные предложения."
            ),
        )


class RapidAPI1688Provider(ChinaDataProvider):
    """Live provider for a confirmed RapidAPI-compatible 1688 search endpoint."""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def search_suppliers(
        self,
        title_ru: str,
        keywords_zh: str,
        sale_price_kzt: float | None = None,
        image_url: str | None = None,
    ) -> ChinaSearchResult:
        base_res = await LinkSearchProvider().search_suppliers(title_ru, keywords_zh, sale_price_kzt, image_url)
        items: list[ChinaSupplierItem] = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {
                    "X-RapidAPI-Key": self.api_key,
                    "X-RapidAPI-Host": self.base_url.removeprefix("https://").removeprefix("http://"),
                }
                resp = await client.get(
                    f"{self.base_url}/search",
                    params={"keywords": keywords_zh, "page": 1, "pageSize": 5},
                    headers=headers,
                )
                if resp.status_code == 200:
                    raw_items = resp.json().get("result", {}).get("items", [])
                    for item in raw_items:
                        items.append(
                            ChinaSupplierItem(
                                title=item.get("title", keywords_zh),
                                price_cny=float(item.get("price", base_res.target_cny_price or 10.0)),
                                moq=int(item.get("moq", 1)),
                                image_url=item.get("picUrl"),
                                detail_url=item.get("detailUrl", base_res.search_urls["1688"]),
                                platform="1688",
                                supplier_name=item.get("supplierName"),
                            )
                        )
        except Exception:
            pass

        base_res.live_items = items
        base_res.live_data_available = bool(items)
        base_res.source_status = "live" if items else "no_results"
        base_res.data_note = (
            "Реальные предложения получены от подключённого провайдера."
            if items else "Провайдер не вернул предложения для этого запроса."
        )
        return base_res


from app.china_live import (
    build_live_1688_image_search_url,
    build_live_1688_search_url,
    build_live_alibaba_search_url,
    build_live_pdd_search_url,
    build_live_taobao_search_url,
    fetch_1688_live_suggestions,
    fetch_1688_live_search,
)


class SmartSourcingEngineProvider(ChinaDataProvider):
    """Smart Sourcing Provider fetching real live 1688 search items or direct price-filtered search URLs."""

    async def search_suppliers(
        self,
        title_ru: str,
        keywords_zh: str,
        sale_price_kzt: float | None = None,
        image_url: str | None = None,
    ) -> ChinaSearchResult:
        target_cny = calculate_target_cny_price(sale_price_kzt) if sale_price_kzt else 0.0

        # Both requests are independent; run them concurrently so a fallback
        # response does not needlessly wait for two network timeouts.
        suggestions, search_result = await asyncio.gather(
            fetch_1688_live_suggestions(keywords_zh),
            fetch_1688_live_search(keywords_zh, target_cny=target_cny if target_cny > 0 else None),
        )
        active_kw = suggestions[0] if suggestions else keywords_zh

        url_1688_factory = build_live_1688_search_url(active_kw, max_price_cny=target_cny if target_cny > 0 else None, factory_only=True)
        url_1688_all = build_live_1688_search_url(active_kw, max_price_cny=target_cny if target_cny > 0 else None, factory_only=False)
        url_pdd = build_live_pdd_search_url(active_kw, max_price_cny=target_cny if target_cny > 0 else None)
        url_tb = build_live_taobao_search_url(active_kw, max_price_cny=target_cny if target_cny > 0 else None)
        url_ali = build_live_alibaba_search_url(active_kw)
        img_url = build_live_1688_image_search_url(image_url) if image_url else None

        search_urls = {
            "1688": url_1688_factory,
            "1688_all": url_1688_all,
            "pinduoduo": url_pdd,
            "taobao": url_tb,
            "alibaba": url_ali,
        }

        # Repeat only if 1688 suggested a different query; otherwise reuse the
        # result above and avoid a duplicate request.
        if active_kw != keywords_zh:
            search_result = await fetch_1688_live_search(active_kw, target_cny=target_cny if target_cny > 0 else None)
        raw_real_items = search_result.items

        live_items: list[ChinaSupplierItem] = []
        for r_item in raw_real_items:
            live_items.append(
                ChinaSupplierItem(
                    title=r_item["title"],
                    price_cny=r_item["price_cny"],
                    moq=r_item.get("moq", 1),
                    detail_url=r_item["detail_url"],
                    platform="1688",
                )
            )

        if live_items:
            data_note = "Реальные предложения поставщиков 1688 получены в режиме реального времени."
            available = True
        else:
            global_keywords = await generate_global_search_keywords(title_ru)
            search_urls["made_in_china"] = build_made_in_china_search_url(global_keywords)
            fallback_items, fallback_note = await search_made_in_china(global_keywords)
            live_items = [ChinaSupplierItem(**item) for item in fallback_items]
            if live_items:
                available = True
                data_note = "1688: " + search_result.detail + ". Результаты получены из публичной выдачи Made-in-China; цена указана в USD."
            else:
                data_note = (
                    "1688: " + search_result.detail + ". Made-in-China: " + fallback_note + ". "
                    "Используйте прямые поисковые ссылки ниже или подключите лицензированный провайдер каталожных данных."
                )
            available = False

        return ChinaSearchResult(
            target_cny_price=target_cny,
            keywords_chinese=active_kw,
            search_urls=search_urls,
            image_search_url=img_url,
            live_items=live_items,
            live_data_available=available,
            source_status="live_fallback" if live_items else search_result.status,
            data_note=data_note,
        )


def get_china_data_provider() -> ChinaDataProvider:
    settings = get_settings()
    if settings.china_provider_configured:
        return RapidAPI1688Provider(settings.china_provider_api_key or "", settings.china_provider_base_url or "")
    return SmartSourcingEngineProvider()

