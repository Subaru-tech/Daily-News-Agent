import requests
import logging
from datetime import datetime

from config.settings import REDDIT_SUBS, CATEGORY_KEYWORDS

logger = logging.getLogger(__name__)

REDDIT_HEADERS = {"User-Agent": "DailyNewsAgent/1.0"}

_CAT_MAP = {
    "MachineLearning": "AI & Tech",
    "investing": "Finance & Stocks",
    "geopolitics": "Geo-Politics",
    "startups": "Startups",
    "IndianStockMarket": "Finance & Stocks",
}


def fetch_reddit(limit: int = 25) -> list[dict]:
    """Fetch hot posts from relevant subreddits."""
    articles = []

    for sub in REDDIT_SUBS:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
            resp = requests.get(url, headers=REDDIT_HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            for post in data.get("data", {}).get("children", []):
                pdata = post.get("data", {})
                title = pdata.get("title", "").strip()
                post_url = pdata.get("url", "")
                selftext = pdata.get("selftext", "")[:300]
                score = pdata.get("score", 0)
                comments = pdata.get("num_comments", 0)

                if not title or score < 10:
                    continue

                permalink = f"https://www.reddit.com{pdata.get('permalink', '')}"

                articles.append({
                    "title": title,
                    "url": post_url if post_url and not post_url.startswith("/r/") else permalink,
                    "summary": selftext if selftext else f"Score: {score} | Comments: {comments}",
                    "category": _CAT_MAP.get(sub, "General"),
                    "source": f"reddit/r/{sub}",
                    "source_type": "api",
                    "reddit_score": score,
                    "fetched_at": datetime.utcnow().isoformat(),
                })
        except Exception as e:
            logger.warning(f"[Reddit] Failed to fetch r/{sub}: {e}")

    logger.info(f"[Reddit] Fetched {len(articles)} posts from {len(REDDIT_SUBS)} subreddits")
    return articles
