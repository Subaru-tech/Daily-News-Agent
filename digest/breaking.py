import logging

from database.db import get_claims_since, mark_breaking_sent
from config.settings import CONFIDENCE_THRESHOLD_BREAKING, BREAKING_CATEGORIES

from notifications.bot_commands import get_portfolio_tickers

logger = logging.getLogger(__name__)


def check_breaking_news() -> list[dict]:
    """
    Check for high-confidence breaking news since last check.
    Triggers for Finance/Geo-Politics >= 85%.
    ALSO triggers for ANY category matching a user portfolio ticker >= 70%.
    """
    claims = get_claims_since(hours=1, sent_field="breaking_sent")
    portfolio = get_portfolio_tickers()

    breaking = []
    for claim in claims:
        category = claim.get("category", "")
        confidence = claim.get("confidence", 0)
        
        tickers = claim.get("tickers", [])
        if isinstance(tickers, str):
            import json
            try: tickers = json.loads(tickers)
            except: tickers = []

        is_portfolio = any(t in portfolio for t in tickers)

        if is_portfolio and confidence >= 70:
            claim["is_portfolio"] = True
            breaking.append(claim)
            mark_breaking_sent(claim["id"])
        elif category in BREAKING_CATEGORIES and confidence >= CONFIDENCE_THRESHOLD_BREAKING:
            breaking.append(claim)
            mark_breaking_sent(claim["id"])

    if breaking:
        logger.info(f"[Breaking] {len(breaking)} breaking alerts triggered")

    return breaking
