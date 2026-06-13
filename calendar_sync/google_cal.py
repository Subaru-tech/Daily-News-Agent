import json
import logging
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config.settings import GOOGLE_CREDENTIALS_JSON, CALENDAR_COLORS

logger = logging.getLogger(__name__)

_service = None
_calendar_id = None

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_NAME = "📰 Daily News"


def _get_service():
    """Get or create Google Calendar API service."""
    global _service
    if _service:
        return _service

    if not GOOGLE_CREDENTIALS_JSON:
        logger.warning("[Calendar] No Google credentials configured")
        return None

    try:
        creds_data = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
            scopes=SCOPES,
        )
        _service = build("calendar", "v3", credentials=creds)
        return _service
    except Exception as e:
        logger.error(f"[Calendar] Auth failed: {e}")
        return None


def _get_or_create_calendar() -> str | None:
    """Get or create the dedicated news calendar."""
    global _calendar_id
    if _calendar_id:
        return _calendar_id

    service = _get_service()
    if not service:
        return None

    try:
        # Check if calendar already exists
        calendars = service.calendarList().list().execute()
        for cal in calendars.get("items", []):
            if cal.get("summary") == CALENDAR_NAME:
                _calendar_id = cal["id"]
                return _calendar_id

        # Create new calendar
        body = {"summary": CALENDAR_NAME, "timeZone": "Asia/Kolkata"}
        new_cal = service.calendars().insert(body=body).execute()
        _calendar_id = new_cal["id"]
        logger.info(f"[Calendar] Created calendar: {CALENDAR_NAME}")
        return _calendar_id
    except Exception as e:
        logger.error(f"[Calendar] Failed to get/create calendar: {e}")
        return None


def _emoji_for_category(category: str) -> str:
    emojis = {
        "AI & Tech": "🤖",
        "Finance & Stocks": "💰",
        "Geo-Politics": "🌍",
        "Startups": "🚀",
        "Leadership": "👔",
    }
    return emojis.get(category, "📰")


def _confidence_badge(confidence: int) -> str:
    if confidence >= 80:
        return "🟢 VERIFIED"
    elif confidence >= 50:
        return "🟡 PARTIALLY VERIFIED"
    else:
        return "🔴 UNVERIFIED"


def create_news_event(claim: dict) -> str | None:
    """Create a Google Calendar event for a verified news item."""
    service = _get_service()
    cal_id = _get_or_create_calendar()
    if not service or not cal_id:
        return None

    category = claim.get("category", "General")
    confidence = claim.get("confidence", 0)
    emoji = _emoji_for_category(category)
    badge = _confidence_badge(confidence)

    # Build description
    description = f"**{badge}** (Confidence: {confidence}%)\n\n"
    description += f"**Category:** {category}\n"
    description += f"**Source:** {claim.get('source', 'Unknown')}\n\n"

    summary_text = claim.get("summary", "")
    if summary_text:
        description += f"**Summary:**\n{summary_text[:500]}\n\n"

    reasoning = claim.get("reasoning", "")
    if reasoning:
        description += f"**Verification Notes:**\n{reasoning}\n\n"

    tickers = claim.get("tickers", [])
    if tickers:
        description += f"**Tickers Mentioned:** {', '.join(tickers)}\n"
        price_data = claim.get("price_data", {})
        for t, p in price_data.items():
            if p:
                change = p.get("change_pct", 0)
                arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                description += f"  {arrow} {t}: ${p.get('price', 'N/A')} ({change:+.2f}%)\n"
        description += "\n"

    description += f"🔗 Read more: {claim.get('url', '')}\n"

    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    event = {
        "summary": f"{emoji} {claim.get('title', 'News')[:80]}",
        "description": description,
        "start": {"date": today},
        "end": {"date": tomorrow},
        "colorId": CALENDAR_COLORS.get(category, "1"),
        "reminders": {"useDefault": False, "overrides": []},
    }

    try:
        created = service.events().insert(calendarId=cal_id, body=event).execute()
        logger.info(f"[Calendar] Created event: {claim.get('title', '')[:40]}...")
        return created.get("id")
    except Exception as e:
        logger.error(f"[Calendar] Failed to create event: {e}")
        return None


def update_event_debunked(event_id: str, note: str) -> bool:
    """Update an existing calendar event with DEBUNKED status."""
    service = _get_service()
    cal_id = _get_or_create_calendar()
    if not service or not cal_id:
        return False

    try:
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()

        # Prepend debunked notice
        event["summary"] = f"❌ DEBUNKED: {event.get('summary', '')}"
        description = event.get("description", "")
        debunked_notice = (
            f"\n\n{'='*40}\n"
            f"❌ **DEBUNKED** — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"{note}\n"
            f"{'='*40}\n\n"
        )
        event["description"] = debunked_notice + description
        event["colorId"] = "4"  # Flamingo (stands out)

        service.events().update(
            calendarId=cal_id, eventId=event_id, body=event
        ).execute()
        logger.info(f"[Calendar] Marked event as debunked: {event_id}")
        return True
    except Exception as e:
        logger.error(f"[Calendar] Failed to update debunked: {e}")
        return False
