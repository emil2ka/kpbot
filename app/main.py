from fastapi import FastAPI, HTTPException

from app.database import save_scan
from app.kaspi import KaspiExtractionError, fetch_product
from app.models import ScanRequest, ScanResult
from app.services import assess_risk, evaluate_hard_filters

app = FastAPI(title="Kaspi Product Research MVP", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/kaspi/scan", response_model=ScanResult)
async def scan_kaspi_product(request: ScanRequest) -> ScanResult:
    try:
        product = await fetch_product(str(request.url))
    except KaspiExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    passes, reasons = evaluate_hard_filters(product)
    assessment = await assess_risk(product) if request.analyze_with_ai and passes else None
    result = ScanResult(product=product, passes_hard_filters=passes, filter_reasons=reasons, ai_assessment=assessment)
    save_scan(result)
    return result

