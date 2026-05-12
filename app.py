"""
Shopify 本地管理系统 — Streamlit 入口。
在个人电脑运行：在项目根目录执行 `streamlit run app.py`
"""

from __future__ import annotations

import io

import streamlit as st

from shopify_mgmt.db import init_db
from shopify_mgmt.product.service import (
    build_manual_template_dataframe,
    export_products_dataframe,
    generate_matrixify_dataframe,
    import_dataframe,
    read_table_file,
    to_csv_bytes,
    to_excel_bytes,
)

MENU = (
    "产品导入导出",
    "海关数据分析",
    "样品订单记录",
    "操作手册百科",
    "到期提醒仪表盘",
)


def page_product_io() -> None:
    st.subheader("产品导入导出")
    st.caption(
        "集成 HTS / MOQ 校验与多模板 HTML 描述（按 Tags：Fleece → 抓绒模板；Stretch 或 Yoga → 弹力模板；否则针织模板）。"
    )

    exp = export_products_dataframe()
    c1, c2, c3 = st.columns(3)
    with c1:
        tpl = build_manual_template_dataframe()
        st.download_button(
            "下载空白模板（Excel）",
            data=to_excel_bytes(tpl),
            file_name="Product_Info_Before_Import.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with c2:
        st.download_button(
            "下载空白模板（CSV）",
            data=to_csv_bytes(tpl),
            file_name="Product_Info_Before_Import.csv",
            mime="text/csv",
        )
    with c3:
        st.download_button(
            "导出数据库中的产品（Excel）",
            data=to_excel_bytes(exp),
            file_name="Import_Product_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=exp.empty,
        )

    st.download_button(
        "导出数据库中的产品（CSV）",
        data=to_csv_bytes(exp),
        file_name="Import_Product_export.csv",
        mime="text/csv",
        disabled=exp.empty,
    )

    force_tags = st.checkbox("始终根据 Tags 重新生成 Body (HTML)", value=False)
    stop_on_err = st.checkbox("遇校验错误时中止整批导入（HTS/MOQ/Handle）", value=True)

    up = st.file_uploader("上传 Matrixify 风格或「空白模板」填写的表格", type=["csv", "xlsx", "xlsm"])
    if up and st.button("导入到 SQLite", type="primary"):
        try:
            df = read_table_file(up.name, up)
        except Exception as e:  # noqa: BLE001
            st.error(f"读取文件失败：{e}")
            return
        n, warnings = import_dataframe(df, force_body_from_tags=force_tags, stop_on_error=stop_on_err)
        if warnings:
            for w in warnings:
                st.warning(w)
        if n:
            st.success(f"已写入或更新 {n} 条产品。")
        elif not warnings:
            st.info("没有可导入的行（请检查 Handle 是否填写）。")

    st.divider()
    with st.expander("仅生成 Matrixify 用 Excel（不入库）", expanded=False):
        st.caption("上传简表，按 Tags 套用 Fleece / Stretch / Knit 模板后下载，可直接交给 Matrixify。")
        gen_force = st.checkbox("始终按 Tags 套用描述模板", value=True, key="app_mf_force")
        up_mf = st.file_uploader("上传用于生成的表格", type=["csv", "xlsx", "xlsm"], key="app_mf_up")
        if st.button("生成 Matrixify Excel", key="app_mf_btn"):
            st.session_state.pop("app_mf_bytes", None)
            if not up_mf:
                st.warning("请先上传文件。")
            else:
                try:
                    raw = up_mf.read()
                    df_mf = read_table_file(up_mf.name, io.BytesIO(raw))
                    out_mf, w_mf = generate_matrixify_dataframe(
                        df_mf, force_body_from_tags=gen_force, skip_rows_without_handle=True
                    )
                    for w in w_mf:
                        st.warning(w)
                    if out_mf.empty:
                        st.error("没有可导出的行。")
                    else:
                        st.session_state["app_mf_bytes"] = to_excel_bytes(out_mf)
                        st.success(f"已生成 {len(out_mf)} 行。")
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))
        if st.session_state.get("app_mf_bytes"):
            st.download_button(
                "下载 Import_Product_Matrixify.xlsx",
                data=st.session_state["app_mf_bytes"],
                file_name="Import_Product_Matrixify.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="app_mf_dl",
            )

    st.divider()
    st.markdown("**数据库预览（最近 5000 条）**")
    preview = exp
    if preview.empty:
        st.info("暂无数据。请先导入或从模板开始。")
    else:
        show_cols = [c for c in preview.columns if c in ("Handle", "Title", "Tags", "Metafield: custom.hts [string]", "Metafield: custom.moq [string]")]
        st.dataframe(preview[show_cols], use_container_width=True, hide_index=True)


def page_customs() -> None:
    st.subheader("海关数据分析")
    st.info("占位模块：后续可接入报关单、HTS 汇总与税率分析等。")


def page_samples() -> None:
    st.subheader("样品订单记录")
    st.info("占位模块：后续可记录寄样客户、物流单号与跟进状态。")


def page_wiki() -> None:
    st.subheader("操作手册百科")
    st.info("占位模块：后续可挂载 Markdown 文档或链接到内部知识库。")


def page_reminders() -> None:
    st.subheader("到期提醒仪表盘")
    st.info("占位模块：后续可对接证书到期、合同续签等提醒。")


def main() -> None:
    st.set_page_config(
        page_title="Shopify 管理系统",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_db()

    st.title("Shopify 管理系统")
    choice = st.sidebar.radio("主菜单", MENU, index=0)

    if choice == "产品导入导出":
        page_product_io()
    elif choice == "海关数据分析":
        page_customs()
    elif choice == "样品订单记录":
        page_samples()
    elif choice == "操作手册百科":
        page_wiki()
    else:
        page_reminders()

    st.sidebar.divider()
    st.sidebar.caption("数据目录：`data/shopify_mgmt.sqlite3`")


if __name__ == "__main__":
    main()
