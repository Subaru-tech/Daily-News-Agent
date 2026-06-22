import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from typing import List, Optional

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
import pathlib
BASE_DIR = pathlib.Path(__file__).resolve().parent
web_dist_path = BASE_DIR / "web" / "dist"

logger.info(f"Looking for React dist at: {web_dist_path}")
if web_dist_path.is_dir():
    app.mount("/assets", StaticFiles(directory=str(web_dist_path / "assets")), name="assets")
    
    @app.get("/", response_class=HTMLResponse)
    def serve_react_app():
        with open(web_dist_path / "index.html", "r") as f:
            return f.read()
            
    # Catch-all for SPA routing (must be placed after all other routes)
    # We will register it at the very bottom of the file.
else:
    logger.warning(f"React dist NOT FOUND at {web_dist_path}! Directory contents: {list(BASE_DIR.glob('*'))}")
    @app.get("/", response_class=HTMLResponse)
    def dashboard_fallback():
        return f"<h1>React dashboard not built yet. Looking at {web_dist_path}</h1>"


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
        from database.db import get_connection
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM source_credibility ORDER BY credibility_score DESC")
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to fetch credibility: {e}")
        return []

@app.get("/api/sources/health")
def get_health_status():
    """Get all source health records."""
    try:
        from database.db import get_connection
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM source_health ORDER BY consecutive_failures DESC")
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to fetch health status: {e}")
        return []

class WebhookMessage(BaseModel):
    role: str
    content: str

class WebhookPayload(BaseModel):
    threadId: str
    messageId: str
    content: str
    history: List[WebhookMessage]
    timestamp: str

@app.head("/api/webhook")
def webhook_head():
    """Endpoint for Qubix connectivity checks."""
    return {"status": "online"}

@app.get("/api/webhook")
def webhook_get():
    """Endpoint for Qubix connectivity checks."""
    return {"status": "online"}

