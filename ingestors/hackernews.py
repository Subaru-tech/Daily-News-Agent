import requests
import logging
from datetime import datetime

from config.settings import CATEGORY_KEYWORDS

logger = logging.getLogger(__name__)

HN_BASE = "https://hacker-news.firebaseio.com/v0"

# Flattened keywords for quick relevance check
_ALL_KEYWORDS = []
for kws in CATEGORY_KEYWORDS.values():
    _ALL_KEYWORDS.extend(kws)


def _is_relevant(title: str) -> bool:
    """Check if HN story is relevant to our niches."""
    t = title.lower()
    return any(kw in t for kw in _ALL_KEYWORDS)


def _detect_category(title: str) -> str:
    """Detect best category from title."""
    t = title.lower()
    best_cat = "AI & Tech"  # HN default
    best_score = 0
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in t)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat


def fetch_hackernews(limit: int = 100) -> list[dict]:
    """Fetch top HN stories, filter by relevance."""
    articles = []
    try:
        resp = requests.get(f"{HN_BASE}/topstories.json", timeout=10)
        resp.raise_for_status()
        story_ids = resp.json()[:limit]

        for story_id in story_ids:
            try:
                item_resp = requests.get(
                    f"{HN_BASE}/item/{story_id}.json", timeout=5
                )
                item = item_resp.json()
                if not item or "title" not in item:
                    continue

                title = item["title"]
                if not _is_relevant(title):
                    continue

                url = item.get("url", f"https://news.ycombinator.com/item?id={story_id}")

                articles.append({
                    "title": title,
                    "url": url,
                    "summary": f"HN Score: {item.get('score', 0)} | "
                               f"Comments: {item.get('descendants', 0)}",
                    "category": _detect_category(title),
                    "source": "hackernews",
                    "source_type": "api",
                    "hn_score": item.get("score", 0),
                    "fetched_at": datetime.utcnow().isoformat(),
                })
            except Exception as e:
                logger.debug(f"[HN] Failed item {story_id}: {e}")

    except Exception as e:
        logger.error(f"[HN] Failed to fetch top stories: {e}")

    logger.info(f"[HN] Fetched {len(articles)} relevant stories from top {limit}")
    return articles
