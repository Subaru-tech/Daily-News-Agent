import requests
import logging
from datetime import datetime

from config.settings import GNEWS_API_KEY
from database.db import get_quota, increment_quota

logger = logging.getLogger(__name__)

GNEWS_URL = "https://gnews.io/api/v4/search"
DAILY_LIMIT = 100


def fetch_gnews(query: str, category: str = "General", limit: int = 10) -> list[dict]:
    """Search GNews API. 100 req/day free tier."""
    if not GNEWS_API_KEY:
        logger.warning("[GNews] No API key configured")
        return []

    quota = get_quota("gnews")
    if quota["calls_used"] >= DAILY_LIMIT:
        logger.info("[GNews] Daily quota reached")
        return []

    articles = []
    try:
        params = {
            "q": query,
            "lang": "en",
            "token": GNEWS_API_KEY,
            "max": limit,
        }

        resp = requests.get(GNEWS_URL, params=params, timeout=15)
        resp.raise_for_status()
        increment_quota("gnews")

        data = resp.json()
        for item in data.get("articles", []):
            articles.append({
                "title": item.get("title", "").strip(),
                "url": item.get("url", ""),
                "summary": item.get("description", "")[:500],
                "category": category,
                "source": "gnews_api",
                "source_type": "api",
                "fetched_at": datetime.utcnow().isoformat(),
            })
    except Exception as e:
        logger.error(f"[GNews] Failed search '{query}': {e}")

    return articles
