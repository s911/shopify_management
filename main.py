import io
import re

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
    generate_matrixify_dataframe,
    read_table_file,
    to_excel_bytes,
)
from shopify_mgmt.product.tag_engine import (
    PRODUCT_TYPE_OPTIONS,
    apply_tag_engine_to_bulk_dataframe,
    build_bulk_import_template_dataframe,
    run_tag_engine,
)
from shopify_mgmt.rmb_cn import format_rmb_cn, insert_readable_rmb_column


# 设置页面风格
st.set_page_config(
    page_title="FabricsWarm Admin",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _auto_format_note_body(raw_text: str) -> str:
    """把粘贴进来的纯文本整理成更清晰的纯文本层次结构。"""
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    # 句号/分号后自动断行，解决整段粘贴成一行的问题
    text = re.sub(r"(?<=[。；;])(?=\S)", "\n", text)
    # 中文大标题（如：一、二、）前断行
    text = re.sub(r"(?<!\n)([一二三四五六七八九十百]+、)", r"\n\1", text)
    # 数字编号（如：1. / 2) / 3、）前断行
    text = re.sub(r"(?<!\n)(\d{1,2}[.)、])\s*", r"\n\1 ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    out: list[str] = []

    def _append_with_gap(line: str, *, gap: bool = False) -> None:
        if gap and out and out[-1] != "":
            out.append("")
        out.append(line)

    def _is_heading_line(s: str) -> bool:
        if re.match(r"^[一二三四五六七八九十百]+、", s):
            return True
        if re.match(r"^\d{1,2}[.)、]\s*", s):
            return True
        if (s.endswith(":") or s.endswith("：")) and len(s) <= 40:
            return True
        return False

    for line in lines:
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue

        # 清洗常见 Markdown 符号，避免粘贴后保留 ### / ** / - 等标记
        line = re.sub(r"^#{1,6}\s*", "", line)  # heading 前缀
        line = re.sub(r"^\s*[-*]\s+(?=\*\*|[A-Za-z0-9\u4e00-\u9fff])", "", line)  # 列表前缀
        line = line.replace("**", "")  # 粗体标记
        line = re.sub(r"^[•·]\s*", "", line)  # 圆点前缀
        line = line.strip()
        if not line:
            continue

        # 一级层次：中文章节（如“一、 纤维成分”）
        if re.match(r"^[一二三四五六七八九十百]+、", line):
            _append_with_gap(line, gap=True)
            continue

        # 二级层次：数字编号（如“1. 天然纤维”）
        m_num = re.match(r"^(\d{1,2})[.)、]\s*(.+)$", line)
        if m_num:
            _append_with_gap(f"{m_num.group(1)}. {m_num.group(2).strip()}", gap=True)
            continue

        # 三级层次：短标题（如“发货说明:” / “发货说明：”）
        if (line.endswith(":") or line.endswith("：")) and len(line) <= 40:
            _append_with_gap(line, gap=True)
            continue

        # 常见项目符号 -> 统一成纯文本缩进
        if line.startswith(("-", "*", "•", "·")):
            item = line[1:].strip()
            _append_with_gap(f"  {item}" if item else "")
            continue

        # “术语：解释” -> 标题行 + 缩进子项
        if "：" in line and not line.startswith("#"):
            left, right = line.split("：", 1)
            left = left.strip()
            right = right.strip()
            if 1 <= len(left) <= 40 and right:
                _append_with_gap(f"{left}：", gap=True)
                # 将逗号分隔的长串拆成缩进子项，增强层次感
                sub_items = [x.strip() for x in re.split(r"[，,]\s*", right) if x.strip()]
                if len(sub_items) >= 2:
                    for s in sub_items:
                        _append_with_gap(f"    {s}")
                else:
                    _append_with_gap(f"  {right}")
                continue

        # 普通正文：如果前一行是标题，则与正文间留一行
        if out and _is_heading_line(out[-1]):
            _append_with_gap(line, gap=True)
        else:
            _append_with_gap(line)

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def render_notebook_page() -> None:
    """简单记事：SQLite 持久化，支持新建 / 编辑 / 删除。"""
    init_db()
    if "note_editing_id" not in st.session_state:
        st.session_state.note_editing_id = None
    if "nb_title" not in st.session_state:
        st.session_state.nb_title = ""
    if "nb_body" not in st.session_state:
        st.session_state.nb_body = ""
    if "nb_format_pending" not in st.session_state:
        st.session_state.nb_format_pending = False
    if "nb_body_formatted" not in st.session_state:
        st.session_state.nb_body_formatted = ""
    if "nb_reset_pending" not in st.session_state:
        st.session_state.nb_reset_pending = False
    if st.session_state.get("nb_reset_pending"):
        st.session_state.nb_title = ""
        st.session_state.nb_body = ""
        st.session_state.nb_reset_pending = False

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
            if st.session_state.get("nb_format_pending"):
                st.session_state.nb_body = st.session_state.get("nb_body_formatted", "")
                st.session_state.nb_format_pending = False
            st.text_area("正文", key="nb_body", height=int(body_h), placeholder="随手记录…")

            c1, c2, c3, _ = st.columns([1, 1, 1.2, 2.8])
            with c1:
                do_save = st.button("保存", type="primary", key="nb_save")
            with c2:
                can_del = st.session_state.note_editing_id is not None
                do_delete = st.button("删除", type="secondary", key="nb_delete", disabled=not can_del)
            with c3:
                do_fmt = st.button("一键整理格式", key="nb_format")

        if do_fmt:
            body_old = st.session_state.get("nb_body") or ""
            if not body_old.strip():
                st.warning("正文为空，无需整理。")
            else:
                st.session_state.nb_body_formatted = _auto_format_note_body(body_old)
                st.session_state.nb_format_pending = True
                st.rerun()

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
            st.session_state.nb_reset_pending = True
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
    st.title("产品录入与 Matrixify 导出")
    st.caption("在线录入支持多行（默认 10 行），`Product Type` 与补充 `Tag` 使用下拉选择；批量模板已精简并保留 Product Type 必填。")

    type_ctl, tag_ctl = st.columns(2)
    with type_ctl:
        add_new_type = st.checkbox("Add New Type", value=False, key="add_new_type_switch")
        new_type_text = ""
        if add_new_type:
            new_type_text = (st.text_input("New Product Type", key="add_new_type_text", placeholder="例如 Waffle Knit") or "").strip()
    with tag_ctl:
        add_new_tag = st.checkbox("Add New Tag", value=False, key="add_new_tag_switch")
        new_tag_text = ""
        if add_new_tag:
            new_tag_text = (st.text_input("New Tag", key="add_new_tag_text", placeholder="例如 Soft Touch") or "").strip()

    type_options = list(PRODUCT_TYPE_OPTIONS)
    if new_type_text and new_type_text not in type_options:
        type_options.append(new_type_text)
        st.success(f"已添加新 Product Type：{new_type_text}")
    tag_options = [
        "Fleece",
        "Stretch",
        "Yoga",
        "Heavyweight",
        "Midweight",
        "Lightweight",
        "Sustainable",
        "Ready-to-Ship",
        "Sample-Available",
    ]
    if new_tag_text and new_tag_text not in tag_options:
        tag_options.append(new_tag_text)
        st.success(f"已添加新 Tag：{new_tag_text}")

    with st.expander("字段与规则说明", expanded=False):
        st.markdown(
            """
- 在线多行：默认 10 行，可改行数；`Product Type` 与 `Tag` 采用下拉。
- `Product Type` 是必填字段（在线与批量都校验）。
- 批量模板仅保留核心列，不再出现多余 I/J 列。
- 最终 `Tags` 统一经引擎生成（自动包含 Product Type，并与下拉 Tag 合并）。
            """
        )

    force_tpl = st.checkbox(
        "始终根据最终 Tags 重新套用 Body (HTML) 模板（推荐）",
        value=True,
        key="matrixify_force_body",
    )

    def _run_matrixify(df_src: pd.DataFrame, *, from_label: str) -> None:
        st.session_state.pop("matrixify_excel_bytes", None)
        st.session_state.pop("matrixify_warnings", None)
        st.session_state.pop("matrixify_preview", None)
        out_df, warns = generate_matrixify_dataframe(
            df_src,
            force_body_from_tags=st.session_state.get("matrixify_force_body", True),
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

    st.subheader("在线多行录入")
    n_rows = int(st.number_input("产品行数", min_value=1, max_value=60, value=10, step=1, key="multi_rows"))
    st.caption("默认 10 行；留空行会自动跳过。")

    headers = ["Handle", "Title", "Product Type", "Tag", "GSM", "Composition", "Price", "Width"]
    col_widths = [1.7, 2.3, 1.3, 1.9, 0.9, 1.7, 0.9, 1.1]
    hcols = st.columns(col_widths)
    for j, h in enumerate(headers):
        hcols[j].markdown(f"**{h}**")

    row_inputs: list[dict[str, object]] = []
    for i in range(n_rows):
        cols = st.columns(col_widths)
        handle = cols[0].text_input(f"handle_{i}", label_visibility="collapsed", key=f"multi_handle_{i}")
        title = cols[1].text_input(f"title_{i}", label_visibility="collapsed", key=f"multi_title_{i}")
        ptype = cols[2].selectbox(f"type_{i}", type_options, index=0, label_visibility="collapsed", key=f"multi_type_{i}")
        with cols[3]:
            picked_labels = st.multiselect(
                f"tag_{i}",
                tag_options,
                default=[],
                label_visibility="collapsed",
                key=f"multi_tags_{i}",
            )
            addon_tags = [str(t).strip() for t in picked_labels if str(t).strip()]
            if addon_tags:
                st.caption("已选: " + ", ".join(addon_tags))
        gsm = cols[4].text_input(f"gsm_{i}", label_visibility="collapsed", key=f"multi_gsm_{i}")
        comp = cols[5].text_input(f"composition_{i}", label_visibility="collapsed", key=f"multi_comp_{i}")
        price = cols[6].number_input(
            f"price_{i}",
            min_value=0.0,
            value=3.0,
            step=0.01,
            format="%.2f",
            label_visibility="collapsed",
            key=f"multi_price_{i}",
        )
        width = cols[7].text_input(f"width_{i}", label_visibility="collapsed", key=f"multi_width_{i}")
        row_inputs.append(
            {
                "Handle": handle,
                "Title": title,
                "Product Type": ptype,
                "Tag": addon_tags,
                "GSM": gsm,
                "Composition": comp,
                "Variant Price": price,
                "Metafield: custom.width [string]": width,
            }
        )

    # 实时检查 Handle 重复（仅检查已填写 Handle 的行）
    live_seen: dict[str, list[int]] = {}
    for idx, r in enumerate(row_inputs, start=1):
        handle_live = str(r.get("Handle", "")).strip()
        if not handle_live:
            continue
        live_seen.setdefault(handle_live.lower(), []).append(idx)
    live_dups = {h: rows for h, rows in live_seen.items() if len(rows) > 1}
    if live_dups:
        dup_preview = "；".join(f"{h}（行 {', '.join(str(x) for x in rows)}）" for h, rows in live_dups.items())
        st.warning(f"检测到重复 Handle：{dup_preview}")

    if st.button("生成表格", type="primary", key="btn_matrixify_multi"):
        out_rows: list[dict[str, object]] = []
        errs: list[str] = []
        seen_handles: dict[str, list[int]] = {}
        for idx, r in enumerate(row_inputs, start=1):
            handle = str(r.get("Handle", "")).strip()
            if not handle:
                continue

            missing_cols: list[str] = []
            if not str(r.get("Title", "")).strip():
                missing_cols.append("Title")
            if not str(r.get("Product Type", "")).strip():
                missing_cols.append("Product Type")
            if not bool(r.get("Tag")):
                missing_cols.append("Tag")
            if not str(r.get("GSM", "")).strip():
                missing_cols.append("GSM")
            if not str(r.get("Composition", "")).strip():
                missing_cols.append("Composition")
            if not str(r.get("Metafield: custom.width [string]", "")).strip():
                missing_cols.append("Width")
            if missing_cols:
                errs.append(f"第 {idx} 行已填写 Handle，以下字段为必填：{', '.join(missing_cols)}。")
                continue

            ptype = str(r.get("Product Type", "")).strip()
            title = str(r.get("Title", "")).strip()
            hkey = handle.lower()
            seen_handles.setdefault(hkey, []).append(idx)
            try:
                price_val = float(r.get("Variant Price"))
            except (TypeError, ValueError):
                errs.append(f"第 {idx} 行 Price 必须为数值。")
                continue
            if price_val < 0:
                errs.append(f"第 {idx} 行 Price 不能小于 0。")
                continue
            extra_tags = ", ".join(str(t).strip() for t in (r.get("Tag") or []) if str(t).strip())
            tags = run_tag_engine(
                product_type=ptype,
                gsm=r.get("GSM"),
                composition=str(r.get("Composition", "")),
                existing_tags=extra_tags,
            )
            out_rows.append(
                {
                    "Handle": handle,
                    "Title": title,
                    "Type": ptype,
                    "Tags": tags,
                    "Variant Price": price_val,
                    "Metafield: custom.gsm [string]": str(r.get("GSM", "")).strip(),
                    "Metafield: custom.composition [string]": str(r.get("Composition", "")).strip(),
                    "Metafield: custom.width [string]": str(r.get("Metafield: custom.width [string]", "")).strip(),
                }
            )
        dup_msgs = []
        for h, rows in seen_handles.items():
            if len(rows) > 1:
                dup_msgs.append(f"{h}（行 {', '.join(str(x) for x in rows)}）")
        if dup_msgs:
            errs.append("Handle 必须唯一，重复项：" + "；".join(dup_msgs))
        if errs:
            st.error("\n".join(errs))
        elif not out_rows:
            st.warning("没有检测到可导出的有效行。")
        else:
            _run_matrixify(pd.DataFrame(out_rows), from_label="在线多行")

    st.markdown("---")
    bottom_left, bottom_mid, bottom_right = st.columns([1.0, 1.2, 1.0])
    with bottom_left:
        st.subheader("批量模板下载")
        tpl_bulk = build_bulk_import_template_dataframe()
        st.download_button(
            label="下载批量导入表头模板（Excel）",
            data=to_excel_bytes(tpl_bulk),
            file_name="Product_Bulk_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_bulk_tpl",
        )
    with bottom_mid:
        st.subheader("上传数据")
        st.caption("Product Type 必填；若有 Tags 列会与引擎标签合并。")
        up = st.file_uploader("选择文件（.xlsx / .xlsm）", type=["xlsx", "xlsm"], key="upload_bulk_matrixify")
        if st.button("生成表格", type="primary", key="btn_matrixify_bulk"):
            if not up:
                st.warning("请先选择 Excel 文件。")
            else:
                try:
                    raw = up.read()
                    df_raw = read_table_file(up.name, io.BytesIO(raw))
                except Exception as e:  # noqa: BLE001
                    st.error(f"读取 Excel 失败：{e}")
                else:
                    cols_strip = [str(c).strip() for c in df_raw.columns]
                    df_raw.columns = cols_strip
                    type_col = "Product Type" if "Product Type" in df_raw.columns else ("Type" if "Type" in df_raw.columns else "")
                    if not type_col:
                        st.error("上传表缺少 Product Type 列（可用列名：`Product Type` 或 `Type`）。")
                    else:
                        missing_rows: list[int] = []
                        for n, (_, row) in enumerate(df_raw.iterrows(), start=1):
                            row_has_data = any(
                                str(row.get(c, "")).strip() and str(row.get(c, "")).strip().lower() != "nan"
                                for c in df_raw.columns
                            )
                            if not row_has_data:
                                continue
                            if not str(row.get(type_col, "")).strip() or str(row.get(type_col, "")).strip().lower() == "nan":
                                missing_rows.append(n)
                        if missing_rows:
                            show = ", ".join(str(x) for x in missing_rows[:20])
                            st.error(f"Product Type 为必填，以下行为空：{show}")
                        else:
                            can_process_bulk = True
                            if "Variant Price" in df_raw.columns:
                                bad_price_rows: list[int] = []
                                for n, (_, row) in enumerate(df_raw.iterrows(), start=1):
                                    raw_price = row.get("Variant Price")
                                    s = str(raw_price).strip().lower()
                                    if s in ("", "nan", "none"):
                                        continue
                                    try:
                                        float(raw_price)
                                    except (TypeError, ValueError):
                                        bad_price_rows.append(n)
                                if bad_price_rows:
                                    show = ", ".join(str(x) for x in bad_price_rows[:20])
                                    st.error(f"Variant Price 必须为数值，以下行非法：{show}")
                                    can_process_bulk = False
                            if can_process_bulk:
                                df_proc = apply_tag_engine_to_bulk_dataframe(df_raw)
                                _run_matrixify(df_proc, from_label="Excel 批量（标签引擎）")
    with bottom_right:
        st.subheader("表格下载")
        b = st.session_state.get("matrixify_excel_bytes")
        if b:
            st.download_button(
                label="下载表格（Excel）",
                data=b,
                file_name="Import_Product_Matrixify.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_matrixify_out",
            )
        else:
            st.info("先生成导入表后可下载。")
    prev = st.session_state.get("matrixify_preview")
    if prev is not None and not prev.empty:
        st.subheader("导出预览（前几列）")
        head_cols = [
            c
            for c in (
                "Handle",
                "Title",
                "Type",
                "Tags",
                "Variant SKU",
                "Metafield: custom.hts [string]",
                "Body (HTML)",
            )
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
