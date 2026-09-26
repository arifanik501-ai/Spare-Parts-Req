import os
import io
import csv
from typing import Optional
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from backend.config import BASE_DIR
from backend.database import (
    init_db,
    get_requisitions,
    get_requisition_by_no,
    get_requisition_items,
    get_all_items,
    get_filter_options,
    get_stats,
    save_physical_check,
    get_all_physical_checks,
    push_all_to_firebase
)
from backend.sync_manager import sync_manager

app = FastAPI(title="MEP Daily Floor Requisition Portal", version="2.0.0")

# Initialize database tables and sync snapshot to Firebase on startup
@app.on_event("startup")
def on_startup():
    init_db()
    push_all_to_firebase()

# Serve static files from frontend
frontend_dir = BASE_DIR / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

@app.get("/")
def serve_index():
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Frontend not found"}

class SyncRequest(BaseModel):
    fdate: Optional[str] = None
    tdate: Optional[str] = None
    sync_details: bool = True

class PhysicalCheckRequest(BaseModel):
    item_key: str
    req_no: str
    item_code: str = ""
    sl: str = "1"
    physical_received: int = 0
    physical_rec_qty: float = 0.0

@app.get("/api/stats")
def api_stats():
    return get_stats()

@app.get("/api/filters")
def api_filters():
    return get_filter_options()

@app.get("/api/requisitions")
def api_requisitions(
    entry_by: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    fdate: Optional[str] = Query(None),
    tdate: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200)
):
    return get_requisitions(
        entry_by=entry_by,
        req_type=type,
        status=status,
        search=search,
        fdate=fdate,
        tdate=tdate,
        page=page,
        page_size=page_size
    )

@app.get("/api/requisitions/{req_no}")
def api_single_requisition(req_no: str, auto_fetch: bool = True):
    req = get_requisition_by_no(req_no)
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found")

    if (not req.get("items") or len(req["items"]) == 0) and req.get("details_synced") != 1 and auto_fetch:
        success, items = sync_manager.sync_single_requisition(req_no)
        if success:
            req = get_requisition_by_no(req_no)

    return req

@app.get("/api/items")
def api_items(
    entry_by: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    fdate: Optional[str] = Query(None),
    tdate: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500)
):
    return get_all_items(
        entry_by=entry_by,
        req_type=type,
        status=status,
        search=search,
        fdate=fdate,
        tdate=tdate,
        page=page,
        page_size=page_size
    )

@app.post("/api/physical-check")
def api_save_physical_check(payload: PhysicalCheckRequest):
    saved = save_physical_check(
        item_key=payload.item_key,
        req_no=payload.req_no,
        item_code=payload.item_code,
        sl=payload.sl,
        physical_received=payload.physical_received,
        physical_rec_qty=payload.physical_rec_qty
    )
    return {"success": True, "data": saved}

@app.get("/api/physical-checks")
def api_get_physical_checks():
    return get_all_physical_checks()

@app.post("/api/sync")
def api_start_sync(req: SyncRequest):
    started, msg = sync_manager.start_sync(
        fdate=req.fdate,
        tdate=req.tdate,
        sync_details=req.sync_details
    )
    if not started:
        return JSONResponse(status_code=400, content={"success": False, "message": msg})
    return {"success": True, "message": msg}

@app.post("/api/sync/stop")
def api_stop_sync():
    stopped, msg = sync_manager.stop_sync()
    return {"success": stopped, "message": msg}

@app.get("/api/sync/status")
def api_sync_status():
    meta = sync_manager.get_status()
    total = meta.get("total_reqs", 0)
    synced = meta.get("synced_reqs", 0)
    pct = round((synced / total * 100), 1) if total > 0 else 0
    return {
        "status": meta.get("status", "idle"),
        "total_reqs": total,
        "synced_reqs": synced,
        "percentage": pct,
        "current_step": meta.get("current_step", ""),
        "last_synced_at": meta.get("last_synced_at"),
        "error_message": meta.get("error_message", "")
    }

@app.post("/api/requisitions/{req_no}/sync")
def api_sync_single(req_no: str):
    success, items = sync_manager.sync_single_requisition(req_no)
    return {"success": success, "items_count": len(items)}

@app.get("/api/export")
def api_export_csv(
    mode: str = Query("items", pattern="^(items|requisitions)$"),
    entry_by: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    fdate: Optional[str] = Query(None),
    tdate: Optional[str] = Query(None)
):
    output = io.StringIO()
    writer = csv.writer(output)

    if mode == "items":
        data = get_all_items(
            entry_by=entry_by,
            req_type=type,
            status=status,
            search=search,
            fdate=fdate,
            tdate=tdate,
            page=1,
            page_size=50000
        )
        writer.writerow([
            "Req No", "Manual Req No", "Req Date", "Req From", "Type",
            "Entry By", "Item Code", "Product Name", "Item Description",
            "Req. Qty", "App. Qty (Apply Qty)", "Unit", "Delivery Date", "Status",
            "Physical Receive", "Physical Receive Qty", "Physical Pending"
        ])
        for it in data["items"]:
            writer.writerow([
                it.get("req_no", ""),
                it.get("manual_req_no", ""),
                it.get("req_date", ""),
                it.get("req_from", ""),
                it.get("req_type", ""),
                it.get("entry_by", ""),
                it.get("item_code", ""),
                it.get("product_name", ""),
                it.get("item_desc", ""),
                it.get("req_qty", 0),
                it.get("app_qty", 0),
                it.get("unit", ""),
                it.get("delivery_date", ""),
                it.get("req_status", ""),
                "YES" if it.get("physical_received") else "NO",
                it.get("physical_rec_qty", 0),
                it.get("physical_pending", 0)
            ])
        filename = f"mep_floor_requisitions_items_{fdate or 'all'}.csv"
    else:
        data = get_requisitions(
            entry_by=entry_by,
            req_type=type,
            status=status,
            search=search,
            fdate=fdate,
            tdate=tdate,
            page=1,
            page_size=50000
        )
        writer.writerow([
            "Req No", "Manual Req No", "Req Date", "Req For", "Req From",
            "Warehouse", "Type", "Need By", "Entry By", "Entry At",
            "Status", "Item Count", "Total Req Qty", "Total App Qty"
        ])
        for r in data["items"]:
            writer.writerow([
                r.get("req_no", ""),
                r.get("manual_req_no", ""),
                r.get("req_date", ""),
                r.get("req_for", ""),
                r.get("req_from", ""),
                r.get("warehouse", ""),
                r.get("req_type", ""),
                r.get("need_by", ""),
                r.get("entry_by", ""),
                r.get("entry_at", ""),
                r.get("status", ""),
                r.get("item_count", 0),
                r.get("total_req_qty", 0),
                r.get("total_app_qty", 0)
            ])
        filename = f"mep_floor_requisitions_summary_{fdate or 'all'}.csv"

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
