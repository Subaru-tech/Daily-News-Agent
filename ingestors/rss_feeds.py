import feedparser
import logging
from datetime import datetime

from config.settings import RSS_SOURCES, CATEGORY_KEYWORDS

logger = logging.getLogger(__name__)


def _match_category(title: str, summary: str) -> str:
    """Match article to best category by keyword overlap."""
    text = f"{title} {summary}".lower()
    best_cat = "General"
    best_score = 0
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat


def fetch_rss_feeds() -> list[dict]:
    """Fetch articles from all RSS feeds, return normalized list."""
    articles = []

    for category, urls in RSS_SOURCES.items():
        for url in urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:  # Top 5 per source
                    title = entry.get("title", "").strip()
                    link = entry.get("link", "").strip()
                    summary = entry.get("summary", "").strip()

                    if not title or not link:
                        continue

                    # Trim summary to 500 chars
                    if len(summary) > 500:
                        summary = summary[:497] + "..."

                    # Try RSS category first, fallback to keyword matching
                    detected_cat = _match_category(title, summary)
                    final_category = detected_cat if detected_cat != "General" else category

                    articles.append({
                        "title": title,
                        "url": link,
                        "summary": summary,
                        "category": final_category,
                        "source": url,
                        "source_type": "rss",
                        "published": entry.get("published", ""),
                        "fetched_at": datetime.utcnow().isoformat(),
                    })
            except Exception as e:
                logger.warning(f"[RSS] Failed to fetch {url}: {e}")

    logger.info(f"[RSS] Fetched {len(articles)} articles from {sum(len(v) for v in RSS_SOURCES.values())} feeds")
    return articles
