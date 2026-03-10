# Directive: AI Content Pipeline

## Goal
Automatically collect AI-related posts from Twitter/X influencers and news sites daily,
transcribe any video content, extract common themes using Claude, and generate draft
posts (tweet + LinkedIn) for review before publishing.

## Sources

### Twitter/X Accounts
- @JulianGoldieSEO — https://x.com/JulianGoldieSEO
- @EHuanglu        — https://x.com/EHuanglu
- @rileybrown      — https://x.com/rileybrown

### News Sites (RSS)
- TechCrunch AI  — https://techcrunch.com/category/artificial-intelligence/feed/
- WSJ Tech/AI    — https://feeds.a.dj.com/rss/RSSWSJD.xml

### News Sites (Scrape)
- Calcalist Tech — https://www.calcalistech.com/ctechnews/category/36042

## Pipeline Steps (in order)

| Step | Script                          | Purpose                                      |
|------|---------------------------------|----------------------------------------------|
| 1    | `execution/init_db.py`          | Create SQLite DB if it doesn't exist         |
| 2    | `execution/fetch_twitter.py`    | Fetch latest tweets via twikit (unofficial)  |
| 3    | `execution/fetch_news.py`       | Fetch RSS feeds + scrape Calcalist           |
| 4    | `execution/transcribe_media.py` | Transcribe video content via Groq Whisper    |
| 5    | `execution/extract_themes.py`   | Extract 3–5 themes using Claude              |
| 6    | `execution/generate_posts.py`   | Generate tweet + LinkedIn draft using Claude |
| 7    | `execution/export_to_sheets.py` | Push digest to Google Sheets for review      |

All steps are orchestrated by `execution/run_pipeline.py`.

## Environment Variables Required

```
TWITTER_USERNAME=       # Twitter/X login handle or email
TWITTER_PASSWORD=       # Twitter/X password
TWITTER_EMAIL=          # Twitter email (used as fallback auth)
ANTHROPIC_API_KEY=      # Claude API (theme extraction + content generation)
GROQ_API_KEY=           # Free Whisper transcription (console.groq.com)
DIGEST_SHEET_ID=        # Google Sheet ID — auto-created on first run, then paste here
```

## Output Format (Google Sheets)

**Sheet: "Summary"**
- Top story of the day
- 3–5 themes with summaries
- Generated tweet (≤280 chars)
- Generated LinkedIn post (150–250 words)

**Sheet: "Raw Posts"**
- All fetched posts: source, author, content, URL

## Database Schema (`.tmp/pipeline.db`)

```sql
posts    (id, source, author, content, url, media_urls, transcript, fetched_at, processed)
digests  (id, date, themes, summary, tweet_draft, linkedin_draft, created_at)
```

## Schedule
- Runs daily at **8:00 AM** local time via scheduled task
- Script: `python execution/run_pipeline.py`
- Working directory: project root

## Edge Cases & Known Constraints

- **Twitter rate limits**: Login cookies saved to `.tmp/twitter_cookies.json` — avoids re-login every run. If expired, delete the file and re-run.
- **Twitter 2FA**: On first login, twikit may prompt for email/phone code. Run `fetch_twitter.py` manually once to authenticate.
- **WSJ paywall**: Only headline + teaser from RSS (no full article). Still useful for theme extraction.
- **Missing GROQ_API_KEY**: Transcription step is skipped silently; posts are still processed without transcripts.
- **Missing DIGEST_SHEET_ID**: A new Google Sheet is created on first export run. The ID is printed to console — copy it to `.env`.
- **Calcalist Hebrew content**: Treated as raw text; Claude handles multilingual input gracefully.
- **Duplicate posts**: Posts are deduplicated by ID before insert. Re-runs are safe.
- **No new content**: If all posts are already processed, steps 5–7 are skipped cleanly.

## Learnings Log
*(Update this section as the pipeline runs and issues are discovered)*

- [2026-03-08] Initial setup
- [2026-03-08] Windows cp1252 encoding: Python on Windows crashes on emoji in print() statements. Fix: replace all emoji with ASCII tags ([OK], [WARN], [ERROR], etc.) across every script. Also pass `PYTHONUTF8=1` in subprocess env in run_pipeline.py.
- [2026-03-08] First run requires: `pip install -r requirements.txt` before launching pipeline.
- [2026-03-08] `load_dotenv()` without `override=True` silently fails on Windows when env vars already exist in parent process. Fix: all scripts use `load_dotenv(override=True)`.
- [2026-03-08] Twitter login blocked by Cloudflare (403) when using username/password via twikit. Fix: use browser cookies instead. Set TWITTER_AUTH_TOKEN + TWITTER_CT0 in .env (see fetch_twitter.py docstring for instructions). Twitter marked non-critical so pipeline continues with news-only content.
- [2026-03-08] twikit cookie format: httpx 0.28+ requires cookies as a list of 2-element lists `[["name","value"],...]`, NOT a dict and NOT a list of browser-format objects. The cookies file must be manually written in this format — do NOT use twikit's `save_cookies` output as a template.
- [2026-03-08] Cookie file rebuild: if TWITTER_AUTH_TOKEN + TWITTER_CT0 change in .env, delete `.tmp/twitter_cookies.json` and re-run to force a rebuild. twikit will use the stale file as long as it exists.
- [2026-03-08] Anthropic API key valid but account needs credits topped up before Claude calls will succeed. Top up at console.anthropic.com → Billing.
- [2026-03-08] News deduplication works correctly — second run shows 0 new articles (expected, not a bug).
- [2026-03-09] Anthropic model  is NOT available on Tier 1 accounts. Use  instead. Available models on Tier 1: , .
- [2026-03-09] Anthropic Credit grants (promotional) do NOT unlock API access on their own — a real credit purchase (Buy Credits button) is required to activate the API. Once purchased, the account moves to Tier 1 and API calls succeed.
- [2026-03-09] Pipeline fully tested end-to-end: 87 posts → 5 themes extracted → tweet + LinkedIn post generated successfully. Cost per full run: approx $0.05-0.10.
- [2026-03-09] Google Sheets export requires credentials.json (OAuth) — if not present, export step fails non-critically. See Step 7 in pipeline steps for setup instructions.
