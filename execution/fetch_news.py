"""
fetch_news.py
Fetch latest AI articles from news sources.
- RSS feeds  → TechCrunch AI, WSJ Tech
- HTML scrape → Calcalist Tech (no RSS available)

Strips HTML from summaries. Deduplicates by hashed URL.
"""

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(override=True)

DB_PATH = Path(".tmp/pipeline.db")

# ── RSS sources ──────────────────────────────────────────────────────────────
RSS_FEEDS = {
    "techcrunch":   "https://techcrunch.com/category/artificial-intelligence/feed/",
    "wsj":          "https://feeds.content.dowjones.io/public/rss/mw_technology",  # MarketWatch Tech (free, frequent)
    "wired":        "https://www.wired.com/feed/rss",
    "marktechpost": "https://www.marktechpost.com/feed/",
}

MAX_AGE_DAYS = 7   # ignore articles older than this

# ── Scrape sources ────────────────────────────────────────────────────────────
SCRAPE_SITES = {
    "calcalist": {
        "url":              "https://www.calcalistech.com/ctechnews/category/36042",
        "article_selector": "article, .article-item, .story-item, li.item",
        "title_selector":   "h1, h2, h3, .title",
        "link_selector":    "a",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def make_id(source: str, url: str) -> str:
    return f"{source}_{hashlib.md5(url.encode()).hexdigest()[:12]}"


def strip_html(raw: str) -> str:
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ").strip()


# ── RSS ───────────────────────────────────────────────────────────────────────

def fetch_rss(conn: sqlite3.Connection) -> int:
    c = conn.cursor()
    total_new = 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    for source, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                url     = entry.get("link", "")
                post_id = make_id(source, url)

                c.execute("SELECT id FROM posts WHERE id = ?", (post_id,))
                if c.fetchone():
                    continue

                # Parse published date
                pub_struct = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub_struct:
                    pub_dt       = datetime(*pub_struct[:6], tzinfo=timezone.utc)
                    published_at = pub_dt.isoformat()
                    if pub_dt < cutoff:
                        continue   # too old
                else:
                    published_at = datetime.utcnow().isoformat()

                # Build content: title + stripped summary
                title   = entry.get("title", "")
                summary = entry.get("summary", "")
                if not summary and entry.get("content"):
                    summary = entry["content"][0].get("value", "")
                content = f"{title}\n\n{strip_html(summary)}"

                c.execute(
                    """INSERT INTO posts
                       (id, source, author, content, url, media_urls, fetched_at, published_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        post_id,
                        source,
                        entry.get("author", source),
                        content,
                        url,
                        json.dumps([]),
                        datetime.utcnow().isoformat(),
                        published_at,
                    ),
                )
                total_new += 1

            print(f"  {source} RSS: processed")

        except Exception as e:
            print(f"  [WARN]  Error fetching {source} RSS: {e}")

    return total_new


# ── HTML scrape ───────────────────────────────────────────────────────────────

def fetch_scrape(conn: sqlite3.Connection) -> int:
    c = conn.cursor()
    total_new = 0

    for source, cfg in SCRAPE_SITES.items():
        try:
            resp = requests.get(cfg["url"], headers=HEADERS, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            articles = soup.select(cfg["article_selector"])[:15]
            for article in articles:
                link_el  = article.select_one(cfg["link_selector"])
                title_el = article.select_one(cfg["title_selector"])

                if not link_el:
                    continue

                href = link_el.get("href", "").strip()
                if not href or href == "#":
                    continue
                if href.startswith("/"):
                    href = urljoin(cfg["url"], href)

                title   = (title_el or link_el).get_text(strip=True)
                post_id = make_id(source, href)

                c.execute("SELECT id FROM posts WHERE id = ?", (post_id,))
                if c.fetchone():
                    continue

                c.execute(
                    """INSERT INTO posts
                       (id, source, author, content, url, media_urls, fetched_at, published_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        post_id,
                        source,
                        source,
                        title,
                        href,
                        json.dumps([]),
                        datetime.utcnow().isoformat(),
                        datetime.utcnow().isoformat(),   # no date available from scrape
                    ),
                )
                total_new += 1

            print(f"  {source} scrape: processed")

        except Exception as e:
            print(f"  [WARN]  Error scraping {source}: {e}")

    return total_new


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_news():
    conn = sqlite3.connect(DB_PATH)
    rss_new    = fetch_rss(conn)
    scrape_new = fetch_scrape(conn)
    conn.commit()
    conn.close()
    print(f"[OK] News: {rss_new + scrape_new} new articles saved")


if __name__ == "__main__":
    fetch_news()
