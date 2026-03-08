import requests
import logging
from datetime import datetime

from config.settings import NEWSDATA_API_KEY
from database.db import get_quota, increment_quota

logger = logging.getLogger(__name__)

NEWSDATA_URL = "https://newsdata.io/api/1/news"
DAILY_LIMIT = 16  # 500/month ≈ 16/day


def fetch_newsdata(query: str, category: str = "General", limit: int = 10) -> list[dict]:
    """Search NewsData.io API. ~16 req/day (500/month)."""
    if not NEWSDATA_API_KEY:
        logger.warning("[NewsData] No API key configured")
        return []

    quota = get_quota("newsdata")
    if quota["calls_used"] >= DAILY_LIMIT:
        logger.info("[NewsData] Daily quota reached")
        return []

    articles = []
    try:
        params = {
            "q": query,
            "language": "en",
            "apikey": NEWSDATA_API_KEY,
            "size": limit,
        }

        resp = requests.get(NEWSDATA_URL, params=params, timeout=15)
        resp.raise_for_status()
        increment_quota("newsdata")

        data = resp.json()
        for item in data.get("results", []):
            articles.append({
                "title": item.get("title", "").strip(),
                "url": item.get("link", ""),
                "summary": (item.get("description") or "")[:500],
                "category": category,
                "source": "newsdata_api",
                "source_type": "api",
                "fetched_at": datetime.utcnow().isoformat(),
            })
    except Exception as e:
        logger.error(f"[NewsData] Failed search '{query}': {e}")

    return articles
