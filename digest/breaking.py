import logging

from database.db import get_claims_since, mark_breaking_sent
from config.settings import CONFIDENCE_THRESHOLD_BREAKING, BREAKING_CATEGORIES

logger = logging.getLogger(__name__)


def check_breaking_news() -> list[dict]:
    """
    Check for high-confidence breaking news since last check (30 min window).
    Only triggers for Finance & Stocks and Geo-Politics categories.
    Requires confidence >= 85%.
    """
    claims = get_claims_since(hours=1, sent_field="breaking_sent")

    breaking = []
    for claim in claims:
        category = claim.get("category", "")
        confidence = claim.get("confidence", 0)

        if category in BREAKING_CATEGORIES and confidence >= CONFIDENCE_THRESHOLD_BREAKING:
            breaking.append(claim)
            mark_breaking_sent(claim["id"])

    if breaking:
        logger.info(f"[Breaking] {len(breaking)} breaking alerts triggered")

    return breaking
