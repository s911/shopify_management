"""
Matrixify 风格默认值（与历史脚本一致），Body (HTML) 在导入时按 Tags 重新生成。
"""

from __future__ import annotations

from shopify_mgmt.product.html_templates import TEMPLATE_KNIT, get_body_html

# 与 import_product_by_excel.py 中字段名保持一致
DEFAULT_VALUES: dict[str, object] = {
    "Command": "New",
    "Option1 Name": "Color",
    "Option1 Value": "Customize",
    "Variant SKU": "SKU-001",
    "Variant Price": 3.00,
    "Variant Inventory Qty": 5000,
    "Type": "Dralon",
    "Metafield: custom.moq [string]": "400 kilograms per color",
    "Body (HTML)": TEMPLATE_KNIT,
    "Status": "Active",
    "Metafield: custom.model_number [string]": "MZ-0000",
    "Metafield: custom.usage [string]": "Sportswear, Outdoor Apparel, Casual Wear",
    "Metafield: custom.hts [string]": "6001.92.00",
    "Metafield: custom.technical_spec [metaobject_reference]": "grs-standard",
    "Metafield: custom.shrinkage [string]": "< 3%",
    "Metafield: custom.warmth [string]": "Level 3",
    "Metafield: custom.hand_feel [string]": "Soft Brushed",
    "Metafield: custom.stretch [string]": "Non-stretch",
}

# 导出列顺序（便于与历史 Excel 对齐）
EXPORT_COLUMN_ORDER: list[str] = [
    "Handle",
    "Title",
    "Tags",
    "Command",
    "Option1 Name",
    "Option1 Value",
    "Variant SKU",
    "Variant Price",
    "Variant Inventory Qty",
    "Type",
    "Metafield: custom.moq [string]",
    "Metafield: custom.gsm [string]",
    "Metafield: custom.width [string]",
    "Metafield: custom.composition [string]",
    "Metafield: custom.hts [string]",
    "Metafield: custom.model_number [string]",
    "Metafield: custom.usage [string]",
    "Metafield: custom.technical_spec [metaobject_reference]",
    "Metafield: custom.shrinkage [string]",
    "Metafield: custom.warmth [string]",
    "Metafield: custom.hand_feel [string]",
    "Metafield: custom.stretch [string]",
    "Body (HTML)",
    "Status",
]


def build_default_row() -> dict[str, object]:
    row = DEFAULT_VALUES.copy()
    row["Body (HTML)"] = get_body_html("")
    return row
