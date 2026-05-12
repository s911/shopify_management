"""
知识库 Streamlit 界面：代码库 / SOP 步骤条 / Prompt 仓库。
"""

from __future__ import annotations

import html
from typing import Sequence

import streamlit as st

from shopify_mgmt.knowledge_base.data import (
    CSS_SNIPPETS,
    LIQUID_SNIPPETS,
    SOP_COLOR_VARIANTS,
    SOP_MATRIXIFY_IMPORT,
    SOPStep,
)
from shopify_mgmt.product.html_templates import TEMPLATE_FLEECE, TEMPLATE_KNIT, TEMPLATE_STRETCH


def _try_copy(text: str, toast_ok: str = "已复制到剪贴板") -> bool:
    try:
        import pyperclip  # type: ignore[import-untyped]

        pyperclip.copy(text)
        st.toast(toast_ok, icon="✅")
        return True
    except Exception:  # noqa: BLE001
        return False


def _render_code_card(title: str, description: str, code: str, language: str, copy_key: str) -> None:
    st.markdown(f"**{title}**")
    st.caption(description)
    st.code(code, language=language)
    if st.button("一键复制", key=f"kb_copy_{copy_key}", type="primary"):
        if not _try_copy(code):
            st.warning("自动复制不可用（常见于远程/无桌面环境）。请全选下方文本后 Ctrl+C。")
            st.text_area("复制区", value=code, height=min(400, 120 + code.count("\n") * 18), key=f"kb_ta_{copy_key}")


def _render_steps_bar(step_titles: list[str]) -> None:
    """横向步骤条（纯 HTML + inline style）。"""
    cells: list[str] = []
    for i, t in enumerate(step_titles, start=1):
        cells.append(
            f'<div style="display:flex;align-items:center;gap:6px;margin-right:12px;">'
            f'<span style="min-width:26px;height:26px;border-radius:50%;background:#1f5fbf;color:#fff;'
            f'display:inline-flex;align-items:center;justify-content:center;font-size:0.85rem;font-weight:700;">{i}</span>'
            f'<span style="font-weight:600;color:#333;white-space:nowrap;">{html.escape(t)}</span>'
            f"</div>"
        )
    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;align-items:center;padding:12px 0 20px 0;'
        'border-bottom:1px solid #e6e6e6;margin-bottom:16px;">'
        + "".join(cells)
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_sop_flow(title: str, steps: Sequence[SOPStep]) -> None:
    st.markdown(f"### {title}")
    titles = [s["title"] for s in steps]
    _render_steps_bar(titles)
    for i, s in enumerate(steps, start=1):
        with st.container(border=True):
            st.markdown(f"#### 步骤 {i}：{s['title']}")
            st.markdown(s["detail"])


def render_code_library() -> None:
    st.subheader("代码库")
    st.caption("按分类浏览 **CSS** 与 **Liquid**；点击 **一键复制** 写入剪贴板（需本机支持 pyperclip）。")

    css_tab, liq_tab = st.tabs(["CSS", "Liquid"])
    with css_tab:
        cur = None
        for sn in CSS_SNIPPETS:
            if sn["category"] != cur:
                cur = sn["category"]
                st.markdown(f"##### {cur}")
            _render_code_card(sn["title"], sn["description"], sn["code"], sn["language"], f"css_{sn['id']}")
            st.divider()

    with liq_tab:
        cur = None
        for sn in LIQUID_SNIPPETS:
            if sn["category"] != cur:
                cur = sn["category"]
                st.markdown(f"##### {cur}")
            _render_code_card(sn["title"], sn["description"], sn["code"], "liquid", f"liq_{sn['id']}")
            st.divider()


def render_sop_flows() -> None:
    st.subheader("SOP 流程")
    st.caption("使用步骤条总览 + 分步说明；与 Matrixify / 变体图片手册一致。")
    _render_sop_flow("如何用 Matrixify 导入产品", SOP_MATRIXIFY_IMPORT)
    st.divider()
    _render_sop_flow("如何设置多颜色与图片关联", SOP_COLOR_VARIANTS)


def render_prompt_warehouse() -> None:
    st.subheader("Prompt 仓库")
    st.caption(
        "类目对应系统内 **英文 HTML 描述模板**（与产品导入逻辑一致：Tags 含 **Fleece** / **Stretch 或 Yoga** / 默认 **Knit**）。"
        "点击下方按钮在弹出层查看并复制。"
    )

    prompts = [
        ("Fleece", "抓绒 / Thermal Fleece 模板", TEMPLATE_FLEECE, "kb_pr_fleece"),
        ("Yoga / Stretch", "瑜伽弹力 / Pro-Stretch 模板（Tags 含 Yoga 或 Stretch）", TEMPLATE_STRETCH, "kb_pr_yoga"),
        ("Knit", "针织默认 / Technical Jersey Knit", TEMPLATE_KNIT, "kb_pr_knit"),
    ]

    c1, c2, c3 = st.columns(3)
    cols = [c1, c2, c3]
    _popover = getattr(st, "popover", None)
    for col, (label, sub, tmpl, kid) in zip(cols, prompts, strict=True):
        with col:
            if _popover is not None:
                ctx = _popover(f"查看：{label}", use_container_width=True)
            else:
                ctx = st.expander(f"查看：{label}", expanded=False)
            with ctx:
                st.markdown(f"**{sub}**")
                st.code(tmpl, language="html")
                if st.button("复制 HTML", key=f"{kid}_copy", type="primary"):
                    if not _try_copy(tmpl.strip()):
                        st.text_area("手动复制", value=tmpl, height=260, key=f"{kid}_ta")


def render_knowledge_base() -> None:
    st.title("知识库")
    st.caption("代码片段 · SOP 步骤 · 英文描述模板（与 `html_templates` / 手册对齐）。")

    t1, t2, t3 = st.tabs(["代码库", "SOP 流程", "Prompt 仓库"])
    with t1:
        render_code_library()
    with t2:
        render_sop_flows()
    with t3:
        render_prompt_warehouse()
