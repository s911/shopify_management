"""
产品导入：合并默认值、HTS/MOQ 校验、按 Tags 选择 HTML 模板；导出 Matrixify 风格列。
"""

from __future__ import annotations

import io
import json
from typing import Any, BinaryIO

import pandas as pd

from shopify_mgmt.db import get_connection, init_db, list_products, upsert_product
from shopify_mgmt.product.defaults import EXPORT_COLUMN_ORDER, build_default_row
from shopify_mgmt.product.html_templates import get_body_html
from shopify_mgmt.product.hts_moq import normalize_hts, validate_hts, validate_moq

# 与简表模板 / 在线表格一致（全部必填）
MANUAL_TEMPLATE_COLUMNS: list[str] = [
    "Handle",
    "Title",
    "Tags",
    "Variant Price",
    "Metafield: custom.gsm [string]",
    "Metafield: custom.width [string]",
    "Metafield: custom.composition [string]",
]


def _manual_cell_filled(col: str, val: Any) -> bool:
    if col == "Variant Price":
        return not (val is None or val == "" or pd.isna(val))
    if val is None:
        return False
    if isinstance(val, float) and pd.isna(val):
        return False
    return bool(str(val).strip())


def validate_manual_template_required(df: pd.DataFrame) -> list[str]:
    """在线表格或等价结构：每一行、每个模板列都必须有值。"""
    df = _strip_columns(df.copy())
    errs: list[str] = []
    for col in MANUAL_TEMPLATE_COLUMNS:
        if col not in df.columns:
            errs.append(f"缺少列：{col}")
    if errs:
        return errs
    df = df[MANUAL_TEMPLATE_COLUMNS].copy()
    df["Variant Price"] = pd.to_numeric(df["Variant Price"], errors="coerce")
    for n, (_, row) in enumerate(df.iterrows(), start=1):
        for col in MANUAL_TEMPLATE_COLUMNS:
            if not _manual_cell_filled(col, row[col]):
                errs.append(f"第 {n} 行「{col}」为必填，请填写完整。")
    return errs


def empty_manual_input_rows(n: int) -> pd.DataFrame:
    """在线编辑用空白网格。"""
    d: dict[str, list[Any]] = {}
    for c in MANUAL_TEMPLATE_COLUMNS:
        if c == "Variant Price":
            d[c] = [pd.NA] * n
        else:
            d[c] = [""] * n
    return coerce_manual_df_for_streamlit_editor(pd.DataFrame(d))


def resize_manual_input_dataframe(existing: pd.DataFrame, n: int) -> pd.DataFrame:
    """按目标行数截断或补齐，列顺序与模板一致。"""
    if n < 1:
        n = 1
    df = _strip_columns(existing.copy())
    for c in MANUAL_TEMPLATE_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA if c == "Variant Price" else ""
    df = df[MANUAL_TEMPLATE_COLUMNS]
    if len(df) >= n:
        out = df.iloc[:n].reset_index(drop=True)
    else:
        pad = empty_manual_input_rows(n - len(df))
        out = pd.concat([df.reset_index(drop=True), pad], ignore_index=True)
    return coerce_manual_df_for_streamlit_editor(out)


def coerce_manual_df_for_streamlit_editor(df: pd.DataFrame) -> pd.DataFrame:
    """
    统一列类型，减轻 st.data_editor 在 Tab 切换单元格时丢字的问题。
    文本列用 pandas StringDtype；价格用 float64（空为 NaN）。
    """
    out = df.reindex(columns=list(MANUAL_TEMPLATE_COLUMNS)).copy()
    for c in MANUAL_TEMPLATE_COLUMNS:
        if c == "Variant Price":
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
        else:
            s = out[c].map(
                lambda x: ""
                if x is None or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and x.lower() == "nan")
                else str(x)
            )
            out[c] = s.astype("string")
    return out


def _strip_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def merge_row_from_dataframe(
    row: pd.Series,
    *,
    row_number: int,
    force_body_from_tags: bool,
) -> dict[str, Any]:
    """将一行 Excel/CSV 与默认值合并，并应用 SKU / 型号 / HTML / HTS 规则。"""
    out: dict[str, Any] = dict(build_default_row())
    for col in row.index:
        val = row[col]
        if _is_blank(val):
            continue
        out[col] = val

    tags = out.get("Tags")
    if force_body_from_tags:
        out["Body (HTML)"] = get_body_html(tags)
    elif "Tags" in row.index and not _is_blank(row.get("Tags")):
        out["Body (HTML)"] = get_body_html(row.get("Tags"))

    handle = out.get("Handle")
    if handle and not _is_blank(handle):
        h = str(handle).strip()
        sku_suffix = f"{row_number:03d}"
        if str(out.get("Variant SKU", "")).strip() in ("", "SKU-001"):
            out["Variant SKU"] = f"{h}-{sku_suffix}"
        if str(out.get("Metafield: custom.model_number [string]", "")).strip() == "MZ-0000":
            out["Metafield: custom.model_number [string]"] = f"MZ-{1000 + row_number}"

    hts_key = "Metafield: custom.hts [string]"
    if hts_key in out and not _is_blank(out.get(hts_key)):
        out[hts_key] = normalize_hts(out[hts_key])

    return out


