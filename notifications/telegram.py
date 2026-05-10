import logging
import requests
from datetime import datetime

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def _send_message(text: str, parse_mode: str = "Markdown",
                  disable_notification: bool = False) -> bool:
    """Core Telegram send function."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("[Telegram] Bot token or chat ID not configured")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
        "disable_notification": disable_notification,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"[Telegram] API error: {data}")
            return False
        return True
    except Exception as e:
        logger.error(f"[Telegram] Send failed: {e}")
        return False


def _emoji(category: str) -> str:
    return {
        "AI & Tech": "🤖",
        "Finance & Stocks": "💰",
        "Geo-Politics": "🌍",
        "Startups": "🚀",
        "Leadership": "👔",
    }.get(category, "📰")


def _confidence_icon(confidence: int) -> str:
    if confidence >= 80:
        return "🟢"
    elif confidence >= 50:
        return "🟡"
    else:
        return "🔴"


def send_morning_brief(articles: list[dict]) -> bool:
    """8 AM IST — Forward-looking daily brief."""
    now = datetime.now().strftime("%B %d, %Y")
    msg = f"📰 *Morning Brief — {now}*\n\n"

    if not articles:
        msg += "_No significant news overnight._\n"
        msg += f"\n📅 [View Calendar](https://calendar.google.com)"
        return _send_message(msg)

    # Group by category
    by_cat: dict[str, list] = {}
    for a in articles:
        cat = a.get("category", "General")
        by_cat.setdefault(cat, []).append(a)

    for cat in ["AI & Tech", "Finance & Stocks", "Geo-Politics", "Startups", "Leadership"]:
        items = by_cat.get(cat, [])
        if not items:
            continue

        emoji = _emoji(cat)
        msg += f"{emoji} *{cat}* ({len(items)})\n"

        for item in items[:3]:
            icon = _confidence_icon(item.get("confidence", 0))
            title = item.get("title", "")[:45]
            url = item.get("url", "")
            msg += f"  {icon} [{title}...]({url})\n"

            # Show ticker data if available
            tickers = item.get("tickers", [])
            price_data = item.get("price_data", {})
            for t in tickers[:2]:
                pd = price_data.get(t, {})
                if pd:
                    change = pd.get("change_pct", 0)
                    arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                    msg += f"    {arrow} {t}: {change:+.2f}%\n"

        msg += "\n"

    total = len(articles)
    verified = len([a for a in articles if a.get("confidence", 0) >= 80])
    msg += f"📅 [View in Calendar](https://calendar.google.com)\n"
    msg += f"🔍 {verified}/{total} verified"

    return _send_message(msg)


def send_evening_recap(articles: list[dict]) -> bool:
    """10 PM IST — Day in review with verification verdicts."""
    now = datetime.now().strftime("%B %d, %Y")
    msg = f"📰 *Evening Recap — {now}*\n\n"

    if not articles:
        msg += "_Quiet news day — nothing significant to report._\n"
        msg += f"\n📅 [View Calendar](https://calendar.google.com)"
        return _send_message(msg)

    msg += "*Today's Confirmed Moves*\n\n"

    by_cat: dict[str, list] = {}
    for a in articles:
        cat = a.get("category", "General")
        by_cat.setdefault(cat, []).append(a)

    for cat in ["AI & Tech", "Finance & Stocks", "Geo-Politics", "Startups", "Leadership"]:
        items = by_cat.get(cat, [])
        if not items:
            continue

        emoji = _emoji(cat)
        verified = len([i for i in items if i.get("confidence", 0) >= 80])
        msg += f"{emoji} *{cat}* ({verified}/{len(items)} verified)\n"

        for item in items[:4]:
            conf = item.get("confidence", 0)
            if conf >= 80:
                icon = "✅"
            elif conf >= 50:
                icon = "🟡"
            elif item.get("debunked"):
                icon = "❌"
            else:
                icon = "⚠️"

            title = item.get("title", "")[:40]
            url = item.get("url", "")
            msg += f"  {icon} [{title}...]({url})\n"

        msg += "\n"

    # Pattern detection
    all_titles = " ".join(a.get("title", "").lower() for a in articles)
    hype_words = ["breakthrough", "revolutionary", "game-changing"]
    hype_count = sum(1 for w in hype_words if w in all_titles)
    if hype_count >= 2:
        msg += f"*⚠️ Pattern Alert*\n"
        msg += f"_{hype_count} 'breakthrough' claims today. Hype cycle detected._\n\n"

    debunked = [a for a in articles if a.get("debunked")]
    if debunked:
        msg += "*❌ Debunked Today*\n"
        for d in debunked[:3]:
            msg += f"  • {d.get('title', '')[:40]}...\n"
        msg += "\n"

    msg += f"📊 [Day in Review](https://calendar.google.com)\n"
    msg += f"📅 [Week Ahead](https://calendar.google.com/calendar/r/week)"

    return _send_message(msg)


def send_breaking_alert(article: dict) -> bool:
    """Instant alert for high-confidence Finance/Geo-politics news."""
    cat = article.get("category", "")
    conf = article.get("confidence", 0)

    if article.get("is_portfolio"):
        msg = f"💼 *PORTFOLIO ALERT — {cat}*\n\n"
    else:
        msg = f"🚨 *BREAKING — {cat}*\n\n"
    msg += f"*{article.get('title', '')}*\n\n"
    msg += f"Confidence: {conf}%\n"

    source = article.get("source", "")
    msg += f"Source: {source}\n\n"

    # Ticker data
    tickers = article.get("tickers", [])
    price_data = article.get("price_data", {})
    if tickers:
        msg += "*Market Impact:*\n"
        for t in tickers[:3]:
            pd = price_data.get(t, {})
            if pd:
                change = pd.get("change_pct", 0)
                arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                msg += f"  {arrow} {t}: ${pd.get('price', 'N/A')} ({change:+.2f}%)\n"
        msg += "\n"

    reasoning = article.get("reasoning", "")
    if reasoning:
        msg += f"_Analysis: {reasoning[:200]}_\n\n"

    msg += f"[Read More]({article.get('url', '')})\n"
    msg += f"[📅 View Calendar](https://calendar.google.com)"

    return _send_message(msg, disable_notification=False)


def send_startup_message() -> bool:
    """Send a message when the agent starts up."""
    msg = (
        "🤖 *Daily News Agent — Online*\n\n"
        "Your AI news intelligence system is running.\n\n"
        "📰 Morning Brief: 8:00 AM IST\n"
        "📊 Evening Recap: 10:00 PM IST\n"
        "🚨 Breaking: Finance & Geo-Politics (instant)\n"
        "⏱ News fetch: Every 15 minutes\n\n"
        "📅 Calendar: 📰 Daily News\n"
        "_Type /help for commands_"
    )
    return _send_message(msg)


# ── Error Alert System ──────────────────────────────────────

_consecutive_failures = 0


def send_error_alert(error_msg: str, job_name: str = "Unknown") -> bool:
    """Send error notification to user."""
    now = datetime.now().strftime("%H:%M IST")
    msg = (
        f"⚠️ *Agent Error — {now}*\n\n"
        f"*Job:* {job_name}\n"
        f"*Error:* `{error_msg[:200]}`\n\n"
        f"_The agent will retry on the next scheduled run._"
    )
    return _send_message(msg)


def track_failure(job_name: str, error: str):
    """Track consecutive failures. Alert after 3 in a row."""
    global _consecutive_failures
    _consecutive_failures += 1
    logger.error(f"[Alert] Failure #{_consecutive_failures} in {job_name}: {error}")

    if _consecutive_failures >= 3:
        send_error_alert(
            f"{_consecutive_failures} consecutive failures. Last: {error}",
            job_name,
        )
        _consecutive_failures = 0  # Reset after alerting


def track_success():
    """Reset failure counter on success."""
    global _consecutive_failures
    _consecutive_failures = 0


def send_document(file_path: str, caption: str = "") -> bool:
    """Send a file as a Telegram document."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                url, 
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, 
                files={"document": f},
                timeout=30
            )
        resp.raise_for_status()
        return resp.json().get("ok", False)
    except Exception as e:
        logger.error(f"[Telegram] Failed to send document: {e}")
        return False


