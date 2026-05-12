import io

import streamlit as st
import pandas as pd

from shopify_mgmt.customs_analysis import (
    analyze_customs_dataframe,
    parse_saved_report_excel,
    read_customs_csv,
    report_to_excel_bytes,
)
from shopify_mgmt.db import (
    delete_customs_run,
    delete_manual_entry,
    delete_note,
    get_connection,
    get_customs_run_blob,
    get_manual_entry,
    init_db,
    insert_customs_run,
    insert_manual_entry,
    insert_note,
    list_customs_runs,
    list_manual_entries,
    list_notes,
    update_manual_entry,
    update_note,
)
from shopify_mgmt.knowledge_base import render_knowledge_base
from shopify_mgmt.product.service import (
    MANUAL_TEMPLATE_COLUMNS,
    build_manual_template_dataframe,
    empty_manual_input_rows,
    generate_matrixify_dataframe,
    read_table_file,
    resize_manual_input_dataframe,
    to_excel_bytes,
    validate_manual_template_required,
)
from shopify_mgmt.rmb_cn import format_rmb_cn, insert_readable_rmb_column

# 设置页面风格
st.set_page_config(
    page_title="FabricsWarm Admin",
    layout="wide",
    initial_sidebar_state="expanded",
)


def render_notebook_page() -> None:
    """简单记事：SQLite 持久化，支持新建 / 编辑 / 删除。"""
    init_db()
    if "note_editing_id" not in st.session_state:
        st.session_state.note_editing_id = None
    if "nb_title" not in st.session_state:
        st.session_state.nb_title = ""
    if "nb_body" not in st.session_state:
        st.session_state.nb_body = ""

    st.title("记事本")
    st.caption("记录保存在本机数据库 `data/shopify_mgmt.sqlite3` 的 `notes` 表中。")

    # 左侧偏窄作导航，右侧为主编辑区（宽屏下约 82% 宽度）
    left, right = st.columns([1, 4.6])
    with left:
        st.markdown("##### 列表")
        if st.button("＋ 新建", use_container_width=True, key="nb_new"):
            st.session_state.note_editing_id = None
            st.session_state.nb_title = ""
            st.session_state.nb_body = ""
            st.rerun()

        conn = get_connection()
        try:
            notes = list_notes(conn)
        finally:
            conn.close()

        if not notes:
            st.info("暂无记事，点击「新建」开始。")
        for row in notes:
            rid = int(row["id"])
            raw_t = (row["title"] or "").strip()
            t = raw_t or "(无标题)"
            preview = t if len(t) <= 26 else t[:23] + "…"
            when = (row["updated_at"] or "")[:19].replace("T", " ")
            if st.button(preview, use_container_width=True, key=f"nb_pick_{rid}", help=f"更新于 {when}"):
                st.session_state.note_editing_id = rid
                st.session_state.nb_title = row["title"] or ""
                st.session_state.nb_body = row["body"] or ""
                st.rerun()
            st.caption(when)

    with right:
        with st.container(border=True):
            mode = "编辑记事" if st.session_state.note_editing_id is not None else "新建记事"
            st.subheader(mode)
            body_h = st.slider(
                "正文编辑区高度",
                min_value=280,
                max_value=720,
                value=480,
                step=40,
                key="nb_body_height",
                help="按需拉高正文框，便于长文书写",
            )
            st.text_input("标题", key="nb_title", placeholder="可选，一句话概括")
            st.text_area("正文", key="nb_body", height=int(body_h), placeholder="随手记录…")

            c1, c2, _ = st.columns([1, 1, 3])
            with c1:
                do_save = st.button("保存", type="primary", key="nb_save")
            with c2:
                can_del = st.session_state.note_editing_id is not None
                do_delete = st.button("删除", type="secondary", key="nb_delete", disabled=not can_del)

        if do_save:
            title = (st.session_state.get("nb_title") or "").strip()
            body = st.session_state.get("nb_body") or ""
            if not title and not body.strip():
                st.warning("请至少填写标题或正文后再保存。")
            else:
                display_title = title or "(无标题)"
                conn = get_connection()
                try:
                    if st.session_state.note_editing_id is None:
                        nid = insert_note(conn, title=display_title, body=body)
                        st.session_state.note_editing_id = nid
                    else:
                        update_note(
                            conn,
                            note_id=int(st.session_state.note_editing_id),
                            title=display_title,
                            body=body,
                        )
                    conn.commit()
                finally:
                    conn.close()
                st.success("已保存")
                st.rerun()

        if do_delete and can_del:
            conn = get_connection()
            try:
                delete_note(conn, int(st.session_state.note_editing_id))
                conn.commit()
            finally:
                conn.close()
            st.session_state.note_editing_id = None
            st.session_state.nb_title = ""
            st.session_state.nb_body = ""
            st.success("已删除")
            st.rerun()


