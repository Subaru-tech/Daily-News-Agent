"""
Telegram Bot Command Handler

Runs as a background polling thread. Handles:
- /status    — Current agent stats
- /latest    — Top 5 recent verified stories
- /weekly    — This week's summary
- /watch     — Add a ticker to watchlist
- /unwatch   — Remove a ticker from watchlist
- /mute      — Mute a news category
- /unmute    — Unmute a news category
- /sentiment — Ticker sentiment report
- /help      — Available commands
"""
import threading
import logging
import time
import json
import requests
from datetime import datetime

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

_last_update_id = 0
_running = False

# ── User Preferences (in-memory, persisted via JSON file) ──
_user_prefs_file = "user_prefs.json"
_user_prefs = {
    "extra_tickers": [],          # Added via /watch
    "muted_categories": [],       # Muted via /mute
    "portfolio_tickers": [],      # Added via /portfolio
}


def _load_prefs():
    """Load user preferences from file."""
    global _user_prefs
    try:
        with open(_user_prefs_file, "r") as f:
            _user_prefs = json.load(f)
            _user_prefs.setdefault("portfolio_tickers", [])
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def _save_prefs():
    """Save user preferences to file."""
    with open(_user_prefs_file, "w") as f:
        json.dump(_user_prefs, f, indent=2)


def get_muted_categories() -> list[str]:
    """Get list of muted categories (used by digest modules)."""
    return _user_prefs.get("muted_categories", [])


def get_extra_tickers() -> list[str]:
    """Get list of user-added tickers."""
    return _user_prefs.get("extra_tickers", [])


def get_portfolio_tickers() -> list[str]:
    """Get list of personal portfolio tickers."""
    return _user_prefs.get("portfolio_tickers", [])


