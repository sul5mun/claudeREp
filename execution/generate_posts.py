"""
generate_posts.py
Generate a ready-to-review tweet and LinkedIn post from today's digest themes.

Reads the latest unfinished digest (tweet_draft IS NULL), asks Claude to write
both posts, then saves them back to the digest row.

Requires: ANTHROPIC_API_KEY in .env
"""

import os
import sqlite3
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

DB_PATH          = Path(".tmp/pipeline.db")
MODEL            = "claude-sonnet-4-5"
CONTENT_LANGUAGE = os.getenv("CONTENT_LANGUAGE", "English")  # Change to "Arabic" if preferred


def generate_posts():
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    conn   = sqlite3.connect(DB_PATH)
    c      = conn.cursor()

    today = date.today().isoformat()

    # Get today's digest that hasn't had content generated yet
    c.execute("""
        SELECT id, themes, summary FROM digests
        WHERE date = ? AND tweet_draft IS NULL
        ORDER BY id DESC LIMIT 1
    """, (today,))
    row = c.fetchone()

    if not row:
        print("[OK] Generate: no pending digest found for today — skipping")
        conn.close()
        return

    digest_id, themes_json, top_story = row

    import json
    themes = json.loads(themes_json) if themes_json else []
    themes_text = "\n".join(
        f"• {t['title']}: {t['summary']}" for t in themes
    )

    lang_note = f"Write in {CONTENT_LANGUAGE}." if CONTENT_LANGUAGE != "English" else ""

    # ── Generate Tweet ────────────────────────────────────────────────────────
    tweet_response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": f"""You are a sharp AI industry commentator. Based on today's AI news, write one tweet.

Top story: {top_story}

Key themes:
{themes_text}

Requirements:
- Maximum 280 characters
- Lead with the most important insight
- Add 1–2 relevant hashtags (#AI, #LLM, #GenAI, etc.)
- Conversational and punchy — not corporate
- No emojis unless they genuinely add value
{lang_note}

Return ONLY the tweet text. No quotes, no labels.""",
        }],
    )

    # ── Generate LinkedIn Post ────────────────────────────────────────────────
    linkedin_response = client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": f"""You are a thoughtful AI industry professional. Write a LinkedIn post based on today's AI news.

Top story: {top_story}

Key themes:
{themes_text}

Requirements:
- 150–250 words
- Open with a hook: a bold statement or provocative question
- Cover 2–3 of the key themes naturally
- End with an engaging question to spark comments
- Use short paragraphs and line breaks for readability
- Professional but human tone — not a press release
{lang_note}

Return ONLY the post text. No labels, no quotes.""",
        }],
    )

    tweet_draft    = tweet_response.content[0].text.strip()
    linkedin_draft = linkedin_response.content[0].text.strip()

    # Save back to digest
    c.execute(
        "UPDATE digests SET tweet_draft = ?, linkedin_draft = ? WHERE id = ?",
        (tweet_draft, linkedin_draft, digest_id),
    )
    conn.commit()
    conn.close()

    print("[OK] Generated content:")
    print(f"\n{'='*60}")
    print("TWEET (for X):")
    print(f"{'='*60}")
    print(tweet_draft)
    print(f"\n{'='*60}")
    print("LINKEDIN POST:")
    print(f"{'='*60}")
    print(linkedin_draft)
    print(f"{'='*60}\n")

    return tweet_draft, linkedin_draft


if __name__ == "__main__":
    generate_posts()
