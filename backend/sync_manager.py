import threading
import time
import logging
from typing import Optional
from backend.scraper import ERPScraper
from backend.database import (
    save_requisitions_batch,
    save_requisition_items,
    update_sync_meta,
    get_sync_meta,
    get_connection
)

logger = logging.getLogger(__name__)

class SyncManager:
    def __init__(self):
        self.scraper = ERPScraper(pool_size=12)
        self.sync_thread: Optional[threading.Thread] = None
        self.stop_requested = False
        self._lock = threading.Lock()

    def get_status(self):
        return get_sync_meta()

    def start_sync(self, fdate: Optional[str] = None, tdate: Optional[str] = None, sync_details: bool = True):
        with self._lock:
            meta = get_sync_meta()
            if meta.get("status") == "syncing":
                return False, "A sync process is already running."

            self.stop_requested = False
            self.sync_thread = threading.Thread(
                target=self._run_sync,
                args=(fdate, tdate, sync_details),
                daemon=True
            )
            self.sync_thread.start()
            return True, "Sync started successfully."

    def stop_sync(self):
        self.stop_requested = True
        update_sync_meta(status="idle", current_step="Sync cancelled by user.")
        return True, "Sync stop requested."

    def _run_sync(self, fdate: Optional[str], tdate: Optional[str], sync_details: bool):
        try:
            update_sync_meta(status="syncing", total_reqs=0, synced_reqs=0, current_step="Connecting to MEP ERP...", error_message="")

            # Step 1: Login
            if not self.scraper.ensure_login():
                update_sync_meta(status="idle", error_message="Failed to log in to MEP ERP. Check credentials.")
                return

            # Step 2: Fetch requisition list (Ultra-fast 1-2s)
            step_msg = f"Fetching requisitions list ({fdate or 'Recent'} to {tdate or 'Today'})..."
            update_sync_meta(status="syncing", current_step=step_msg)

            req_list = self.scraper.fetch_requisitions_list(fdate=fdate, tdate=tdate)
            total = len(req_list)

            if total == 0:
                update_sync_meta(status="idle", total_reqs=0, synced_reqs=0, current_step="No requisitions found for selected criteria.")
                return

            # Instantly save requisitions list so UI can display them immediately!
            update_sync_meta(status="syncing", total_reqs=total, synced_reqs=0, current_step=f"Loaded {total} requisitions. Saving to local database...")
            save_requisitions_batch(req_list)

            # Step 3: If sync_details is True, fetch latest Req. Qty & App. Qty in parallel
            if sync_details:
                conn = get_connection()
                cur = conn.cursor()
                if fdate or tdate:
                    # For a specific date range sync, ALWAYS refresh all requisitions in that range
                    # PLUS any recent requisitions that still have App. Qty = 0 or Pending status
                    req_nos = [r["req_no"] for r in req_list]
                    placeholders = ",".join(["?"] * len(req_nos))
                    cur.execute(f"""
                        SELECT r.req_no
                        FROM requisitions r
                        LEFT JOIN requisition_items i ON r.req_no = i.req_no
                        WHERE r.req_no IN ({placeholders})
                           OR r.details_synced = 0
                           OR UPPER(TRIM(r.status)) NOT IN ('RECEIVED', 'COMPLETE', 'COMPLETED')
                        GROUP BY r.req_no
                        ORDER BY r.req_date DESC, r.req_no DESC
                    """, req_nos)
                else:
                    cur.execute("""
                        SELECT r.req_no
                        FROM requisitions r
                        LEFT JOIN requisition_items i ON r.req_no = i.req_no
                        GROUP BY r.req_no
                        HAVING r.details_synced = 0
                            OR UPPER(TRIM(r.status)) NOT IN ('RECEIVED', 'COMPLETE', 'COMPLETED')
                            OR COALESCE(SUM(i.app_qty), 0) = 0
                        ORDER BY r.req_date DESC, r.req_no DESC
                        LIMIT 500
                    """)

                pending_req_nos = [r[0] for r in cur.fetchall()]
                conn.close()

                total_items_to_sync = len(pending_req_nos)

                if total_items_to_sync > 0:
                    update_sync_meta(
                        status="syncing",
                        total_reqs=total_items_to_sync,
                        synced_reqs=0,
                        current_step=f"Updating Req. Qty & App. Qty for {total_items_to_sync} requisitions..."
                    )

                    def on_item_saved(req_no, items, completed, total_count):
                        save_requisition_items(req_no, items)
                        update_sync_meta(
                            status="syncing",
                            total_reqs=total_count,
                            synced_reqs=completed,
                            current_step=f"Updated #{req_no} ({completed}/{total_count})..."
                        )

                    # High-speed parallel scraping
                    self.scraper.fetch_requisitions_details_batch(
                        req_nos=pending_req_nos,
                        on_item_fetched=on_item_saved,
                        is_cancelled=lambda: self.stop_requested
                    )

            update_sync_meta(status="idle", total_reqs=total, synced_reqs=total, current_step="Sync completed successfully!")
            logger.info("Sync finished successfully")

        except Exception as e:
            logger.exception(f"Sync failed: {e}")
            update_sync_meta(status="idle", current_step="Sync error occurred", error_message=str(e))

    def sync_single_requisition(self, req_no: str):
        """Fetches and saves details for a single requisition synchronously."""
        try:
            items = self.scraper.fetch_requisition_details(req_no)
            save_requisition_items(req_no, items)
            return True, items
        except Exception as e:
            logger.error(f"Error in on-demand sync for {req_no}: {e}")
            return False, []

# Global sync manager instance
sync_manager = SyncManager()