def render_customs_analysis_page() -> None:
    """海关出口 CSV：国家 ABC 分级 + 贸易方式汇总；结果写入本地库便于回看。"""
    init_db()

    def _cda_clear_preview() -> None:
        for k in (
            "cda_country",
            "cda_trade",
            "cda_clean",
            "cda_xlsx",
            "cda_clean_rows",
            "cda_source_label",
            "cda_view_run_id",
        ):
            st.session_state.pop(k, None)

    def _cda_set_preview(
        country: pd.DataFrame,
        trade: pd.DataFrame,
        clean: pd.DataFrame,
        xlsx_bytes: bytes,
        *,
        source_label: str,
        view_run_id: int | None,
    ) -> None:
        st.session_state["cda_country"] = country
        st.session_state["cda_trade"] = trade
        st.session_state["cda_clean"] = clean
        st.session_state["cda_clean_rows"] = len(clean)
        st.session_state["cda_xlsx"] = xlsx_bytes
        st.session_state["cda_source_label"] = source_label
        st.session_state["cda_view_run_id"] = view_run_id

    def _cda_render_results() -> None:
        country = st.session_state.get("cda_country")
        trade = st.session_state.get("cda_trade")
        xlsx_bytes = st.session_state.get("cda_xlsx")
        clean = st.session_state.get("cda_clean")
        if country is None or trade is None or xlsx_bytes is None:
            return
        if clean is None:
            try:
                _, _, clean = parse_saved_report_excel(xlsx_bytes)
                st.session_state["cda_clean"] = clean
            except Exception:  # noqa: BLE001
                clean = None

        lbl = st.session_state.get("cda_source_label")
        if lbl:
            st.info(lbl)
        st.divider()

        total_rmb = float(country["人民币"].sum())
        n_partner = len(country)
        n_trade = len(trade)
        n_detail = int(st.session_state.get("cda_clean_rows") or 0) or (len(clean) if clean is not None else 0)

        st.subheader("决策总览")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric(
            "出口人民币合计",
            format_rmb_cn(total_rmb),
            delta=f"约 {total_rmb:,.0f} 元",
            delta_color="off",
        )
        m2.metric("贸易伙伴数", f"{n_partner}")
        m3.metric("贸易方式种类", f"{n_trade}")
        m4.metric("原始明细行数", f"{n_detail}")
        if "市场分级" in country.columns:
            tier_sums = country.groupby("市场分级", dropna=False)["人民币"].sum()
            a_rmb = float(tier_sums.get("A类-核心市场", 0))
            m5.metric(
                "A 类市场金额",
                format_rmb_cn(a_rmb),
                delta=f"约 {a_rmb:,.0f} 元",
                delta_color="off",
            )

        if "市场分级" in country.columns:
            st.markdown("**ABC 市场分级 — 金额结构**（与累计占比法一致；「金额(直观)」为万/亿口径）")
            tier_agg = country.groupby("市场分级", dropna=False).agg(金额=("人民币", "sum"), 伙伴数=("贸易伙伴名称", "count")).reset_index()
            tier_agg = tier_agg.sort_values("金额", ascending=False)
            tier_disp = insert_readable_rmb_column(tier_agg, "金额", "金额(直观)")
            c_left, c_right = st.columns([1.1, 1])
            with c_left:
                st.dataframe(
                    tier_disp,
                    use_container_width=True,
                    hide_index=True,
                    height=min(280, 80 + len(tier_disp) * 35),
                    column_config={
                        "金额": st.column_config.NumberColumn(format="%.2f"),
                    },
                )
            with c_right:
                st.bar_chart(tier_agg.set_index("市场分级")[["金额"]])

        tab_ov, tab_country, tab_trade, tab_detail = st.tabs(
            ["图表与洞察", "国家/地区全表", "贸易方式全表", "原始明细全表"]
        )

        with tab_ov:
            st.markdown("**出口金额排名 — 柱状图**（可调整展示数量，便于聚焦头部市场）")
            max_bar = min(200, max(5, n_partner))
            default_bar = min(50, max_bar)
            n_bar = st.slider(
                "柱状图展示前 N 个贸易伙伴",
                min_value=5,
                max_value=max_bar,
                value=default_bar,
                step=5,
                key="cda_bar_n",
            )
            bar_df = country.head(n_bar).set_index("贸易伙伴名称")[["人民币"]]
            st.bar_chart(bar_df)

            st.markdown("**累计占比曲线（帕累托）** — 横轴为排名，纵轴为累计金额占总额 %；约 70%/90% 处对应 A/B 分界直觉。")
            pareto = country[["贸易伙伴名称", "人民币", "累计占比(%)"]].copy()
            pareto["排名"] = range(1, len(pareto) + 1)
            st.line_chart(pareto.set_index("排名")[["累计占比(%)"]])

            if len(trade) > 0:
                st.markdown("**贸易方式 — 金额对比（全部）**")
                st.bar_chart(trade.set_index("贸易方式")[["总金额"]])

        with tab_country:
            st.caption(f"共 **{n_partner}** 行，按出口金额降序；**人民币(直观)** 为万/亿口径读法，便于扫一眼判断量级。")
            country_disp = insert_readable_rmb_column(country, "人民币")
            st.dataframe(
                country_disp,
                use_container_width=True,
                hide_index=True,
                height=560,
                column_config={
                    "人民币": st.column_config.NumberColumn(format="%.2f"),
                    "占比(%)": st.column_config.NumberColumn(format="%.2f"),
                    "累计占比(%)": st.column_config.NumberColumn(format="%.2f"),
                },
            )

        with tab_trade:
            st.caption(f"共 **{n_trade}** 种贸易方式。**总金额(直观)** 为万/亿口径。")
            trade_disp = insert_readable_rmb_column(trade, "总金额", "总金额(直观)")
            st.dataframe(
                trade_disp,
                use_container_width=True,
                hide_index=True,
                height=min(520, 120 + n_trade * 36),
                column_config={
                    "总金额": st.column_config.NumberColumn(format="%.2f"),
                    "交易笔数": st.column_config.NumberColumn(format="%d"),
                },
            )

        with tab_detail:
            if clean is None:
                st.warning("无法加载原始明细表。")
            else:
                st.caption(f"共 **{len(clean)}** 行；含「人民币」列时增加 **人民币(直观)**。")
                clean_disp = (
                    insert_readable_rmb_column(clean, "人民币")
                    if "人民币" in clean.columns
                    else clean
                )
                st.dataframe(clean_disp, use_container_width=True, hide_index=True, height=560)

        rid = st.session_state.get("cda_view_run_id")
        dl_name = f"海关数据_全量决策报表_{rid}.xlsx" if rid else "海关数据_全量决策报表.xlsx"
        st.download_button(
            label="下载全量决策报表（Excel，三工作表）",
            data=xlsx_bytes,
            file_name=dl_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="cda_dl",
        )
        if st.button("清除当前预览", key="cda_clear_preview"):
            _cda_clear_preview()
            st.rerun()

    st.title("海关数据分析")
    st.caption("与 `mianliao/custom_data_analysis.py` 一致：按贸易伙伴汇总人民币、ABC 市场分级；按贸易方式汇总。每次分析结果会保存到本地，可随时加载或删除。")

    # —— 历史记录 ——
    st.subheader("历史分析记录")
    conn_h = get_connection()
    try:
        hist = list_customs_runs(conn_h, limit=50)
    finally:
        conn_h.close()

    if not hist:
        st.caption("暂无历史记录；完成一次「开始分析」后会自动保存到此列表。")
    else:
        for h in hist:
            hid = int(h["id"])
            fn = (h["source_filename"] or "").strip() or "（未命名文件）"
            ts = (h["created_at"] or "")[:19].replace("T", " ")
            c1, c2, c3, c4, c5 = st.columns([0.45, 1.2, 0.55, 0.55, 0.55])
            with c1:
                st.markdown(f"**#{hid}**")
            with c2:
                st.markdown(f"{ts} · `{fn}`")
            with c3:
                st.caption(f"{h['detail_rows']} 行")
            with c4:
                if st.button("加载", key=f"cda_load_{hid}", help="在下方恢复此次图表与下载"):
                    connx = get_connection()
                    try:
                        blob = get_customs_run_blob(connx, hid)
                    finally:
                        connx.close()
                    if not blob:
                        st.error("记录不存在或已损坏。")
                    else:
                        try:
                            country, trade, detail = parse_saved_report_excel(blob)
                            _cda_set_preview(
                                country,
                                trade,
                                detail,
                                blob,
                                source_label=f"已加载历史记录 **#{hid}** · {fn} · {ts}",
                                view_run_id=hid,
                            )
                            st.toast("已加载该次分析结果")
                            st.rerun()
                        except Exception as e:  # noqa: BLE001
                            st.error(f"无法解析已存报表：{e}")
            with c5:
                if st.button("删除", key=f"cda_del_{hid}", type="secondary"):
                    connx = get_connection()
                    try:
                        delete_customs_run(connx, hid)
                        connx.commit()
                    finally:
                        connx.close()
                    if st.session_state.get("cda_view_run_id") == hid:
                        _cda_clear_preview()
                    st.toast(f"已删除记录 #{hid}")
                    st.rerun()

    st.divider()

    with st.expander("CSV 需包含的列名", expanded=False):
        st.markdown(
            "至少需要：**贸易伙伴名称**、**人民币**、**贸易方式名称**（与海关导出字段一致）。"
        )

    up = st.file_uploader("上传海关数据 CSV", type=["csv"], key="cda_csv")
    enc_label = st.radio(
        "文件编码",
        ["自动（gb18030 → utf-8-sig → utf-8）", "gb18030", "utf-8-sig", "utf-8"],
        horizontal=True,
        key="cda_enc",
    )
    enc: str | None
    if enc_label.startswith("自动"):
        enc = None
    else:
        enc = enc_label

    if st.button("开始分析", type="primary", key="cda_go"):
        _cda_clear_preview()
        if not up:
            st.warning("请先上传 CSV 文件。")
        else:
            try:
                raw = up.read()
                bio = io.BytesIO(raw)
                df = read_customs_csv(bio, encoding=enc)
                country, trade, clean = analyze_customs_dataframe(df)
                xlsx_bytes = report_to_excel_bytes(country, trade, clean)
                connx = get_connection()
                try:
                    new_id = insert_customs_run(
                        connx,
                        source_filename=up.name,
                        detail_rows=len(clean),
                        partner_rows=len(country),
                        trade_mode_rows=len(trade),
                        excel_blob=xlsx_bytes,
                    )
                    connx.commit()
                finally:
                    connx.close()
                _cda_set_preview(
                    country,
                    trade,
                    clean,
                    xlsx_bytes,
                    source_label=f"本次分析已保存为历史 **#{new_id}** · `{up.name}`",
                    view_run_id=new_id,
                )
                st.toast(f"分析完成，已写入历史 #{new_id}", icon="✅")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"分析失败：{e}")

    _cda_render_results()