def _send_reply(chat_id: int, text: str):
    """Send a reply to a specific chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, timeout=10)
    except Exception as e:
        logger.error(f"[Bot] Reply failed: {e}")


def _handle_status(chat_id: int, args: str = ""):
    """Handle /status command."""
    from database.db import get_claims_since

    today = get_claims_since(hours=24)
    verified = [c for c in today if c.get("confidence", 0) >= 80]
    categories = set(c.get("category", "") for c in today)

    now = datetime.now().strftime("%H:%M IST")
    muted = _user_prefs.get("muted_categories", [])
    extra = _user_prefs.get("extra_tickers", [])

    msg = (
        f"📊 *Agent Status — {now}*\n\n"
        f"🟢 Status: Running\n"
        f"📰 Today: {len(today)} articles processed\n"
        f"✅ Verified: {len(verified)} (≥80% confidence)\n"
        f"📂 Categories: {', '.join(categories) if categories else 'N/A'}\n"
    )
    if muted:
        msg += f"🔇 Muted: {', '.join(muted)}\n"
    if extra:
        msg += f"👀 Extra tickers: {', '.join(extra)}\n"

    msg += (
        f"\n⏱ Fetching every 15 min\n"
        f"📰 Morning: 8:00 AM IST\n"
        f"📊 Evening: 10:00 PM IST\n"
    )
    _send_reply(chat_id, msg)


def _handle_latest(chat_id: int, args: str = ""):
    """Handle /latest command — top 5 most recent verified stories."""
    from database.db import get_claims_since

    claims = get_claims_since(hours=12)
    claims.sort(key=lambda c: c.get("confidence", 0), reverse=True)
    top = claims[:5]

    if not top:
        _send_reply(chat_id, "📰 No recent stories in the last 12 hours.")
        return

    msg = "📰 *Latest Top Stories*\n\n"
    for i, c in enumerate(top, 1):
        conf = c.get("confidence", 0)
        icon = "🟢" if conf >= 80 else "🟡" if conf >= 50 else "🔴"
        title = c.get("title", "")[:50]
        url = c.get("url", "")
        cat = c.get("category", "")
        msg += f"{i}. {icon} *{cat}*\n   [{title}...]({url})\n   Confidence: {conf}%\n\n"

    _send_reply(chat_id, msg)


def _handle_metrics(chat_id: int, args: str = ""):
    """Handle /metrics command — on-demand metrics snapshot."""
    from database.db import get_recent_metrics, get_claims_since

    metrics = get_recent_metrics(168)
    articles = get_claims_since(hours=168)

    if not metrics:
        _send_reply(chat_id, "📊 No metrics available yet.")
        return

    latencies = [m["latency_ms"] for m in metrics if m.get("event_type") == "fetch_cycle"]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    volumes = [m["llm_cost"] for m in metrics if m.get("event_type") == "fetch_cycle"]
    avg_volume = sum(volumes) / len(volumes) if volumes else 0

    hype_scores = [a.get("hype_score", 0) for a in articles]
    avg_hype = sum(hype_scores) / len(hype_scores) if hype_scores else 0

    msg = (
        "📊 *System Metrics Snapshot (7 Days)*\n\n"
        f"⏱ Avg Latency: {avg_latency:.0f}ms\n"
        f"📦 Avg Volume: {avg_volume:.1f} novel/cycle\n"
        f"🔥 Avg Hype Index: {avg_hype:.1f}"
    )
    _send_reply(chat_id, msg)


def _handle_weekly(chat_id: int, args: str = ""):
    """Handle /weekly command — this week's summary."""
    from database.db import get_claims_since

    claims = get_claims_since(hours=168)

    if not claims:
        _send_reply(chat_id, "📅 No data available for this week yet.")
        return

    cat_counts: dict[str, int] = {}
    ticker_counts: dict[str, int] = {}
    verified_count = 0

    for c in claims:
        cat = c.get("category", "General")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        if c.get("confidence", 0) >= 80:
            verified_count += 1
        tickers = c.get("tickers", [])
        if isinstance(tickers, str):
            try:
                tickers = json.loads(tickers)
            except Exception:
                tickers = []
        for t in tickers:
            ticker_counts[t] = ticker_counts.get(t, 0) + 1

    top_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    msg = "📅 *Weekly Summary*\n\n"
    msg += f"📰 Total articles: {len(claims)}\n"
    msg += f"✅ Verified: {verified_count}\n\n"

    msg += "*By Category:*\n"
    for cat in ["AI & Tech", "Finance & Stocks", "Geo-Politics", "Startups", "Leadership"]:
        count = cat_counts.get(cat, 0)
        if count > 0:
            msg += f"  • {cat}: {count}\n"

    if top_tickers:
        msg += "\n*Most Mentioned Tickers:*\n"
        for ticker, count in top_tickers:
            msg += f"  📈 {ticker}: {count} mentions\n"

    top_stories = sorted(claims, key=lambda c: c.get("confidence", 0), reverse=True)[:3]
    msg += "\n*Top Stories This Week:*\n"
    for i, c in enumerate(top_stories, 1):
        title = c.get("title", "")[:45]
        msg += f"  {i}. {title}...\n"

    _send_reply(chat_id, msg)


def _handle_watch(chat_id: int, args: str = ""):
    """Handle /watch TICKER — add a ticker to watchlist."""
    ticker = args.strip().upper()
    if not ticker:
        extra = _user_prefs.get("extra_tickers", [])
        if extra:
            _send_reply(chat_id, f"👀 *Watching:* {', '.join(extra)}\n\nUse `/watch TSLA` to add, `/unwatch TSLA` to remove.")
        else:
            _send_reply(chat_id, "👀 No extra tickers. Use `/watch TSLA` to add one.")
        return

    extra = _user_prefs.setdefault("extra_tickers", [])
    if ticker in extra:
        _send_reply(chat_id, f"👀 Already watching *{ticker}*")
        return

    extra.append(ticker)
    _save_prefs()
    _send_reply(chat_id, f"✅ Now watching *{ticker}*\n\nYou'll get alerts when {ticker} is mentioned in news.")


def _handle_unwatch(chat_id: int, args: str = ""):
    """Handle /unwatch TICKER — remove a ticker."""
    ticker = args.strip().upper()
    if not ticker:
        _send_reply(chat_id, "Usage: `/unwatch TSLA`")
        return

    extra = _user_prefs.get("extra_tickers", [])
    if ticker in extra:
        extra.remove(ticker)
        _save_prefs()
        _send_reply(chat_id, f"🗑 Stopped watching *{ticker}*")
    else:
        _send_reply(chat_id, f"*{ticker}* wasn't in your watchlist.")


