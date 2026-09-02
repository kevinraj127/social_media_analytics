"""
storage.py — local snapshot layer for the Bytes on Disc / k_diesel_finds analytics dashboard.

Why this exists:
Instagram's Insights API only retains ~90 days of data, and there's no endpoint
that returns historical follower count. To chart trends over time (e.g. progress
toward the 1,000-follower threshold), this app has to snapshot the numbers itself
on every visit and keep its own history. eBay is not snapshotted — its API isn't
retention-limited, so it's pulled live each time instead (see ebay_api.py).

This module uses a single local SQLite file. At this data volume (a handful of
writes per day, small row counts), SQLite is more than sufficient — no need for
a heavier database.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "dashboard.db"


def get_connection() -> sqlite3.Connection:
    """Open a connection to the local dashboard database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't already exist. Safe to call on every app start."""
    conn = get_connection()
    cur = conn.cursor()

    # One row per snapshot of account-level Instagram numbers.
    # Note: 'impressions' and 'profile_views' were deprecated by Meta in April 2025
    # and replaced with a unified 'views' metric. Using 'views' here, not the old names.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ig_account_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,       -- ISO date, e.g. '2026-09-01'
            followers_count INTEGER,
            reach INTEGER,
            views INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(snapshot_date)
        )
    """)

    # One row per Instagram post, updated each time we re-pull its insights.
    # media_id is the stable key; engagement numbers get overwritten on refresh
    # since a post's likes/comments/reach change over its lifetime.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ig_media_snapshots (
            media_id TEXT PRIMARY KEY,
            caption_preview TEXT,
            media_type TEXT,
            timestamp TEXT,                    -- when the post was published
            permalink TEXT,
            engagement INTEGER,
            reach INTEGER,
            likes INTEGER,
            comments INTEGER,
            last_updated TEXT NOT NULL
        )
    """)

    # One row per Substack CSV import. Kevin uploads the export manually;
    # each upload becomes one snapshot row so the trend is still chartable
    # even though there's no live API for this channel.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS substack_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,
            total_subscribers INTEGER,
            free_subscribers INTEGER,
            paid_subscribers INTEGER,
            open_rate REAL,
            created_at TEXT NOT NULL,
            UNIQUE(snapshot_date)
        )
    """)

    conn.commit()
    conn.close()


def save_ig_account_snapshot(
    followers_count: int,
    reach: Optional[int] = None,
    views: Optional[int] = None,
    snapshot_date: Optional[str] = None,
) -> None:
    """
    Save (or overwrite) today's Instagram account-level snapshot.
    Uses INSERT OR REPLACE keyed on date, so re-running the dashboard multiple
    times in one day updates today's row instead of creating duplicates.
    """
    date_str = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT INTO ig_account_snapshots
            (snapshot_date, followers_count, reach, views, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_date) DO UPDATE SET
            followers_count=excluded.followers_count,
            reach=excluded.reach,
            views=excluded.views,
            created_at=excluded.created_at
    """, (date_str, followers_count, reach, views,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def save_ig_media_snapshot(
    media_id: str,
    caption_preview: str,
    media_type: str,
    timestamp: str,
    permalink: str,
    engagement: Optional[int] = None,
    reach: Optional[int] = None,
    likes: Optional[int] = None,
    comments: Optional[int] = None,
) -> None:
    """Save or update the latest insights for one Instagram post."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO ig_media_snapshots
            (media_id, caption_preview, media_type, timestamp, permalink,
             engagement, reach, likes, comments, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(media_id) DO UPDATE SET
            engagement=excluded.engagement,
            reach=excluded.reach,
            likes=excluded.likes,
            comments=excluded.comments,
            last_updated=excluded.last_updated
    """, (media_id, caption_preview, media_type, timestamp, permalink,
          engagement, reach, likes, comments, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def save_substack_snapshot(
    total_subscribers: int,
    free_subscribers: Optional[int] = None,
    paid_subscribers: Optional[int] = None,
    open_rate: Optional[float] = None,
    snapshot_date: Optional[str] = None,
) -> None:
    """Save a Substack snapshot from a manually-uploaded CSV export."""
    date_str = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT INTO substack_snapshots
            (snapshot_date, total_subscribers, free_subscribers, paid_subscribers, open_rate, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_date) DO UPDATE SET
            total_subscribers=excluded.total_subscribers,
            free_subscribers=excluded.free_subscribers,
            paid_subscribers=excluded.paid_subscribers,
            open_rate=excluded.open_rate,
            created_at=excluded.created_at
    """, (date_str, total_subscribers, free_subscribers, paid_subscribers, open_rate,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_ig_account_history() -> list[sqlite3.Row]:
    """Return all Instagram account snapshots, oldest first — for trend charts."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM ig_account_snapshots ORDER BY snapshot_date ASC"
    ).fetchall()
    conn.close()
    return rows


def get_latest_ig_snapshot() -> Optional[sqlite3.Row]:
    """Return the most recent Instagram account snapshot, or None if empty."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM ig_account_snapshots ORDER BY snapshot_date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def get_ig_media_history(limit: int = 25) -> list[sqlite3.Row]:
    """Return recent Instagram post snapshots, most recently posted first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM ig_media_snapshots ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def get_substack_history() -> list[sqlite3.Row]:
    """Return all Substack snapshots, oldest first — for trend charts."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM substack_snapshots ORDER BY snapshot_date ASC"
    ).fetchall()
    conn.close()
    return rows


def get_latest_substack_snapshot() -> Optional[sqlite3.Row]:
    """Return the most recent Substack snapshot, or None if empty."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM substack_snapshots ORDER BY snapshot_date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row