def render_manual_wiki_page() -> None:
    """操作手册：按分类存储，支持 Markdown、新建、编辑、删除。"""
    init_db()

    SECTION_LABELS = ["常用代码片段", "操作步骤备忘", "图片/命名规范"]
    SECTION_KEYS = ["snippet", "sop", "design"]
    label_to_key = dict(zip(SECTION_LABELS, SECTION_KEYS))

    if "mw_edit_id" not in st.session_state:
        st.session_state.mw_edit_id = None

    st.title("📚 网站维护百科全书（可编辑）")
    st.caption("内容保存在本地数据库 `manual_entries` 表；支持 **Markdown**（代码块、列表等）。首次进入会自动写入与旧版相同的示例条目。")

    choice = st.radio("选择分类", SECTION_LABELS, horizontal=True, key="mw_top_section")
    section_key = label_to_key[choice]

    conn = get_connection()
    try:
        entries = list_manual_entries(conn, section_key)
    finally:
        conn.close()

    edit_row = None
    if st.session_state.mw_edit_id is not None:
        conn = get_connection()
        try:
            edit_row = get_manual_entry(conn, int(st.session_state.mw_edit_id))
        finally:
            conn.close()
        if edit_row is None:
            st.session_state.mw_edit_id = None

    st.subheader(f"「{choice}」下的条目")
    if st.button("＋ 在此分类下新建", key="mw_new_entry"):
        st.session_state.mw_edit_id = None
        st.session_state.pop("mw_title", None)
        st.session_state.pop("mw_body", None)
        st.rerun()

    c_list, c_edit = st.columns([1, 1.2])
    with c_list:
        if not entries:
            st.info("该分类下暂无条目，点击上方「新建」添加。")
        for e in entries:
            eid = int(e["id"])
            title_disp = (e["title"] or "").strip() or f"（未命名 #{eid}）"
            r1, r2 = st.columns([3, 1])
            with r1:
                if st.button(title_disp, key=f"mw_pick_{eid}", use_container_width=True):
                    st.session_state.mw_edit_id = eid
                    st.session_state.mw_title = e["title"] or ""
                    st.session_state.mw_body = e["body"] or ""
                    st.rerun()
            with r2:
                if st.button("删除", key=f"mw_del_{eid}", type="secondary"):
                    connx = get_connection()
                    try:
                        delete_manual_entry(connx, eid)
                        connx.commit()
                    finally:
                        connx.close()
                    if st.session_state.get("mw_edit_id") == eid:
                        st.session_state.mw_edit_id = None
                        st.session_state.pop("mw_title", None)
                        st.session_state.pop("mw_body", None)
                    st.toast("已删除该条目")
                    st.rerun()

    with c_edit:
        mode = "编辑条目" if st.session_state.mw_edit_id else "新建条目"
        st.subheader(mode)

        if edit_row is not None:
            sec_idx = SECTION_KEYS.index(edit_row["section"]) if edit_row["section"] in SECTION_KEYS else 0
        else:
            sec_idx = SECTION_KEYS.index(section_key)
        save_label = st.selectbox("归属分类", SECTION_LABELS, index=sec_idx, key="mw_save_section")
        save_sec = label_to_key[save_label]

        st.text_input("标题", key="mw_title", placeholder="简短标题，便于列表识别")
        st.text_area("正文（Markdown）", key="mw_body", height=320, placeholder="支持标题、列表、代码块等…")

        with st.expander("预览渲染效果", expanded=False):
            st.markdown(st.session_state.get("mw_body") or "_（空）_")

        b1, b2 = st.columns(2)
        with b1:
            do_save = st.button("保存", type="primary", key="mw_save")
        with b2:
            if st.session_state.mw_edit_id is not None:
                do_cancel = st.button("取消编辑", key="mw_cancel")
            else:
                do_cancel = False

        if do_cancel:
            st.session_state.mw_edit_id = None
            st.session_state.pop("mw_title", None)
            st.session_state.pop("mw_body", None)
            st.rerun()

        if do_save:
            title = (st.session_state.get("mw_title") or "").strip()
            body = st.session_state.get("mw_body") or ""
            if not title and not body.strip():
                st.warning("请填写标题或正文后再保存。")
            else:
                display_title = title or "（未命名）"
                connx = get_connection()
                try:
                    if st.session_state.mw_edit_id is None:
                        insert_manual_entry(connx, section=save_sec, title=display_title, body=body)
                    else:
                        update_manual_entry(
                            connx,
                            entry_id=int(st.session_state.mw_edit_id),
                            section=save_sec,
                            title=display_title,
                            body=body,
                        )
                    connx.commit()
                finally:
                    connx.close()
                st.session_state.mw_edit_id = None
                st.session_state.pop("mw_title", None)
                st.session_state.pop("mw_body", None)
                st.toast("已保存")
                st.rerun()