def send_weekly_summary(articles: list[dict]) -> bool:
    """Sunday 9 AM — Weekly summary with trends and tickers."""
    import json

    now = datetime.now().strftime("%B %d, %Y")
    msg = f"📅 *Weekly Summary — {now}*\n\n"

    if not articles:
        msg += "_No data for this week yet._"
        return _send_message(msg)

    # Stats
    verified = len([a for a in articles if a.get("confidence", 0) >= 80])
    msg += f"📰 Total: {len(articles)} articles\n"
    msg += f"✅ Verified: {verified}\n\n"

    # Category breakdown
    cat_counts: dict[str, int] = {}
    ticker_counts: dict[str, int] = {}
    for a in articles:
        cat = a.get("category", "General")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        tickers = a.get("tickers", [])
        if isinstance(tickers, str):
            try:
                tickers = json.loads(tickers)
            except Exception:
                tickers = []
        for t in tickers:
            ticker_counts[t] = ticker_counts.get(t, 0) + 1

    msg += "*📊 Category Breakdown:*\n"
    for cat in ["AI & Tech", "Finance & Stocks", "Geo-Politics", "Startups", "Leadership"]:
        count = cat_counts.get(cat, 0)
        if count:
            msg += f"  {_emoji(cat)} {cat}: {count}\n"

    # Top tickers
    top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    if top_tickers:
        msg += "\n*📈 Hot Tickers:*\n"
        for ticker, count in top_tickers:
            msg += f"  • {ticker}: {count} mentions\n"

    # Top 5 stories
    top = sorted(articles, key=lambda a: a.get("confidence", 0), reverse=True)[:5]
    msg += "\n*🏆 Top Stories:*\n"
    for i, a in enumerate(top, 1):
        icon = _confidence_icon(a.get("confidence", 0))
        title = a.get("title", "")[:40]
        url = a.get("url", "")
        msg += f"  {i}. {icon} [{title}...]({url})\n"

    msg += f"\n📅 [View Full Week](https://calendar.google.com/calendar/r/week)"
    
    # Output the initial message
    success = _send_message(msg)

    # Export & attach full MD report
    try:
        from digest.export import export_weekly_markdown
        md_file = export_weekly_markdown(articles)
        send_document(md_file, f"📄 Attached: Full Weekly Report ({now})")
    except Exception as e:
        logger.error(f"[Telegram] Failed to generate/send markdown: {e}")

    return success

