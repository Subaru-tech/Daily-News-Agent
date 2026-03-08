import os
import json
import hashlib
import sqlite3
import logging
from datetime import datetime, timedelta

from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

_is_postgres = DATABASE_URL.startswith("postgresql")


def get_connection():
    """Get a database connection (SQLite for local, PostgreSQL for Render)."""
    if _is_postgres:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    else:
        db_path = DATABASE_URL.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _execute(conn, query, params=None):
    """Execute query — handles both sqlite3 and psycopg2 parameter styles."""
    cur = conn.cursor()
    if params:
        if _is_postgres:
            cur.execute(query, params)
        else:
            # Convert %s to ? for SQLite
            query = query.replace("%s", "?")
            # Convert ANY(%s) for SQLite
            if "ANY(" in query:
                # Flatten for SQLite
                return cur  # Skip ANY queries for SQLite
            cur.execute(query, params)
    else:
        cur.execute(query)
    return cur


def init_db():
    """Initialize the database schema."""
    conn = get_connection()
    try:
        cur = conn.cursor()

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
        cur.execute("SELECT id FROM claims WHERE url_hash = ?", (h,))
        if cur.fetchone():
            return None  # Already exists

        cur.execute(
            """INSERT INTO claims
               (title, url, url_hash, summary, category, confidence,
                verification_status, sources_json, reasoning, tickers_json, price_data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        query = "SELECT * FROM claims WHERE created_at >= ?"
        params = [since]

        if sent_field and sent_field in ("morning_sent", "evening_sent", "breaking_sent"):
            query += f" AND {sent_field} = 0"

        query += " ORDER BY confidence DESC LIMIT 50"
        cur.execute(query, params)
        rows = cur.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            # Parse JSON fields
            d["sources"] = json.loads(d.get("sources_json", "[]"))
            d["tickers"] = json.loads(d.get("tickers_json", "[]"))
            d["price_data"] = json.loads(d.get("price_data_json", "{}"))
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
        placeholders = ",".join("?" * len(claim_ids))
        cur.execute(
            f"UPDATE claims SET {field} = 1 WHERE id IN ({placeholders})",
            claim_ids,
        )
        conn.commit()
    except Exception as e:
        logger.error(f"[DB] Mark digest failed: {e}")
    finally:
        conn.close()


def mark_breaking_sent(claim_id: int):
    conn = get_connection()
    try:
        cur = conn.cursor()
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
            "UPDATE claims SET calendar_event_id = ? WHERE id = ?",
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
            "SELECT result_json FROM verification_cache "
            "WHERE claim_hash = ? AND verified_at >= ?",
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
        cur.execute(
            "INSERT OR REPLACE INTO verification_cache (claim_hash, result_json, verified_at) "
            "VALUES (?, ?, ?)",
            (claim_hash, json.dumps(result), datetime.utcnow().isoformat()),
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
        cur.execute("SELECT * FROM api_quotas WHERE api_name = ?", (api_name,))
        row = cur.fetchone()
        if not row:
            return {"api_name": api_name, "calls_used": 0, "resets_at": None}
        d = dict(row)
        # Auto-reset if past reset time
        if d["resets_at"] and datetime.utcnow().isoformat() >= d["resets_at"]:
            reset_time = (datetime.utcnow() + timedelta(days=1)).isoformat()
            cur.execute(
                "UPDATE api_quotas SET calls_used = 0, resets_at = ? WHERE api_name = ?",
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
