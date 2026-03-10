"""
export_to_sheets.py
Push today's digest to Google Sheets for human review.

Sheet structure:
  Tab "Summary"   — top story, themes, tweet draft, LinkedIn draft
  Tab "Raw Posts" — all posts fetched today with source, author, content, URL

On first run: creates a new Google Sheet and prints its ID.
              → copy that ID into DIGEST_SHEET_ID in .env

Requires: Google OAuth credentials.json in project root
          DIGEST_SHEET_ID in .env (after first run)
"""

import json
import os
import sqlite3
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv(override=True)

DB_PATH          = Path(".tmp/pipeline.db")
CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
TOKEN_PATH       = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
SHEET_ID         = os.getenv("DIGEST_SHEET_ID", "")
SCOPES           = ["https://www.googleapis.com/auth/spreadsheets"]


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_sheets_service():
    creds = None
    if Path(TOKEN_PATH).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(CREDENTIALS_PATH).exists():
                raise FileNotFoundError(
                    f"Google credentials not found at '{CREDENTIALS_PATH}'. "
                    "Download it from Google Cloud Console → APIs & Services → Credentials."
                )
            flow  = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("sheets", "v4", credentials=creds)


# ── Helpers ───────────────────────────────────────────────────────────────────

def write_range(service, sheet_id: str, tab_range: str, values: list):
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=tab_range,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def create_sheet(service, title: str) -> str:
    """Create a new spreadsheet with Summary and Raw Posts tabs."""
    result = service.spreadsheets().create(body={
        "properties": {"title": title},
        "sheets": [
            {"properties": {"title": "Summary",   "index": 0}},
            {"properties": {"title": "Raw Posts", "index": 1}},
        ],
    }).execute()
    return result["spreadsheetId"]


# ── Main ──────────────────────────────────────────────────────────────────────

def export_digest():
    conn  = sqlite3.connect(DB_PATH)
    c     = conn.cursor()
    today = date.today().isoformat()

    # Get today's digest
    c.execute("""
        SELECT themes, summary, tweet_draft, linkedin_draft
        FROM digests WHERE date = ?
        ORDER BY id DESC LIMIT 1
    """, (today,))
    digest_row = c.fetchone()

    if not digest_row:
        print("[OK] Export: no digest found for today — skipping")
        conn.close()
        return

    themes_json, top_story, tweet_draft, linkedin_draft = digest_row
    themes = json.loads(themes_json) if themes_json else []

    # Get today's posts
    c.execute("""
        SELECT source, author, content, url, transcript
        FROM posts WHERE date(fetched_at) = ?
        ORDER BY fetched_at DESC
    """, (today,))
    posts = c.fetchall()
    conn.close()

    # ── Build Summary tab data ────────────────────────────────────────────────
    summary_rows = [
        [f"[AI] AI Daily Digest — {today}"],
        [],
        ["TOP STORY"],
        [top_story or "(none)"],
        [],
        ["THEMES", "Summary", "Sources"],
    ]
    for t in themes:
        sources_str = ", ".join(t.get("sources", []))
        summary_rows.append([t.get("title", ""), t.get("summary", ""), sources_str])

    summary_rows += [
        [],
        ["━" * 40],
        ["TWEET (for X)"],
        [tweet_draft or "(not generated)"],
        [],
        ["LINKEDIN POST"],
        [linkedin_draft or "(not generated)"],
    ]

    # ── Build Raw Posts tab data ──────────────────────────────────────────────
    posts_rows = [["Source", "Author", "Content (truncated)", "URL", "Has Transcript"]]
    for source, author, content, url, transcript in posts:
        posts_rows.append([
            source,
            f"@{author}",
            (content or "")[:300].replace("\n", " "),
            url or "",
            "Yes" if transcript else "No",
        ])

    # ── Google Sheets ─────────────────────────────────────────────────────────
    service  = get_sheets_service()
    sheet_id = SHEET_ID

    if not sheet_id:
        sheet_id = create_sheet(service, "AI Content Pipeline — Digest")
        print(f"\n[SHEET] New Google Sheet created!")
        print(f"   URL: https://docs.google.com/spreadsheets/d/{sheet_id}")
        print(f"   → Add this to .env:  DIGEST_SHEET_ID={sheet_id}\n")
    else:
        # Clear existing content before writing
        service.spreadsheets().values().batchClear(
            spreadsheetId=sheet_id,
            body={"ranges": ["Summary!A1:Z500", "Raw Posts!A1:Z500"]},
        ).execute()

    write_range(service, sheet_id, "Summary!A1",   summary_rows)
    write_range(service, sheet_id, "Raw Posts!A1", posts_rows)

    print(f"[OK] Exported to Google Sheets:")
    print(f"   https://docs.google.com/spreadsheets/d/{sheet_id}")


if __name__ == "__main__":
    export_digest()
