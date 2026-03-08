# 📰 Daily News Agent

AI-powered news aggregation, verification, and delivery system. Fetches news from 20+ sources, verifies claims using structured APIs and LLM, syncs verified items to Google Calendar, and sends Telegram digests twice daily.

## Features

- **Multi-source ingestion** — RSS feeds, HackerNews, Reddit, Currents API, GNews, NewsData.io
- **Smart verification** — 80% structured (source reliability, multi-source corroboration, ticker enrichment) + 20% LLM (Groq/Gemini for complex claims)
- **Google Calendar sync** — Dedicated "📰 Daily News" calendar with color-coded, confidence-badged events
- **Telegram notifications** — Morning brief (8 AM IST) + Evening recap (10 PM IST) + Breaking alerts (Finance & Geo-politics)
- **Ticker tracking** — NVDA, TSLA, AAPL, MSFT, GOOGL, AMZN, META, BTC, ETH, RELIANCE, INFY, TCS
- **Hype detection** — Flags "breakthrough" claims and reduces confidence for unsubstantiated hype

## Coverage

| Domain | Sources |
|--------|---------|
| AI & Tech | HackerNews, ArXiv, TechCrunch, The Verge, Wired |
| Finance | WSJ, Moneycontrol, Economic Times, SEC EDGAR, Federal Reserve |
| Geo-Politics | BBC World, Al Jazeera, Reuters, Foreign Policy, NDTV |
| India | RBI, SEBI, PIB, Moneycontrol, Economic Times, LiveMint |
| Startups | TechCrunch Startups, LiveMint |

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/Daily-News-Agent.git
cd Daily-News-Agent
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your API keys:

```bash
copy .env.example .env
```

Required keys:
| Key | Get from |
|-----|----------|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) on Telegram |
| `TELEGRAM_CHAT_ID` | Send a message to your bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` |
| `GNEWS_API_KEY` | [gnews.io](https://gnews.io) |
| `NEWSDATA_API_KEY` | [newsdata.io](https://newsdata.io) |

### 3. Google Calendar Setup (One-time)

```bash
python auth_calendar.py
```

This opens your browser for Google login. After authorizing, it prints the `GOOGLE_CREDENTIALS_JSON` value — paste it into your `.env` file.

### 4. Get Telegram Chat ID

1. Open Telegram and send any message to your bot
2. Run:
```bash
# PowerShell
Invoke-RestMethod -Uri "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" | ConvertTo-Json
```
3. Find `"chat":{"id": 123456789}` in the response
4. Add that ID to `.env` as `TELEGRAM_CHAT_ID`

### 5. Run Locally

```bash
uvicorn main:app --reload
```

The agent will:
- Start fetching news immediately
- Fetch every 15 minutes
- Send morning brief at 8:00 AM IST
- Send evening recap at 10:00 PM IST
- Send breaking alerts for Finance/Geo-politics (confidence > 85%)

### 6. API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/status` | GET | Current stats + scheduled jobs |
| `/trigger` | POST | Manual fetch + verify |
| `/claims?hours=24` | GET | Recent claims |

## Deploy to Render

1. Push to GitHub
2. Go to [render.com](https://render.com) → New → Blueprint
3. Connect your repo
4. Render will read `render.yaml` and create the web service + database
5. Add all `.env` variables to Render's Environment tab
6. Deploy!

## Architecture

```
RSS Feeds (20+) ─┐
HackerNews API  ──┤
Reddit JSON API ──┤──► Ingest Manager ──► Structured Verify (80%)─┐
Currents API    ──┤        │               LLM Verify (20%) ──────┤
GNews API       ──┤        │                                      │
NewsData.io     ──┘        ▼                                      ▼
               Deduplication                              Confidence Score
                                                              │
                                ┌──────────────────────────────┤
                                ▼                              ▼
                        Google Calendar                 Telegram Bot
                       (📰 Daily News)              (8AM / 10PM / Breaking)
```

## License

MIT
