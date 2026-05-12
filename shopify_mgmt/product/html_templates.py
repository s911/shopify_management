"""
多模板 HTML 描述生成逻辑（自 mianliao/import_product_by_excel.py 迁移）。
根据 Tags 在 Fleece / Stretch(Yoga) / 默认 Knit 模板间切换。
"""

from __future__ import annotations

import pandas as pd
# ==========================================
# 1. Professional HTML Description Templates
# ==========================================

TEMPLATE_PREFIX = """
<p><strong>For Small Orders (&lt;50kg):</strong><br>
Please select the quantity and checkout directly. We maintain steady stock for fast shipping.</p>
<p><strong>For Bulk Inquiries (&gt;400kg):</strong><br>
Contact our sales team via WhatApp or Eamil Us for exclusive FOB/CIF pricing and customized logistics solutions.</p>
"""

TEMPLATE_SUFFIX = """
<!-- Shopify Fabric Policy Accordion -->
<div style="margin-top: 20px; font-size: 0.9em; line-height: 1.6; color: #333;" class="fabric-policy-section">
<details style="border-bottom: 1px solid #eee; padding: 10px 0; cursor: pointer;" open="">
<summary style="font-weight: bold; list-style: none; display: flex; justify-content: space-between; align-items: center;">1. Shipping &amp; Samples <span>+</span></summary>
<div style="padding: 10px 5px; color: #666;">
<ul>
<li><strong>Dispatch:</strong> In-stock items ship within 48 business hours.</li>
<li><strong>Samples:</strong> Swatches are available via <strong>Freight Collect</strong> (paid by receiver).</li>
</ul>
</div>
</details>
<details style="border-bottom: 1px solid #eee; padding: 10px 0; cursor: pointer;">
<summary style="font-weight: bold; list-style: none; display: flex; justify-content: space-between; align-items: center;">2. Quality &amp; Batch Variations <span>+</span></summary>
<div style="padding: 10px 5px; color: #666;">
<ul>
<li><strong>Consistency:</strong> Minor variations in texture and thickness are inherent between different production batches.</li>
<li><strong>Weight:</strong> Industry-standard weight (GSM) tolerance of <strong>±5%</strong> applies.</li>
<li><strong>Color Fastness:</strong> Rating Level 2-3. Slight fading may occur in dark colors (Black, Deep Red, etc.).</li>
</ul>
</div>
</details>
<details style="border-bottom: 1px solid #eee; padding: 10px 0; cursor: pointer;">
<summary style="font-weight: bold; list-style: none; display: flex; justify-content: space-between; align-items: center;">3. Packaging &amp; Returns <span>+</span></summary>
<div style="padding: 10px 5px; color: #666;">
<ul>
<li><strong>Packaging:</strong> Bulk orders are rolled and double-packed for protection.</li>
<li><strong>Condition:</strong> Light dust on light-colored fabrics is a normal part of the industrial process and does not affect usability.</li>
<li><strong>Policy:</strong> Returns are not accepted for minor batch variations. We recommend ordering a sample first.</li>
</ul>
</div>
</details>
</div>
"""


def build_template_body(title: str, description: str, best_for_items: list[str], key_benefits: str) -> str:
    """Build a consistent HTML layout for all fabric types."""
    best_for_html = "\n".join(f"<li>{item}</li>" for item in best_for_items)
    return (
        TEMPLATE_PREFIX
        + f"""
<h3><strong>{title}</strong></h3>
<p>{description}</p>
<p><strong>Best For:</strong></p>
<ul>
{best_for_html}
</ul>
<p><strong>Key Benefits:</strong></p>
<p>{key_benefits}</p>
"""
        + TEMPLATE_SUFFIX
    )


TEMPLATE_FLEECE = build_template_body(
    "Premium High-Loft Thermal Fleece",
    "Engineered for maximum heat retention without the bulk, this high-performance fleece is a staple for professional winter collections. The double-brushed finish provides a cashmere-like hand feel that remains soft even after multiple industrial washes.",
    [
        "Heavyweight Hoodies &amp; Sweatpants",
        "Outdoor Performance Mid-layers",
        "Thermal Linings for Technical Jackets",
    ],
    "Treated with a specialized anti-pilling process to ensure a long-lasting, clean aesthetic. It offers excellent breathability while maintaining a stable micro-climate for the wearer.",
)

TEMPLATE_STRETCH = build_template_body(
    "Pro-Stretch Performance Interlock",
    "Designed for high-intensity movement, this fabric features a dense, non-see-through construction with superior four-way stretch. It provides optimal compression and muscle support, making it the top choice for activewear brands.",
    [
        "Yoga Leggings &amp; Sports Bras",
        "Compression Training Gear",
        "High-Performance Athletic Apparel",
    ],
    "Features moisture-wicking technology and rapid-dry capabilities. The high Lycra/Spandex content ensures long-term shape retention, preventing bagging at the knees or elbows over time.",
)

TEMPLATE_KNIT = build_template_body(
    "Versatile Technical Jersey Knit",
    "A high-density knit that balances softness with structural integrity. This fabric is treated with an anti-static finish, making it exceptionally comfortable for year-round base layers and casual essentials.",
    [
        "Premium T-shirts &amp; Polos",
        "Technical Base Layers",
        "Soft-Touch Casual Wear",
    ],
    "Sourced for its exceptional skin-friendliness and durability. It takes reactive dyes beautifully, ensuring vibrant color saturation and excellent color fastness for commercial use.",
)


def get_body_html(tags: object) -> str:
    """Assigns description templates based on product tags."""
    if tags is None or pd.isna(tags):
        return TEMPLATE_KNIT
    s = str(tags).strip()
    if not s:
        return TEMPLATE_KNIT
    if "Fleece" in s:
        return TEMPLATE_FLEECE
    if "Stretch" in s or "Yoga" in s:
        return TEMPLATE_STRETCH
    return TEMPLATE_KNIT
