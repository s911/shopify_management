import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from shopify_mgmt.config import DB_PATH, ensure_data_dir


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_connection() -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_data_dir()
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                handle TEXT NOT NULL UNIQUE,
                title TEXT,
                tags TEXT,
                metafield_hts TEXT,
                metafield_moq TEXT,
                body_html TEXT,
                row_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_products_handle ON products(handle)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notes_updated_at ON notes(updated_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customs_analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source_filename TEXT,
                detail_rows INTEGER NOT NULL,
                partner_rows INTEGER NOT NULL,
                trade_mode_rows INTEGER NOT NULL,
                excel_blob BLOB NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_customs_runs_created ON customs_analysis_runs(created_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_manual_section_order ON manual_entries(section, sort_order)"
        )
        seed_manual_entries_if_empty(conn)
        conn.commit()
    finally:
        conn.close()


def upsert_product(
    conn: sqlite3.Connection,
    *,
    handle: str,
    title: str | None,
    tags: str | None,
    metafield_hts: str | None,
    metafield_moq: str | None,
    body_html: str | None,
    row: dict[str, Any],
) -> None:
    payload = json.dumps(row, ensure_ascii=False)
    ts = _utc_now_iso()
    conn.execute(
        """
        INSERT INTO products (handle, title, tags, metafield_hts, metafield_moq, body_html, row_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(handle) DO UPDATE SET
            title = excluded.title,
            tags = excluded.tags,
            metafield_hts = excluded.metafield_hts,
            metafield_moq = excluded.metafield_moq,
            body_html = excluded.body_html,
            row_json = excluded.row_json,
            updated_at = excluded.updated_at
        """,
        (handle, title, tags, metafield_hts, metafield_moq, body_html, payload, ts),
    )


def list_products(conn: sqlite3.Connection, limit: int = 5000) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM products ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )
    return list(cur.fetchall())


def delete_product(conn: sqlite3.Connection, handle: str) -> None:
    conn.execute("DELETE FROM products WHERE handle = ?", (handle,))


# --- 简单记事本 ---


def list_notes(conn: sqlite3.Connection, limit: int = 500) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT id, title, body, created_at, updated_at FROM notes ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )
    return list(cur.fetchall())


def get_note(conn: sqlite3.Connection, note_id: int) -> sqlite3.Row | None:
    cur = conn.execute(
        "SELECT id, title, body, created_at, updated_at FROM notes WHERE id = ?",
        (note_id,),
    )
    row = cur.fetchone()
    return row


def insert_note(conn: sqlite3.Connection, *, title: str, body: str) -> int:
    ts = _utc_now_iso()
    cur = conn.execute(
        "INSERT INTO notes (title, body, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (title.strip(), body, ts, ts),
    )
    return int(cur.lastrowid)


def update_note(conn: sqlite3.Connection, *, note_id: int, title: str, body: str) -> None:
    ts = _utc_now_iso()
    conn.execute(
        "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ?",
        (title.strip(), body, ts, note_id),
    )


def delete_note(conn: sqlite3.Connection, note_id: int) -> None:
    conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))


# --- 海关分析历史（保存完整 Excel 报表） ---


def insert_customs_run(
    conn: sqlite3.Connection,
    *,
    source_filename: str | None,
    detail_rows: int,
    partner_rows: int,
    trade_mode_rows: int,
    excel_blob: bytes,
) -> int:
    ts = _utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO customs_analysis_runs
            (created_at, source_filename, detail_rows, partner_rows, trade_mode_rows, excel_blob)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ts, source_filename or "", detail_rows, partner_rows, trade_mode_rows, excel_blob),
    )
    return int(cur.lastrowid)


