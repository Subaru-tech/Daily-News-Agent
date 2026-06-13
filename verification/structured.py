import hashlib
import logging
import requests
from datetime import datetime

from config.settings import WATCHED_TICKERS, CATEGORY_KEYWORDS, TICKER_ALIASES
from database.db import check_cache, set_cache

logger = logging.getLogger(__name__)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _count_keyword_hits(text: str, category: str) -> int:
    """Count how many category keywords appear in text."""
    t = text.lower()
    keywords = CATEGORY_KEYWORDS.get(category, [])
    return sum(1 for kw in keywords if kw in t)


def _check_multi_source(article: dict, all_articles: list[dict]) -> int:
    """Check if the same event is reported by multiple sources."""
    title_words = set(article["title"].lower().split())
    # Remove common words
    title_words -= {"the", "a", "an", "is", "are", "was", "in", "to", "for", "of", "on", "at", "and", "or"}

    if len(title_words) < 3:
        return 0

    count = 0
    for other in all_articles:
        if other["url"] == article["url"]:
            continue
        other_words = set(other["title"].lower().split())
        overlap = title_words & other_words
        if len(overlap) >= 3:
            count += 1

    return count


def _check_ticker_mention(article: dict) -> dict:
    """Check if any watched ticker is mentioned, get basic price context."""
    text = f"{article['title']} {article.get('summary', '')}".upper()
    text_lower = f"{article['title']} {article.get('summary', '')}".lower()
    
    # 1. Check direct mentions
    mentioned = set([t for t in WATCHED_TICKERS if t in text])
    
    # 2. Check indirect aliases
    for alias, mapped_tickers in TICKER_ALIASES.items():
        if alias in text_lower:
            mentioned.update(mapped_tickers)
            
    mentioned = list(mentioned)

    result = {"tickers_mentioned": mentioned, "price_data": {}}

    # Fetch basic price for US tickers (free Yahoo Finance)
    for ticker in mentioned[:3]:  # Max 3 to avoid rate limits
        try:
            if ticker in ("BTC", "ETH"):
                symbol = f"{ticker}-USD"
            elif ticker in ("RELIANCE", "INFY", "TCS"):
                symbol = f"{ticker}.NS"
            else:
                symbol = ticker

            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
            resp = requests.get(url, timeout=5, headers={"User-Agent": "DailyNewsAgent/1.0"})
            if resp.status_code == 200:
                data = resp.json()
                meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                result["price_data"][ticker] = {
                    "price": meta.get("regularMarketPrice", 0),
                    "prev_close": meta.get("previousClose", 0),
                    "change_pct": round(
                        ((meta.get("regularMarketPrice", 0) - meta.get("previousClose", 1))
                         / meta.get("previousClose", 1)) * 100, 2
                    ) if meta.get("previousClose") else 0,
                }
        except Exception as e:
            logger.debug(f"[Verify] Price fetch failed for {ticker}: {e}")

    return result


def verify_structured(article: dict, all_articles: list[dict]) -> dict:
    """
    Structured verification (no LLM). Handles ~80% of claims.

    Returns:
        {
            "confidence": 0-100,
            "category": str,
            "verification_status": str,
            "reasoning": str,
            "tickers": list,
            "price_data": dict,
        }
    """
    # Check cache first
    cache_key = _text_hash(article["title"])
    cached = check_cache(cache_key)
    if cached:
        return cached

    title = article.get("title", "")
    summary = article.get("summary", "")
    text = f"{title} {summary}"
    source_type = article.get("source_type", "rss")

    confidence = 30  # Base confidence
    reasoning_parts = []

    # ── 1. Source reliability ──
    source = article.get("source", "")
    if any(s in source for s in ["reuters", "bbc", "ap", "sec.gov", "federalreserve", "rbi.org"]):
        confidence += 25
        reasoning_parts.append("High-reliability source (+25)")
    elif any(s in source for s in ["hackernews", "techcrunch", "bloomberg", "wsj", "moneycontrol"]):
        confidence += 15
        reasoning_parts.append("Reputable source (+15)")
    elif "reddit" in source:
        confidence += 5
        reasoning_parts.append("Community source (+5)")
    else:
        confidence += 10
        reasoning_parts.append("Standard source (+10)")

    # ── 1.5. Source Credibility (Historical) ──
    try:
        from urllib.parse import urlparse
        from database.db import get_source_credibility
        url = article.get("url", "")
        domain = urlparse(url).netloc.lower().replace("www.", "")
        if not domain:
            domain = source.lower()
            
        cred = get_source_credibility(domain)
        # Normalize credibility: 50 is neutral, 100 adds 15, 0 subtracts 15
        cred_modifier = (cred - 50) * 0.3
        confidence += cred_modifier
        if abs(cred_modifier) > 1.0:
            reasoning_parts.append(f"Historical Credibility {cred:.1f}/100 ({cred_modifier:+.1f})")
    except Exception as e:
        logger.debug(f"[Verify] Source credibility check failed: {e}")

    # ── 2. Multi-source corroboration ──
    corroboration = _check_multi_source(article, all_articles)
    if corroboration >= 3:
        confidence += 20
        reasoning_parts.append(f"Reported by {corroboration + 1} sources (+20)")
    elif corroboration >= 1:
        confidence += 10
        reasoning_parts.append(f"Reported by {corroboration + 1} sources (+10)")

    # ── 3. Category keyword relevance ──
    best_cat = article.get("category", "General")
    best_score = 0
    for cat, _ in CATEGORY_KEYWORDS.items():
        score = _count_keyword_hits(text, cat)
        if score > best_score:
            best_score = score
            best_cat = cat
    if best_score >= 3:
        confidence += 5
        reasoning_parts.append(f"Strong category match: {best_cat} (+5)")

    # ── 4. Ticker enrichment ──
    ticker_info = _check_ticker_mention(article)
    if ticker_info["tickers_mentioned"]:
        confidence += 5
        reasoning_parts.append(f"Tickers: {', '.join(ticker_info['tickers_mentioned'])} (+5)")

    # ── 5. HN score boost ──
    if article.get("hn_score", 0) > 100:
        confidence += 10
        reasoning_parts.append(f"HN score {article['hn_score']} (+10)")
    elif article.get("reddit_score", 0) > 100:
        confidence += 5
        reasoning_parts.append(f"Reddit score {article['reddit_score']} (+5)")

    # ── 6. Hype detection (reduce confidence) ──
    hype_words = ["breakthrough", "revolutionary", "game-changing", "disruptive",
                  "to the moon", "100x", "crushes", "destroys", "killer"]
    hype_count = sum(1 for w in hype_words if w in text.lower())
    hype_score = hype_count * 15
    if hype_count >= 2:
        confidence -= 15
        reasoning_parts.append(f"Hype language detected ({hype_count} terms, -15)")

    # Cap confidence
    confidence = max(0, min(100, confidence))

    # Determine status
    if confidence >= 70:
        status = "verified"
    elif confidence >= 40:
        status = "unverified"
    else:
        status = "disputed"

    result = {
        "confidence": confidence,
        "category": best_cat,
        "verification_status": status,
        "reasoning": " | ".join(reasoning_parts),
        "tickers": ticker_info["tickers_mentioned"],
        "price_data": ticker_info["price_data"],
        "hype_score": hype_score,
    }

    # Cache result
    set_cache(cache_key, result)
    return result
