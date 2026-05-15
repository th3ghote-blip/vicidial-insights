# vicidial-insights

Backend service that pulls call-center data from a client's Vicidial MySQL,
scores leads by conversion likelihood, generates Spanish-first AI summaries,
and serves it to a Base44 React dashboard.

## Architecture

```
Vicidial MySQL  →  Railway (Python/FastAPI)  →  Supabase (cache)  →  Base44 (UI)
                          ↓
                    Claude Haiku (weekly summaries)
```

- **Vicidial MySQL** — read-only, never written to
- **Railway** — FastAPI service + nightly cron job; ~$5/mo
- **Supabase** — caches scored snapshots so the dashboard doesn't hammer Vicidial; free tier
- **Base44** — frontend (already paid, $0 marginal); reads from FastAPI
- **Claude Haiku** — generates the weekly natural-language summary (~$0.10/day)

## Local dev (mock mode)

```bash
pip install -r requirements.txt
copy .env.example .env       # then edit; keep MOCK_MODE=true
uvicorn app.main:app --reload --port 8000
```

Then hit:
- http://localhost:8000/health
- http://localhost:8000/leads/priority
- http://localhost:8000/agents/leaderboard
- http://localhost:8000/insights/weekly?lang=es

## Deploy to Railway

```bash
railway login
railway link
railway up
```

Set env vars on Railway:
- `MOCK_MODE=false`
- `VICIDIAL_HOST`, `VICIDIAL_USER`, `VICIDIAL_PASSWORD`, `VICIDIAL_DB` (default `asterisk`)
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service role — this is a worker)
- `ANTHROPIC_API_KEY`
- `DISPO_SALE` (e.g. `SALE`), `DISPO_CALLBACK` (e.g. `CALLBK`) — confirm with admin
- `API_TOKEN` — bearer token Base44 sends on every request

## Auth

All endpoints except `/health` require `Authorization: Bearer <API_TOKEN>`.

Generate a fresh token:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set the same value in Railway env (`API_TOKEN`) AND in Base44's API client config.
Rotate by changing both sides.

`/insights/weekly` is also rate-limited to 30 calls/hour per process — caps Haiku
spend if a Base44 component re-render loop ever fires it in a tight loop.

## Schema swap

When real Vicidial creds land, only `MOCK_MODE=false` should change behavior.
If real-DB column names diverge from mock, update `app/vicidial.py` SQL — not the API layer.
