"""
run_pipeline.py
Main orchestrator. Runs all pipeline steps in sequence.

Usage:
    python execution/run_pipeline.py

Steps are defined as (name, script_path, critical).
If a critical step fails, the pipeline halts.
Non-critical steps (e.g. transcription) log a warning and continue.
"""

import io
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Force UTF-8 stdout on Windows to handle unicode in print statements
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# (display_name, script_path, is_critical)
STEPS = [
    ("Init Database",        "execution/init_db.py",                  True),
    ("Fetch Twitter",        "execution/fetch_twitter.py",             False),  # Non-critical: needs browser cookies
    ("Fetch News",           "execution/fetch_news.py",                True),
    ("Transcribe Media",     "execution/transcribe_media.py",          False),  # Optional: needs GROQ_API_KEY + ffmpeg
    ("Arabic Titles",        "execution/generate_arabic_titles.py",    False),  # Optional: needs ANTHROPIC_API_KEY
    ("Extract Themes",       "execution/extract_themes.py",            True),
    ("Generate Posts",       "execution/generate_posts.py",            True),
    ("Export to Sheets",     "execution/export_to_sheets.py",          False),  # Optional: needs Google credentials
]


def run_step(name: str, script: str) -> bool:
    """Run a single step. Returns True on success."""
    print(f"\n{'─'*60}")
    print(f"  >  {name}")
    print(f"{'─'*60}")
    result = subprocess.run(
        [sys.executable, script],
        capture_output=False,
        text=True,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    return result.returncode == 0


def main():
    start = datetime.now()
    print(f"\n{'='*60}")
    print(f"  [START] AI Content Pipeline — {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    for name, script, is_critical in STEPS:
        if not Path(script).exists():
            print(f"  [WARN]  Script not found: {script} — skipping")
            continue

        success = run_step(name, script)

        if not success:
            if is_critical:
                print(f"\n  [ERROR] Critical step failed: {name}")
                print(f"     Pipeline halted. Fix the error above and re-run.")
                sys.exit(1)
            else:
                print(f"\n  [WARN]  Non-critical step failed: {name} — continuing")

    elapsed = (datetime.now() - start).seconds
    print(f"\n{'='*60}")
    print(f"  [OK] Pipeline complete in {elapsed}s")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
