"""
HTS（美国协调关税表常见写法）与 MOQ 校验/规范化。
"""

from __future__ import annotations

import re
from typing import Tuple

# 常见格式：####.##.#### 或 10 位连续数字
_HTS_DOTTED = re.compile(r"^\d{4}\.\d{2}\.\d{4}$")
_HTS_PLAIN10 = re.compile(r"^\d{10}$")


def normalize_hts(value: object) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if _HTS_DOTTED.match(s):
        return s
    digits = re.sub(r"\D", "", s)
    if len(digits) == 10:
        return f"{digits[0:4]}.{digits[4:6]}.{digits[6:10]}"
    return s


def validate_hts(value: object) -> Tuple[bool, str]:
    """
    返回 (是否通过, 说明)。
    空字符串视为「未填写」，通过校验（由业务决定是否必填）。
    """
    s = normalize_hts(value)
    if not s:
        return True, ""
    if _HTS_DOTTED.match(s) and len(s.replace(".", "")) == 10:
        return True, s
    return False, f"HTS 格式异常：{value!r}（期望 ####.##.#### 或 10 位数字）"


def validate_moq(value: object) -> Tuple[bool, str]:
    """MOQ 为展示用字符串；非空时建议至少包含数字。"""
    if value is None:
        return True, ""
    s = str(value).strip()
    if not s:
        return True, ""
    if re.search(r"\d", s):
        return True, s
    return False, "MOQ 建议包含数量数字（例如「400 kilograms per color」）"
