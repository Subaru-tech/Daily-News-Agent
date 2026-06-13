import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import (
    TIMEZONE, MORNING_HOUR, MORNING_MINUTE,
    EVENING_HOUR, EVENING_MINUTE, FETCH_INTERVAL_MINUTES,
)
from ingestors.manager import manager
from database.db import get_claims_since, cleanup_old_metrics
from notifications.telegram import (
    send_morning_brief, send_evening_recap,
    send_weekly_summary, track_failure
)
from digest.morning import compile_morning_digest
from digest.evening import compile_evening_digest

import asyncio

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=TIMEZONE)

async def job_fetch_and_verify():
    """Delegates to the AsyncIngestionManager for non-blocking fetch & verification."""
    logger.info(f"[Scheduler] Fetch cycle triggered at {datetime.now()}")
    try:
        await manager.run_fetch_cycle()
    except Exception as e:
        await asyncio.to_thread(track_failure, "fetch_and_verify", str(e))
        logger.error(f"[Scheduler] Fetch failed: {e}", exc_info=True)

async def job_morning_brief():
    """Send 8 AM morning brief via Telegram."""
    logger.info("[Scheduler] Sending morning brief...")
    try:
        articles = await asyncio.to_thread(compile_morning_digest)
        await asyncio.to_thread(send_morning_brief, articles)
        logger.info(f"[Scheduler] Morning brief sent: {len(articles)} items")
    except Exception as e:
        await asyncio.to_thread(track_failure, "morning_brief", str(e))
        logger.error(f"[Scheduler] Morning brief failed: {e}", exc_info=True)

async def job_evening_recap():
    """Send 10 PM evening recap via Telegram."""
    logger.info("[Scheduler] Sending evening recap...")
    try:
        articles = await asyncio.to_thread(compile_evening_digest)
        await asyncio.to_thread(send_evening_recap, articles)
        logger.info(f"[Scheduler] Evening recap sent: {len(articles)} items")
    except Exception as e:
        await asyncio.to_thread(track_failure, "evening_recap", str(e))
        logger.error(f"[Scheduler] Evening recap failed: {e}", exc_info=True)

async def job_weekly_summary():
    """Send Sunday 10 PM weekly summary via Telegram."""
    logger.info("[Scheduler] Sending weekly summary...")
    try:
        articles = await asyncio.to_thread(get_claims_since, 168)  # 7 days
        await asyncio.to_thread(send_weekly_summary, articles)

        # --- Metrics Snapshot ---
        try:
            from database.db import get_recent_metrics
            from notifications.telegram import _send_message
            metrics = await asyncio.to_thread(get_recent_metrics, 168)
            if metrics:
                latencies = [m["latency_ms"] for m in metrics if m.get("event_type") == "fetch_cycle"]
                avg_latency = sum(latencies) / len(latencies) if latencies else 0
                
                volumes = [m["llm_cost"] for m in metrics if m.get("event_type") == "fetch_cycle"]
                avg_volume = sum(volumes) / len(volumes) if volumes else 0
                
                hype_scores = [a.get("hype_score", 0) for a in articles]
                avg_hype = sum(hype_scores) / len(hype_scores) if hype_scores else 0
                
                msg = (
                    "📊 *Weekly System Snapshot*\n"
                    f"⏱ Avg Latency: {avg_latency:.0f}ms\n"
                    f"📦 Avg Volume: {avg_volume:.1f} novel/cycle\n"
                    f"🔥 Avg Hype Index: {avg_hype:.1f}"
                )
                await asyncio.to_thread(_send_message, msg)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send metrics snapshot: {e}")
        # ------------------------

        await asyncio.to_thread(cleanup_old_metrics, 7)  # Clean up metrics older than 7 days
        logger.info(f"[Scheduler] Weekly summary sent: {len(articles)} items")
    except Exception as e:
        await asyncio.to_thread(track_failure, "weekly_summary", str(e))
        logger.error(f"[Scheduler] Weekly summary failed: {e}", exc_info=True)

async def job_keep_alive():
    """Self-ping to prevent Render free tier from spinning down."""
    import os
    import requests as req

    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if not render_url:
        return  # Skip locally

    try:
        resp = await asyncio.to_thread(req.get, f"{render_url}/health", timeout=10)
        logger.debug(f"[Keep-Alive] Pinged {render_url}: {resp.status_code}")
    except Exception as e:
        logger.warning(f"[Keep-Alive] Ping failed: {e}")

    # Health Monitor: Check if fetch cycle is hung
    try:
        import time
        if manager.last_fetch_time > 0:
            elapsed_mins = (time.monotonic() - manager.last_fetch_time) / 60
            if elapsed_mins > (FETCH_INTERVAL_MINUTES * 2):
                await asyncio.to_thread(
                    track_failure, 
                    "health_monitor", 
                    f"⚠️ Agent Health Warning: No fetch cycle completed in {elapsed_mins:.1f} minutes! Instance might be hung."
                )
    except Exception as e:
        logger.error(f"[Health-Monitor] Check failed: {e}")

def start_scheduler():
    """Start all scheduled jobs."""
    scheduler.add_job(
        job_fetch_and_verify,
        IntervalTrigger(minutes=FETCH_INTERVAL_MINUTES),
        id="fetch_and_verify",
        replace_existing=True,
        next_run_time=datetime.now(),  # Run immediately on startup
    )

    scheduler.add_job(
        job_morning_brief,
        CronTrigger(hour=MORNING_HOUR, minute=MORNING_MINUTE, timezone=TIMEZONE),
        id="morning_brief",
        replace_existing=True,
    )

    scheduler.add_job(
        job_evening_recap,
        CronTrigger(hour=EVENING_HOUR, minute=EVENING_MINUTE, timezone=TIMEZONE),
        id="evening_recap",
        replace_existing=True,
    )

    scheduler.add_job(
        job_weekly_summary,
        CronTrigger(day_of_week="sun", hour=22, minute=0, timezone=TIMEZONE),
        id="weekly_summary",
        replace_existing=True,
    )

    scheduler.add_job(
        job_keep_alive,
        IntervalTrigger(minutes=10),
        id="keep_alive",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"[Scheduler] Started — "
        f"Fetch: every {FETCH_INTERVAL_MINUTES}min | "
        f"Morning: {MORNING_HOUR}:{MORNING_MINUTE:02d} | "
        f"Evening: {EVENING_HOUR}:{EVENING_MINUTE:02d} | "
        f"Weekly: Sun 22:00 | "
        f"Keep-alive: every 10min "
        f"({TIMEZONE})"
    )

def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped")

