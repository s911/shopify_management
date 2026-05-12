"""
人民币金额中文直观展示（万 / 亿），便于决策者快速感知量级。
"""

from __future__ import annotations

import math


def _trim_trailing_zeros(s: str) -> str:
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def format_rmb_cn(n: float | int | None) -> str:
    """
    将金额转为「一眼能懂」的万/亿口径字符串。

    示例：45_200_000 →「4520万」；128_000_000 →「1.28亿」；
    8_500 →「8500元」；不足 1 万时保留元或千元级表述。
    """
    if n is None:
        return "—"
    try:
        x = float(n)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(x) or math.isinf(x):
        return "—"

    sign = "-" if x < 0 else ""
    v = abs(x)

    yi = 100_000_000.0
    wan = 10_000.0

    if v >= yi:
        s = _trim_trailing_zeros(f"{v / yi:.2f}")
        return f"{sign}{s}亿"
    if v >= wan:
        s = _trim_trailing_zeros(f"{v / wan:.2f}")
        return f"{sign}{s}万"
    if v >= 1000:
        s = _trim_trailing_zeros(f"{v / 1000:.1f}")
        return f"{sign}{s}千"
    if v >= 1:
        return f"{sign}{int(round(v))}元"
    return f"{sign}0元"


def insert_readable_rmb_column(df, money_col: str = "人民币", out_col: str | None = None) -> object:
    """在 money_col 右侧插入一列直观读法（返回新 DataFrame）。"""
    import pandas as pd

    out = df.copy()
    name = out_col or f"{money_col}(直观)"
    if money_col not in out.columns:
        return out
    idx = list(out.columns).index(money_col) + 1
    out.insert(idx, name, out[money_col].map(format_rmb_cn))
    return out
