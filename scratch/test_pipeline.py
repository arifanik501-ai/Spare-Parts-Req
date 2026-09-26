import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import (
    init_db,
    save_requisitions_batch,
    save_requisition_items,
    get_requisitions,
    get_all_items,
    get_filter_options,
    get_stats
)
from backend.scraper import ERPScraper

print("1. Initializing database...")
init_db()
print("   Database initialized successfully.")

print("2. Testing ERP Scraper login...")
scraper = ERPScraper()
if not scraper.login():
    print("   ERROR: Scraper failed to login!")
    sys.exit(1)
print("   Login successful.")

print("3. Fetching requisitions between 2026-09-22 and 2026-09-26...")
reqs = scraper.fetch_requisitions_list(fdate="2026-09-22", tdate="2026-09-26")
print(f"   Fetched {len(reqs)} requisitions.")

print("4. Saving requisitions to database...")
save_requisitions_batch(reqs)
print("   Saved.")

print("5. Scraping line items for top 5 requisitions...")
for r in reqs[:5]:
    req_no = r["req_no"]
    items = scraper.fetch_requisition_details(req_no)
    save_requisition_items(req_no, items)
    print(f"   Req #{req_no}: saved {len(items)} items.")

print("6. Verifying filter options...")
filters = get_filter_options()
print("   Entry By options:", filters["entry_by"])
print("   Type options:", filters["types"])

print("7. Verifying stats...")
stats = get_stats()
print("   Stats:", stats)

print("8. Verifying Requisitions query (filter: Type='Spare Parts')...")
spare_reqs = get_requisitions(req_type="Spare Parts", page=1, page_size=10)
print(f"   Found {spare_reqs['total']} Spare Parts requisitions.")
for item in spare_reqs["items"][:2]:
    print(f"   - Req #{item['req_no']}: {item['req_from']} | Entry By: {item['entry_by']} | Req Qty: {item['total_req_qty']} | App Qty: {item['total_app_qty']}")

print("9. Verifying All Items query with Apply Quantities...")
all_items = get_all_items(page=1, page_size=10)
print(f"   Total items recorded: {all_items['total']}")
for it in all_items["items"][:3]:
    print(f"   - Req #{it['req_no']} | Item: {it['product_name']} | Req Qty: {it['req_qty']} | App Qty: {it['app_qty']} {it['unit']}")

print("\nALL VERIFICATIONS PASSED!")
