"""Niche Trend Scanner & High-ROI Product Sourcing Finder for Kaspi sellers."""
from pydantic import BaseModel, Field

from app.china_live import build_live_1688_search_url
from app.economics import calculate_target_cny_price


class NicheOpportunity(BaseModel):
    title_ru: str
    category_ru: str
    chinese_keywords: str
    suggested_sale_price_kzt: float
    target_purchase_cny: float
    estimated_margin_percent: float
    estimated_roi_percent: float
    why_promising: str
    risk_factor: str
    direct_1688_url: str


class NicheTrendsResponse(BaseModel):
    category: str
    summary_ru: str
    opportunities: list[NicheOpportunity]


async def find_trending_sourcing_niches(category: str = "все категории") -> NicheTrendsResponse:
    """Return curated sourcing hypotheses, not measured market trends.

    No sales or competition data source is connected, so fixed examples must
    never be presented as current demand, competition, or verified ROI.
    """
    opportunities = [
        NicheOpportunity(
            title_ru="Мини-увлажнитель воздуха с LED подсветкой",
            category_ru="Товары для дома / Климат",
            chinese_keywords="加湿器 迷你 桌面 家用",
            suggested_sale_price_kzt=6490.0,
            target_purchase_cny=22.5,
            estimated_margin_percent=42.0,
            estimated_roi_percent=140.0,
            why_promising="Гипотеза для проверки: компактный товар с понятной ценой и удобной логистикой.",
            risk_factor="Проверять герметичность и комплектность USB-кабелей при приемке.",
            direct_1688_url=build_live_1688_search_url("加湿器 迷你 桌面", max_price_cny=22.5, factory_only=True),
        ),
        NicheOpportunity(
            title_ru="Ортопедическая подушка с эффектом памяти (Memory Foam)",
            category_ru="Спальня / Текстиль",
            chinese_keywords="记忆棉 慢回弹 慢回弹枕头",
            suggested_sale_price_kzt=9890.0,
            target_purchase_cny=38.0,
            estimated_margin_percent=38.5,
            estimated_roi_percent=115.0,
            why_promising="Гипотеза для проверки: товар допускает вакуумную упаковку и может иметь достаточный средний чек.",
            risk_factor="Запрашивать у фабрики вакуумную спрессовку при упаковке коробок.",
            direct_1688_url=build_live_1688_search_url("记忆棉 枕头 工厂", max_price_cny=38.0, factory_only=True),
        ),
        NicheOpportunity(
            title_ru="Беспроводной автомобильный компрессор / Насос",
            category_ru="Автотовары / Электроника",
            chinese_keywords="充气泵 无线 车用 充气宝",
            suggested_sale_price_kzt=12990.0,
            target_purchase_cny=55.0,
            estimated_margin_percent=36.0,
            estimated_roi_percent=98.0,
            why_promising="Гипотеза для проверки: автомобильный аксессуар с понятным сценарием использования.",
            risk_factor="Проверять емкость аккумуляторов 18650 и наличие сертификатов безопасности.",
            direct_1688_url=build_live_1688_search_url("充气宝 无线 车用", max_price_cny=55.0, factory_only=True),
        ),
    ]

    return NicheTrendsResponse(
        category=category,
        summary_ru=(
            "Три стартовые гипотезы для ручной проверки. Цены и показатели — "
            "ориентиры юнит-экономики, а не подтверждённые тренды, спрос или конкуренция."
        ),
        opportunities=opportunities,
    )