def validate_product_row(row: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    handle = row.get("Handle")
    if _is_blank(handle):
        errs.append("缺少 Handle")
    ok, msg = validate_hts(row.get("Metafield: custom.hts [string]"))
    if not ok:
        errs.append(msg)
    ok_m, msg_m = validate_moq(row.get("Metafield: custom.moq [string]"))
    if not ok_m:
        errs.append(msg_m)
    return errs


def generate_matrixify_dataframe(
    df: pd.DataFrame,
    *,
    force_body_from_tags: bool = True,
    skip_rows_without_handle: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    """
    将「简表」或部分列的 Excel 转为可直接交给 Matrixify 导入的宽表。
    Body (HTML) 按 Tags 匹配：Fleece / Stretch·Yoga / 默认 Knit 三套模板之一。
    """
    rows, errs = dataframe_to_rows(df, force_body_from_tags=force_body_from_tags)
    if not skip_rows_without_handle:
        out_df = align_export_columns(pd.DataFrame(rows))
        return out_df, errs

    kept: list[dict[str, Any]] = []
    skipped = 0
    for r in rows:
        if _is_blank(r.get("Handle")):
            skipped += 1
            continue
        kept.append(r)
    if skipped:
        errs = list(errs)
        errs.append(f"已跳过无 Handle 的行：共 {skipped} 行。")
    if not kept:
        return pd.DataFrame(columns=EXPORT_COLUMN_ORDER), errs
    return align_export_columns(pd.DataFrame(kept)), errs


def dataframe_to_rows(
    df: pd.DataFrame,
    *,
    force_body_from_tags: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    df = _strip_columns(df)
    rows: list[dict[str, Any]] = []
    all_errors: list[str] = []
    for n, (_, r) in enumerate(df.iterrows(), start=1):
        merged = merge_row_from_dataframe(r, row_number=n, force_body_from_tags=force_body_from_tags)
        ve = validate_product_row(merged)
        if ve:
            all_errors.extend([f"第{n}行 ({merged.get('Handle','?')}): {e}" for e in ve])
        rows.append(merged)
    return rows, all_errors


def import_dataframe(
    df: pd.DataFrame,
    *,
    force_body_from_tags: bool,
    stop_on_error: bool,
) -> tuple[int, list[str]]:
    init_db()
    rows, errs = dataframe_to_rows(df, force_body_from_tags=force_body_from_tags)
    if stop_on_error and errs:
        return 0, errs
    conn = get_connection()
    try:
        n = 0
        for row in rows:
            handle = str(row.get("Handle", "")).strip()
            if not handle:
                continue
            upsert_product(
                conn,
                handle=handle,
                title=None if _is_blank(row.get("Title")) else str(row.get("Title")),
                tags=None if _is_blank(row.get("Tags")) else str(row.get("Tags")),
                metafield_hts=None if _is_blank(row.get("Metafield: custom.hts [string]")) else str(row.get("Metafield: custom.hts [string]")),
                metafield_moq=None if _is_blank(row.get("Metafield: custom.moq [string]")) else str(row.get("Metafield: custom.moq [string]")),
                body_html=None if _is_blank(row.get("Body (HTML)")) else str(row.get("Body (HTML)")),
                row=row,
            )
            n += 1
        conn.commit()
        return n, errs
    finally:
        conn.close()


def read_table_file(name: str, data: BinaryIO) -> pd.DataFrame:
    lower = name.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(data)
    if lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        return pd.read_excel(data)
    raise ValueError("仅支持 .csv / .xlsx / .xlsm")


def export_products_dataframe() -> pd.DataFrame:
    init_db()
    conn = get_connection()
    try:
        items = list_products(conn)
        if not items:
            return pd.DataFrame(columns=EXPORT_COLUMN_ORDER)
        dicts: list[dict[str, Any]] = []
        for it in items:
            d = json.loads(it["row_json"])
            dicts.append(d)
        return align_export_columns(pd.DataFrame(dicts))
    finally:
        conn.close()


def align_export_columns(df: pd.DataFrame) -> pd.DataFrame:
    for c in EXPORT_COLUMN_ORDER:
        if c not in df.columns:
            df[c] = None
    extra = [c for c in df.columns if c not in EXPORT_COLUMN_ORDER]
    return df[EXPORT_COLUMN_ORDER + extra]


def build_manual_template_dataframe() -> pd.DataFrame:
    """与历史脚本一致的「手工填写」最小列（表头与在线表格一致）。"""
    return pd.DataFrame(columns=list(MANUAL_TEMPLATE_COLUMNS))


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    return buf.getvalue()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")
