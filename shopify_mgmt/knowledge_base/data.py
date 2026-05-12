"""
知识库结构化数据（与 sop_data / 手册一致，可在此维护）。
"""

from __future__ import annotations

from typing import TypedDict


class CodeSnippet(TypedDict):
    id: str
    category: str
    title: str
    description: str
    language: str
    code: str


CSS_SNIPPETS: list[CodeSnippet] = [
    {
        "id": "collection-card",
        "category": "列表页 Collection",
        "title": "标题 / 价格 / 起订量（工业风）",
        "description": "标题去粗、限高 2 行；价格加粗放大；价格下方 Min. Order；可配合隐藏加购按钮使用。",
        "language": "css",
        "code": """/* 列表页：标题、价格、起订量 */
.card__heading {
  font-weight: 400;
  height: 4.5rem;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-align: left;
}
.price-item--regular {
  font-weight: 700;
  font-size: 1.8rem;
  color: #000;
}
.min-order-text {
  font-size: 1.25rem;
  color: #888;
  margin-top: 4px;
  text-align: left;
}""",
    },
    {
        "id": "mobile-menu",
        "category": "手机端",
        "title": "Header：汉堡图标改为 MENU 字样",
        "description": "与 Logo 水平对齐；窄屏可读性更好。",
        "language": "css",
        "code": """/* 手机端 MENU 文字 */
.header__icon--menu::before {
  content: "MENU";
  font-size: 1.2rem;
  font-weight: 700;
  height: 4.4rem;
  display: flex;
  align-items: center;
}""",
    },
    {
        "id": "hide-sample",
        "category": "列表 / 全站",
        "title": "隐藏样品 SKU（列表）",
        "description": "按 handle 隐藏样品，详情页仍可通过「Request Sample」进入。",
        "language": "css",
        "code": """.grid__item:has([data-product-handle="fabric-sample-swatch"]) {
  display: none !important;
}""",
    },
    {
        "id": "cart-compact",
        "category": "购物车 / 筛选",
        "title": "购物车与筛选器（示例）",
        "description": "压缩行高、强化缩略图；可按主题再微调。",
        "language": "css",
        "code": """/* 示例：可按实际 class 调整 */
.cart__line-item { line-height: 1.35; }
.cart__image { border: 1px solid #e5e5e5; }""",
    },
]


class LiquidSnippet(TypedDict):
    id: str
    category: str
    title: str
    description: str
    code: str


LIQUID_SNIPPETS: list[LiquidSnippet] = [
    {
        "id": "moq-card",
        "category": "snippets / card-product",
        "title": "动态起订量（MOQ）注入",
        "description": "在 `render 'price'` 下方插入；依赖 Metafield `custom.moq`。",
        "code": """{% comment %} snippets/card-product.liquid — 在 render 'price' 下方 {% endcomment %}
<p class="min-order-text">
  Min. Order: {{ card_product.metafields.custom.moq.value | default: '30 kilograms' }}
</p>""",
    },
    {
        "id": "catalog-label",
        "category": "主题文案",
        "title": "目录名 CATALOG",
        "description": "Online Store → Themes → Edit default theme content → 搜索 Product type → 改为 CATALOG。",
        "code": """{# 此为后台「编辑模板内容」操作，无单一 Liquid 文件。
   在主题语言/模板字符串中将 Product type 文案替换为 CATALOG 即可。#}""",
    },
]


class SOPStep(TypedDict):
    title: str
    detail: str


SOP_MATRIXIFY_IMPORT: list[SOPStep] = [
    {
        "title": "准备字段与 Matrixify 表头",
        "detail": """- **Type**：与左侧 **CATALOG** 导航分类一致。
- **Metafield: custom.moq [string]**：列表页起订量文案。
- **Metafield: custom.gsm / width / composition** 等：详情页 Specs。
- **Metafield: custom.hts [string]**：海关参考。
- **Metafield: custom.technical_spec**：洗涤/认证等 metaobject 引用。""",
    },
    {
        "title": "在本地或 Excel 维护行数据",
        "detail": """使用本系统 **产品导入 → Matrixify** 生成宽表；或按 Matrixify 模板填写 **Handle、Title、Tags、Variant** 与各 Metafield 列。""",
    },
    {
        "title": "Matrixify 导入 Shopify",
        "detail": """在 Matrixify 中选择 **Products** 工作表 → 校验列名与 Metafield 命名空间 → 使用 **MERGE** 或 **REPLACE** 试跑小批量 → 确认后再全量导入。""",
    },
    {
        "title": "上架校验",
        "detail": """检查列表页价格/起订量、详情页 Metafield、变体价格与库存是否与表内一致。""",
    },
]


SOP_COLOR_VARIANTS: list[SOPStep] = [
    {
        "title": "同一 Handle 多行变体",
        "detail": """一个 **Handle** 对应多行；**Option1 Name** 固定为 **Color**（或与主题一致）；每行 **Option1 Value** 为具体颜色名。""",
    },
    {
        "title": "步骤一：首行聚合图（入库）",
        "detail": """在 **第一行** 的 **Image Src**（或 Matrixify 对应图片列）填入 **所有颜色主图 URL**，多个地址用 **分号 `;`** 分隔，便于后台一次性入库。""",
    },
    {
        "title": "步骤二：每行指派变体图",
        "detail": """在 **每一颜色行** 的 **Variant Image**（或变体级图片列）填入 **该颜色对应的一张 URL**，与 Option1 Value 一一对应。""",
    },
    {
        "title": "导入与前台验证",
        "detail": """导入后在前台切换颜色，确认图片与 SKU、价格联动正确。""",
    },
]
