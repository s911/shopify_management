"""
海关出口数据汇总分析（自 mianliao/custom_data_analysis.py 迁移）。
按贸易伙伴汇总人民币金额、ABC 市场分级；按贸易方式汇总。
"""

from __future__ import annotations

import io
from typing import BinaryIO

import pandas as pd


def read_customs_csv(source: BinaryIO | str, *, encoding: str | None = None) -> pd.DataFrame:
    """读取海关导出 CSV，优先 gb18030，失败则尝试 utf-8-sig / utf-8。"""
    order: list[str] = []
    if encoding:
        order.append(encoding)
    for e in ("gb18030", "utf-8-sig", "utf-8"):
        if e not in order:
            order.append(e)

    last_err: Exception | None = None
    for enc in order:
        try:
            if isinstance(source, str):
                return pd.read_csv(source, encoding=enc, quotechar='"')
            source.seek(0)
            return pd.read_csv(source, encoding=enc, quotechar='"')
        except (UnicodeDecodeError, UnicodeError) as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    raise RuntimeError("无法解码 CSV")


def _clean_rmb_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["人民币"] = (
        out["人民币"].astype(str).str.replace('"', "", regex=False).str.replace(",", "", regex=False).astype(float)
    )
    return out


def _country_report(df: pd.DataFrame) -> pd.DataFrame:
    country_report = df.groupby("贸易伙伴名称")["人民币"].sum().reset_index()
    country_report = country_report.sort_values(by="人民币", ascending=False)
    total_val = country_report["人民币"].sum()
    if total_val <= 0:
        country_report["占比(%)"] = 0.0
        country_report["累计占比(%)"] = 0.0
    else:
        country_report["占比(%)"] = country_report["人民币"] / total_val * 100
        country_report["累计占比(%)"] = country_report["占比(%)"].cumsum()

    def classify(row: pd.Series) -> str:
        if row["累计占比(%)"] <= 70:
            return "A类-核心市场"
        if row["累计占比(%)"] <= 90:
            return "B类-重点市场"
        return "C类-长尾市场"

    country_report["市场分级"] = country_report.apply(classify, axis=1)
    return country_report


def _trade_report(df: pd.DataFrame) -> pd.DataFrame:
    trade_report = df.groupby("贸易方式名称")["人民币"].agg(["sum", "count"]).reset_index()
    trade_report.columns = ["贸易方式", "总金额", "交易笔数"]
    trade_report = trade_report.sort_values("总金额", ascending=False)
    return trade_report


REQUIRED_COLUMNS = ("贸易伙伴名称", "人民币", "贸易方式名称")


def analyze_customs_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    返回 (国家/地区分级表, 贸易方式汇总表, 清洗后的明细)。
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"数据缺少必需列：{missing}。请确认与海关导出字段一致。")
    df_clean = _clean_rmb_column(df)
    country_report = _country_report(df_clean)
    trade_report = _trade_report(df_clean)
    return country_report, trade_report, df_clean


def analyze_customs_csv(source: BinaryIO | str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = read_customs_csv(source)
    return analyze_customs_dataframe(df)


def report_to_excel_bytes(
    country_report: pd.DataFrame,
    trade_report: pd.DataFrame,
    df_clean: pd.DataFrame,
) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        country_report.to_excel(writer, sheet_name="国家全排名", index=False)
        trade_report.to_excel(writer, sheet_name="贸易方式分析", index=False)
        df_clean.to_excel(writer, sheet_name="清洗后的原始明细", index=False)
    return buf.getvalue()


SHEET_COUNTRY = "国家全排名"
SHEET_TRADE = "贸易方式分析"
SHEET_DETAIL = "清洗后的原始明细"


def parse_saved_report_excel(data: bytes) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """从本系统导出的决策报表 xlsx 还原三张表。"""
    bio = io.BytesIO(data)
    country = pd.read_excel(bio, sheet_name=SHEET_COUNTRY, engine="openpyxl")
    trade = pd.read_excel(bio, sheet_name=SHEET_TRADE, engine="openpyxl")
    detail = pd.read_excel(bio, sheet_name=SHEET_DETAIL, engine="openpyxl")
    return country, trade, detail
