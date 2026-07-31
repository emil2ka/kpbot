from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from app.china import build_search_urls, parse_china_url
from app.config import get_settings
from app.database import DatabaseError, save_scan
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
)
from app.services import (
    XAIServiceError,
    assess_risk,
    build_product_insight,
    evaluate_hard_filters,
    generate_chinese_keywords,
)
from app.telegram import handle_update, register_commands


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


@app.post("/api/v1/telegram/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def telegram_webhook(request: Request) -> None:
    settings = get_settings()
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if settings.telegram_webhook_secret and secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram webhook secret")
    await handle_update(await request.json())
