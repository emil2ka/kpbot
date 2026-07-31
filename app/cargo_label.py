"""Cargo Box Marking & Shipping Label Generator for China to Kazakhstan shipments."""
from html import escape
from pydantic import BaseModel, Field


class CargoLabelRequest(BaseModel):
    consignee_name: str = Field(description="ФИО или ник получателя в Казахстане")
    city: str = Field(default="Алматы", description="Город назначения")
    cargo_code: str = Field(default="KZ-8899", description="Код клиента в карго-компании")
    product_title_zh: str = Field(description="Наименование товара на китайском")
    carton_number: int = Field(default=1, ge=1, description="Номер коробки")
    total_cartons: int = Field(default=1, ge=1, description="Всего коробок в партии")
    quantity_per_carton: int = Field(default=50, ge=1, description="Количество штук в коробке")
    weight_kg: float = Field(default=15.0, ge=0.1, description="Вес коробки в кг")
    is_fragile: bool = Field(default=False, description="Хрупкий груз")


class CargoLabelResult(BaseModel):
    label_text_cn_ru: str
    html_printable: str


def generate_cargo_label(req: CargoLabelRequest) -> CargoLabelResult:
    """Generate professional B2B Cargo Box Shipping Markings (箱唛) for Chinese suppliers."""
    fragile_tag_zh = "⚠️ 易碎物品 谨慎轻放 (ХРУПКОЕ! Обращаться с осторожностью)" if req.is_fragile else "正常货物 (Стандартный груз)"
    waterproof_tag_zh = "☔ 防水防潮 (Беречь от влаги)"

    label_text = f"""
==================================================
              KAZAKHSTAN CARGO SHIPPING MARK (箱唛)
==================================================
目的地 / Destination: Kazakhstan, {req.city} (Казахстан, г. {req.city})
客户编号 / Client Code: {req.cargo_code}
收货人 / Consignee: {req.consignee_name}

品名 / Product (CN): {req.product_title_zh}
箱号 / Carton No.: {req.carton_number} / {req.total_cartons}
数量 / Qty: {req.quantity_per_carton} PCS / 件
毛重 / Gross Weight: {req.weight_kg} KG / 公斤

注意 / Note:
{fragile_tag_zh}
{waterproof_tag_zh}
==================================================
    """.strip()

    html = f"""
    <!DOCTYPE html>
    <html lang="zh">
    <head>
        <meta charset="UTF-8">
        <title>箱唛 Cargo Shipping Label - {escape(req.cargo_code)}</title>
        <style>
            body {{ font-family: Arial, sans-serif; display: flex; justify-content: center; padding: 20px; background: #f0f2f5; }}
            .label-card {{ width: 450px; background: white; border: 4px solid #000; padding: 24px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
            .header {{ text-align: center; border-bottom: 3px solid #000; padding-bottom: 12px; margin-bottom: 16px; }}
            .header h1 {{ margin: 0; font-size: 22px; text-transform: uppercase; letter-spacing: 1px; }}
            .header p {{ margin: 4px 0 0; font-size: 14px; font-weight: bold; color: #d97706; }}
            .field {{ font-size: 16px; margin-bottom: 10px; display: flex; justify-content: space-between; border-bottom: 1px dashed #ccc; padding-bottom: 4px; }}
            .field-label {{ font-weight: bold; color: #374151; }}
            .field-val {{ font-weight: bold; color: #000; text-align: right; }}
            .big-val {{ font-size: 22px; color: #dc2626; font-weight: 900; }}
            .warnings {{ margin-top: 16px; border: 2px solid #dc2626; padding: 10px; background: #fef2f2; text-align: center; font-weight: bold; color: #991b1b; border-radius: 6px; }}
            .print-btn {{ display: block; width: 100%; margin-top: 16px; padding: 12px; background: #2563eb; color: white; border: none; font-size: 16px; font-weight: bold; border-radius: 6px; cursor: pointer; text-align: center; text-decoration: none; }}
            @media print {{ .print-btn {{ display: none; }} body {{ background: white; padding: 0; }} }}
        </style>
    </head>
    <body>
        <div class="label-card">
            <div class="header">
                <h1>KAZAKHSTAN CARGO (箱唛)</h1>
                <p>中国 → 哈萨克斯坦 专线运输</p>
            </div>
            <div class="field"><span class="field-label">目的地 / City:</span><span class="field-val big-val">{escape(req.city)}</span></div>
            <div class="field"><span class="field-label">客户编号 / Cargo ID:</span><span class="field-val big-val">{escape(req.cargo_code)}</span></div>
            <div class="field"><span class="field-label">收货人 / Consignee:</span><span class="field-val">{escape(req.consignee_name)}</span></div>
            <div class="field"><span class="field-label">品名 / Product:</span><span class="field-val">{escape(req.product_title_zh)}</span></div>
            <div class="field"><span class="field-label">箱号 / Carton:</span><span class="field-val">{req.carton_number} / {req.total_cartons}</span></div>
            <div class="field"><span class="field-label">数量 / Qty:</span><span class="field-val">{req.quantity_per_carton} PCS</span></div>
            <div class="field"><span class="field-label">毛重 / Weight:</span><span class="field-val">{req.weight_kg} KG</span></div>
            <div class="warnings">
                {escape(fragile_tag_zh)}<br>
                {escape(waterproof_tag_zh)}
            </div>
            <button class="print-btn" onclick="window.print()">🖨 Распечатать Маркировку (Print Box Label)</button>
        </div>
    </body>
    </html>
    """

    return CargoLabelResult(label_text_cn_ru=label_text, html_printable=html.strip())
