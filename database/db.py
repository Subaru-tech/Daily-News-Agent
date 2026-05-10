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
    """Initialize the database schema."""
    conn = get_connection()
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
                    price_data_json TEXT DEFAULT '{}'
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
                    price_data_json TEXT DEFAULT '{}'
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

        conn.commit()
        logger.info("[DB] Schema initialized successfully.")
    except Exception as e:
        logger.error(f"[DB] Schema init failed: {e}")
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
                verification_status, sources_json, reasoning, tickers_json, price_data_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""),
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
            ),
        )
        conn.commit()

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
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
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
        now = datetime.utcnow().isoformat()
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
