import json
import logging

from groq import Groq
from config.settings import GROQ_API_KEY, NEWS_CATEGORIES
from database.db import check_cache, set_cache
from verification.structured import _text_hash

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None and GROQ_API_KEY:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def verify_with_llm(article: dict) -> dict:
    """
    LLM-powered verification for complex claims (~20% of articles).
    Uses Groq API with Llama-3.1-70B.

    Called when:
    - Structured verification gives 40-60% confidence (ambiguous)
    - Article contains comparative claims ("X beats Y")
    - Multiple contradictory signals detected
    """
    client = _get_client()
    if not client:
        logger.warning("[LLM] No Groq API key configured")
        return {"confidence": 50, "category": "General", "reasoning": "LLM unavailable"}

    # Check cache
    cache_key = "llm_" + _text_hash(article["title"])
    cached = check_cache(cache_key)
    if cached:
        return cached

    title = article.get("title", "")
    summary = article.get("summary", "")
    source = article.get("source", "")

    prompt = f"""Analyze this news article for verification. Be skeptical and precise.

Title: {title}
Summary: {summary}
Source: {source}

Return a JSON object with exactly these fields:
{{
  "category": one of {json.dumps(NEWS_CATEGORIES)},
  "confidence": integer 0-100 (how confident this is a real, verified event),
  "claim_type": "factual_event" | "performance_comparison" | "prediction" | "opinion" | "announcement",
  "verification_status": "verified" | "unverified" | "disputed",
  "key_claims": ["list of specific verifiable claims extracted"],
  "red_flags": ["list of any hype, vagueness, or unverifiable elements"],
  "reasoning": "one paragraph explaining your confidence assessment"
}}

Guidelines:
- Official announcements from companies/gov = higher confidence
- Performance comparisons need specific benchmarks to be verifiable
- Predictions are never "verified", cap at 50% confidence
- Vague claims like "revolutionary" or "game-changing" are red flags
- Multiple independent sources increase confidence
- Single anonymous source = low confidence
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a fact-checking analyst. Return only valid JSON, no markdown."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500,
        )

        result = json.loads(response.choices[0].message.content)

        # Normalize fields
        result.setdefault("confidence", 50)
        result.setdefault("category", "General")
        result.setdefault("verification_status", "unverified")
        result.setdefault("reasoning", "LLM analysis completed")

        # Cache result
        set_cache(cache_key, result)
        logger.info(f"[LLM] Verified: '{title[:50]}...' → {result['confidence']}%")
        return result

    except Exception as e:
        logger.error(f"[LLM] Verification failed: {e}")
        return {
            "confidence": 50,
            "category": article.get("category", "General"),
            "verification_status": "unverified",
            "reasoning": f"LLM verification failed: {str(e)}",
        }


def needs_llm_verification(article: dict, structured_result: dict) -> bool:
    """
    Decide if an article needs LLM verification on top of structured checks.

    Triggers:
    - Ambiguous confidence (40-65%)
    - Comparative claims in title
    - Hype language detected
    """
    confidence = structured_result.get("confidence", 0)

    # Ambiguous confidence zone
    if 40 <= confidence <= 65:
        return True

    # Comparative claims
    title_lower = article.get("title", "").lower()
    comparison_words = ["beats", "better than", "outperforms", "crushes",
                        "vs", "versus", "compared to", "surpasses"]
    if any(w in title_lower for w in comparison_words):
        return True

    # Contains hype + high source reliability (contradiction = needs LLM)
    if "Hype language" in structured_result.get("reasoning", "") and confidence > 50:
        return True

    return False
