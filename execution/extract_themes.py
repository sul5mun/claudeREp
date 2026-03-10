"""
extract_themes.py
Send all unprocessed posts to Claude and extract the day's key AI themes.

Output is stored in the `digests` table as a JSON array of themes.
Posts are marked as processed=1 after a successful digest is created.

Requires: ANTHROPIC_API_KEY in .env
"""

import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

DB_PATH = Path(".tmp/pipeline.db")
MODEL   = "claude-sonnet-4-5"
MAX_CONTENT_CHARS = 1200  # Per post, to stay within token limits


def extract_themes():
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    conn   = sqlite3.connect(DB_PATH)
    c      = conn.cursor()

    # Pull all unprocessed posts
    c.execute("""
        SELECT id, source, author, content, transcript
        FROM posts
        WHERE processed = 0
        ORDER BY fetched_at DESC
    """)
    posts = c.fetchall()

    if not posts:
        print("[OK] Themes: no unprocessed posts — skipping")
        conn.close()
        return None

    # Build the prompt block — prefer transcript over raw content for videos
    posts_block = ""
    for post_id, source, author, content, transcript in posts:
        text = (transcript or content or "")[:MAX_CONTENT_CHARS]
        posts_block += f"\n\n---\nSource: {source} | Author: @{author}\n{text}"

    prompt = f"""You are an AI industry analyst. Below are the latest posts and articles from AI influencers and tech news sites collected today.

{posts_block}

---

Your task:
1. Identify the 3–5 main themes being discussed across all sources today.
2. For each theme write a 1–2 sentence summary.
3. Note which sources/authors discuss each theme.
4. Write a single "top story" sentence — the single most important development today.
5. List any specific AI models, tools, companies, or people mentioned.

Respond with valid JSON only (no markdown fences), using this exact structure:
{{
  "top_story": "...",
  "themes": [
    {{
      "title": "...",
      "summary": "...",
      "sources": ["source1", "source2"]
    }}
  ],
  "entities": ["GPT-5", "Anthropic", "...]
}}"""

    print(f"  [AI] Sending {len(posts)} posts to Claude for theme extraction...")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Parse JSON — strip any accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        themes_data = json.loads(raw)

    except json.JSONDecodeError as e:
        print(f"  [WARN]  Claude returned invalid JSON: {e}")
        conn.close()
        return None
    except Exception as e:
        print(f"  [WARN]  Claude API error: {e}")
        conn.close()
        return None

    # Save digest
    today = date.today().isoformat()
    c.execute(
        """INSERT INTO digests (date, themes, summary, created_at)
           VALUES (?, ?, ?, ?)""",
        (
            today,
            json.dumps(themes_data.get("themes", [])),
            themes_data.get("top_story", ""),
            datetime.utcnow().isoformat(),
        ),
    )

    # Mark all posts as processed
    post_ids = [row[0] for row in posts]
    c.executemany("UPDATE posts SET processed = 1 WHERE id = ?", [(pid,) for pid in post_ids])

    conn.commit()
    conn.close()

    print(f"[OK] Themes: {len(themes_data.get('themes', []))} themes extracted from {len(posts)} posts")
    print(f"   Top story: {themes_data.get('top_story', '')[:100]}")
    return themes_data


if __name__ == "__main__":
    extract_themes()
