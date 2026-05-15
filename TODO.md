# vicidial-insights — TODO

## Blocked on client
- [ ] Vicidial admin: read-only MySQL credentials (host, user, password, db name — likely `asterisk`)
- [ ] Vicidial admin: confirm DISPO codes used for **Sale closed** (e.g. `SALE` / `SOLD` / `CLOSED`)
- [ ] Vicidial admin: confirm DISPO codes for **Callback** (e.g. `CALLBK` / `CB`)
- [ ] Vicidial admin: list any custom lead fields beyond name/phone/address/state/zip
- [ ] Vicidial admin: confirm external MySQL connections allowed (or fall back to Non-Agent API)

## Scaffold (mock-mode build)
- [x] Project skeleton, README, .env.example, .gitignore, requirements.txt
- [x] Mock Vicidial layer matching real schema (vicidial_list, vicidial_log, vicidial_agent_log, vicidial_campaigns)
- [x] Real Vicidial layer (PyMySQL queries — same return shapes as mock)
- [x] Rule-based lead scoring (called_count, last duration, lead age, dispo, time-of-day fit)
- [x] FastAPI endpoints (`/leads/priority`, `/agents/leaderboard`, `/insights/weekly`, `/health`)
- [x] Claude Haiku weekly summary (Spanish-first, EN on request)
- [x] Supabase schema for cached snapshots (`supabase_schema.sql` — lead_scores, weekly_summaries, agent_stats, dispositions)
- [x] Railway deploy config (`railway.json` + `Procfile`)
- [x] Smoke test (`smoke_test.py`) — passes against mocks, all 6 endpoints 200

- [x] Supabase project provisioned (`otscnkluhdmxahlogzpb`), schema applied, end-to-end write/read verified
- [x] Supabase write path — `app/cache.py` via httpx → PostgREST (skipped supabase-py SDK; new key format incompatible)

## Not yet built
- [ ] Nightly job runner — `app/jobs.py` with CLI entry + Railway cron config (or `/schedule` routine)
- [ ] Trend endpoints that read from `lead_score_snapshots` / `agent_stats_snapshots` over time
- [x] Auth on the FastAPI surface — bearer token via `app/auth.py`, all endpoints except `/health` require it
- [x] Rate limiting on `/insights/weekly` — 30 calls/hour in-process sliding window
- [ ] Rotate `sb_secret_` key after pipeline is stable (was pasted in chat)

## Wire-up (when creds land)
- [ ] Drop creds into Railway env vars
- [ ] Flip `MOCK_MODE=false`
- [ ] Verify schema match against real Vicidial (column names, types)
- [ ] First nightly cron run end-to-end
- [ ] Base44 frontend points at Railway URL

## Pre-flight before declaring "done"
- [ ] DISPO codes from admin actually match what scoring expects
- [ ] Service role key on Railway, anon key on Base44
- [ ] Railway cron in UTC, schedule sane vs client's call hours
- [ ] Cost check: Haiku spend after first week
