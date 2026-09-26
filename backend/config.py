import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Database configuration
DATABASE_FILE = os.environ.get("DATABASE_FILE", str(BASE_DIR / "spare_parts.db"))

# MEP ERP Configuration
ERP_BASE_URL = os.environ.get("ERP_BASE_URL", "https://mepgrouperp.com/1027/")
ERP_DB = os.environ.get("ERP_DB", "erpcombd")
ERP_CID = os.environ.get("ERP_CID", "mep")
ERP_UID = os.environ.get("ERP_UID", "15387")
ERP_PASS = os.environ.get("ERP_PASS", "anikanik556")

# Server Configuration
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8000"))
