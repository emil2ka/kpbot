"""Plug-and-play provider architecture for fetching or searching China suppliers (1688, PDD, Taobao)."""
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.china import build_image_search_url, build_search_urls
from app.config import get_settings
from app.economics import calculate_target_cny_price


class ChinaSupplierItem(BaseModel):
    title: str
    price_cny: float
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
        )


class RapidAPI1688Provider(ChinaDataProvider):
    """Live API provider querying RapidAPI 1688 API when API key is available."""

    def __init__(self, api_key: str):
        self.api_key = api_key

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
                    "X-RapidAPI-Host": "1688-api.p.rapidapi.com",
                }
                resp = await client.get(
                    "https://1688-api.p.rapidapi.com/search",
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
        return base_res


def get_china_data_provider() -> ChinaDataProvider:
    api_key = os.getenv("CHINA_API_KEY")
    if api_key:
        return RapidAPI1688Provider(api_key)
    return LinkSearchProvider()
