import os
import json
import hashlib
import logging
from datetime import datetime, timedelta

from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

_is_postgres = DATABASE_URL.startswith("postgres")


def get_connection():
    """Get a database connection (SQLite for local, PostgreSQL for Render)."""
    if _is_postgres:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    else:
        import sqlite3
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _q(query: str) -> str:
    """Convert query placeholders for the current database.
    Write all queries using %s (PostgreSQL style).
    This function converts them to ? for SQLite.
    """
    if not _is_postgres:
        return query.replace("%s", "?")
    return query


def init_db():
    """Initialize the database schema with connection retries."""
    import time
    conn = None
    for attempt in range(15):
        try:
            conn = get_connection()
            break
        except Exception as e:
            logger.warning(f"[DB] Waiting for database (attempt {attempt+1}/15): {e}")
            if attempt < 14:
                time.sleep(5)
    
    if not conn:
        logger.error("[DB] FATAL: Could not connect to database after 75 seconds of retries.")
        raise RuntimeError("Database connection failed")

    try:
        cur = conn.cursor()

        if _is_postgres:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    id              SERIAL PRIMARY KEY,
                    title           TEXT NOT NULL,
                    url             TEXT NOT NULL,
                    url_hash        TEXT NOT NULL,
                    summary         TEXT DEFAULT '',
                    category        TEXT DEFAULT 'General',
                    confidence      INTEGER DEFAULT 0,
                    verification_status TEXT DEFAULT 'unverified',
                    sources_json    TEXT DEFAULT '[]',
                    calendar_event_id TEXT DEFAULT NULL,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    morning_sent    BOOLEAN DEFAULT false,
                    evening_sent    BOOLEAN DEFAULT false,
                    breaking_sent   BOOLEAN DEFAULT false,
                    debunked        BOOLEAN DEFAULT false,
                    debunked_note   TEXT DEFAULT NULL,
                    reasoning       TEXT DEFAULT '',
                    tickers_json    TEXT DEFAULT '[]',
                    price_data_json TEXT DEFAULT '{}',
                    hype_score      INTEGER DEFAULT 0
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    title           TEXT NOT NULL,
                    url             TEXT NOT NULL,
                    url_hash        TEXT NOT NULL,
                    summary         TEXT DEFAULT '',
                    category        TEXT DEFAULT 'General',
                    confidence      INTEGER DEFAULT 0,
                    verification_status TEXT DEFAULT 'unverified',
                    sources_json    TEXT DEFAULT '[]',
                    calendar_event_id TEXT DEFAULT NULL,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    morning_sent    BOOLEAN DEFAULT 0,
                    evening_sent    BOOLEAN DEFAULT 0,
                    breaking_sent   BOOLEAN DEFAULT 0,
                    debunked        BOOLEAN DEFAULT 0,
                    debunked_note   TEXT DEFAULT NULL,
                    reasoning       TEXT DEFAULT '',
                    tickers_json    TEXT DEFAULT '[]',
                    price_data_json TEXT DEFAULT '{}',
                    hype_score      INTEGER DEFAULT 0
                )
            """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_claims_url_hash ON claims(url_hash)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_claims_created_at ON claims(created_at)
        """)

        if _is_postgres:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS verification_cache (
                    claim_hash      TEXT PRIMARY KEY,
                    result_json     TEXT NOT NULL,
                    verified_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_quotas (
                    api_name        TEXT PRIMARY KEY,
                    calls_used      INTEGER DEFAULT 0,
                    resets_at       TIMESTAMP NOT NULL
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS verification_cache (
                    claim_hash      TEXT PRIMARY KEY,
                    result_json     TEXT NOT NULL,
                    verified_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_quotas (
                    api_name        TEXT PRIMARY KEY,
                    calls_used      INTEGER DEFAULT 0,
                    resets_at       TIMESTAMP NOT NULL
                )
            """)

        # Add hype_score if missing
        try:
            cur.execute("ALTER TABLE claims ADD COLUMN hype_score INTEGER DEFAULT 0")
        except Exception:
            pass  # Ignore if column already exists

        # System Metrics table
        if _is_postgres:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS system_metrics (
                    id              SERIAL PRIMARY KEY,
                    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_type      TEXT NOT NULL,
                    latency_ms      INTEGER DEFAULT 0,
                    source          TEXT DEFAULT '',
                    cache_hit       BOOLEAN DEFAULT FALSE,
                    llm_cost        REAL DEFAULT 0.0
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS system_metrics (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_type      TEXT NOT NULL,
                    latency_ms      INTEGER DEFAULT 0,
                    source          TEXT DEFAULT '',
                    cache_hit       BOOLEAN DEFAULT 0,
                    llm_cost        REAL DEFAULT 0.0
                )
            """)

        # Source Credibility
        cur.execute("""
            CREATE TABLE IF NOT EXISTS source_credibility (
                source_domain   TEXT PRIMARY KEY,
                total_articles  INTEGER DEFAULT 0,
                verified_claims INTEGER DEFAULT 0,
                debunked_claims INTEGER DEFAULT 0,
                credibility_score REAL DEFAULT 50.0,
                last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Source Health (Self-Healing Ingestors)
        if _is_postgres:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS source_health (
                    source_id       TEXT PRIMARY KEY,
                    consecutive_failures INTEGER DEFAULT 0,
                    next_attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_degraded     BOOLEAN DEFAULT FALSE,
                    last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS source_health (
                    source_id       TEXT PRIMARY KEY,
                    consecutive_failures INTEGER DEFAULT 0,
                    next_attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_degraded     BOOLEAN DEFAULT 0,
                    last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        conn.commit()
        logger.info("[DB] Schema initialized successfully.")
    except Exception as e:
        logger.error(f"[DB] Schema init failed: {e}")
    finally:
        conn.close()


# ── Source Health (Self-Healing) ────────────────────────────

def get_source_health(source_id: str) -> dict:
    """Returns the health status of a source. If next_attempt_at is in the future, it should be skipped."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_q("SELECT consecutive_failures, next_attempt_at, is_degraded FROM source_health WHERE source_id = %s"), (source_id,))
        row = cur.fetchone()
        if not row:
            return {"consecutive_failures": 0, "next_attempt_at": datetime.utcnow(), "is_degraded": False}
            
        next_attempt = row["next_attempt_at"]
        if isinstance(next_attempt, str):
            try:
                next_attempt = datetime.fromisoformat(next_attempt.replace("Z", "+00:00"))
            except ValueError:
                # SQLite fallback
                next_attempt = datetime.strptime(next_attempt, "%Y-%m-%d %H:%M:%S")
                
        # SQLite returns 0/1 for boolean, Postgres True/False
        is_degraded = bool(row["is_degraded"]) 
        return {
            "consecutive_failures": row["consecutive_failures"],
            "next_attempt_at": next_attempt,
            "is_degraded": is_degraded
        }
    except Exception as e:
        logger.error(f"[DB] Get source health failed for {source_id}: {e}")
        return {"consecutive_failures": 0, "next_attempt_at": datetime.utcnow(), "is_degraded": False}
    finally:
        conn.close()

def report_source_success(source_id: str):
    """Reset consecutive failures for a source on success."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        if _is_postgres:
            cur.execute("""
                INSERT INTO source_health (source_id, consecutive_failures, next_attempt_at, is_degraded, last_updated)
                VALUES (%s, 0, %s, false, %s)
                ON CONFLICT (source_id) DO UPDATE SET 
                    consecutive_failures = 0, is_degraded = false, last_updated = %s
            """, (source_id, now, now, now))
        else:
            # SQLite upsert
            cur.execute("""
                INSERT INTO source_health (source_id, consecutive_failures, next_attempt_at, is_degraded, last_updated)
                VALUES (?, 0, ?, 0, ?)
                ON CONFLICT(source_id) DO UPDATE SET 
                    consecutive_failures=0, is_degraded=0, last_updated=?
            """, (source_id, now, now, now))
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Report source success failed for {source_id}: {e}")
    finally:
        conn.close()

def report_source_failure(source_id: str):
    """Increment consecutive failures and calculate exponential backoff."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        health = get_source_health(source_id)
        failures = health["consecutive_failures"] + 1
        
        # Exponential backoff: 5m, 15m, 45m, 135m, capped at 6h
        backoff_minutes = min(5 * (3 ** (failures - 1)), 360)
        next_attempt = (datetime.utcnow() + timedelta(minutes=backoff_minutes)).strftime("%Y-%m-%d %H:%M:%S")
        is_degraded = failures >= 3
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        
        if _is_postgres:
            cur.execute("""
                INSERT INTO source_health (source_id, consecutive_failures, next_attempt_at, is_degraded, last_updated)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source_id) DO UPDATE SET 
                    consecutive_failures = %s, next_attempt_at = %s, is_degraded = %s, last_updated = %s
            """, (source_id, failures, next_attempt, is_degraded, now, failures, next_attempt, is_degraded, now))
        else:
            # SQLite upsert
            cur.execute("""
                INSERT INTO source_health (source_id, consecutive_failures, next_attempt_at, is_degraded, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET 
                    consecutive_failures=?, next_attempt_at=?, is_degraded=?, last_updated=?
            """, (source_id, failures, next_attempt, 1 if is_degraded else 0, now, failures, next_attempt, 1 if is_degraded else 0, now))
        conn.commit()
        
        if is_degraded and failures == 3:
            logger.warning(f"[Health] Source {source_id} is now DEGRADED (failed 3 times). Backoff: {backoff_minutes}m")
            
    except Exception as e:
        logger.error(f"[DB] Report source failure failed for {source_id}: {e}")
    finally:
        conn.close()


# ── Source Credibility ──────────────────────────────────────

def get_source_credibility(domain: str) -> float:
    """Get the credibility score of a domain (default 50.0)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_q("SELECT credibility_score FROM source_credibility WHERE source_domain = %s"), (domain,))
        row = cur.fetchone()
        return row["credibility_score"] if row else 50.0
    except Exception as e:
        logger.error(f"[DB] Get source credibility failed: {e}")
        return 50.0
    finally:
        conn.close()

def update_source_credibility(domain: str, is_verified: bool, is_debunked: bool):
    """Update source credibility based on verification outcomes."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Upsert logic
        cur.execute(_q("SELECT * FROM source_credibility WHERE source_domain = %s"), (domain,))
        row = cur.fetchone()
        
        if row:
            total = row["total_articles"] + 1
            verified = row["verified_claims"] + (1 if is_verified else 0)
            debunked = row["debunked_claims"] + (1 if is_debunked else 0)
            
            # Simple scoring formula: base 50, +2 for verified, -10 for debunked, normalized 0-100
            score = 50.0 + (verified * 2.0) - (debunked * 10.0)
            score = max(0.0, min(100.0, score))
            
            cur.execute(
                _q("UPDATE source_credibility SET total_articles = %s, verified_claims = %s, debunked_claims = %s, credibility_score = %s, last_updated = CURRENT_TIMESTAMP WHERE source_domain = %s"),
                (total, verified, debunked, score, domain)
            )
        else:
            total = 1
            verified = 1 if is_verified else 0
            debunked = 1 if is_debunked else 0
            score = 50.0 + (verified * 2.0) - (debunked * 10.0)
            score = max(0.0, min(100.0, score))
            
            cur.execute(
                _q("INSERT INTO source_credibility (source_domain, total_articles, verified_claims, debunked_claims, credibility_score) VALUES (%s, %s, %s, %s, %s)"),
                (domain, total, verified, debunked, score)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Update source credibility failed: {e}")
    finally:
        conn.close()


# ── Claims ──────────────────────────────────────────────────

def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def save_claim(claim: dict) -> int | None:
    """Insert a claim if not exists (by url_hash). Returns claim id."""
    h = url_hash(claim["url"])
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Check duplicate
        cur.execute(_q("SELECT id FROM claims WHERE url_hash = %s"), (h,))
        if cur.fetchone():
            return None  # Already exists

        cur.execute(
            _q("""INSERT INTO claims
               (title, url, url_hash, summary, category, confidence,
                verification_status, sources_json, reasoning, tickers_json, price_data_json, hype_score)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""),
            (
                claim.get("title", ""),
                claim["url"],
                h,
                claim.get("summary", ""),
                claim.get("category", "General"),
                claim.get("confidence", 0),
                claim.get("verification_status", "unverified"),
                json.dumps(claim.get("sources", [])),
                claim.get("reasoning", ""),
                json.dumps(claim.get("tickers", [])),
                json.dumps(claim.get("price_data", {})),
                claim.get("hype_score", 0),
            ),
        )
        conn.commit()

        # Update source credibility
        try:
            from urllib.parse import urlparse
            domain = urlparse(claim["url"]).netloc.lower().replace("www.", "")
            if not domain:
                domain = claim.get("source", "unknown").lower()
            
            status = claim.get("verification_status", "unverified")
            is_verified = (status == "verified")
            is_debunked = (status == "debunked" or claim.get("debunked", False))
            
            update_source_credibility(domain, is_verified, is_debunked)
        except Exception as e:
            logger.debug(f"[DB] Failed to trigger source credibility update: {e}")

        if _is_postgres:
            cur.execute("SELECT lastval()")
            row = cur.fetchone()
            return row["lastval"] if row else None
        return cur.lastrowid
    except Exception as e:
        logger.error(f"[DB] Save claim failed: {e}")
        return None
    finally:
        conn.close()


def get_claims_since(hours: int, sent_field: str | None = None) -> list[dict]:
    """Get claims from the last N hours."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Use strftime instead of isoformat to match SQLite CURRENT_TIMESTAMP format (YYYY-MM-DD HH:MM:SS)
        # SQLite string comparison fails if we compare '2024-05-09 10:00:00' with '2024-05-09T10:00:00'
        since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        query = "SELECT * FROM claims WHERE created_at >= %s"
        params: list = [since]

        if sent_field and sent_field in ("morning_sent", "evening_sent", "breaking_sent"):
            if _is_postgres:
                query += f" AND {sent_field} = false"
            else:
                query += f" AND {sent_field} = 0"

        query += " ORDER BY confidence DESC LIMIT 50"
        cur.execute(_q(query), params)
        rows = cur.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            # Parse JSON fields
            d["sources"] = json.loads(d.get("sources_json", "[]") or "[]")
            d["tickers"] = json.loads(d.get("tickers_json", "[]") or "[]")
            d["price_data"] = json.loads(d.get("price_data_json", "{}") or "{}")
            results.append(d)
        return results
    except Exception as e:
        logger.error(f"[DB] Get claims failed: {e}")
        return []
    finally:
        conn.close()


def mark_digest_sent(claim_ids: list[int], field: str):
    """Mark claims as included in a digest."""
    if not claim_ids or field not in ("morning_sent", "evening_sent"):
        return
    conn = get_connection()
    try:
        cur = conn.cursor()
        if _is_postgres:
            placeholders = ",".join(["%s"] * len(claim_ids))
            val = True
        else:
            placeholders = ",".join(["?"] * len(claim_ids))
            val = 1

        query = f"UPDATE claims SET {field} = {val} WHERE id IN ({placeholders})"
        if _is_postgres:
            cur.execute(query, claim_ids)
        else:
            cur.execute(query, claim_ids)
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Mark digest failed: {e}")
    finally:
        conn.close()


def mark_breaking_sent(claim_id: int):
    conn = get_connection()
    try:
        cur = conn.cursor()
        if _is_postgres:
            cur.execute("UPDATE claims SET breaking_sent = true WHERE id = %s", (claim_id,))
        else:
            cur.execute("UPDATE claims SET breaking_sent = 1 WHERE id = ?", (claim_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Mark breaking failed: {e}")
    finally:
        conn.close()


def update_claim_calendar_id(claim_id: int, event_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            _q("UPDATE claims SET calendar_event_id = %s WHERE id = %s"),
            (event_id, claim_id),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Update calendar ID failed: {e}")
    finally:
        conn.close()


def update_claim_debunked(claim_id: int, note: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        if _is_postgres:
            cur.execute(
                "UPDATE claims SET debunked = true, debunked_note = %s, "
                "verification_status = 'debunked' WHERE id = %s",
                (note, claim_id),
            )
        else:
            cur.execute(
                "UPDATE claims SET debunked = 1, debunked_note = ?, "
                "verification_status = 'debunked' WHERE id = ?",
                (note, claim_id),
            )
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Update debunked failed: {e}")
    finally:
        conn.close()


# ── Verification Cache ──────────────────────────────────────

def check_cache(claim_hash: str) -> dict | None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            _q("SELECT result_json FROM verification_cache "
               "WHERE claim_hash = %s AND verified_at >= %s"),
            (claim_hash, week_ago),
        )
        row = cur.fetchone()
        return json.loads(row["result_json"]) if row else None
    except Exception as e:
        logger.debug(f"[DB] Cache check failed: {e}")
        return None
    finally:
        conn.close()


def set_cache(claim_hash: str, result: dict):
    conn = get_connection()
    try:
        cur = conn.cursor()
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        if _is_postgres:
            cur.execute(
                "INSERT INTO verification_cache (claim_hash, result_json, verified_at) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (claim_hash) DO UPDATE SET result_json = %s, verified_at = %s",
                (claim_hash, json.dumps(result), now, json.dumps(result), now),
            )
        else:
            cur.execute(
                "INSERT OR REPLACE INTO verification_cache (claim_hash, result_json, verified_at) "
                "VALUES (?, ?, ?)",
                (claim_hash, json.dumps(result), now),
            )
        conn.commit()
    except Exception as e:
        logger.debug(f"[DB] Cache set failed: {e}")
    finally:
        conn.close()


# ── API Quotas ──────────────────────────────────────────────

def get_quota(api_name: str) -> dict:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_q("SELECT * FROM api_quotas WHERE api_name = %s"), (api_name,))
        row = cur.fetchone()
        if not row:
            return {"api_name": api_name, "calls_used": 0, "resets_at": None}
        d = dict(row)
        # Auto-reset if past reset time
        if d["resets_at"] and datetime.utcnow().isoformat() >= str(d["resets_at"]):
            reset_time = (datetime.utcnow() + timedelta(days=1)).isoformat()
            cur.execute(
                _q("UPDATE api_quotas SET calls_used = 0, resets_at = %s WHERE api_name = %s"),
                (reset_time, api_name),
            )
            conn.commit()
            return {"api_name": api_name, "calls_used": 0, "resets_at": reset_time}
        return d
    except Exception as e:
        logger.debug(f"[DB] Quota check failed: {e}")
        return {"api_name": api_name, "calls_used": 0, "resets_at": None}
    finally:
        conn.close()


def increment_quota(api_name: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        reset_time = (datetime.utcnow() + timedelta(days=1)).isoformat()
        if _is_postgres:
            cur.execute(
                "INSERT INTO api_quotas (api_name, calls_used, resets_at) "
                "VALUES (%s, 1, %s) "
                "ON CONFLICT (api_name) DO UPDATE SET calls_used = api_quotas.calls_used + 1",
                (api_name, reset_time),
            )
        else:
            cur.execute(
                "INSERT OR REPLACE INTO api_quotas (api_name, calls_used, resets_at) "
                "VALUES (?, COALESCE((SELECT calls_used FROM api_quotas WHERE api_name = ?), 0) + 1, "
                "COALESCE((SELECT resets_at FROM api_quotas WHERE api_name = ?), ?))",
                (api_name, api_name, api_name, reset_time),
            )
        conn.commit()
    except Exception as e:
        logger.debug(f"[DB] Quota increment failed: {e}")
    finally:
        conn.close()

# ── Metrics ─────────────────────────────────────────────────

def log_metric(event_type: str, latency_ms: int = 0, source: str = "", cache_hit: bool = False, llm_cost: float = 0.0):
    """Log a system metric event."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            _q("INSERT INTO system_metrics (event_type, latency_ms, source, cache_hit, llm_cost) VALUES (%s, %s, %s, %s, %s)"),
            (event_type, latency_ms, source, cache_hit, llm_cost)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Log metric failed: {e}")
    finally:
        conn.close()

def get_recent_metrics(hours: int = 24) -> list[dict]:
    """Get metrics from the last N hours."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(_q("SELECT * FROM system_metrics WHERE timestamp >= %s ORDER BY timestamp ASC"), (since,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"[DB] Get metrics failed: {e}")
        return []
    finally:
        conn.close()

def cleanup_old_metrics(days: int = 7):
    """Delete metrics older than N days."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        threshold = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(_q("DELETE FROM system_metrics WHERE timestamp < %s"), (threshold,))
        conn.commit()
        logger.info(f"[DB] Cleaned up metrics older than {days} days.")
    except Exception as e:
        logger.error(f"[DB] Cleanup metrics failed: {e}")
    finally:
        conn.close()
