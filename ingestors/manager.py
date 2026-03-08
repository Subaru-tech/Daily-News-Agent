import hashlib
import logging
from datetime import datetime

from ingestors.rss_feeds import fetch_rss_feeds
from ingestors.hackernews import fetch_hackernews
from ingestors.reddit import fetch_reddit
from ingestors.currents import fetch_currents
from ingestors.gnews import fetch_gnews
from ingestors.newsdata import fetch_newsdata
from config.settings import WATCHED_TICKERS, CATEGORY_KEYWORDS

logger = logging.getLogger(__name__)


def _dedup_articles(articles: list[dict]) -> list[dict]:
    """Deduplicate articles by URL hash."""
    seen = set()
    unique = []
    for a in articles:
        h = hashlib.sha256(a["url"].encode()).hexdigest()[:16]
        if h not in seen:
            seen.add(h)
            unique.append(a)
    return unique


def _api_keyword_searches() -> list[dict]:
    """Run targeted API searches for watched tickers and trending topics."""
    articles = []

    # Ticker-specific searches via Currents (primary API)
    ticker_groups = [
        (" ".join(WATCHED_TICKERS[:4]), "Finance & Stocks"),   # NVDA TSLA AAPL MSFT
        (" ".join(WATCHED_TICKERS[4:7]), "Finance & Stocks"),  # GOOGL AMZN META
        ("Bitcoin Ethereum crypto", "Finance & Stocks"),
        ("RELIANCE INFY TCS NSE", "Finance & Stocks"),
    ]
    for query, cat in ticker_groups:
        articles.extend(fetch_currents(query, category=cat, limit=5))

    # Topic searches via Currents
    topic_searches = [
        ("artificial intelligence AI tools", "AI & Tech"),
        ("startup funding venture capital", "Startups"),
        ("geopolitics sanctions conflict", "Geo-Politics"),
    ]
    for query, cat in topic_searches:
        articles.extend(fetch_currents(query, category=cat, limit=5))

    # GNews backup for top stories
    gnews_queries = [
        ("AI artificial intelligence", "AI & Tech"),
        ("stock market earnings", "Finance & Stocks"),
        ("war sanctions geopolitics", "Geo-Politics"),
    ]
    for query, cat in gnews_queries:
        articles.extend(fetch_gnews(query, category=cat, limit=5))

    # NewsData for deep verification (use sparingly)
    newsdata_queries = [
        ("NVIDIA Tesla Apple earnings", "Finance & Stocks"),
        ("startup Series funding India", "Startups"),
    ]
    for query, cat in newsdata_queries:
        articles.extend(fetch_newsdata(query, category=cat, limit=5))

    return articles


def fetch_all() -> list[dict]:
    """
    Orchestrate all ingestors. Returns deduplicated list of articles.

    Priority:
    1. RSS feeds (unlimited, primary volume)
    2. HackerNews API (unlimited, tech signal)
    3. Reddit (60/min, community sentiment)
    4. Currents API (600/day, structured search)
    5. GNews (100/day, backup)
    6. NewsData (16/day, verification only)
    """
    all_articles = []

    # === Tier 1: Unlimited sources ===
    logger.info("[Manager] Fetching RSS feeds...")
    all_articles.extend(fetch_rss_feeds())

    logger.info("[Manager] Fetching HackerNews...")
    all_articles.extend(fetch_hackernews(limit=50))

    logger.info("[Manager] Fetching Reddit...")
    all_articles.extend(fetch_reddit(limit=15))

    # === Tier 2: Rate-limited APIs ===
    logger.info("[Manager] Running API keyword searches...")
    all_articles.extend(_api_keyword_searches())

    # === Deduplicate ===
    unique = _dedup_articles(all_articles)

    logger.info(
        f"[Manager] Total: {len(all_articles)} raw → {len(unique)} unique articles"
    )
    return unique
