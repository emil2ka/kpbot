from datetime import datetime, timezone

from pydantic import BaseModel, Field, HttpUrl, field_validator


class KaspiProduct(BaseModel):
    source_url: HttpUrl
    title: str
    price_kzt: int | None = None
    review_count: int | None = None
    seller_count: int | None = None
    rating: float | None = None
    image_url: HttpUrl | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScanRequest(BaseModel):
    url: HttpUrl
    analyze_with_ai: bool = False


class RiskAssessment(BaseModel):
    score: int = Field(ge=1, le=10)
    verdict: str
    risks: list[str]
    checks: list[str]


class ScanResult(BaseModel):
    product: KaspiProduct
    passes_hard_filters: bool
    filter_reasons: list[str]
    ai_assessment: RiskAssessment | None = None


class ProductInsight(BaseModel):
    score: int = Field(ge=0, le=100)
    verdict: str
    summary: str
    strengths: list[str]
    concerns: list[str]
    next_step: str


class SupplierLink(BaseModel):
    platform: str
    url: HttpUrl
    unit_price_cny: float | None = Field(default=None, ge=0)
    minimum_order_quantity: int | None = Field(default=None, ge=1)
    weight_kg: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class EconomicsRequest(BaseModel):
    sale_price_kzt: float = Field(gt=0)
    unit_price_cny: float = Field(gt=0)
    quantity: int = Field(gt=0)
    exchange_rate_cny_kzt: float = Field(default=72, gt=0)
    cargo_cost_kzt: float = Field(default=0, ge=0)
    kaspi_fee_percent: float = Field(default=12, ge=0, le=100)
    packaging_per_unit_kzt: float = Field(default=150, ge=0)
    advertising_per_unit_kzt: float = Field(default=0, ge=0)
    return_reserve_percent: float = Field(default=5, ge=0, le=100)
    customs_per_unit_kzt: float = Field(default=0, ge=0)
    target_margin_percent: float = Field(default=35, ge=0, le=100)


class EconomicsResult(BaseModel):
    unit_cost_kzt: float
    marketplace_fee_kzt: float
    return_reserve_kzt: float
    profit_per_unit_kzt: float
    margin_percent: float
    roi_percent: float
    total_profit_kzt: float
    maximum_purchase_price_cny: float
    recommendation: str


class CargoQuoteRequest(BaseModel):
    actual_weight_kg: float = Field(gt=0)
    length_cm: float = Field(gt=0)
    width_cm: float = Field(gt=0)
    height_cm: float = Field(gt=0)
    quantity: int = Field(default=1, gt=0)
    urgency: str = Field(default="normal")
    cargo_type: str = Field(default="standard")

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, value: str) -> str:
        if value not in {"low", "normal", "high"}:
            raise ValueError("urgency must be low, normal, or high")
        return value


class CargoQuote(BaseModel):
    carrier: str
    route: str
    method: str
    chargeable_weight_kg: float
    total_cost_kzt: float
    cost_per_unit_kzt: float
    delivery_days: str
    insurance_included: bool
    fit_score: int
    recommendation: str
    is_estimate: bool = True
    pricing_note: str = "Оценка по демонстрационному тарифу; подтвердите цену у карго-партнёра."


class ChinaParseRequest(BaseModel):
    url: str


class ChinaParseResult(BaseModel):
    raw_url: str
    platform: str
    item_id: str | None = None
    canonical_url: str
    extracted_title: str | None = None
    extracted_image_url: str | None = None


class ChinaSearchRequest(BaseModel):
    title_ru: str


class TrendWatchRequest(BaseModel):
    kaspi_url: HttpUrl


class TrendReport(BaseModel):
    kaspi_url: str
    title: str
    observed_at: datetime
    confidence_score: int = Field(ge=0, le=100)
    confidence_label: str
    kaspi_observations: int
    price_change_percent: float | None = None
    review_change: int | None = None
    seller_change: int | None = None
    youtube: dict
    tiktok: dict | None = None
    telegram: dict | None = None
    evidence: list[str]
    caveats: list[str]


class ChinaSearchResponse(BaseModel):
    keywords_chinese: str
    search_urls: dict[str, str]


class ChinaIdea(BaseModel):
    title_ru: str
    chinese_keywords: str
    why_interesting: str
    risk_to_check: str


class ChinaIdeaResearch(BaseModel):
    interpretation: str
    ideas: list[ChinaIdea] = Field(min_length=1, max_length=10)


class SupplierComparisonRequest(BaseModel):
    kaspi_url: HttpUrl
    supplier_url: HttpUrl
    unit_price_cny: float = Field(gt=0)
    quantity: int = Field(default=50, gt=0)
    cargo_cost_kzt: float = Field(default=30000, ge=0)


class SupplierComparisonResult(BaseModel):
    kaspi_title: str
    kaspi_price_kzt: float
    supplier_platform: str
    supplier_url: str
    unit_price_cny: float
    unit_cost_kzt: float
    profit_per_unit_kzt: float
    margin_percent: float
    roi_percent: float
    recommendation: str


class PriceTier(BaseModel):
    min_quantity: int
    max_quantity: int | None = None
    price_cny: float


class SKUVariant(BaseModel):
    variant_id: str
    name_zh: str
    name_ru: str | None = None
    price_cny: float
    stock: int | None = None
    image_url: str | None = None


class SupplierProfile(BaseModel):
    company_name: str | None = None
    location: str | None = None
    is_verified: bool = False
    years_in_business: int | None = None
    rating_score: float | None = None


class ChinaDeepAnalysisResult(BaseModel):
    raw_url: str
    platform: str
    item_id: str | None = None
    canonical_url: str
    title_zh: str
    title_ru: str | None = None
    price_cny: float | None = None
    price_tiers: list[PriceTier] = Field(default_factory=list)
    sku_variants: list[SKUVariant] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    supplier: SupplierProfile = Field(default_factory=SupplierProfile)
    estimated_weight_kg: float | None = None
    data_notes: list[str] = Field(default_factory=list)


class ProcurementItem(BaseModel):
    product_title_ru: str
    product_title_zh: str
    supplier_url: str
    platform: str
    sku_name: str
    quantity: int = Field(gt=0)
    target_price_cny: float = Field(gt=0)
    total_cny: float = 0.0
    notes: str | None = None


class ProcurementSheetRequest(BaseModel):
    items: list[ProcurementItem]
    custom_cny_rate: float | None = Field(default=None, ge=0)


class ProcurementSheetResult(BaseModel):
    total_items_count: int
    total_quantity: int
    total_amount_cny: float
    total_amount_kzt: float
    exchange_rate: float
    items: list[ProcurementItem]
    csv_content: str
    html_preview: str