def list_customs_runs(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT id, created_at, source_filename, detail_rows, partner_rows, trade_mode_rows
        FROM customs_analysis_runs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return list(cur.fetchall())


def get_customs_run_blob(conn: sqlite3.Connection, run_id: int) -> bytes | None:
    cur = conn.execute(
        "SELECT excel_blob FROM customs_analysis_runs WHERE id = ?",
        (run_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row["excel_blob"]


def delete_customs_run(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("DELETE FROM customs_analysis_runs WHERE id = ?", (run_id,))


# --- 操作手册 / SOP（按分类存储，Markdown 正文） ---


def _next_manual_sort_order(conn: sqlite3.Connection, section: str) -> int:
    cur = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM manual_entries WHERE section = ?",
        (section,),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 1


def list_manual_entries(conn: sqlite3.Connection, section: str, limit: int = 200) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT id, section, title, body, sort_order, created_at, updated_at
        FROM manual_entries
        WHERE section = ?
        ORDER BY sort_order ASC, id ASC
        LIMIT ?
        """,
        (section, limit),
    )
    return list(cur.fetchall())


def get_manual_entry(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row | None:
    cur = conn.execute(
        "SELECT id, section, title, body, sort_order, created_at, updated_at FROM manual_entries WHERE id = ?",
        (entry_id,),
    )
    return cur.fetchone()


def insert_manual_entry(
    conn: sqlite3.Connection,
    *,
    section: str,
    title: str,
    body: str,
    sort_order: int | None = None,
) -> int:
    ts = _utc_now_iso()
    so = sort_order if sort_order is not None else _next_manual_sort_order(conn, section)
    cur = conn.execute(
        """
        INSERT INTO manual_entries (section, title, body, sort_order, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (section, title.strip(), body, so, ts, ts),
    )
    return int(cur.lastrowid)


def update_manual_entry(
    conn: sqlite3.Connection,
    *,
    entry_id: int,
    section: str,
    title: str,
    body: str,
) -> None:
    ts = _utc_now_iso()
    conn.execute(
        """
        UPDATE manual_entries
        SET section = ?, title = ?, body = ?, updated_at = ?
        WHERE id = ?
        """,
        (section, title.strip(), body, ts, entry_id),
    )


def delete_manual_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("DELETE FROM manual_entries WHERE id = ?", (entry_id,))


def seed_manual_entries_if_empty(conn: sqlite3.Connection) -> None:
    """首次部署时写入与旧版页面等价的默认条目（仅表为空时执行）。"""
    cur = conn.execute("SELECT COUNT(*) AS c FROM manual_entries")
    if int(cur.fetchone()["c"]) > 0:
        return

    defaults: list[tuple[str, str, str, int]] = [
        (
            "snippet",
            "列表页起订量与标题优化（base.css）",
            """```css
/* 列表页标题去粗、价格加粗、起订量对齐 */
.card__heading { font-weight: 400 !important; height: 4.5rem !important; }
.price-item--regular { font-weight: 700 !important; font-size: 1.6rem !important; }
.min-order-text { font-size: 1.2rem; color: #666; margin-top: 8px; }
```""",
            1,
        ),
        (
            "snippet",
            "隐藏样品产品（全端）",
            """```css
.grid__item:has([data-product-handle="fabric-sample-swatch"]) { display: none !important; }
```""",
            2,
        ),
        (
            "sop",
            "如何批量关联变体图片？",
            """1. 先将图片上传至 Shopify 后台 **Content > Files**。
2. 确保文件名格式为：`handle-color.JPG`。
3. 在 Matrixify Excel 中，**Variant Image Src** 填入完整 URL。
4. 使用 **REPLACE** 模式导入。""",
            1,
        ),
        (
            "sop",
            "如何修改 CATALOG 侧边栏标题？",
            "在线商店 > 主题 > 编辑默认模板内容 > 搜索 `Product type` 并改为 `CATALOG`。",
            2,
        ),
        (
            "design",
            "Logo 与主图规范",
            """- **Logo** 建议尺寸：180×50px（PNG 透明）
- **产品主图** 建议比例：1:1 或 3:4""",
            1,
        ),
    ]
    for section, title, body, so in defaults:
        insert_manual_entry(conn, section=section, title=title, body=body, sort_order=so)
