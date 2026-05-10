import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse

from database.db import init_db, get_claims_since
from scheduler.jobs import (
    start_scheduler, stop_scheduler,
    job_fetch_and_verify, scheduler,
)
from notifications.telegram import send_startup_message
from notifications.bot_commands import start_bot_polling, stop_bot_polling
from dashboard.web import DASHBOARD_HTML
from verification.sentiment import get_ticker_sentiment

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    from ingestors.manager import manager

    logger.info("🚀 Daily News Agent starting up...")
    init_db()
    
    # Start async ingestion workers
    await manager.start()
    
    # Start cron jobs
    start_scheduler()
    
    start_bot_polling()
    send_startup_message()
    
    yield
    
    stop_bot_polling()
    stop_scheduler()
    
    # Shutdown ingestion workers gracefully
    await manager.shutdown()
    
    logger.info("👋 Daily News Agent shutting down.")


# ── App ──
app = FastAPI(
    title="Daily News Agent",
    description="AI-powered news aggregation, verification, and delivery",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the web dashboard."""
    return DASHBOARD_HTML


@app.get("/health")
def health_check():
    """Health check — keeps Render alive."""
    return {"status": "running", "timestamp": datetime.utcnow().isoformat()}


@app.get("/status")
def get_status():
    """Current agent status with stats."""
    today_claims = get_claims_since(hours=24)
    verified = [c for c in today_claims if c.get("confidence", 0) >= 80]

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        })

    return {
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "today": {
            "total_articles": len(today_claims),
            "verified": len(verified),
            "categories": list(set(c.get("category", "") for c in today_claims)),
        },
        "scheduled_jobs": jobs,
    }


@app.post("/trigger")
async def trigger_manual():
    """Manually trigger a news fetch + verification cycle."""
    try:
        await job_fetch_and_verify()
        return {"message": "Fetch and verify triggered successfully"}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@app.get("/claims")
def get_recent_claims(hours: int = 24, limit: int = 20):
    """Get recent claims."""
    claims = get_claims_since(hours=hours)
    claims.sort(key=lambda c: c.get("confidence", 0), reverse=True)
    return {"claims": claims[:limit], "total": len(claims)}


@app.get("/sentiment")
def sentiment_endpoint(hours: int = 168):
    """Get ticker sentiment analysis."""
    data = get_ticker_sentiment(hours=hours)
    return {"tickers": data}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
