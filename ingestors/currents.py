import requests
import logging
from datetime import datetime

from config.settings import CURRENTS_API_KEY
from database.db import get_quota, increment_quota

logger = logging.getLogger(__name__)

CURRENTS_URL = "https://api.currentsapi.services/v1/search"
DAILY_LIMIT = 600


def fetch_currents(keywords: str, category: str | None = None, limit: int = 10) -> list[dict]:
    """Search Currents API. 600 req/day free tier."""
    if not CURRENTS_API_KEY:
        logger.warning("[Currents] No API key configured")
        return []

    quota = get_quota("currents")
    if quota["calls_used"] >= DAILY_LIMIT:
        logger.info("[Currents] Daily quota reached")
        return []

    articles = []
    try:
        params = {
            "keywords": keywords,
            "language": "en",
            "apiKey": CURRENTS_API_KEY,
            "page_size": limit,
        }
        if category:
            params["category"] = category

        resp = requests.get(CURRENTS_URL, params=params, timeout=15)
        resp.raise_for_status()
        increment_quota("currents")

        data = resp.json()
        for item in data.get("news", []):
            articles.append({
                "title": item.get("title", "").strip(),
                "url": item.get("url", ""),
                "summary": item.get("description", "")[:500],
                "category": category or "General",
                "source": "currents_api",
                "source_type": "api",
                "fetched_at": datetime.utcnow().isoformat(),
            })
    except Exception as e:
        logger.error(f"[Currents] Failed search '{keywords}': {e}")

    return articles
