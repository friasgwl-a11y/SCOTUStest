import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

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

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
