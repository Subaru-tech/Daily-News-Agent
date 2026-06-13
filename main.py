import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse

from database.db import init_db, get_claims_since, get_recent_metrics
from scheduler.jobs import (
    start_scheduler, stop_scheduler,
    job_fetch_and_verify, scheduler,
)
from notifications.telegram import send_startup_message
from notifications.bot_commands import start_bot_polling, stop_bot_polling
from verification.sentiment import get_ticker_sentiment
import sqlite3
import os
from fastapi.staticfiles import StaticFiles

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

# Serve React App
web_dist_path = os.path.join(os.path.dirname(__file__), "web", "dist")
if os.path.isdir(web_dist_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(web_dist_path, "assets")), name="assets")
    
    @app.get("/", response_class=HTMLResponse)
    def serve_react_app():
        with open(os.path.join(web_dist_path, "index.html"), "r") as f:
            return f.read()
else:
    @app.get("/", response_class=HTMLResponse)
    def dashboard_fallback():
        return "<h1>React dashboard not built yet. Run `npm run build` in web directory.</h1>"


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


@app.get("/metrics")
def get_metrics():
    """Return recent system metrics."""
    metrics = get_recent_metrics(hours=48)
    return {"metrics": metrics}


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

@app.get("/api/sources/credibility")
def get_credibility():
    """Get all source credibility scores."""
    try:
        from database.db import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM source_credibility ORDER BY credibility_score DESC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to fetch credibility: {e}")
        return []

@app.get("/api/sources/health")
def get_health_status():
    """Get all source health records."""
    try:
        from database.db import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM source_health ORDER BY consecutive_failures DESC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to fetch health status: {e}")
        return []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
