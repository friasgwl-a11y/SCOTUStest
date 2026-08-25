import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SCOTUS_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("SCOTUS_DATABASE_URL", f"sqlite:///{DATA_DIR / 'scotus.db'}")

BASE_URL = "https://www.supremecourt.gov"
USER_AGENT = os.getenv(
    "SCOTUS_USER_AGENT",
    "SCOTUSDashboardBot/1.0 (+https://github.com/; contact via repo issues)",
)
REQUEST_TIMEOUT = int(os.getenv("SCOTUS_REQUEST_TIMEOUT", "30"))
REQUEST_DELAY_SECONDS = float(os.getenv("SCOTUS_REQUEST_DELAY_SECONDS", "1.0"))

# SCOTUS terms are named by the year they begin (e.g. "25" = October Term 2025).
# Fetch the current and previous term by default; override with a comma-separated
# list of two-digit term codes, e.g. SCOTUS_TERMS="25,24,23".
_default_terms = os.getenv("SCOTUS_TERMS", "25,24")
TERMS = [t.strip() for t in _default_terms.split(",") if t.strip()]

FETCH_INTERVAL_MINUTES = int(os.getenv("SCOTUS_FETCH_INTERVAL_MINUTES", "180"))
FETCH_ON_STARTUP = os.getenv("SCOTUS_FETCH_ON_STARTUP", "true").lower() != "false"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

MAX_SUMMARY_SENTENCES = int(os.getenv("SCOTUS_SUMMARY_SENTENCES", "5"))