def _handle_mute(chat_id: int, args: str = ""):
    """Handle /mute Category — mute a news category."""
    category = args.strip()
    if not category:
        muted = _user_prefs.get("muted_categories", [])
        if muted:
            _send_reply(chat_id, f"🔇 *Muted:* {', '.join(muted)}\n\nUse `/unmute Startups` to unmute.")
        else:
            _send_reply(chat_id, (
                "🔇 No categories muted.\n\n"
                "*Available categories:*\n"
                "• AI & Tech\n• Finance & Stocks\n"
                "• Geo-Politics\n• Startups\n• Leadership\n\n"
                "Use: `/mute Startups`"
            ))
        return

    # Fuzzy match category names
    cat_map = {
        "ai": "AI & Tech", "tech": "AI & Tech", "ai & tech": "AI & Tech",
        "finance": "Finance & Stocks", "stocks": "Finance & Stocks", "finance & stocks": "Finance & Stocks",
        "geo": "Geo-Politics", "politics": "Geo-Politics", "geo-politics": "Geo-Politics",
        "startups": "Startups", "startup": "Startups",
        "leadership": "Leadership", "leader": "Leadership",
    }
    resolved = cat_map.get(category.lower(), category)

    muted = _user_prefs.setdefault("muted_categories", [])
    if resolved in muted:
        _send_reply(chat_id, f"🔇 *{resolved}* is already muted.")
        return

    muted.append(resolved)
    _save_prefs()
    _send_reply(chat_id, f"🔇 Muted *{resolved}*\n\nYou won't receive digest items from this category.\nUse `/unmute {resolved}` to restore.")


def _handle_unmute(chat_id: int, args: str = ""):
    """Handle /unmute Category — unmute a news category."""
    category = args.strip()
    if not category:
        _send_reply(chat_id, "Usage: `/unmute Startups`")
        return

    cat_map = {
        "ai": "AI & Tech", "tech": "AI & Tech", "ai & tech": "AI & Tech",
        "finance": "Finance & Stocks", "stocks": "Finance & Stocks",
        "geo": "Geo-Politics", "politics": "Geo-Politics",
        "startups": "Startups", "startup": "Startups",
        "leadership": "Leadership",
    }
    resolved = cat_map.get(category.lower(), category)

    muted = _user_prefs.get("muted_categories", [])
    if resolved in muted:
        muted.remove(resolved)
        _save_prefs()
        _send_reply(chat_id, f"🔊 Unmuted *{resolved}*")
    else:
        _send_reply(chat_id, f"*{resolved}* wasn't muted.")


def _handle_portfolio(chat_id: int, args: str = ""):
    """Handle /portfolio add|remove TICKER."""
    parts = args.strip().upper().split()
    action = parts[0].lower() if parts else ""
    ticker = parts[1] if len(parts) > 1 else ""

    portfolio = _user_prefs.get("portfolio_tickers", [])

    if not action or action not in ["add", "remove"] or not ticker:
        if portfolio:
            _send_reply(chat_id, f"💼 *Your Portfolio:* {', '.join(portfolio)}\n\nUse `/portfolio add NVDA` or `/portfolio remove TSLA`.")
        else:
            _send_reply(chat_id, "💼 Portfolio is empty.\n\nUse `/portfolio add NVDA` to track your holdings. Portfolio matches trigger breaking alerts even on lower confidence bounds.")
        return

    if action == "add":
        if ticker in portfolio:
            _send_reply(chat_id, f"💼 *{ticker}* is already in your portfolio.")
        else:
            portfolio.append(ticker)
            _user_prefs["portfolio_tickers"] = portfolio
            _save_prefs()
            _send_reply(chat_id, f"💼 Added *{ticker}* to your portfolio.\n\nYou will receive dedicated breaking alerts for this holding.")
    elif action == "remove":
        if ticker in portfolio:
            portfolio.remove(ticker)
            _user_prefs["portfolio_tickers"] = portfolio
            _save_prefs()
            _send_reply(chat_id, f"🗑 Removed *{ticker}* from your portfolio.")
        else:
            _send_reply(chat_id, f"💼 *{ticker}* is not in your portfolio.")


