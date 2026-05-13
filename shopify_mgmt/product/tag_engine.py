"""
智能标签推导引擎：所有 Tags（在线单条与 Excel 批量）均经此模块生成/合并后再进入 Matrixify 流程。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd

# --- Product Type（目录核心）---
PRODUCT_TYPE_OPTIONS: tuple[str, ...] = (
    "Dralon",
    "Polar Fleece",
    "Bonded Fabric",
    "Technical Knit",
)

# --- 功能标签（界面复选框 / Excel 可选列）---
FEATURE_TAG_NAMES: tuple[str, ...] = (
    "Anti-Pilling",
    "Anti-Static",
    "Water-Repellent",
    "Fast-Drying",
)

DEFAULT_COMMERCIAL_TAGS: tuple[str, ...] = ("Ready-to-Ship", "Sample-Available")

# 规范化：常见别称 → 规范写法（避免 .title() 破坏连字符大小写）
_TAG_CANONICAL: dict[str, str] = {
    "ready-to-ship": "Ready-to-Ship",
    "sample-available": "Sample-Available",
    "anti-pilling": "Anti-Pilling",
    "anti-static": "Anti-Static",
    "water-repellent": "Water-Repellent",
    "fast-drying": "Fast-Drying",
    "heavyweight": "Heavyweight",
    "lightweight": "Lightweight",
    "midweight": "Midweight",
    "stretch": "Stretch",
    "sustainable": "Sustainable",
    "dralon": "Dralon",
    "polar fleece": "Polar Fleece",
    "bonded fabric": "Bonded Fabric",
    "technical knit": "Technical Knit",
}


def _strip_col(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def _parse_gsm(val: Any) -> float | None:
    if _is_blank(val):
        return None
    if isinstance(val, (int, float)) and not pd.isna(val):
        return float(val)
    s = str(val).strip()
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    return float(m.group(1))


def _gsm_weight_tag(gsm: float | None) -> str | None:
    if gsm is None:
        return None
    if gsm > 280:
        return "Heavyweight"
    if gsm < 150:
        return "Lightweight"
    return "Midweight"


def _composition_derived_tags(composition: str) -> list[str]:
    comp = (composition or "").lower()
    out: list[str] = []
    if any(k in comp for k in ("spandex", "lycra", "elastane")):
        out.append("Stretch")
    if "recycled" in comp or "grs" in comp:
        out.append("Sustainable")
    return out


def _split_tag_string(s: str | None) -> list[str]:
    if not s or not str(s).strip():
        return []
    parts = re.split(r"\s*,\s*", str(s).strip())
    return [p for p in parts if p.strip()]


def _normalize_one_tag(raw: str) -> str:
    t = raw.strip()
    if not t:
        return ""
    key = t.lower()
    if key in _TAG_CANONICAL:
        return _TAG_CANONICAL[key]
    if "-" in t:
        return "-".join(w.capitalize() for w in t.split("-") if w)
    return " ".join(w.capitalize() for w in t.split() if w)


def finalize_tag_list(raw_tags: Iterable[str]) -> str:
    """去重（忽略大小写）、规范化、英文逗号+空格连接。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in raw_tags:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        c = _normalize_one_tag(s)
        if not c:
            continue
        lk = c.lower()
        if lk in seen:
            continue
        seen.add(lk)
        ordered.append(c)
    return ", ".join(ordered)


def run_tag_engine(
    *,
    product_type: str,
    gsm: Any,
    composition: str,
    feature_flags: dict[str, bool] | None = None,
    existing_tags: str | None = None,
) -> str:
    """
    根据 Type / GSM / Composition / 功能勾选 / 默认商业标签生成 Tags；
    若提供 existing_tags（如 Excel 原有 Tags），与生成结果合并后再规范化。
    """
    flags = feature_flags or {}
    segments: list[str] = []

    pt = (product_type or "").strip()
    if pt:
        segments.append(pt)

    gsm_val = _parse_gsm(gsm)
    wt = _gsm_weight_tag(gsm_val)
    if wt:
        segments.append(wt)

    segments.extend(_composition_derived_tags(composition or ""))

    for name in FEATURE_TAG_NAMES:
        if flags.get(name):
            segments.append(name)

    segments.extend(DEFAULT_COMMERCIAL_TAGS)

    if existing_tags and str(existing_tags).strip():
        segments.extend(_split_tag_string(str(existing_tags)))

    return finalize_tag_list(segments)


