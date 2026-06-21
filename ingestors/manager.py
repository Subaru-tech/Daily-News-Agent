import asyncio
import logging
import signal
import time
from typing import List, Dict, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import httpx
from concurrent.futures import ThreadPoolExecutor

from ingestors.rss_feeds import fetch_rss_feeds
from ingestors.hackernews import fetch_hackernews
from ingestors.reddit import fetch_reddit
from ingestors.currents import fetch_currents
from ingestors.gnews import fetch_gnews
from ingestors.newsdata import fetch_newsdata
from config.settings import WATCHED_TICKERS
from notifications.bot_commands import get_portfolio_tickers
from database.db import log_metric

logger = logging.getLogger(__name__)

@dataclass
class Article:
    id: str
    headline: str
    summary: str = ""
    source: str = ""
    url: str = ""
    published_at: str = ""
    tickers: List[str] = field(default_factory=list)
    cluster_id: str = ""
    verification: Dict[str, Any] = field(default_factory=dict)
    narrative: str = ""
    price_data: Dict[str, Any] = field(default_factory=dict)
    category: str = "General"

class AsyncIngestionManager:
    def __init__(
        self,
        llm_workers: int = 2,
        queue_maxsize: int = 200,
        jaccard_threshold: float = 0.75,
    ):
        self.llm_queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=queue_maxsize)
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
        )
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fetch_")
        
        self.jaccard_threshold = jaccard_threshold
        self.clusters: Dict[str, Dict[str, Any]] = {}
        self.recent_headlines: List[Tuple[str, Set[str]]] = []
        self.max_window = 500
        
        self._shutdown_event = asyncio.Event()
        self._llm_tasks: List[asyncio.Task] = []
        self._running = False
        self.llm_workers_count = llm_workers
        self.last_fetch_time = 0.0

    async def start(self):
        """Call once at application startup."""
        self._running = True
        self._llm_tasks = [
            asyncio.create_task(self._llm_worker(f"worker-{i}"))
            for i in range(self.llm_workers_count)
        ]
        logger.info("AsyncIngestionManager started with %d LLM workers", len(self._llm_tasks))

    async def shutdown(self):
        """Graceful shutdown. Call on SIGINT/SIGTERM."""
        logger.info("Shutting down ingestion manager...")
        self._running = False
        self._shutdown_event.set()
        
        for task in self._llm_tasks:
            task.cancel()
            
        try:
            await asyncio.wait_for(self.llm_queue.join(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Queue drain timed out, dropping tasks")
            
        if self.http_client:
            await self.http_client.aclose()
        self.executor.shutdown(wait=False)
        logger.info("Shutdown complete")

    # ==================================================================
    # FETCH CYCLE
    # ==================================================================
    async def fetch_from_all_sources(self) -> List[Dict]:
        loop = asyncio.get_running_loop()
        
        def _fetch_sync():
            from database.db import get_source_health, report_source_success, report_source_failure
            from datetime import datetime
            
            all_articles = []
            
            def _safe_fetch(source_id: str, fetch_func, *args, **kwargs):
                health = get_source_health(source_id)
                if health["next_attempt_at"] > datetime.utcnow():
                    logger.debug(f"[Manager] Skipping {source_id} (backoff until {health['next_attempt_at']})")
                    return
                try:
                    res = fetch_func(*args, **kwargs)
                    all_articles.extend(res)
                    report_source_success(source_id)
                except Exception as e:
                    logger.error(f"[Manager] {source_id} fetch error: {e}")
                    report_source_failure(source_id)

            # RSS Feeds (Internal tracking handles individual feeds)
            try:
                all_articles.extend(fetch_rss_feeds())
            except Exception as e:
                logger.error(f"[Manager] RSS fetch error: {e}")

            # HackerNews
            _safe_fetch("hackernews", fetch_hackernews, limit=50)
            
            # Reddit
            _safe_fetch("reddit", fetch_reddit, limit=15)
            
            # Currents API - Finance
            ticker_groups = [
                (" ".join(WATCHED_TICKERS[:4]), "Finance & Stocks"),
                (" ".join(WATCHED_TICKERS[4:7]), "Finance & Stocks"),
                ("Bitcoin Ethereum crypto", "Finance & Stocks"),
                ("RELIANCE INFY TCS NSE", "Finance & Stocks"),
            ]
            for i, (query, cat) in enumerate(ticker_groups):
                _safe_fetch(f"currents_finance_{i}", fetch_currents, query, category=cat, limit=5)

            # Currents API - Topics
            topic_searches = [
                ("artificial intelligence AI tools", "AI & Tech"),
                ("startup funding venture capital", "Startups"),
                ("geopolitics sanctions conflict", "Geo-Politics"),
            ]
            for i, (query, cat) in enumerate(topic_searches):
                _safe_fetch(f"currents_topics_{i}", fetch_currents, query, category=cat, limit=5)

            # GNews API
            gnews_queries = [("AI artificial intelligence", "AI & Tech"), ("stock market earnings", "Finance & Stocks")]
            for i, (query, cat) in enumerate(gnews_queries):
                _safe_fetch(f"gnews_{i}", fetch_gnews, query, category=cat, limit=3)
            return all_articles

        logger.info("[Manager] Fetching all raw sources asynchronously...")
        return await loop.run_in_executor(self.executor, _fetch_sync)


    async def run_fetch_cycle(self):
        """Called every 15 minutes by cron/scheduler."""
        start_time = time.monotonic()
        
        raw_articles = await self.fetch_from_all_sources()
        if not raw_articles:
            log_metric("fetch_cycle", int((time.monotonic() - start_time) * 1000), "all", False, 0.0)
            return

        articles = [self._normalize(a) for a in raw_articles]
        
        novel_articles = []
        for art in articles:
            cluster_id = self._assign_cluster(art)
            if cluster_id:
                art.cluster_id = cluster_id
                novel_articles.append(art)

        if not novel_articles:
            logger.info("All %d articles were duplicates", len(raw_articles))
            log_metric("fetch_cycle", int((time.monotonic() - start_time) * 1000), "all", False, 0.0)
            return

        affected_clusters = set()
        
        all_art_dicts = [
            {
                "title": a.headline,
                "category": a.category,
                "url": a.url,
                "source": a.source,
                "summary": a.summary
            }
            for a in articles
        ]

        for art in novel_articles:
            priority = 0 if self._is_portfolio_relevant(art) else 1
            await self.llm_queue.put((
                priority,
                time.monotonic(),
                {
                    "type": "verification",
                    "article": art,
                    "all_articles": all_art_dicts,
                }
            ))
            affected_clusters.add(art.cluster_id)

        for cid in affected_clusters:
            cluster = self.clusters.get(cid)
            if cluster and len(cluster["articles"]) > 1:
                await self.llm_queue.put((
                    2,
                    time.monotonic(),
                    {
                        "type": "narrative_drift",
                        "cluster_id": cid,
                        "cluster_data": cluster
                    }
                ))

        self.last_fetch_time = time.monotonic()
        novel_count = len(novel_articles)
        log_metric("fetch_cycle", int((time.monotonic() - start_time) * 1000), "all", True, float(novel_count))
        logger.info("Cycle complete: %d raw -> %d novel. Queue depth: %d", len(raw_articles), novel_count, self.llm_queue.qsize())

        # Volume Anomaly Detector
        if novel_count > 10:
            try:
                from database.db import get_recent_metrics
                recent = get_recent_metrics(24)
                if recent:
                    volumes = [m["llm_cost"] for m in recent if m.get("event_type") == "fetch_cycle"]
                    if len(volumes) >= 5:  # Need a baseline
                        avg_vol = sum(volumes) / len(volumes)
                        if avg_vol > 0 and novel_count > (avg_vol * 3):
                            msg = f"📈 *Volume Anomaly Detected*\n\nProcessed {novel_count} novel articles in this cycle (3x normal average of {avg_vol:.1f}). Possible major news event."
                            from notifications.telegram import _send_message
                            _send_message(msg)
            except Exception as e:
                logger.error(f"[Manager] Volume anomaly check failed: {e}")

    # ==================================================================
    # CLUSTERING (Jaccard)
    # ==================================================================
    def _tokenize(self, text: str) -> Set[str]:
        import re
        text = re.sub(r'[^\w\s]', '', text)
        return set(text.lower().split())

    def _jaccard(self, a: Set[str], b: Set[str]) -> float:
        if not a or not b: return 0.0
        union = len(a | b)
        return len(a & b) / union if union > 0 else 0.0

    def _assign_cluster(self, article: Article) -> str | None:
        tokens = self._tokenize(article.headline)
        
        for headline, existing_tokens in self.recent_headlines[-50:]: 
            if self._jaccard(tokens, existing_tokens) > 0.92:
                return None  # Drop duplicate
        
        best_cid = None
        best_score = 0.0
        
        for cid, cluster in self.clusters.items():
            if article.category == cluster.get("category"):
                score = self._jaccard(tokens, cluster["centroid_tokens"])
                if score > best_score:
                    best_score = score
                    best_cid = cid
        
        if best_cid and best_score >= self.jaccard_threshold:
            self.clusters[best_cid]["articles"].append(article)
            self.clusters[best_cid]["centroid_tokens"].update(tokens)
            return best_cid
        
        new_cid = f"cluster_{hash(article.id)}_{int(time.time())}"
        self.clusters[new_cid] = {
            "id": new_cid,
            "centroid_tokens": set(tokens),
            "articles": [article],
            "narrative": None,
            "category": article.category,
        }
        
        self.recent_headlines.append((article.headline, tokens))
        if len(self.recent_headlines) > self.max_window:
            self.recent_headlines.pop(0)
            
        return new_cid

    # ==================================================================
    # LLM WORKERS
    # ==================================================================
    async def _llm_worker(self, name: str):
        logger.info("[%s] Started", name)
        while not self._shutdown_event.is_set():
            try:
                priority, _, task = await asyncio.wait_for(self.llm_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            
            try:
                if task["type"] == "verification":
                    await self._verify_article(task["article"], task.get("all_articles", []))
                elif task["type"] == "narrative_drift":
                    await self._synthesize_narrative(task)
                
                # Rate limit protection for Groq (30 RPM free tier = 2s delay)
                await asyncio.sleep(2.0)
            except Exception as e:
                logger.error("[%s] Task failed: %s", name, e, exc_info=True)
            finally:
                self.llm_queue.task_done()

    async def _verify_article(self, article: Article, all_articles: List[Dict] = []):
        """Invoke structured check, then potentially LLM check, then dispatch."""
        from verification.structured import verify_structured
        from config.settings import CONFIDENCE_THRESHOLD_CALENDAR
        
        # 1. Structured Validation 
        # (Assuming existing logic expects a dict, we pass dict representations)
        raw_dict = {"title": article.headline, "category": article.category, "url": article.url, "source": article.source, "summary": article.summary}
        base_result = verify_structured(raw_dict, all_articles or [raw_dict])
        
        article.verification = {
            "confidence": base_result.get("confidence", 50),
            "verification_status": base_result.get("verification_status", "unverified"),
            "reasoning": base_result.get("reasoning", ""),
        }
        article.tickers = base_result.get("tickers", [])
        article.price_data = base_result.get("price_data", {})
        article.category = base_result.get("category", article.category)

        # 2. Add Narrative Drift note if cluster is large
        drift = self.clusters.get(article.cluster_id, {}).get("narrative")
        if drift and "consistently report" not in drift.lower():
            article.verification["reasoning"] += f" | Narrative Drift: {drift}"

        # 3. LLM API checking if ambiguous
        conf = article.verification["confidence"]
        if 40 <= conf <= 65:
            prompt = self._build_verification_prompt(article)
            if not self._groq_key:
                logger.warning(f"Async LLM verification skipped for {article.id}: GROQ_API_KEY missing")
                await self._dispatch(article)
                return
            try:
                response = await self.http_client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._groq_key}"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [{"role": "system", "content": "You are a fact-checking analyst. Return only JSON."}, {"role": "user", "content": prompt}],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.1,
                        "max_tokens": 512,
                    }
                )
                response.raise_for_status()
                data = response.json()
                import json
                llm_parsed = json.loads(data["choices"][0]["message"]["content"])
                
                if llm_parsed.get("confidence", 0) != 50:
                    article.verification["confidence"] = llm_parsed["confidence"]
                    article.verification["reasoning"] += " | LLM: " + llm_parsed.get("reasoning", "")
                    article.verification["verification_status"] = llm_parsed.get("verification_status", article.verification["verification_status"])
            
            except Exception as e:
                logger.warning(f"Async LLM verification failed for {article.id}: {e}")

        # 4. Dispatch!
        await self._dispatch(article)

    async def _synthesize_narrative(self, task: Dict):
        cluster_data = task["cluster_data"]
        articles = cluster_data.get("articles", [])
        if len(articles) < 2: return
            
        sources = [a.source for a in articles]
        headlines = [a.headline for a in articles]
        
        prompt = f"Sources: {sources}\nHeadlines: {headlines}\nSynthesize in 1-2 sentences how reporting differs or converges. If exactly the same across sources, state 'Sources consistently report this event.'"
        
        if not self._groq_key:
            logger.warning("Narrative synthesis skipped: GROQ_API_KEY missing")
            return
            
        try:
            response = await self.http_client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._groq_key}"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "system", "content": "You analyze news bias and progression."}, {"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 128,
                }
            )
            response.raise_for_status()
            data = response.json()
            narrative = data["choices"][0]["message"]["content"].strip()
            self.clusters[task["cluster_id"]]["narrative"] = narrative
            logger.info("Updated narrative for %s", task["cluster_id"])
        except Exception as e:
            logger.error("Narrative synthesis failed: %s", e)

    async def _dispatch(self, article: Article):
        """Asynchronous wrap for database save, telegram alerts, etc."""
        from database.db import save_claim, update_claim_calendar_id
        from calendar_sync.google_cal import create_news_event
        from digest.breaking import BREAKING_CATEGORIES, CONFIDENCE_THRESHOLD_BREAKING
        from notifications.telegram import send_breaking_alert
        from database.db import mark_breaking_sent
        from config.settings import CONFIDENCE_THRESHOLD_CALENDAR

        # 1. Transform back to dict for generic DB functions 
        c = article.verification["confidence"]
        
        # Portfolio overrides
        if self._is_portfolio_relevant(article):
            article.verification["is_portfolio_alert"] = True
            
        art_dict = {
            "id": article.id, "title": article.headline, "summary": article.summary,
            "url": article.url, "source": article.source, "category": article.category,
            "tickers": article.tickers, "price_data": article.price_data, 
            "confidence": c,
            "verification_status": article.verification["verification_status"],
            "reasoning": article.verification["reasoning"],
            "sources": [article.source],
            "is_portfolio": article.verification.get("is_portfolio_alert", False)
        }

        # 2. Database Save
        claim_id = save_claim(art_dict)
        if claim_id:
            art_dict["id"] = claim_id
        
        # 3. Calendar
        if claim_id and c >= CONFIDENCE_THRESHOLD_CALENDAR:
            try:
                loop = asyncio.get_running_loop()
                event_id = await loop.run_in_executor(self.executor, lambda: create_news_event(art_dict))
                if event_id:
                    update_claim_calendar_id(claim_id, event_id)
            except Exception as e:
                logger.error(f"Failed to sync calendar for {claim_id}: {e}")

        # 4. Breaking Alerts
        is_port = article.verification.get("is_portfolio_alert")
        if (is_port and c >= 70) or (article.category in BREAKING_CATEGORIES and c >= CONFIDENCE_THRESHOLD_BREAKING):
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(self.executor, lambda: send_breaking_alert(art_dict))
                if claim_id:
                    mark_breaking_sent(claim_id)
            except Exception as e:
                logger.error(f"Failed to send breaking alert for {claim_id}: {e}")


    # ==================================================================
    # HELPERS
    # ==================================================================
    def _normalize(self, raw: Dict) -> Article:
        import hashlib
        return Article(
            id=raw.get("id", hashlib.md5(raw.get("url", str(time.time())).encode()).hexdigest()[:12]),
            headline=raw.get("headline") or raw.get("title") or "",
            summary=raw.get("summary", ""),
            source=raw.get("source", ""),
            url=raw.get("url", raw.get("link", "")),
            published_at=raw.get("published_at", ""),
            tickers=raw.get("tickers", []),
            category=raw.get("category", "General")
        )

    def _is_portfolio_relevant(self, article: Article) -> bool:
        portfolio = get_portfolio_tickers()
        if not portfolio: return False
        article_tickers = set(t.upper() for t in article.tickers)
        return not article_tickers.isdisjoint(portfolio)

    def _build_verification_prompt(self, article: Article) -> str:
        return (f"Title: {article.headline}\nSummary: {article.summary}\nSource: {article.source}\n"
                "Return a JSON object with exactly these fields: "
                "{\"category\": \"...\", \"confidence\": (0-100), \"claim_type\": \"...\", \"verification_status\": \"...\", "
                "\"key_claims\": [], \"red_flags\": [], \"reasoning\": \"...\"}")

    @property
    def _groq_key(self) -> str:
        import os
        return os.getenv("GROQ_API_KEY", "")

# Global singleton
manager = AsyncIngestionManager()