def _handle_sentiment(chat_id: int, args: str = ""):
    """Handle /sentiment — ticker sentiment report."""
    from verification.sentiment import get_ticker_sentiment

    data = get_ticker_sentiment(hours=168)

    if not data:
        _send_reply(chat_id, "📊 No ticker data yet. Check back after a few fetch cycles.")
        return

    msg = "📊 *Ticker Sentiment (7 days)*\n\n"
    for t in data[:8]:
        total = t["total"]
        pos_pct = round((t["positive"] / total) * 100) if total else 0
        neg_pct = round((t["negative"] / total) * 100) if total else 0

        if pos_pct > 60:
            icon = "🟢"
        elif neg_pct > 40:
            icon = "🔴"
        else:
            icon = "🟡"

        bar_filled = round(pos_pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)

        msg += f"{icon} *{t['ticker']}* — {total} mentions\n"
        msg += f"   [{bar}] {pos_pct}% positive\n\n"

    _send_reply(chat_id, msg)


def _handle_help(chat_id: int, args: str = ""):
    """Handle /help command."""
    msg = (
        "🤖 *Daily News Agent — Commands*\n\n"
        "📊 /status — Agent stats & config\n"
        "📰 /latest — Top 5 recent stories\n"
        "📈 /metrics — On-demand metrics snapshot\n"
        "📅 /weekly — This week's summary\n"
        "📈 /sentiment — Ticker sentiment report\n\n"
        "*Custom Alerts:*\n"
        "👀 /watch TSLA — Add ticker to watchlist\n"
        "🗑 /unwatch TSLA — Remove ticker\n"
        "🔇 /mute Startups — Mute a category\n"
        "🔊 /unmute Startups — Unmute category\n\n"
        "❓ /help — This message\n\n"
        "_Digests: 8 AM + 10 PM IST + breaking alerts_"
    )
    _send_reply(chat_id, msg)


# ── Command Router ──

def _parse_command(text: str) -> tuple[str, str]:
    """Parse '/command args' into (command, args)."""
    text = text.strip()
    # Remove @botname suffix
    if "@" in text:
        parts = text.split(None, 1)
        cmd = parts[0].split("@")[0] if parts else text
        args = parts[1] if len(parts) > 1 else ""
    else:
        parts = text.split(None, 1)
        cmd = parts[0] if parts else text
        args = parts[1] if len(parts) > 1 else ""
    return cmd.lower(), args


COMMAND_HANDLERS = {
    "/status": _handle_status,
    "/latest": _handle_latest,
    "/metrics": _handle_metrics,
    "/weekly": _handle_weekly,
    "/watch": _handle_watch,
    "/unwatch": _handle_unwatch,
    "/mute": _handle_mute,
    "/unmute": _handle_unmute,
    "/portfolio": _handle_portfolio,
    "/sentiment": _handle_sentiment,
    "/help": _handle_help,
    "/start": _handle_help,
}


def _poll_updates():
    """Long-poll Telegram for new messages."""
    global _last_update_id, _running

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"

    while _running:
        try:
            resp = requests.get(url, params={
                "offset": _last_update_id + 1,
                "timeout": 30,
            }, timeout=35)

            if resp.status_code != 200:
                time.sleep(5)
                continue

            data = resp.json()
            for update in data.get("result", []):
                _last_update_id = update["update_id"]
                message = update.get("message", {})
                text = message.get("text", "").strip()
                chat_id = message.get("chat", {}).get("id")

                if not chat_id:
                    continue

                command, args = _parse_command(text)

                handler = COMMAND_HANDLERS.get(command)
                if handler:
                    handler(chat_id, args)
                elif text and not text.startswith("/"):
                    _send_reply(chat_id, "🤖 I'm your news agent! Use /help to see commands.")

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            logger.error(f"[Bot] Polling error: {e}")
            time.sleep(10)


def start_bot_polling():
    """Start the bot command handler in a background thread."""
    global _running

    if not TELEGRAM_BOT_TOKEN:
        logger.warning("[Bot] No token configured, skipping polling")
        return

    _load_prefs()
    _running = True
    thread = threading.Thread(target=_poll_updates, daemon=True, name="telegram-bot")
    thread.start()
    logger.info("[Bot] Command polling started")


def stop_bot_polling():
    """Stop the bot polling."""
    global _running
    _running = False
    logger.info("[Bot] Command polling stopped")
