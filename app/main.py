from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from app.china import build_search_urls, parse_china_url
from app.china_api import ChinaSearchResult, get_china_data_provider
from app.config import get_settings
from app.database import DatabaseError, get_cached_youtube_signal, get_trend_history, save_scan, save_trend_observation
from app.kaspi import KaspiExtractionError, fetch_product
from app.economics import calculate_economics, compare_cargo
from app.models import (
    CargoQuote,
    CargoQuoteRequest,
    ChinaParseRequest,
    ChinaParseResult,
    ChinaSearchRequest,
    ChinaSearchResponse,
    EconomicsRequest,
    EconomicsResult,
    ProductInsight,
    ScanRequest,
    ScanResult,
    SupplierComparisonRequest,
    SupplierComparisonResult,
    TrendReport,
    TrendWatchRequest,
)
from app.services import (
    XAIServiceError,
    assess_risk,
    build_product_insight,
    evaluate_hard_filters,
    generate_chinese_keywords,
)
from app.telegram import handle_update, register_commands
from app.trends import build_trend_report
from app.youtube_trends import fetch_youtube_trend_signal


@asynccontextmanager
async def lifespan(_: FastAPI):
    await register_commands()
    yield


app = FastAPI(title="Kaspi Sourcing AI", version="0.3.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "services": {
            "supabase_configured": settings.supabase_configured,
            "xai_configured": settings.xai_configured,
            "telegram_configured": settings.telegram_configured,
            "china_live_data_configured": settings.china_live_data_configured,
            "youtube_configured": settings.youtube_configured,
        },

    }


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    configured_key = get_settings().app_api_key
    if configured_key and x_api_key != configured_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


@app.post("/api/v1/kaspi/scan", response_model=ScanResult)
async def scan_kaspi_product(request: ScanRequest, _: None = Depends(require_api_key)) -> ScanResult:
    try:
        product = await fetch_product(str(request.url))
    except KaspiExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    passes, reasons = evaluate_hard_filters(product)
    try:
        assessment = await assess_risk(product) if request.analyze_with_ai and passes else None
    except XAIServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result = ScanResult(product=product, passes_hard_filters=passes, filter_reasons=reasons, ai_assessment=assessment)
    try:
        save_scan(result)
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result


@app.post("/api/v1/kaspi/insight", response_model=ProductInsight)
async def kaspi_insight(request: ScanRequest, _: None = Depends(require_api_key)) -> ProductInsight:
    try:
        product = await fetch_product(str(request.url))
    except KaspiExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return build_product_insight(product)


@app.post("/api/v1/trends/watch", response_model=TrendReport)
async def trend_watch(request: TrendWatchRequest, _: None = Depends(require_api_key)) -> TrendReport:
    """Record a daily product observation and return evidence, never a fabricated trend."""
    try:
        product = await fetch_product(str(request.kaspi_url))
        youtube = get_cached_youtube_signal(product.title) or await fetch_youtube_trend_signal(product.title)
        save_trend_observation(product, youtube)
        watch, snapshots = get_trend_history(str(product.source_url))
        return build_trend_report(watch, snapshots, youtube)
    except KaspiExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/v1/trends/report", response_model=TrendReport)
async def trend_report(kaspi_url: str, _: None = Depends(require_api_key)) -> TrendReport:
    try:
        watch, snapshots = get_trend_history(kaspi_url)
        youtube = get_cached_youtube_signal(watch["title"]) or await fetch_youtube_trend_signal(watch["title"])
        return build_trend_report(watch, snapshots, youtube)
    except DatabaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/economics/calculate", response_model=EconomicsResult)
async def economics_calculate(request: EconomicsRequest, _: None = Depends(require_api_key)) -> EconomicsResult:
    return calculate_economics(request)


@app.post("/api/v1/cargo/compare", response_model=list[CargoQuote])
async def cargo_compare(request: CargoQuoteRequest, _: None = Depends(require_api_key)) -> list[CargoQuote]:
    return compare_cargo(request)


@app.post("/api/v1/china/parse", response_model=ChinaParseResult)
async def china_parse(request: ChinaParseRequest, _: None = Depends(require_api_key)) -> ChinaParseResult:
    return await parse_china_url(request.url)


