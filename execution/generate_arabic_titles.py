"""
generate_arabic_titles.py
For every post that doesn't have an arabic_title yet, generate a concise
Arabic summary title (5-10 words) using the Claude API in batches.

- Processes posts without arabic_title in batches of 20
- Skips posts whose content is too short to summarise (< 20 chars)
- Writes results back to the DB immediately after each batch
- Safe to re-run: only processes posts with arabic_title IS NULL
"""

import json
import os
import re
import sqlite3
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=True)

DB_PATH    = Path(".tmp/pipeline.db")
BATCH_SIZE = 20     # posts per API call
MODEL      = "claude-haiku-4-5"   # fast + cheap for short titles


def fetch_untitled_posts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT id, content FROM posts
           WHERE arabic_title IS NULL AND LENGTH(COALESCE(content,'')) >= 20
           ORDER BY fetched_at DESC"""
    ).fetchall()
    return [{"id": r[0], "content": r[1]} for r in rows]


def build_prompt(batch: list[dict]) -> str:
    items = "\n\n".join(
        f'[{i+1}] id="{p["id"]}"\n{p["content"][:300]}'
        for i, p in enumerate(batch)
    )
    return (
        "أنت مساعد تلخيص إخباري. لكل منشور أدناه، اكتب عنواناً عربياً مختصراً"
        " من 5 إلى 10 كلمات يلخّص الفكرة الرئيسية.\n"
        "أرجع JSON فقط — مصفوفة بهذا الشكل بالضبط، بدون أي نص إضافي:\n"
        '[{"id":"...","title":"..."},...]\n\n'
        "المنشورات:\n\n" + items
    )


def generate_batch(client: anthropic.Anthropic, batch: list[dict]) -> dict[str, str]:
    """Returns {post_id: arabic_title} for the batch."""
    prompt = build_prompt(batch)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()

    # Extract JSON array from response (model may wrap it in markdown)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return {}
    try:
        items = json.loads(m.group())
        return {item["id"]: item["title"] for item in items if "id" in item and "title" in item}
    except (json.JSONDecodeError, KeyError):
        return {}


def generate_arabic_titles():
    conn   = sqlite3.connect(DB_PATH)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    posts   = fetch_untitled_posts(conn)
    total   = len(posts)
    updated = 0

    if total == 0:
        print("[OK] Arabic Titles: all posts already have titles — nothing to do")
        conn.close()
        return

    print(f"  [AI] Generating Arabic titles for {total} posts in batches of {BATCH_SIZE}...")

    for i in range(0, total, BATCH_SIZE):
        batch   = posts[i : i + BATCH_SIZE]
        titles  = generate_batch(client, batch)

        for post_id, title in titles.items():
            conn.execute(
                "UPDATE posts SET arabic_title = ? WHERE id = ?",
                (title, post_id),
            )
            updated += 1

        conn.commit()
        done = min(i + BATCH_SIZE, total)
        print(f"     {done}/{total} processed ({len(titles)} titles generated in this batch)")

    conn.close()
    print(f"[OK] Arabic Titles: {updated}/{total} titles written to DB")


if __name__ == "__main__":
    generate_arabic_titles()
