from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class KaspiProduct(BaseModel):
    source_url: HttpUrl
    title: str
    price_kzt: int | None = None
    review_count: int | None = None
    seller_count: int | None = None
    rating: float | None = None
    image_url: HttpUrl | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


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

