import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import (
    TIMEZONE, MORNING_HOUR, MORNING_MINUTE,
    EVENING_HOUR, EVENING_MINUTE, FETCH_INTERVAL_MINUTES,
    CONFIDENCE_THRESHOLD_CALENDAR,
)
from ingestors.manager import fetch_all
from verification.structured import verify_structured
from verification.llm_verify import verify_with_llm, needs_llm_verification
from database.db import save_claim, update_claim_calendar_id, get_claims_since
from calendar_sync.google_cal import create_news_event
from notifications.telegram import (
    send_morning_brief, send_evening_recap, send_breaking_alert,
    send_weekly_summary, track_failure, track_success,
)
from digest.morning import compile_morning_digest
from digest.evening import compile_evening_digest
from digest.breaking import check_breaking_news

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone=TIMEZONE)


def job_fetch_and_verify():
    """Fetch news, verify, save to DB + calendar. Runs every 15 min."""
    logger.info(f"[Scheduler] Fetch started at {datetime.now()}")

    try:
        # 1. Fetch from all sources
        articles = fetch_all()
        logger.info(f"[Scheduler] Fetched {len(articles)} articles")

        # 2. Verify each article
        for article in articles:
            # Structured verification first (80%)
            result = verify_structured(article, articles)

            # LLM verification if needed (20%)
            if needs_llm_verification(article, result):
                llm_result = verify_with_llm(article)
                # Merge: use LLM confidence if it's more specific
                if llm_result.get("confidence", 0) != 50:  # Not default
                    result["confidence"] = llm_result["confidence"]
                    result["category"] = llm_result.get("category", result["category"])
                    result["reasoning"] = (
                        result.get("reasoning", "") + " | LLM: " +
                        llm_result.get("reasoning", "")
                    )
                    result["verification_status"] = llm_result.get(
                        "verification_status", result["verification_status"]
                    )

            # 3. Enrich article with verification data
            article.update({
                "confidence": result["confidence"],
                "category": result["category"],
                "verification_status": result["verification_status"],
                "reasoning": result.get("reasoning", ""),
                "tickers": result.get("tickers", []),
                "price_data": result.get("price_data", {}),
                "sources": [article.get("source", "")],
            })

            # 4. Save to database
            claim_id = save_claim(article)

            # 5. Save to Google Calendar if above threshold
            if claim_id and article["confidence"] >= CONFIDENCE_THRESHOLD_CALENDAR:
                event_id = create_news_event(article)
                if event_id:
                    update_claim_calendar_id(claim_id, event_id)

        # 6. Check for breaking news
        breaking = check_breaking_news()
        for item in breaking:
            send_breaking_alert(item)

        track_success()  # Reset failure counter
        logger.info(f"[Scheduler] Fetch complete. {len(articles)} processed.")

    except Exception as e:
        track_failure("fetch_and_verify", str(e))
        logger.error(f"[Scheduler] Fetch failed: {e}", exc_info=True)


def job_morning_brief():
    """Send 8 AM morning brief via Telegram."""
    logger.info("[Scheduler] Sending morning brief...")
    try:
        articles = compile_morning_digest()
        send_morning_brief(articles)
        logger.info(f"[Scheduler] Morning brief sent: {len(articles)} items")
    except Exception as e:
        track_failure("morning_brief", str(e))
        logger.error(f"[Scheduler] Morning brief failed: {e}", exc_info=True)


def job_evening_recap():
    """Send 10 PM evening recap via Telegram."""
    logger.info("[Scheduler] Sending evening recap...")
    try:
        articles = compile_evening_digest()
        send_evening_recap(articles)
        logger.info(f"[Scheduler] Evening recap sent: {len(articles)} items")
    except Exception as e:
        track_failure("evening_recap", str(e))
        logger.error(f"[Scheduler] Evening recap failed: {e}", exc_info=True)


def job_weekly_summary():
    """Send Sunday 9 AM weekly summary via Telegram."""
    logger.info("[Scheduler] Sending weekly summary...")
    try:
        articles = get_claims_since(hours=168)  # 7 days
        send_weekly_summary(articles)
        logger.info(f"[Scheduler] Weekly summary sent: {len(articles)} items")
    except Exception as e:
        track_failure("weekly_summary", str(e))
        logger.error(f"[Scheduler] Weekly summary failed: {e}", exc_info=True)


def start_scheduler():
    """Start all scheduled jobs."""
    # Every 15 minutes: fetch + verify + save
    scheduler.add_job(
        job_fetch_and_verify,
        IntervalTrigger(minutes=FETCH_INTERVAL_MINUTES),
        id="fetch_and_verify",
        replace_existing=True,
        next_run_time=datetime.now(),  # Run immediately on startup
    )

    # 8:00 AM IST: Morning brief
    scheduler.add_job(
        job_morning_brief,
        CronTrigger(hour=MORNING_HOUR, minute=MORNING_MINUTE, timezone=TIMEZONE),
        id="morning_brief",
        replace_existing=True,
    )

    # 10:00 PM IST: Evening recap
    scheduler.add_job(
        job_evening_recap,
        CronTrigger(hour=EVENING_HOUR, minute=EVENING_MINUTE, timezone=TIMEZONE),
        id="evening_recap",
        replace_existing=True,
    )

    # Sunday 9:00 AM IST: Weekly summary
    scheduler.add_job(
        job_weekly_summary,
        CronTrigger(day_of_week="sun", hour=9, minute=0, timezone=TIMEZONE),
        id="weekly_summary",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"[Scheduler] Started — "
        f"Fetch: every {FETCH_INTERVAL_MINUTES}min | "
        f"Morning: {MORNING_HOUR}:{MORNING_MINUTE:02d} | "
        f"Evening: {EVENING_HOUR}:{EVENING_MINUTE:02d} | "
        f"Weekly: Sun 9:00 "
        f"({TIMEZONE})"
    )


def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped")
