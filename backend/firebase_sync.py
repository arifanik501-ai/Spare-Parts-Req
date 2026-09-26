import logging
import threading
import requests
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

FIREBASE_DB_URL = "https://whatsapp-c10ef-default-rtdb.firebaseio.com"

def _put_json_async(path: str, data: Any):
    def _worker():
        try:
            url = f"{FIREBASE_DB_URL}/{path}.json"
            requests.put(url, json=data, timeout=20)
        except Exception as e:
            logger.warning(f"Firebase PUT failed for {path}: {e}")
    threading.Thread(target=_worker, daemon=True).start()

def _patch_json_async(path: str, data: Any):
    def _worker():
        try:
            url = f"{FIREBASE_DB_URL}/{path}.json"
            requests.patch(url, json=data, timeout=20)
        except Exception as e:
            logger.warning(f"Firebase PATCH failed for {path}: {e}")
    threading.Thread(target=_worker, daemon=True).start()

def sync_requisitions_to_firebase(req_list: List[Dict[str, Any]]):
    """Instantly syncs a batch of requisitions to Firebase Realtime Database."""
    if not req_list:
        return
    payload = {}
    for r in req_list:
        req_no = str(r.get("req_no", "")).strip()
        if not req_no or not req_no.isdigit():
            continue
        if str(r.get("req_type", "")).strip().upper() == "DSTR":
            continue
        if str(r.get("status", "")).strip().upper() == "RECEIVED":
            continue
        payload[req_no] = r
    if payload:
        _patch_json_async("mep_erp/requisitions", payload)

def delete_requisitions_from_firebase(req_nos: List[str]):
    """Removes RECEIVED or deleted requisitions from Firebase."""
    if not req_nos:
        return
    payload = {str(r): None for r in req_nos if str(r).strip()}
    if payload:
        _patch_json_async("mep_erp/requisitions", payload)
        _patch_json_async("mep_erp/requisition_items", payload)

def sync_items_to_firebase(req_no: str, items: List[Dict[str, Any]]):
    """Instantly syncs a requisition's line items to Firebase Realtime Database."""
    if not req_no:
        return
    _put_json_async(f"mep_erp/requisition_items/{req_no}", items)

def sync_physical_check_to_firebase(item_key: str, data: Dict[str, Any]):
    """Instantly syncs physical receive check and quantity to Firebase."""
    if not item_key:
        return
    _put_json_async(f"mep_erp/physical_checks/{item_key}", data)

def sync_full_database_snapshot_to_firebase(all_reqs: List[Dict[str, Any]], all_items: List[Dict[str, Any]], physical_checks: Dict[str, Any], stats: Dict[str, Any], filters: Dict[str, Any]):
    """Pushes full snapshot of bot-collected data to Firebase for instant mobile/cloud access."""
    def _worker():
        try:
            reqs_map = {str(r["req_no"]): r for r in all_reqs if r.get("req_no")}
            items_by_req = {}
            flat_items_map = {}
            for it in all_items:
                rno = str(it.get("req_no", ""))
                if rno not in items_by_req:
                    items_by_req[rno] = []
                items_by_req[rno].append(it)
                ikey = it.get("item_key")
                if ikey:
                    flat_items_map[ikey] = it

            requests.put(f"{FIREBASE_DB_URL}/mep_erp/requisitions.json", json=reqs_map, timeout=30)
            requests.put(f"{FIREBASE_DB_URL}/mep_erp/requisition_items.json", json=items_by_req, timeout=30)
            requests.put(f"{FIREBASE_DB_URL}/mep_erp/flat_items.json", json=flat_items_map, timeout=30)
            requests.put(f"{FIREBASE_DB_URL}/mep_erp/stats.json", json=stats, timeout=15)
            requests.put(f"{FIREBASE_DB_URL}/mep_erp/filters.json", json=filters, timeout=15)
            if physical_checks:
                requests.patch(f"{FIREBASE_DB_URL}/mep_erp/physical_checks.json", json=physical_checks, timeout=15)
            logger.info("Full database snapshot synced to Firebase successfully.")
        except Exception as e:
            logger.warning(f"Failed full snapshot sync to Firebase: {e}")

    threading.Thread(target=_worker, daemon=True).start()
