import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime
from backend.config import DATABASE_FILE
from backend.firebase_sync import (
    sync_requisitions_to_firebase,
    delete_requisitions_from_firebase,
    sync_items_to_firebase,
    sync_physical_check_to_firebase,
    sync_full_database_snapshot_to_firebase
)

def get_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def make_item_key(req_no: str, item_code: str, sl: str) -> str:
    clean_req = str(req_no or "").strip()
    clean_code = str(item_code or "").strip().replace("/", "_").replace(".", "_")
    clean_sl = str(sl or "1").strip()
    return f"{clean_req}_{clean_code}_{clean_sl}"

def init_db():
    conn = get_connection()
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS requisitions (
            req_no TEXT PRIMARY KEY,
            manual_req_no TEXT,
            req_date TEXT,
            req_for TEXT,
            req_from TEXT,
            warehouse TEXT,
            req_type TEXT,
            need_by TEXT,
            entry_by TEXT,
            entry_at TEXT,
            status TEXT,
            details_synced INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS requisition_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            req_no TEXT NOT NULL,
            sl TEXT,
            item_code TEXT,
            product_name TEXT,
            item_desc TEXT,
            cwh REAL DEFAULT 0,
            req_qty REAL DEFAULT 0,
            app_qty REAL DEFAULT 0,
            unit TEXT,
            delivery_date TEXT,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (req_no) REFERENCES requisitions (req_no) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS physical_checks (
            item_key TEXT PRIMARY KEY,
            req_no TEXT NOT NULL,
            item_code TEXT,
            sl TEXT,
            physical_received INTEGER DEFAULT 0,
            physical_rec_qty REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sync_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            status TEXT DEFAULT 'idle',
            total_reqs INTEGER DEFAULT 0,
            synced_reqs INTEGER DEFAULT 0,
            current_step TEXT DEFAULT '',
            last_synced_at TEXT,
            error_message TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_req_entry_by ON requisitions (entry_by);
        CREATE INDEX IF NOT EXISTS idx_req_type ON requisitions (req_type);
        CREATE INDEX IF NOT EXISTS idx_req_date ON requisitions (req_date);
        CREATE INDEX IF NOT EXISTS idx_req_status ON requisitions (status);
        CREATE INDEX IF NOT EXISTS idx_items_req_no ON requisition_items (req_no);
        CREATE INDEX IF NOT EXISTS idx_items_code ON requisition_items (item_code);
        CREATE INDEX IF NOT EXISTS idx_items_name ON requisition_items (product_name);
        CREATE INDEX IF NOT EXISTS idx_phys_req_no ON physical_checks (req_no);

        INSERT OR IGNORE INTO sync_meta (id, status, total_reqs, synced_reqs, current_step, last_synced_at, error_message)
        VALUES (1, 'idle', 0, 0, 'Ready', NULL, '');
        """)
    conn.close()

def delete_requisitions_by_nos(req_nos: List[str]):
    if not req_nos:
        return
    conn = get_connection()
    with conn:
        for i in range(0, len(req_nos), 500):
            chunk = req_nos[i:i+500]
            placeholders = ",".join(["?"] * len(chunk))
            conn.execute(f"DELETE FROM requisitions WHERE req_no IN ({placeholders})", chunk)
    conn.close()
    delete_requisitions_from_firebase(req_nos)

def save_requisitions_batch(req_list: List[Dict[str, Any]]):
    if not req_list:
        return
    conn = get_connection()
    valid_for_fb = []
    deleted_for_fb = []
    with conn:
        for r in req_list:
            if str(r.get("req_type", "")).strip().upper() == "DSTR":
                continue
            if str(r.get("status", "")).strip().upper() == "RECEIVED":
                req_no = str(r.get("req_no", ""))
                conn.execute("DELETE FROM requisitions WHERE req_no = ?", (req_no,))
                deleted_for_fb.append(req_no)
                continue
            valid_for_fb.append(r)
            conn.execute("""
                INSERT INTO requisitions (
                    req_no, manual_req_no, req_date, req_for, req_from, warehouse,
                    req_type, need_by, entry_by, entry_at, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(req_no) DO UPDATE SET
                    manual_req_no = excluded.manual_req_no,
                    req_date = excluded.req_date,
                    req_for = excluded.req_for,
                    req_from = excluded.req_from,
                    warehouse = excluded.warehouse,
                    req_type = excluded.req_type,
                    need_by = excluded.need_by,
                    entry_by = excluded.entry_by,
                    entry_at = excluded.entry_at,
                    details_synced = CASE
                        WHEN requisitions.status != excluded.status THEN 0
                        WHEN UPPER(TRIM(excluded.status)) NOT IN ('RECEIVED', 'COMPLETE', 'COMPLETED') THEN 0
                        ELSE requisitions.details_synced
                    END,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                r.get("req_no"),
                r.get("manual_req_no", ""),
                r.get("req_date", ""),
                r.get("req_for", ""),
                r.get("req_from", ""),
                r.get("warehouse", ""),
                r.get("req_type", ""),
                r.get("need_by", ""),
                r.get("entry_by", ""),
                r.get("entry_at", ""),
                r.get("status", "")
            ))
    conn.close()
    if valid_for_fb:
        sync_requisitions_to_firebase(valid_for_fb)
    if deleted_for_fb:
        delete_requisitions_from_firebase(deleted_for_fb)

def save_requisition_items(req_no: str, items: List[Dict[str, Any]]):
    conn = get_connection()
    enriched_items = []
    with conn:
        # Load existing physical checks for this req_no
        cur = conn.cursor()
        cur.execute("SELECT item_key, physical_received, physical_rec_qty FROM physical_checks WHERE req_no = ?", (req_no,))
        phys_map = {row["item_key"]: dict(row) for row in cur.fetchall()}

        conn.execute("DELETE FROM requisition_items WHERE req_no = ?", (req_no,))
        for it in items:
            def parse_float(val):
                try:
                    return float(str(val).replace(",", "").strip())
                except:
                    return 0.0

            sl = str(it.get("sl", "1"))
            item_code = str(it.get("item_code", ""))
            req_qty = parse_float(it.get("req_qty", 0))
            app_qty = parse_float(it.get("app_qty", 0))
            cwh = parse_float(it.get("cwh", 0))
            ikey = make_item_key(req_no, item_code, sl)

            conn.execute("""
                INSERT INTO requisition_items (
                    req_no, sl, item_code, product_name, item_desc,
                    cwh, req_qty, app_qty, unit, delivery_date, remarks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req_no,
                sl,
                item_code,
                it.get("product_name", ""),
                it.get("item_desc", ""),
                cwh,
                req_qty,
                app_qty,
                it.get("unit", ""),
                it.get("delivery_date", ""),
                it.get("remarks", "")
            ))

            phys = phys_map.get(ikey, {})
            phys_rec = int(phys.get("physical_received", 0))
            phys_qty = float(phys.get("physical_rec_qty", 0.0))
            phys_pending = max(0.0, round(req_qty - phys_qty, 2))

            enriched_items.append({
                "item_key": ikey,
                "req_no": req_no,
                "sl": sl,
                "item_code": item_code,
                "product_name": it.get("product_name", ""),
                "item_desc": it.get("item_desc", ""),
                "cwh": cwh,
                "req_qty": req_qty,
                "app_qty": app_qty,
                "unit": it.get("unit", ""),
                "delivery_date": it.get("delivery_date", ""),
                "remarks": it.get("remarks", ""),
                "physical_received": phys_rec,
                "physical_rec_qty": phys_qty,
                "physical_pending": phys_pending
            })

        conn.execute("UPDATE requisitions SET details_synced = 1, updated_at = CURRENT_TIMESTAMP WHERE req_no = ?", (req_no,))
    conn.close()
    sync_items_to_firebase(req_no, enriched_items)

def save_physical_check(
    item_key: str,
    req_no: str,
    item_code: str,
    sl: str,
    physical_received: int,
    physical_rec_qty: float
) -> Dict[str, Any]:
    conn = get_connection()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute("""
            INSERT INTO physical_checks (item_key, req_no, item_code, sl, physical_received, physical_rec_qty, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_key) DO UPDATE SET
                physical_received = excluded.physical_received,
                physical_rec_qty = excluded.physical_rec_qty,
                updated_at = excluded.updated_at
        """, (item_key, str(req_no), str(item_code), str(sl), int(physical_received), float(physical_rec_qty), now_str))
    conn.close()

    data = {
        "item_key": item_key,
        "req_no": str(req_no),
        "item_code": str(item_code),
        "sl": str(sl),
        "physical_received": int(physical_received),
        "physical_rec_qty": float(physical_rec_qty),
        "updated_at": now_str
    }
    sync_physical_check_to_firebase(item_key, data)
    return data

def get_all_physical_checks() -> Dict[str, Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM physical_checks")
    rows = {r["item_key"]: dict(r) for r in cur.fetchall()}
    conn.close()
    return rows

def _enrich_item_row(row_dict: Dict[str, Any], phys_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    req_no = str(row_dict.get("req_no", ""))
    item_code = str(row_dict.get("item_code", ""))
    sl = str(row_dict.get("sl", "1"))
    ikey = make_item_key(req_no, item_code, sl)
    row_dict["item_key"] = ikey

    phys = phys_map.get(ikey)
    req_qty = float(row_dict.get("req_qty") or 0.0)
    phys_rec = int(phys["physical_received"]) if phys else 0
    phys_qty = float(phys["physical_rec_qty"]) if phys else 0.0
    phys_pending = max(0.0, round(req_qty - phys_qty, 2))

    row_dict["physical_received"] = phys_rec
    row_dict["physical_rec_qty"] = phys_qty
    row_dict["physical_pending"] = phys_pending
    return row_dict

def get_requisitions(
    entry_by: Optional[str] = None,
    req_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    fdate: Optional[str] = None,
    tdate: Optional[str] = None,
    page: int = 1,
    page_size: int = 25
) -> Dict[str, Any]:
    conn = get_connection()
    query = """
        SELECT r.*,
               COUNT(i.id) as item_count,
               COALESCE(SUM(i.req_qty), 0) as total_req_qty,
               COALESCE(SUM(i.app_qty), 0) as total_app_qty
        FROM requisitions r
        LEFT JOIN requisition_items i ON r.req_no = i.req_no
        WHERE 1=1
    """
    params = []

    if entry_by and entry_by.strip():
        query += " AND r.entry_by = ?"
        params.append(entry_by.strip())

    if req_type and req_type.strip():
        query += " AND r.req_type = ?"
        params.append(req_type.strip())

    if status and status.strip():
        query += " AND r.status = ?"
        params.append(status.strip())

    if fdate and fdate.strip():
        query += " AND r.req_date >= ?"
        params.append(fdate.strip())

    if tdate and tdate.strip():
        query += " AND r.req_date <= ?"
        params.append(tdate.strip())

    if search and search.strip():
        term = f"%{search.strip()}%"
        query += """ AND (
            r.req_no LIKE ? OR
            r.manual_req_no LIKE ? OR
            r.req_from LIKE ? OR
            r.warehouse LIKE ? OR
            EXISTS (SELECT 1 FROM requisition_items i2 WHERE i2.req_no = r.req_no AND (i2.item_code LIKE ? OR i2.product_name LIKE ?))
        )"""
        params.extend([term, term, term, term, term, term])

    query += " GROUP BY r.req_no ORDER BY r.req_date DESC, r.req_no DESC"

    count_query = f"SELECT COUNT(*) FROM ({query})"
    cur = conn.cursor()
    cur.execute(count_query, params)
    total_count = cur.fetchone()[0]

    offset = (page - 1) * page_size
    query += " LIMIT ? OFFSET ?"
    params.extend([page_size, offset])

    cur.execute(query, params)
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()

    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

    return {
        "items": rows,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

def get_requisition_items(req_no: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM physical_checks WHERE req_no = ?", (req_no,))
    phys_map = {r["item_key"]: dict(r) for r in cur.fetchall()}

    cur.execute("SELECT * FROM requisition_items WHERE req_no = ? ORDER BY id ASC", (req_no,))
    items = [_enrich_item_row(dict(r), phys_map) for r in cur.fetchall()]
    conn.close()
    return items

def get_requisition_by_no(req_no: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM requisitions WHERE req_no = ?", (req_no,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    req = dict(row)
    cur.execute("SELECT * FROM physical_checks WHERE req_no = ?", (req_no,))
    phys_map = {r["item_key"]: dict(r) for r in cur.fetchall()}

    cur.execute("SELECT * FROM requisition_items WHERE req_no = ? ORDER BY id ASC", (req_no,))
    req["items"] = [_enrich_item_row(dict(item), phys_map) for item in cur.fetchall()]
    conn.close()
    return req

def get_all_items(
    entry_by: Optional[str] = None,
    req_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    fdate: Optional[str] = None,
    tdate: Optional[str] = None,
    page: int = 1,
    page_size: int = 50
) -> Dict[str, Any]:
    conn = get_connection()
    query = """
        SELECT i.*,
               r.req_date, r.manual_req_no, r.req_from, r.req_type, r.entry_by, r.status as req_status
        FROM requisition_items i
        JOIN requisitions r ON i.req_no = r.req_no
        WHERE 1=1
    """
    params = []

    if entry_by and entry_by.strip():
        query += " AND r.entry_by = ?"
        params.append(entry_by.strip())

    if req_type and req_type.strip():
        query += " AND r.req_type = ?"
        params.append(req_type.strip())

    if status and status.strip():
        query += " AND r.status = ?"
        params.append(status.strip())

    if fdate and fdate.strip():
        query += " AND r.req_date >= ?"
        params.append(fdate.strip())

    if tdate and tdate.strip():
        query += " AND r.req_date <= ?"
        params.append(tdate.strip())

    if search and search.strip():
        term = f"%{search.strip()}%"
        query += """ AND (
            i.item_code LIKE ? OR
            i.product_name LIKE ? OR
            i.item_desc LIKE ? OR
            i.req_no LIKE ? OR
            r.manual_req_no LIKE ? OR
            r.req_from LIKE ?
        )"""
        params.extend([term, term, term, term, term, term])

    query += " ORDER BY r.req_date DESC, i.req_no DESC, i.id ASC"

    count_query = f"SELECT COUNT(*) FROM ({query})"
    cur = conn.cursor()
    cur.execute(count_query, params)
    total_count = cur.fetchone()[0]

    offset = (page - 1) * page_size
    query += " LIMIT ? OFFSET ?"
    params.extend([page_size, offset])

    cur.execute(query, params)
    raw_rows = [dict(row) for row in cur.fetchall()]

    cur.execute("SELECT * FROM physical_checks")
    phys_map = {r["item_key"]: dict(r) for r in cur.fetchall()}
    conn.close()

    rows = [_enrich_item_row(r, phys_map) for r in raw_rows]
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

    return {
        "items": rows,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

def get_filter_options() -> Dict[str, List[str]]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT entry_by FROM requisitions WHERE entry_by IS NOT NULL AND entry_by != '' ORDER BY entry_by ASC")
    entry_by_list = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT DISTINCT req_type FROM requisitions WHERE req_type IS NOT NULL AND req_type != '' ORDER BY req_type ASC")
    type_list = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT DISTINCT status FROM requisitions WHERE status IS NOT NULL AND status != '' ORDER BY status ASC")
    status_list = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT DISTINCT req_from FROM requisitions WHERE req_from IS NOT NULL AND req_from != '' ORDER BY req_from ASC")
    from_list = [r[0] for r in cur.fetchall()]

    conn.close()
    return {
        "entry_by": entry_by_list,
        "types": type_list,
        "statuses": status_list,
        "sections": from_list
    }

def get_stats() -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM requisitions")
    total_requisitions = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM requisitions WHERE req_type = 'Spare Parts'")
    spare_parts_requisitions = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM requisition_items")
    total_items = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(req_qty), 0), COALESCE(SUM(app_qty), 0) FROM requisition_items")
    sum_row = cur.fetchone()
    total_req_qty = round(sum_row[0], 2)
    total_app_qty = round(sum_row[1], 2)

    cur.execute("SELECT COUNT(*) FROM requisitions WHERE details_synced = 1")
    synced_details_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM physical_checks WHERE physical_received = 1")
    physical_received_count = cur.fetchone()[0]

    cur.execute("SELECT status, COUNT(*) FROM requisitions GROUP BY status")
    status_counts = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute("SELECT req_type, COUNT(*) FROM requisitions GROUP BY req_type")
    type_counts = {r[0]: r[1] for r in cur.fetchall()}

    conn.close()
    return {
        "total_requisitions": total_requisitions,
        "spare_parts_requisitions": spare_parts_requisitions,
        "total_items": total_items,
        "total_req_qty": total_req_qty,
        "total_app_qty": total_app_qty,
        "synced_details_count": synced_details_count,
        "physical_received_count": physical_received_count,
        "status_counts": status_counts,
        "type_counts": type_counts
    }

def push_all_to_firebase():
    """Syncs the entire local SQLite database to Firebase Realtime Database."""
    reqs = get_requisitions(page=1, page_size=10000)["items"]
    items = get_all_items(page=1, page_size=50000)["items"]
    phys = get_all_physical_checks()
    stats = get_stats()
    filters = get_filter_options()
    sync_full_database_snapshot_to_firebase(reqs, items, phys, stats, filters)

def update_sync_meta(status: str, total_reqs: int = 0, synced_reqs: int = 0, current_step: str = "", error_message: str = ""):
    conn = get_connection()
    with conn:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if status == "idle":
            conn.execute("""
                UPDATE sync_meta SET
                    status = ?, total_reqs = ?, synced_reqs = ?,
                    current_step = ?, last_synced_at = ?, error_message = ?
                WHERE id = 1
            """, (status, total_reqs, synced_reqs, current_step, now_str, error_message))
        else:
            conn.execute("""
                UPDATE sync_meta SET
                    status = ?, total_reqs = ?, synced_reqs = ?,
                    current_step = ?, error_message = ?
                WHERE id = 1
            """, (status, total_reqs, synced_reqs, current_step, error_message))
    conn.close()
    if status == "idle":
        push_all_to_firebase()

def get_sync_meta() -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sync_meta WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"status": "idle", "total_reqs": 0, "synced_reqs": 0, "current_step": "Ready", "last_synced_at": None, "error_message": ""}
