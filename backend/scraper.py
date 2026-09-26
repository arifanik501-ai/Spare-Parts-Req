import logging
import queue
import time
import concurrent.futures
from typing import List, Dict, Any, Optional, Callable
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from backend.config import (
    ERP_BASE_URL,
    ERP_DB,
    ERP_CID,
    ERP_UID,
    ERP_PASS
)

logger = logging.getLogger(__name__)

def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    })
    return session

class ERPScraper:
    def __init__(self, pool_size: int = 12):
        self.pool_size = pool_size
        self.primary_session = create_session()
        self.is_logged_in = False
        self.session_pool = queue.Queue()
        self._pool_initialized = False

    def _login_session(self, session: requests.Session) -> bool:
        login_url = urljoin(ERP_BASE_URL, "login/pages/main/index.php")
        payload = {
            "db": ERP_DB,
            "cid": ERP_CID,
            "uid": ERP_UID,
            "ibssignin": "",
            "pass": ERP_PASS,
            "submit": "Log in"
        }
        try:
            resp = session.post(login_url, data=payload, timeout=20, allow_redirects=True)
            if resp.status_code == 200 and "PHPSESSID" in session.cookies:
                if "An account with this email address" in resp.text and "home.php" not in resp.url:
                    return False
                return True
            return False
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    def login(self) -> bool:
        success = self._login_session(self.primary_session)
        self.is_logged_in = success
        return success

    def ensure_login(self) -> bool:
        if not self.is_logged_in or "PHPSESSID" not in self.primary_session.cookies:
            return self.login()
        return True

    def init_pool(self):
        """Initializes a pool of 12 separate authenticated sessions for concurrent scraping."""
        if self._pool_initialized and self.session_pool.qsize() >= self.pool_size:
            return

        needed = self.pool_size - self.session_pool.qsize()
        if needed <= 0:
            self._pool_initialized = True
            return

        def make_auth_session():
            s = create_session()
            if self._login_session(s):
                return s
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=needed) as executor:
            futures = [executor.submit(make_auth_session) for _ in range(needed)]
            for f in concurrent.futures.as_completed(futures):
                s = f.result()
                if s:
                    self.session_pool.put(s)

        self._pool_initialized = True
        logger.info(f"Initialized scraper session pool with {self.session_pool.qsize()} active sessions.")

    def fetch_requisitions_list(
        self,
        fdate: Optional[str] = None,
        tdate: Optional[str] = None,
        req_for: str = "",
        status: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Submits the form to mr_status.php and parses all requisitions in ~1-2 seconds.
        """
        if not self.ensure_login():
            raise RuntimeError("Failed to log in to MEP ERP")

        mr_status_url = urljoin(ERP_BASE_URL, "production_mod/pages/mr/mr_status.php")
        payload = {
            "fdate": fdate or "",
            "tdate": tdate or "",
            "req_for": req_for or "",
            "status": status or "",
            "submitit": "VIEW DETAIL"
        }

        try:
            resp = self.primary_session.post(mr_status_url, data=payload, timeout=30)
            if "login/pages/main" in resp.url:
                self.login()
                resp = self.primary_session.post(mr_status_url, data=payload, timeout=30)

            soup = BeautifulSoup(resp.text, "html.parser")
            requisitions = []
            received_req_nos = []
            for tr in soup.find_all("tr"):
                tds = [td.get_text(strip=True) for td in tr.find_all("td")]
                if tds and len(tds) >= 11 and tds[0].isdigit():
                    req_no = tds[0]
                    req_type = tds[6] if len(tds) > 6 else ""
                    row_status = tds[10] if len(tds) > 10 else ""

                    # Skip DSTR requisitions
                    if req_type.strip().upper() == "DSTR":
                        continue

                    # Skip RECEIVED requisitions (and track to remove if previously pending in DB)
                    if row_status.strip().upper() == "RECEIVED":
                        received_req_nos.append(req_no)
                        continue

                    requisitions.append({
                        "req_no": req_no,
                        "manual_req_no": tds[1] if len(tds) > 1 else "",
                        "req_date": tds[2] if len(tds) > 2 else "",
                        "req_for": tds[3] if len(tds) > 3 else "",
                        "req_from": tds[4] if len(tds) > 4 else "",
                        "warehouse": tds[5] if len(tds) > 5 else "",
                        "req_type": req_type,
                        "need_by": tds[7] if len(tds) > 7 else "",
                        "entry_by": tds[8] if len(tds) > 8 else "",
                        "entry_at": tds[9] if len(tds) > 9 else "",
                        "status": row_status
                    })

            if received_req_nos:
                from backend.database import delete_requisitions_by_nos
                delete_requisitions_by_nos(received_req_nos)

            logger.info(f"Fetched {len(requisitions)} active (non-DSTR, non-RECEIVED) requisitions from ERP")
            return requisitions
        except Exception as e:
            logger.error(f"Error fetching requisitions list: {e}")
            raise

    def parse_items_from_html(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        items_table = None
        for t in tables:
            txt = t.get_text()
            if "Item Code" in txt and ("App. Qty" in txt or "Req. Qty" in txt):
                items_table = t
                break

        if not items_table and len(tables) >= 3:
            items_table = tables[2]

        items = []
        if items_table:
            for row in items_table.find_all("tr"):
                cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if not cols or cols[0] == "SL." or "Item Code" in cols:
                    continue

                if len(cols) >= 7:
                    items.append({
                        "sl": cols[0],
                        "item_code": cols[1] if len(cols) > 1 else "",
                        "product_name": cols[2] if len(cols) > 2 else "",
                        "item_desc": cols[3] if len(cols) > 3 else "",
                        "cwh": cols[4] if len(cols) > 4 else "0",
                        "req_qty": cols[5] if len(cols) > 5 else "0",
                        "app_qty": cols[6] if len(cols) > 6 else "0",
                        "unit": cols[7] if len(cols) > 7 else "",
                        "delivery_date": cols[8] if len(cols) > 8 else "",
                        "remarks": cols[9] if len(cols) > 9 else ""
                    })
        return items

    def fetch_requisition_details(self, req_no: str) -> List[Dict[str, Any]]:
        """Single on-demand fetch using primary session."""
        if not self.ensure_login():
            raise RuntimeError("Failed to log in to MEP ERP")

        detail_url = urljoin(ERP_BASE_URL, f"production_mod/pages/mr/mr_print_view.php?req_no={req_no}")
        try:
            resp = self.primary_session.get(detail_url, timeout=20)
            if "login/pages/main" in resp.url:
                self.login()
                resp = self.primary_session.get(detail_url, timeout=20)
            return self.parse_items_from_html(resp.text)
        except Exception as e:
            logger.error(f"Error fetching detail for req #{req_no}: {e}")
            return []

    def fetch_requisitions_details_batch(
        self,
        req_nos: List[str],
        on_item_fetched: Optional[Callable[[str, List[Dict[str, Any]], int, int], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        High-speed parallel item detail scraping using a pre-authenticated session pool.
        """
        if not req_nos:
            return {}

        self.init_pool()
        total = len(req_nos)
        completed = 0
        results = {}

        def worker_fetch(req_no: str):
            sess = None
            try:
                sess = self.session_pool.get(timeout=30)
                url = urljoin(ERP_BASE_URL, f"production_mod/pages/mr/mr_print_view.php?req_no={req_no}")
                resp = sess.get(url, timeout=20)
                if "login/pages/main" in resp.url:
                    self._login_session(sess)
                    resp = sess.get(url, timeout=20)
                return req_no, self.parse_items_from_html(resp.text)
            except Exception as e:
                logger.warning(f"Error fetching #{req_no} in pool: {e}")
                return req_no, []
            finally:
                if sess:
                    self.session_pool.put(sess)

        # Concurrently process requisitions
        max_workers = min(self.pool_size, len(req_nos))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_req = {executor.submit(worker_fetch, r): r for r in req_nos}

            for future in concurrent.futures.as_completed(future_to_req):
                if is_cancelled and is_cancelled():
                    # Cancel remaining futures
                    for f in future_to_req:
                        f.cancel()
                    break

                req_no, items = future.result()
                results[req_no] = items
                completed += 1

                if on_item_fetched:
                    try:
                        on_item_fetched(req_no, items, completed, total)
                    except Exception as e:
                        logger.error(f"Error in on_item_fetched callback: {e}")

        return results
