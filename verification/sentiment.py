"""
Sentiment Tracking for News Articles

Analyzes article titles for positive/negative/neutral sentiment
per ticker symbol. Uses keyword-based sentiment (no ML dependency).
"""
import json
import logging
from datetime import datetime

from database.db import get_claims_since
from config.settings import WATCHED_TICKERS

logger = logging.getLogger(__name__)

# ── Sentiment Keywords ──
POSITIVE_WORDS = {
    "surge", "soar", "rally", "gain", "rise", "jump", "boom", "record",
    "breakthrough", "profit", "growth", "bullish", "upgrade", "beat",
    "outperform", "strong", "positive", "success", "innovation", "launch",
    "expand", "partnership", "acquisition", "approve", "milestone", "revenue",
}

NEGATIVE_WORDS = {
    "crash", "fall", "drop", "decline", "loss", "plunge", "tumble", "bear",
    "downgrade", "miss", "weak", "negative", "fail", "lawsuit", "fine",
    "scandal", "layoff", "cut", "slash", "warning", "risk", "debt", "sell",
    "ban", "investigate", "fraud", "default", "recession", "bankruptcy",
}


def analyze_sentiment(text: str) -> str:
    """Simple keyword-based sentiment analysis."""
    text_lower = text.lower()
    pos_count = sum(1 for w in POSITIVE_WORDS if w in text_lower)
    neg_count = sum(1 for w in NEGATIVE_WORDS if w in text_lower)

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    return "neutral"


def get_ticker_sentiment(hours: int = 168) -> list[dict]:
    """Get sentiment breakdown per ticker for the given period."""
    claims = get_claims_since(hours=hours)

    ticker_data: dict[str, dict] = {}

    for claim in claims:
        title = claim.get("title", "")
        tickers = claim.get("tickers", [])

        # Parse tickers if stored as JSON string
        if isinstance(tickers, str):
            try:
                tickers = json.loads(tickers)
            except Exception:
                tickers = []

        if not tickers:
            # Check if title mentions any watched ticker
            title_upper = title.upper()
            tickers = [t for t in WATCHED_TICKERS if t in title_upper]

        sentiment = analyze_sentiment(title)

        for ticker in tickers:
            if ticker not in ticker_data:
                ticker_data[ticker] = {
                    "ticker": ticker,
                    "positive": 0,
                    "negative": 0,
                    "neutral": 0,
                    "total": 0,
                    "headlines": [],
                }
            ticker_data[ticker][sentiment] += 1
            ticker_data[ticker]["total"] += 1
            if len(ticker_data[ticker]["headlines"]) < 3:
                ticker_data[ticker]["headlines"].append({
                    "title": title[:60],
                    "sentiment": sentiment,
                })

    # Sort by total mentions
    result = sorted(ticker_data.values(), key=lambda x: x["total"], reverse=True)
    return result
