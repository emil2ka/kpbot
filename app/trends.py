"""Evidence-first trend reports from stored marketplace observations."""
from app.models import TrendReport
from app.youtube_trends import YouTubeTrendSignal


def build_trend_report(watch: dict, snapshots: list[dict], youtube: YouTubeTrendSignal) -> TrendReport:
    latest, first = snapshots[-1], snapshots[0]
    evidence = [f"Kaspi: {len(snapshots)} наблюдений, последнее — {latest['observed_at']}"]
    caveats: list[str] = []
    score = 20
    reviews_delta = None if latest.get("review_count") is None or first.get("review_count") is None else latest["review_count"] - first["review_count"]
    sellers_delta = None if latest.get("seller_count") is None or first.get("seller_count") is None else latest["seller_count"] - first["seller_count"]
    price_change = None
    if latest.get("price_kzt") and first.get("price_kzt"):
        price_change = round((latest["price_kzt"] - first["price_kzt"]) / first["price_kzt"] * 100, 1)
    if len(snapshots) < 7:
        caveats.append("История короче 7 наблюдений: это ранняя гипотеза, а не подтверждённый тренд.")
    else:
        score += 25
    if reviews_delta and reviews_delta > 0:
        score += 15; evidence.append(f"Отзывы Kaspi: +{reviews_delta}")
    if sellers_delta is not None:
        evidence.append(f"Продавцы Kaspi: {'+' if sellers_delta >= 0 else ''}{sellers_delta}")
        if sellers_delta <= 1: score += 10
    if youtube.status == "live":
        evidence.append(f"YouTube KZ: {youtube.video_count_7d} новых видео за 7 дней; {youtube.video_count_30d} за 30 дней")
        score += min(25, youtube.video_count_7d * 3)
    else:
        caveats.append("YouTube-сигнал пока недоступен.")
        # A marketplace-only signal is useful but cannot independently confirm
        # a cross-source trend.
        score = min(score, 69)
    score = max(0, min(100, score))
    label = "высокая" if score >= 70 else "средняя" if score >= 45 else "низкая"
    return TrendReport(kaspi_url=watch["kaspi_url"], title=watch["title"], observed_at=latest["observed_at"], confidence_score=score, confidence_label=label, kaspi_observations=len(snapshots), price_change_percent=price_change, review_change=reviews_delta, seller_change=sellers_delta, youtube=youtube.model_dump(mode="json"), evidence=evidence, caveats=caveats)