# --- 侧边栏导航（全部展开可见，非下拉） ---
menu = st.sidebar.radio(
    "主菜单",
    [
        "仪表盘",
        "操作百科 (SOP)",
        "知识库",
        "产品导入",
        "海关数据分析",
        "客户/样品管理",
        "记事本",
    ],
    index=0,
    key="main_nav_menu",
)

# --- 模块一：仪表盘 (运维提醒) ---
if menu == "仪表盘":
    st.title("🚀 FabricsWarm 管理看板")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Shopify 续费提醒", "25 Days Left", delta="-2 days")
    with col2:
        st.metric("域名过期", "2027-05-10")
    with col3:
        st.info("💡 备忘：本周需上传 10 款新面料图片")

# --- 模块二：操作百科 (你的核心需求) ---
elif menu == "操作百科 (SOP)":
    render_manual_wiki_page()

elif menu == "知识库":
    render_knowledge_base()

elif menu == "产品导入":
    st.title("产品导入 → Matrixify Excel")
    st.caption(
        "在线表格与 Excel 二选一或组合使用：合并默认值并写入 Body (HTML)；"
        "描述按 Tags：含 **Fleece** → 抓绒；含 **Stretch** 或 **Yoga** → 弹力；否则 **Knit** 针织。"
    )

    with st.expander("字段说明", expanded=False):
        st.markdown(
            """
- **在线表格**：与下载模板相同的 **7 个字段**，当前设置的每一行均为 **必填**（默认 10 行即 10 条产品）。
- **上传 Excel**：列名需与模板一致；空单元格仍会用系统默认值填充（与历史简表逻辑一致）。
- 生成文件建议命名：`Import_Product_Matrixify.xlsx`，导入 Matrixify 前请再核对 HTS/MOQ 等。
            """
        )

    c1, c2 = st.columns(2)
    with c1:
        tpl = build_manual_template_dataframe()
        st.download_button(
            label="下载简表模板（Excel）",
            data=to_excel_bytes(tpl),
            file_name="Product_Info_Before_Import.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with c2:
        st.info("模板列与在线表格一致，共 7 列；在线模式下每一行都必须填完整。")

    force_tpl = st.checkbox(
        "始终根据合并后的 Tags 套用 Fleece / Stretch / Knit 模板（推荐）",
        value=True,
        help="关闭后：仅当表中有 Tags 列且该行 Tags 非空时，才按 Tags 更新 Body (HTML)。",
    )

    def _run_matrixify(df_src: pd.DataFrame, *, from_label: str) -> None:
        st.session_state.pop("matrixify_excel_bytes", None)
        st.session_state.pop("matrixify_warnings", None)
        st.session_state.pop("matrixify_preview", None)
        out_df, warns = generate_matrixify_dataframe(
            df_src,
            force_body_from_tags=force_tpl,
            skip_rows_without_handle=True,
        )
        for w in warns:
            st.warning(w)
        if out_df.empty:
            st.error("没有可导出的行：请检查 Handle 是否填写。")
        else:
            st.session_state["matrixify_excel_bytes"] = to_excel_bytes(out_df)
            st.session_state["matrixify_warnings"] = warns
            st.session_state["matrixify_preview"] = out_df
            st.success(f"已从{from_label}生成 {len(out_df)} 行，可下载下方 Excel。")

    tab_online, tab_excel = st.tabs(["在线填写（模板全必填）", "上传 Excel"])

    with tab_online:
        st.markdown(
            f"下方表格共 **{len(MANUAL_TEMPLATE_COLUMNS)}** 列，与模板一致；"
            "请设置「产品行数」后逐行填写，**全部格子填完**再点生成。"
        )
        n_rows = st.number_input(
            "产品行数（每条产品一行）",
            min_value=1,
            max_value=50,
            value=10,
            step=1,
            help="默认 10 行；改行数会截断末尾或向下补齐空行。",
        )
        if "online_df" not in st.session_state:
            st.session_state.online_df = empty_manual_input_rows(int(n_rows))
        resized = resize_manual_input_dataframe(st.session_state.online_df, int(n_rows))
        edited = st.data_editor(
            resized,
            column_config={
                "Handle": st.column_config.TextColumn("Handle", required=True, width="medium"),
                "Title": st.column_config.TextColumn("Title", required=True, width="large"),
                "Tags": st.column_config.TextColumn("Tags", required=True, help="含 Fleece / Stretch / Yoga 等以匹配描述模板", width="medium"),
                "Variant Price": st.column_config.NumberColumn(
                    "Variant Price",
                    required=True,
                    min_value=0.0,
                    format="%.2f",
                    step=0.01,
                ),
                "Metafield: custom.gsm [string]": st.column_config.TextColumn("GSM", required=True, width="small"),
                "Metafield: custom.width [string]": st.column_config.TextColumn("幅宽", required=True, width="small"),
                "Metafield: custom.composition [string]": st.column_config.TextColumn("成分", required=True, width="medium"),
            },
            hide_index=True,
            num_rows="fixed",
            use_container_width=True,
            key="online_products_editor",
        )
        st.session_state.online_df = edited.reindex(columns=MANUAL_TEMPLATE_COLUMNS)

        if st.button("从在线表格生成 Matrixify Excel", type="primary", key="btn_matrixify_online"):
            df_try = edited.reindex(columns=MANUAL_TEMPLATE_COLUMNS).copy()
            df_try["Variant Price"] = pd.to_numeric(df_try["Variant Price"], errors="coerce")
            v_errs = validate_manual_template_required(df_try)
            if v_errs:
                st.error("请补全以下必填项后再生成：\n\n" + "\n".join(v_errs))
            else:
                _run_matrixify(df_try, from_label="在线表格")

    with tab_excel:
        up = st.file_uploader("上传 Excel（.xlsx / .xlsm）", type=["xlsx", "xlsm"], key="upload_matrixify_excel")
        if st.button("从上传文件生成 Matrixify Excel", type="primary", key="btn_matrixify_file"):
            if not up:
                st.warning("请先选择要上传的 Excel 文件。")
            else:
                try:
                    raw = up.read()
                    df = read_table_file(up.name, io.BytesIO(raw))
                except Exception as e:  # noqa: BLE001
                    st.error(f"读取 Excel 失败：{e}")
                else:
                    _run_matrixify(df, from_label="上传文件")

    b = st.session_state.get("matrixify_excel_bytes")
    if b:
        st.download_button(
            label="下载 Matrixify 导入表（Excel）",
            data=b,
            file_name="Import_Product_Matrixify.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    prev = st.session_state.get("matrixify_preview")
    if prev is not None and not prev.empty:
        st.subheader("预览（前几列）")
        head_cols = [
            c
            for c in ("Handle", "Title", "Tags", "Variant SKU", "Metafield: custom.hts [string]", "Body (HTML)")
            if c in prev.columns
        ]
        show = prev[head_cols].head(20).copy()
        if "Body (HTML)" in show.columns:

            def _short_html(val: object) -> str:
                t = str(val)
                return t[:120] + ("…" if len(t) > 120 else "")

            show["Body (HTML)"] = show["Body (HTML)"].map(_short_html)
        st.dataframe(show, use_container_width=True, hide_index=True)

elif menu == "海关数据分析":
    render_customs_analysis_page()

elif menu == "记事本":
    render_notebook_page()

elif menu == "客户/样品管理":
    st.title(f"{menu} 模块")
    st.warning("该功能正在开发中，请使用 Cursor 继续生成...")
else:
    st.title("导航")
    st.error("未知菜单项。")
