# Lead Loop

Lead Loop is a pipeline that turns local business listings into booked sales meetings. It scrapes businesses by city and category, opens outreach on WhatsApp with a short video instead of a cold pitch, and once a lead replies, an LLM tool-calling agent (LangGraph, GPT-4o-mini) takes over — qualifying them in Russian, Kazakh, or English, then booking straight onto a real Google Calendar with a Meet link. A status field per lead keeps scraping, messaging, and live chats from colliding.

## Stack

Python, Flask, Playwright, Green API, LangGraph, GPT-4o-mini, Google Calendar API, Supabase.

## Setup

Copy `.env.example` to `.env` and fill in your own keys. Google Calendar access needs an `oauth_credentials.json` client secrets file (not included) in the project root; the first run opens a browser to authorize and caches the token locally.

```
pip install -r requirements.txt
python webhook.py
```

`admin_panel_2gis.html` is a static dashboard for running the scraper and broadcast — open it in a browser and fill in `CONFIG.SUPABASE_KEY` locally before use.
