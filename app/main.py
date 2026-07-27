from fastapi import Depends, FastAPI, Header, HTTPException, status

from app.config import get_settings
from app.database import DatabaseError, save_scan
from app.kaspi import KaspiExtractionError, fetch_product
from app.models import ScanRequest, ScanResult
from app.services import XAIServiceError, assess_risk, evaluate_hard_filters

app = FastAPI(title="Kaspi Product Research MVP", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "services": {
            "supabase_configured": settings.supabase_configured,
            "xai_configured": settings.xai_configured,
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
