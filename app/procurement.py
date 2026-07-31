"""Procurement Order Sheet generator for forwarding agents and Cargo companies in China (Yiwu, Guangzhou, Urumqi)."""
import csv
import io
from html import escape

from app.currency import get_cny_to_kzt_rate
from app.models import ProcurementItem, ProcurementSheetRequest, ProcurementSheetResult


async def generate_procurement_sheet(
    items: list[ProcurementItem],
    custom_cny_rate: float | None = None,
) -> ProcurementSheetResult:
    rate = custom_cny_rate if custom_cny_rate and custom_cny_rate > 0 else await get_cny_to_kzt_rate()

    total_qty = 0
    total_cny = 0.0
    processed_items: list[ProcurementItem] = []

    for item in items:
        tot_item_cny = round(item.quantity * item.target_price_cny, 2)
        total_qty += item.quantity
        total_cny += tot_item_cny
        processed_items.append(
            ProcurementItem(
                product_title_ru=item.product_title_ru,
                product_title_zh=item.product_title_zh,
                supplier_url=item.supplier_url,
                platform=item.platform,
                sku_name=item.sku_name,
                quantity=item.quantity,
                target_price_cny=item.target_price_cny,
                total_cny=tot_item_cny,
                notes=item.notes,
            )
        )

    total_kzt = round(total_cny * rate, 2)

    # Build UTF-8 CSV with BOM for Excel compatibility
    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM
    writer = csv.writer(output)
    writer.writerow([
        "№", "Платформа", "Товар (RU)", "Название (CN)", "Модификация / SKU",
        "Количество (шт)", "Целевая цена (CNY)", "Сумма (CNY)", "Сумма (KZT)", "Ссылка на поставщика", "Заметки"
    ])

    for idx, it in enumerate(processed_items, start=1):
        writer.writerow([
            idx,
            it.platform,
            it.product_title_ru,
            it.product_title_zh,
            it.sku_name,
            it.quantity,
            it.target_price_cny,
            it.total_cny,
            round(it.total_cny * rate, 2),
            it.supplier_url,
            it.notes or "",
        ])

    csv_content = output.getvalue()

    # Build HTML Preview
    rows_html = ""
    for idx, it in enumerate(processed_items, start=1):
        rows_html += f"""
        <tr>
            <td>{idx}</td>
            <td><b>{escape(it.platform)}</b></td>
            <td>{escape(it.product_title_ru)}</td>
            <td><code>{escape(it.product_title_zh)}</code></td>
            <td>{escape(it.sku_name)}</td>
            <td><b>{it.quantity:,}</b></td>
            <td>{it.target_price_cny} ¥</td>
            <td><b>{it.total_cny:,.2f} ¥</b></td>
            <td><a href="{escape(it.supplier_url)}" target="_blank">Ссылка</a></td>
        </tr>
        """

    html_preview = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Бланк закупки в Китае / Sourcing Order Sheet</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background: #f8fafc; color: #1e293b; }}
            .card {{ background: white; padding: 24px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
            h2 {{ margin-top: 0; color: #0f172a; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
            th {{ background-color: #f1f5f9; font-weight: 600; }}
            .summary {{ display: flex; gap: 24px; margin-top: 20px; background: #e0f2fe; padding: 16px; border-radius: 8px; }}
            .stat {{ display: flex; flex-direction: column; }}
            .stat-label {{ font-size: 12px; color: #0369a1; text-transform: uppercase; font-weight: bold; }}
            .stat-val {{ font-size: 20px; font-weight: bold; color: #0c4a6e; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>📦 Бланк закупки товара в Китае (для Карго)</h2>
            <div class="summary">
                <div class="stat"><span class="stat-label">Позиций</span><span class="stat-val">{len(processed_items)}</span></div>
                <div class="stat"><span class="stat-label">Всего штук</span><span class="stat-val">{total_qty:,}</span></div>
                <div class="stat"><span class="stat-label">Итого CNY</span><span class="stat-val">{total_cny:,.2f} ¥</span></div>
                <div class="stat"><span class="stat-label">Итого KZT</span><span class="stat-val">{total_kzt:,.2f} ₸</span></div>
                <div class="stat"><span class="stat-label">Курс CNY/KZT</span><span class="stat-val">{rate:.2f}</span></div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>№</th>
                        <th>Платформа</th>
                        <th>Товар (RU)</th>
                        <th>Иероглифы (CN)</th>
                        <th>SKU / Модификация</th>
                        <th>Кол-во</th>
                        <th>Цена CNY</th>
                        <th>Сумма CNY</th>
                        <th>Ссылка</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """

    return ProcurementSheetResult(
        total_items_count=len(processed_items),
        total_quantity=total_qty,
        total_amount_cny=total_cny,
        total_amount_kzt=total_kzt,
        exchange_rate=rate,
        items=processed_items,
        csv_content=csv_content,
        html_preview=html_preview.strip(),
    )
