import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import FETCH_INTERVAL_MINUTES
from app.ingest import run_fetch

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job() -> None:
    logger.info("Running scheduled SCOTUS fetch")
    result = run_fetch()
    logger.info("Scheduled fetch finished: %s", result)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _job,
        "interval",
        minutes=FETCH_INTERVAL_MINUTES,
        id="scotus_fetch",
        next_run_time=None,  # first run is triggered explicitly at startup if configured
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