def _truthy_cell(v: Any) -> bool:
    if _is_blank(v):
        return False
    if isinstance(v, (int, float)) and not pd.isna(v):
        return float(v) != 0.0
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "是", "✓", "x")


def _first_nonblank(row: pd.Series, names: tuple[str, ...]) -> Any:
    for n in names:
        if n in row.index and not _is_blank(row.get(n)):
            return row.get(n)
    return None


def _row_feature_flags(row: pd.Series) -> dict[str, bool]:
    return {name: _truthy_cell(row.get(name)) for name in FEATURE_TAG_NAMES}


def _pick_product_type(row: pd.Series) -> str:
    v = _first_nonblank(
        row,
        ("Type", "Product Type", "type", "PRODUCT TYPE", "Catalog Type"),
    )
    return "" if v is None else str(v).strip()


def _pick_gsm(row: pd.Series) -> Any:
    return _first_nonblank(
        row,
        ("GSM", "gsm", "Metafield: custom.gsm [string]"),
    )


def _pick_composition(row: pd.Series) -> str:
    v = _first_nonblank(
        row,
        ("Composition", "composition", "Metafield: custom.composition [string]"),
    )
    return "" if v is None else str(v)


def _pick_existing_tags(row: pd.Series) -> str | None:
    v = _first_nonblank(row, ("Tags", "tags", "TAGS"))
    if v is None:
        return None
    return str(v)


def ensure_matrixify_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将简写列复制到 Matrixify 合并逻辑使用的标准列名（若标准列已空）。"""
    out = df.copy()

    def _meta_empty(series: pd.Series) -> pd.Series:
        s = series.astype(str).str.strip()
        return series.isna() | (s == "") | (s.lower() == "nan")

    if "Metafield: custom.gsm [string]" not in out.columns and "GSM" in out.columns:
        out["Metafield: custom.gsm [string]"] = out["GSM"]
    elif "Metafield: custom.gsm [string]" in out.columns and "GSM" in out.columns:
        m = out["Metafield: custom.gsm [string]"]
        g = out["GSM"]
        empty = _meta_empty(m)
        out.loc[empty, "Metafield: custom.gsm [string]"] = g.loc[empty]

    if "Metafield: custom.composition [string]" not in out.columns and "Composition" in out.columns:
        out["Metafield: custom.composition [string]"] = out["Composition"]
    elif "Metafield: custom.composition [string]" in out.columns and "Composition" in out.columns:
        m = out["Metafield: custom.composition [string]"]
        c = out["Composition"]
        empty = _meta_empty(m)
        out.loc[empty, "Metafield: custom.composition [string]"] = c.loc[empty]

    if "Type" not in out.columns:
        for alt in ("Product Type", "PRODUCT TYPE"):
            if alt in out.columns:
                out["Type"] = out[alt]
                break

    return out


def apply_tag_engine_to_bulk_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    遍历每一行：根据 Type、GSM、Composition 与可选功能列运行标签引擎；
    若该行原有 Tags，与生成结果合并。写回 Tags，并保证 Type / 成分 metafield 列存在。
    """
    df = _strip_col(df)
    df = ensure_matrixify_alias_columns(df)
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        r = row.to_dict()
        pt = _pick_product_type(row) or str(r.get("Type", "") or "").strip()
        gsm = _pick_gsm(row)
        comp = _pick_composition(row)
        existing = _pick_existing_tags(row)
        flags = _row_feature_flags(row)
        tags = run_tag_engine(
            product_type=pt,
            gsm=gsm,
            composition=comp,
            feature_flags=flags,
            existing_tags=existing,
        )
        r["Tags"] = tags
        if pt:
            r["Type"] = pt
        rows.append(r)
    return pd.DataFrame(rows)


def build_bulk_import_template_dataframe() -> pd.DataFrame:
    """批量导入表头模板（去除多余列，Product Type 为必填列）。"""
    cols = [
        "Handle",
        "Title",
        "Product Type",
        "GSM",
        "Composition",
        "Tags",
        "Variant Price",
        "Metafield: custom.width [string]",
    ]
    return pd.DataFrame(columns=cols)
