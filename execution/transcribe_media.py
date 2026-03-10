"""
transcribe_media.py
Download video from posts and transcribe using Groq Whisper API (free tier).

Processes posts that have media_urls but no transcript yet.
Audio files are downloaded to .tmp/audio/ and deleted after transcription.

Requires: GROQ_API_KEY in .env (free at https://console.groq.com)
          ffmpeg installed and on PATH (for yt-dlp audio extraction)
"""

import json
import os
import sqlite3
from pathlib import Path

import yt_dlp
from dotenv import load_dotenv
from groq import Groq

load_dotenv(override=True)

DB_PATH      = Path(".tmp/pipeline.db")
AUDIO_DIR    = Path(".tmp/audio")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Video URL patterns to look for
VIDEO_PATTERNS = [
    "video", ".mp4", ".m3u8", ".webm",
    "youtube.com/watch", "youtu.be/",
    "t.co",  # Twitter shortened URLs that may link to video
]


def is_video_url(url: str) -> bool:
    return any(pat in url.lower() for pat in VIDEO_PATTERNS)


def transcribe_audio_file(audio_path: Path) -> str | None:
    """Send audio file to Groq Whisper for transcription."""
    if not GROQ_API_KEY:
        print("  [WARN]  GROQ_API_KEY not set — skipping transcription")
        return None

    client = Groq(api_key=GROQ_API_KEY)
    try:
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(audio_path.name, f.read()),
                model="whisper-large-v3",
                language="en",
                response_format="text",
            )
        return result.strip() if isinstance(result, str) else result.text.strip()
    except Exception as e:
        print(f"  [WARN]  Groq transcription failed: {e}")
        return None


def download_audio(url: str, out_stem: str) -> Path | None:
    """Download audio track from a video URL using yt-dlp."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    out_path = AUDIO_DIR / f"{out_stem}.mp3"

    ydl_opts = {
        "format":        "bestaudio/best",
        "outtmpl":       str(AUDIO_DIR / out_stem),
        "postprocessors": [{
            "key":            "FFmpegExtractAudio",
            "preferredcodec": "mp3",
        }],
        "quiet":       True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return out_path if out_path.exists() else None
    except Exception as e:
        print(f"  [WARN]  yt-dlp failed for {url[:60]}: {e}")
        return None


def process_media():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    # Posts with media URLs but no transcript yet
    c.execute("""
        SELECT id, media_urls FROM posts
        WHERE transcript IS NULL
          AND media_urls IS NOT NULL
          AND media_urls != '[]'
    """)
    posts = c.fetchall()

    if not posts:
        print("[OK] Transcription: no new media to process")
        conn.close()
        return

    transcribed = 0
    for post_id, media_urls_json in posts:
        media_urls = json.loads(media_urls_json)
        for url in media_urls:
            if not is_video_url(url):
                continue

            safe_id   = post_id.replace("/", "_").replace(":", "_")
            print(f"  [VIDEO] Transcribing {url[:70]}...")

            audio_path = download_audio(url, safe_id)
            if not audio_path:
                continue

            transcript = transcribe_audio_file(audio_path)

            # Clean up audio file
            try:
                audio_path.unlink()
            except Exception:
                pass

            if transcript:
                c.execute("UPDATE posts SET transcript = ? WHERE id = ?", (transcript, post_id))
                conn.commit()
                transcribed += 1
                print(f"  [OK] Transcript saved ({len(transcript)} chars)")
            break  # One video per post is enough

    conn.close()
    print(f"[OK] Transcription: {transcribed} posts transcribed")


if __name__ == "__main__":
    process_media()
