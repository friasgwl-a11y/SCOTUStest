import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.routes import router as api_router
from app.config import FETCH_ON_STARTUP
from app.db import init_db
from app.ingest import run_fetch
from app.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    if FETCH_ON_STARTUP:
        # Run the first fetch in the background so the server starts
        # responding immediately even on a cold, empty database.
        threading.Thread(target=run_fetch, daemon=True).start()
    yield
    shutdown_scheduler()


app = FastAPI(title="SCOTUS Tracker", lifespan=lifespan)
app.include_router(api_router)


@app.get("/app.js")
def app_js():
    return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")


@app.get("/styles.css")
def styles_css():
    return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    # The dashboard is a single-page app with client-side routing (History
    # API) for Home/Opinions/Orders/case-detail "pages", so every
    # non-API, non-asset path serves the same shell -- app.js reads
    # location.pathname and renders the right view. This is what makes a
    # direct link to (or refresh of) e.g. /opinions/123 work instead of
    # 404ing, and what makes the browser back/forward buttons behave like
    # real navigation.
    return FileResponse(STATIC_DIR / "index.html")
