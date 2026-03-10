"""
init_db.py
Initialize the SQLite database for the AI content pipeline.
Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(".tmp/pipeline.db")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # All fetched content from Twitter and news sites
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id           TEXT PRIMARY KEY,
            source       TEXT NOT NULL,        -- 'twitter', 'techcrunch', 'wsj', 'calcalist'
            author       TEXT,
            content      TEXT,
            url          TEXT,
            media_urls   TEXT DEFAULT '[]',    -- JSON array of video/image URLs
            transcript   TEXT,                 -- Whisper transcript (if video found)
            fetched_at   TEXT,                 -- ISO timestamp (when we fetched it)
            published_at TEXT,                 -- ISO timestamp (when content was originally published)
            arabic_title TEXT,                 -- AI-generated Arabic summary title
            processed    INTEGER DEFAULT 0    -- 0=new, 1=included in a digest
        )
    """)

    # Daily digests: themes, summary, generated content
    c.execute("""
        CREATE TABLE IF NOT EXISTS digests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT,             -- YYYY-MM-DD
            themes          TEXT,             -- JSON array of {title, summary, sources}
            summary         TEXT,             -- Top story sentence
            tweet_draft     TEXT,
            linkedin_draft  TEXT,
            created_at      TEXT
        )
    """)

    conn.commit()
    conn.close()
    print(f"[OK] Database ready: {DB_PATH}")


if __name__ == "__main__":
    init_db()
