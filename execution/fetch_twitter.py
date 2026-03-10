"""
fetch_twitter.py
Fetch latest tweets from configured accounts using twikit.

Auth priority:
  1. Saved cookies at .tmp/twitter_cookies.json  (fastest, used after first successful auth)
  2. TWITTER_AUTH_TOKEN + TWITTER_CT0 from .env  (bypass Cloudflare login block)
  3. Username/password login                      (may be blocked by Cloudflare)

To get TWITTER_AUTH_TOKEN and TWITTER_CT0:
  1. Open x.com in your browser and log in
  2. Open DevTools (F12) -> Application -> Cookies -> https://x.com
  3. Copy the value of `auth_token`  -> paste as TWITTER_AUTH_TOKEN in .env
  4. Copy the value of `ct0`         -> paste as TWITTER_CT0 in .env
"""

import asyncio
import json
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
import twikit

load_dotenv(override=True)

DB_PATH            = Path(".tmp/pipeline.db")
COOKIES_PATH       = Path(".tmp/twitter_cookies.json")
ACCOUNTS           = os.getenv("TWITTER_ACCOUNTS", "JulianGoldieSEO,EHuanglu,rileybrown,Marktechpost,omarsar0,dair_ai,AskPerplexity").split(",")
USERNAME           = os.getenv("TWITTER_USERNAME", "")
PASSWORD           = os.getenv("TWITTER_PASSWORD", "")
EMAIL              = os.getenv("TWITTER_EMAIL", "")
AUTH_TOKEN         = os.getenv("TWITTER_AUTH_TOKEN", "")
CT0                = os.getenv("TWITTER_CT0", "")
TWEETS_PER_ACCOUNT = 20          # fetch more to have enough after filtering
MAX_AGE_HOURS      = 48          # ignore tweets older than this


def parse_tweet_date(created_at) -> str | None:
    """Parse twikit's created_at into an ISO UTC string."""
    if not created_at:
        return None
    s = str(created_at)
    for fmt in (
        "%a %b %d %H:%M:%S +0000 %Y",   # legacy: "Mon Mar 09 12:34:56 +0000 2026"
        "%Y-%m-%dT%H:%M:%S.%fZ",         # API v2 with microseconds
        "%Y-%m-%dT%H:%M:%SZ",            # API v2 without microseconds
    ):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def build_cookies_file_from_tokens(auth_token: str, ct0: str) -> None:
    """Write cookies as a list of [name, value] pairs — required by httpx 0.28+ via twikit."""
    cookies = [
        ["auth_token", auth_token],
        ["ct0",        ct0],
    ]
    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(COOKIES_PATH, "w") as f:
        json.dump(cookies, f)
    print("[COOKIES] Cookie file built from TWITTER_AUTH_TOKEN + TWITTER_CT0")


async def get_client() -> twikit.Client:
    client = twikit.Client("en-US")

    # 1. Saved cookies file
    if COOKIES_PATH.exists():
        client.load_cookies(str(COOKIES_PATH))
        print("[COOKIES] Loaded saved Twitter cookies")

    # 2. Auth token from .env (bypasses Cloudflare login block)
    elif AUTH_TOKEN and CT0:
        build_cookies_file_from_tokens(AUTH_TOKEN, CT0)
        client.load_cookies(str(COOKIES_PATH))

    # 3. Username/password (may hit Cloudflare)
    elif USERNAME and PASSWORD:
        print("[LOGIN] Logging in to Twitter with username/password...")
        print("[LOGIN] Note: if Cloudflare blocks this, use TWITTER_AUTH_TOKEN + TWITTER_CT0 instead")
        await client.login(
            auth_info_1=USERNAME,
            auth_info_2=EMAIL or USERNAME,
            password=PASSWORD,
        )
        COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        client.save_cookies(str(COOKIES_PATH))
        print(f"[COOKIES] Cookies saved to {COOKIES_PATH}")

    else:
        raise ValueError(
            "No Twitter auth configured. Set TWITTER_AUTH_TOKEN + TWITTER_CT0 in .env\n"
            "  -> Open x.com in browser -> DevTools -> Application -> Cookies -> x.com\n"
            "  -> Copy 'auth_token' and 'ct0' values"
        )

    return client


def extract_media_urls(tweet) -> list:
    """Pull video/image URLs from a twikit tweet object."""
    urls = []
    if not hasattr(tweet, "media") or not tweet.media:
        return urls

    for media in tweet.media:
        if hasattr(media, "variants") and media.variants:
            best = max(
                (v for v in media.variants if v.get("content_type") == "video/mp4"),
                key=lambda v: v.get("bitrate", 0),
                default=None,
            )
            if best:
                urls.append(best["url"])
        elif hasattr(media, "media_url_https"):
            urls.append(media.media_url_https)

    return urls


async def fetch_tweets():
    client    = await get_client()
    conn      = sqlite3.connect(DB_PATH)
    c         = conn.cursor()
    total_new = 0

    for handle in ACCOUNTS:
        handle = handle.strip().lstrip("@")
        try:
            user   = await client.get_user_by_screen_name(handle)
            tweets = await user.get_tweets("Tweets", count=TWEETS_PER_ACCOUNT)

            cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

            for tweet in tweets:
                # Skip retweets — they are old content being reshared
                if tweet.text.startswith("RT @"):
                    continue

                post_id = f"twitter_{tweet.id}"
                c.execute("SELECT id FROM posts WHERE id = ?", (post_id,))
                if c.fetchone():
                    continue

                # Parse and filter by publish date
                published_at = parse_tweet_date(getattr(tweet, "created_at", None))
                if published_at:
                    pub_dt = datetime.fromisoformat(published_at)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue   # too old

                media_urls = extract_media_urls(tweet)
                c.execute(
                    """INSERT INTO posts
                       (id, source, author, content, url, media_urls, fetched_at, published_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        post_id, "twitter", handle, tweet.text,
                        f"https://x.com/{handle}/status/{tweet.id}",
                        json.dumps(media_urls),
                        datetime.utcnow().isoformat(),
                        published_at,
                    ),
                )
                total_new += 1

            print(f"  @{handle}: done")

        except Exception as e:
            print(f"  [WARN]  Error fetching @{handle}: {e}")

    conn.commit()
    conn.close()
    print(f"[OK] Twitter: {total_new} new posts saved")


if __name__ == "__main__":
    asyncio.run(fetch_tweets())