@app.post("/api/v1/china/search-keywords", response_model=ChinaSearchResponse)
async def china_search_keywords(request: ChinaSearchRequest, _: None = Depends(require_api_key)) -> ChinaSearchResponse:
    keywords = await generate_chinese_keywords(request.title_ru)
    urls = build_search_urls(keywords)
    return ChinaSearchResponse(keywords_chinese=keywords, search_urls=urls)


@app.post("/api/v1/china/suppliers/search", response_model=ChinaSearchResult)
async def china_suppliers_search(request: ChinaSearchRequest, _: None = Depends(require_api_key)) -> ChinaSearchResult:
    """Return real supplier listings only through an explicitly configured provider."""
    keywords = await generate_chinese_keywords(request.title_ru)
    return await get_china_data_provider().search_suppliers(request.title_ru, keywords)


@app.post("/api/v1/china/compare-supplier", response_model=SupplierComparisonResult)
async def china_compare_supplier(request: SupplierComparisonRequest, _: None = Depends(require_api_key)) -> SupplierComparisonResult:
    try:
        product = await fetch_product(str(request.kaspi_url))
    except KaspiExtractionError as exc:
        raise HTTPException(status_code=422, detail=f"Kaspi product error: {exc}") from exc

    parse_res = await parse_china_url(str(request.supplier_url))
    kaspi_price = product.price_kzt or 0.0

    econ_req = EconomicsRequest(
        sale_price_kzt=kaspi_price if kaspi_price > 0 else 10000.0,
        unit_price_cny=request.unit_price_cny,
        quantity=request.quantity,
        cargo_cost_kzt=request.cargo_cost_kzt,
    )
    econ_res = calculate_economics(econ_req)

    return SupplierComparisonResult(
        kaspi_title=product.title,
        kaspi_price_kzt=kaspi_price,
        supplier_platform=parse_res.platform,
        supplier_url=parse_res.canonical_url,
        unit_price_cny=request.unit_price_cny,
        unit_cost_kzt=econ_res.unit_cost_kzt,
        profit_per_unit_kzt=econ_res.profit_per_unit_kzt,
        margin_percent=econ_res.margin_percent,
        roi_percent=econ_res.roi_percent,
        recommendation=econ_res.recommendation,
    )


from app.china_scraper import deep_extract_china_product
from app.currency import get_cny_to_kzt_rate
from app.models import (
    CargoQuote,
    CargoQuoteRequest,
    ChinaDeepAnalysisResult,
    ChinaParseRequest,
    ChinaParseResult,
    ChinaSearchRequest,
    ChinaSearchResponse,
    EconomicsRequest,
    EconomicsResult,
    ProductInsight,
    ProcurementItem,
    ProcurementSheetResult,
    ScanRequest,
    ScanResult,
    SupplierComparisonRequest,
    SupplierComparisonResult,
)
from app.procurement import generate_procurement_sheet


from app.cargo_label import CargoLabelRequest, CargoLabelResult, generate_cargo_label
from app.niche_finder import NicheTrendsResponse, find_trending_sourcing_niches


@app.get("/api/v1/currency/cny-rate")
async def get_cny_rate() -> dict[str, float]:
    rate = await get_cny_to_kzt_rate()
    return {"cny_to_kzt": rate}


@app.post("/api/v1/china/deep-extract", response_model=ChinaDeepAnalysisResult)
async def china_deep_extract(request: ChinaParseRequest, _: None = Depends(require_api_key)) -> ChinaDeepAnalysisResult:
    return await deep_extract_china_product(request.url)


@app.post("/api/v1/china/export-procurement", response_model=ProcurementSheetResult)
async def export_procurement(items: list[ProcurementItem], _: None = Depends(require_api_key)) -> ProcurementSheetResult:
    return await generate_procurement_sheet(items)


@app.post("/api/v1/cargo/generate-label", response_model=CargoLabelResult)
async def cargo_generate_label(request: CargoLabelRequest, _: None = Depends(require_api_key)) -> CargoLabelResult:
    return generate_cargo_label(request)


@app.get("/api/v1/sourcing/niche-trends", response_model=NicheTrendsResponse)
async def sourcing_niche_trends(category: str = "все категории", _: None = Depends(require_api_key)) -> NicheTrendsResponse:
    return await find_trending_sourcing_niches(category)



@app.post("/api/v1/telegram/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def telegram_webhook(request: Request) -> None:
    settings = get_settings()
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if settings.telegram_webhook_secret and secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram webhook secret")
    await handle_update(await request.json())
