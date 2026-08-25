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

# How often (hours) to re-fetch term-level data: the current-term label,
# the Granted & Noted List, and the argument calendars. This changes far
# less often than the opinions/orders listings, so it's cached aggressively
# and re-fetched only when stale.
TERM_DATA_REFRESH_HOURS = float(os.getenv("SCOTUS_TERM_DATA_REFRESH_HOURS", "12"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

MAX_SUMMARY_SENTENCES = int(os.getenv("SCOTUS_SUMMARY_SENTENCES", "5"))

# How many PDFs to download+process per fetch run, per document type. Kept
# small so a run finishes well within the resources of a small/free hosting
# tier; the scheduler drains any backlog over subsequent runs.
DOCUMENT_LIMIT = int(os.getenv("SCOTUS_DOCUMENT_LIMIT", "4"))

# Only documents released within this many days are summarized automatically
# in the background. Everything older is summarized on demand, the first
# time someone actually opens it. Set to 0 to disable background
# summarization entirely (fully lazy).
AUTO_PROCESS_DAYS = int(os.getenv("SCOTUS_AUTO_PROCESS_DAYS", "1"))

# Pages read per PDF. Slip opinions put the syllabus and holding up front;
# the tail is separate opinions and appendices, which cost memory without
# improving the summary.
MAX_PDF_PAGES = int(os.getenv("SCOTUS_MAX_PDF_PAGES", "20"))

# Upper bound on extracted text kept per document.
MAX_STORED_TEXT_CHARS = int(os.getenv("SCOTUS_MAX_STORED_TEXT_CHARS", "120000"))
