"""Transparent unit economics and cargo comparison for sourcing decisions."""

from app.models import CargoQuote, CargoQuoteRequest, EconomicsRequest, EconomicsResult


def calculate_economics(data: EconomicsRequest) -> EconomicsResult:
    purchase = data.unit_price_cny * data.exchange_rate_cny_kzt
    cargo_per_unit = data.cargo_cost_kzt / data.quantity
    unit_cost = purchase + cargo_per_unit + data.packaging_per_unit_kzt + data.customs_per_unit_kzt
    marketplace_fee = data.sale_price_kzt * data.kaspi_fee_percent / 100
    return_reserve = data.sale_price_kzt * data.return_reserve_percent / 100
    profit = data.sale_price_kzt - unit_cost - marketplace_fee - return_reserve - data.advertising_per_unit_kzt
    margin = profit / data.sale_price_kzt * 100
    roi = profit / unit_cost * 100 if unit_cost else 0
    # Use the same assumptions as the displayed profit calculation.  The old
    # shortcut used a fixed 30% margin and omitted fees and reserves.
    maximum_purchase = max(
        0,
        (
            data.sale_price_kzt * (1 - data.target_margin_percent / 100)
            - marketplace_fee
            - return_reserve
            - data.advertising_per_unit_kzt
            - cargo_per_unit
            - data.packaging_per_unit_kzt
            - data.customs_per_unit_kzt
        ) / data.exchange_rate_cny_kzt,
    )
    if margin >= 35:
        recommendation = "Можно тестировать: запас по марже выглядит здоровым."
    elif margin >= 20:
        recommendation = "Умеренный вариант: начинайте только с небольшой тестовой партии."
    else:
        recommendation = "Не рекомендуем без снижения закупочной цены или роста цены продажи."
    return EconomicsResult(
        unit_cost_kzt=round(unit_cost, 2), marketplace_fee_kzt=round(marketplace_fee, 2),
        return_reserve_kzt=round(return_reserve, 2), profit_per_unit_kzt=round(profit, 2),
        margin_percent=round(margin, 1), roi_percent=round(roi, 1),
        total_profit_kzt=round(profit * data.quantity, 2), maximum_purchase_price_cny=round(maximum_purchase, 2),
        recommendation=recommendation,
    )


def calculate_target_cny_price(
    sale_price_kzt: float,
    target_margin_percent: float = 35.0,
    exchange_rate_cny_kzt: float = 72.0,
    estimated_cargo_per_unit_kzt: float = 1200.0,
    kaspi_fee_percent: float = 12.0,
    packaging_per_unit_kzt: float = 150.0,
    return_reserve_percent: float = 5.0,
) -> float:
    """Calculate target CNY purchase price to hit desired net profit margin percentage."""
    if sale_price_kzt <= 0 or exchange_rate_cny_kzt <= 0:
        return 0.0

    target_profit_kzt = sale_price_kzt * (target_margin_percent / 100.0)
    marketplace_fee_kzt = sale_price_kzt * (kaspi_fee_percent / 100.0)
    return_reserve_kzt = sale_price_kzt * (return_reserve_percent / 100.0)

    # profit = sale_price - unit_cost - marketplace_fee - return_reserve
    # unit_cost = (cny_price * exchange_rate) + cargo + packaging
    # cny_price * exchange_rate = sale_price - target_profit - marketplace_fee - return_reserve - cargo - packaging
    max_cny = (
        sale_price_kzt - target_profit_kzt - marketplace_fee_kzt - return_reserve_kzt - estimated_cargo_per_unit_kzt - packaging_per_unit_kzt
    ) / exchange_rate_cny_kzt

    return max(0.0, round(max_cny, 2))



_CARRIERS = (
    {"carrier": "Cargo Air", "method": "Авиа", "per_kg": 3900, "days": "6–9 дней", "insurance": True},
    {"carrier": "Cargo Auto", "method": "Авто", "per_kg": 2300, "days": "13–18 дней", "insurance": True},
    {"carrier": "Cargo Economy", "method": "Авто эконом", "per_kg": 1850, "days": "22–32 дня", "insurance": False},
)


def compare_cargo(data: CargoQuoteRequest) -> list[CargoQuote]:
    volume_weight = data.length_cm * data.width_cm * data.height_cm / 6000
    chargeable_weight = max(data.actual_weight_kg, volume_weight)
    quotes: list[CargoQuote] = []
    for carrier in _CARRIERS:
        cost = chargeable_weight * carrier["per_kg"]
        score = 70
        if data.urgency == "high":
            score += 25 if carrier["method"] == "Авиа" else -15
        elif data.urgency == "low":
            score += 20 if carrier["method"] == "Авто эконом" else 0
        else:
            score += 15 if carrier["method"] == "Авто" else 0
        if data.cargo_type in {"fragile", "electronics"}:
            score += 10 if carrier["insurance"] else -25
        recommendation = "Лучший баланс цены, скорости и риска." if score >= 85 else "Подходит, если приоритет — скорость или низкая цена."
        quotes.append(CargoQuote(
            carrier=carrier["carrier"], route="Китай → Казахстан", method=carrier["method"],
            chargeable_weight_kg=round(chargeable_weight, 2), total_cost_kzt=round(cost, 2),
            cost_per_unit_kzt=round(cost / data.quantity, 2), delivery_days=carrier["days"],
            insurance_included=carrier["insurance"], fit_score=max(0, min(100, score)), recommendation=recommendation,
        ))
    return sorted(quotes, key=lambda quote: quote.fit_score, reverse=True)