@app.post("/api/webhook")
async def webhook_post(payload: WebhookPayload):
    """
    Qubix Webhook interface.
    Handles user commands/queries about status, news, claims, credibility, health, metrics.
    If general, queries Groq API (Llama 3.3) grounded in the last 48 hours of news claims.
    """
    try:
        user_msg = payload.content.strip().lower()
        
        # 1. Check commands
        if user_msg == "status":
            from database.db import get_claims_since
            today_claims = get_claims_since(hours=24)
            verified = [c for c in today_claims if c.get("confidence", 0) >= 80]
            
            jobs = []
            try:
                for job in scheduler.get_jobs():
                    jobs.append(f"- `{job.id}`: next run at {job.next_run_time}")
            except Exception:
                pass
            jobs_str = "\n".join(jobs) if jobs else "None"
            
            msg = (
                "📊 **Daily News Agent Status**\n"
                "• **Status:** Running\n"
                f"• **Time (UTC):** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
                "• **Today's Stats (Last 24h):**\n"
                f"  - Total Ingested Articles: {len(today_claims)}\n"
                f"  - Verified Claims (>=80% Confidence): {len(verified)}\n"
                f"  - Active Categories: {', '.join(set(c.get('category', 'General') for c in today_claims)) if today_claims else 'None'}\n"
                "• **Scheduled Jobs:**\n"
                f"{jobs_str}"
            )
            return {"content": msg}
            
        elif user_msg in ("news", "claims"):
            from database.db import get_claims_since
            recent = get_claims_since(hours=24)
            recent.sort(key=lambda c: c.get("confidence", 0), reverse=True)
            
            if not recent:
                return {"content": "📰 No news claims have been ingested in the last 24 hours."}
                
            lines = ["📰 **Top News Claims (Last 24h):**"]
            for idx, c in enumerate(recent[:10], 1):
                title = c.get("title", "No Title")
                conf = c.get("confidence", 0)
                cat = c.get("category", "General")
                status = c.get("verification_status", "unverified")
                lines.append(f"{idx}. **[{cat}]** {title} (Confidence: **{conf}%**, Status: *{status}*)")
                
            return {"content": "\n".join(lines)}
            
        elif user_msg in ("credibility", "sources"):
            from database.db import get_connection
            conn = get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM source_credibility ORDER BY credibility_score DESC LIMIT 10")
                rows = cur.fetchall()
                if not rows:
                    return {"content": "🔍 No source credibility records found."}
                
                lines = ["🔍 **Top Source Credibility Scores:**", "| Source Domain | Total Articles | Verified | Debunked | Credibility Score |", "|---|---|---|---|---|"]
                for r in rows:
                    lines.append(f"| {r['source_domain']} | {r['total_articles']} | {r['verified_claims']} | {r['debunked_claims']} | {r['credibility_score']:.1f}% |")
                return {"content": "\n".join(lines)}
            except Exception as e:
                logger.error(f"Webhook credibility query failed: {e}")
                return {"content": f"❌ Error querying credibility scores: {str(e)}"}
            finally:
                conn.close()
                
        elif user_msg == "health":
            from database.db import get_connection
            conn = get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM source_health ORDER BY consecutive_failures DESC LIMIT 10")
                rows = cur.fetchall()
                if not rows:
                    return {"content": "🏥 No source health records found."}
                
                lines = ["🏥 **Source Ingestor Health (Failures/Status):**", "| Source ID | Consecutive Failures | Next Attempt (UTC) | Degraded? |", "|---|---|---|---|"]
                for r in rows:
                    is_deg = "Yes ⚠️" if r['is_degraded'] else "No ✅"
                    lines.append(f"| {r['source_id']} | {r['consecutive_failures']} | {r['next_attempt_at']} | {is_deg} |")
                return {"content": "\n".join(lines)}
            except Exception as e:
                logger.error(f"Webhook health query failed: {e}")
                return {"content": f"❌ Error querying source health: {str(e)}"}
            finally:
                conn.close()
                
        elif user_msg == "metrics":
            from database.db import get_recent_metrics
            metrics = get_recent_metrics(hours=48)
            if not metrics:
                return {"content": "📈 No system metrics logged in the last 48 hours."}
            
            stats = {}
            for m in metrics:
                etype = m.get("event_type", "unknown")
                latency = m.get("latency_ms", 0)
                cost = m.get("llm_cost", 0.0)
                if etype not in stats:
                    stats[etype] = {"count": 0, "total_latency": 0, "total_cost": 0.0}
                stats[etype]["count"] += 1
                stats[etype]["total_latency"] += latency
                stats[etype]["total_cost"] += cost
                
            lines = ["📈 **System Performance & Metrics (Last 48h):**", "| Event Type | Count | Avg Latency | Total LLM Cost |", "|---|---|---|---|"]
            for etype, data in stats.items():
                avg_lat = data["total_latency"] / data["count"]
                lines.append(f"| {etype} | {data['count']} | {avg_lat:.0f}ms | ${data['total_cost']:.5f} |")
            return {"content": "\n".join(lines)}
            
        # 2. General Query: use LLM (Groq) with news claims grounding context
        from verification.llm_verify import _get_client
        client = _get_client()
        if not client:
            return {"content": "❌ Groq API key is not configured on the Daily News Agent server."}
            
        from database.db import get_claims_since
        recent_claims = get_claims_since(hours=48)
        
        grounding_context = ""
        if recent_claims:
            grounding_context += "Here is the verified news claims grounding context from the last 48 hours:\n"
            for c in recent_claims[:30]:
                grounding_context += (
                    f"- Title: {c.get('title')}\n"
                    f"  Category: {c.get('category')}\n"
                    f"  Confidence: {c.get('confidence')}%\n"
                    f"  Status: {c.get('verification_status')}\n"
                    f"  Summary: {c.get('summary')}\n\n"
                )
        else:
            grounding_context += "No recent news claims found in the database for the last 48 hours.\n"
            
        system_prompt = (
            "You are the Daily News Agent assistant, integrated into the Qubix platform.\n"
            "Your job is to answer user queries about recent news, tech trends, and financial announcements.\n"
            "Use the provided news claims grounding context to answer questions factually and refer to the confidence/verification status when appropriate.\n"
            "Be concise, professional, and clear. Format your output nicely using markdown.\n"
            f"{grounding_context}"
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        for h in payload.history:
            messages.append({"role": h.role, "content": h.content})
            
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=800,
        )
        
        reply = response.choices[0].message.content
        return {"content": reply}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"content": f"❌ An error occurred inside Daily News Agent: {str(e)}"}

# Catch-all route for SPA (React Router)
@app.get("/{catchall:path}", response_class=HTMLResponse)
def serve_spa(catchall: str):
    import pathlib
    web_dist_path = pathlib.Path(__file__).resolve().parent / "web" / "dist"
    if web_dist_path.is_dir() and (web_dist_path / "index.html").exists():
        with open(web_dist_path / "index.html", "r") as f:
            return f.read()
    return f"<h1>React dashboard not built yet. Looking at {web_dist_path}</h1>"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
