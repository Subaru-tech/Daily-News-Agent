import logging
from datetime import datetime

from database.db import get_claims_since, mark_digest_sent
from config.settings import MAX_ITEMS_PER_DIGEST

logger = logging.getLogger(__name__)


def compile_morning_digest() -> list[dict]:
    """
    Compile articles for the 8 AM morning brief.
    Looks back 14 hours (6 PM yesterday to 8 AM today).
    Returns top items by confidence, unsent only.
    """
    claims = get_claims_since(hours=14, sent_field="morning_sent")

    # Sort by confidence descending
    claims.sort(key=lambda c: c.get("confidence", 0), reverse=True)

    # Take top N
    top = claims[:MAX_ITEMS_PER_DIGEST]

    if top:
        ids = [c["id"] for c in top]
        mark_digest_sent(ids, "morning_sent")
        logger.info(f"[Digest] Morning: {len(top)} items compiled")

    return top
