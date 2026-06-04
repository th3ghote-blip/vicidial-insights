"""
FastAPI surface consumed by the Next.js dashboard.

Endpoints stay thin: check Redis cache first, fall back to vicidial layer
(mock or real MySQL), return JSON. No business logic in this file.

Auth: bearer token required on every endpoint except /health.
Cache: Redis pre-warmed every 4 min by APScheduler (see prefetch.py).
       Endpoints read from cache on hit; on miss they query and write back.
       Cache is a no-op when REDIS_URL is not set.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from . import vicidial, scoring, summary
from .auth import rate_limit_weekly, require_token
from .redis_cache import cache_get, cache_set, is_available

log = logging.getLogger(__name__)

TTL = settings.cache_ttl  # 300s


# ---------------------------------------------------------------------------
# Lifespan — start APScheduler prefetch worker on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    if not settings.mock_mode and is_available():
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from .prefetch import run_prefetch

            scheduler = BackgroundScheduler(daemon=True)
            scheduler.add_job(run_prefetch, "interval", minutes=4, id="prefetch")
            scheduler.start()

            # Warm the cache immediately so the first request is instant
            import threading
            threading.Thread(target=run_prefetch, daemon=True).start()

            log.info("prefetch scheduler started — interval 4 min")
        except Exception as exc:
            log.warning("could not start prefetch scheduler: %s", exc)
    yield
    # nothing to clean up


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="vicidial-insights", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin] if settings.allowed_origin != "*" else ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "mock_mode": settings.mock_mode,
        "auth_configured": bool(settings.api_token),
        "anthropic_configured": bool(settings.anthropic_api_key),
        "redis_configured": bool(settings.redis_url),
        "redis_available": is_available(),
        "dispo_sale": settings.dispo_sale,
        "dispo_callback": settings.dispo_callback,
    }


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

@app.get("/leads/priority", dependencies=[Depends(require_token)])
def leads_priority(
    top_n: int = Query(40, ge=1, le=500),
    days_back: int = Query(30, ge=1, le=180),
):
    key = f"vi:leads:{days_back}:{top_n}"
    cached = cache_get(key)
    if cached:
        return cached
    leads = vicidial.fetch_leads(days_back=days_back)
    result = {
        "count": len(leads),
        "returned": min(top_n, len(leads)),
        "leads": scoring.score_and_rank(leads, top_n=top_n),
    }
    cache_set(key, result, TTL)
    return result


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@app.get("/agents/leaderboard", dependencies=[Depends(require_token)])
def agents_leaderboard(days_back: int = Query(7, ge=1, le=90)):
    key = f"vi:agents:{days_back}"
    cached = cache_get(key)
    if cached:
        return cached
    result = {"agents": vicidial.fetch_agent_stats(days_back=days_back)}
    cache_set(key, result, TTL)
    return result


@app.get("/agents/momentum", dependencies=[Depends(require_token)])
def agents_momentum(days_back: int = Query(28, ge=1, le=90)):
    key = f"vi:momentum:{days_back}"
    cached = cache_get(key)
    if cached:
        return cached
    result = {"agents": vicidial.fetch_agent_momentum(days_back=days_back)}
    cache_set(key, result, TTL)
    return result


@app.get("/agents/by-campaign", dependencies=[Depends(require_token)])
def agents_by_campaign(days_back: int = Query(30, ge=1, le=180)):
    key = f"vi:agent_campaign:{days_back}"
    cached = cache_get(key)
    if cached:
        return cached
    result = {"matrix": vicidial.fetch_agent_campaign_matrix(days_back=days_back)}
    cache_set(key, result, TTL)
    return result


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

@app.get("/insights/dispositions", dependencies=[Depends(require_token)])
def dispositions(days_back: int = Query(7, ge=1, le=90)):
    key = f"vi:dispos:{days_back}"
    cached = cache_get(key)
    if cached:
        return cached
    result = {"dispositions": vicidial.fetch_disposition_breakdown(days_back=days_back)}
    cache_set(key, result, TTL)
    return result


@app.get("/insights/call-times", dependencies=[Depends(require_token)])
def call_times(days_back: int = Query(7, ge=1, le=90)):
    key = f"vi:call_times:{days_back}"
    cached = cache_get(key)
    if cached:
        return cached
    result = {"hours": vicidial.fetch_call_times_by_hour(days_back=days_back)}
    cache_set(key, result, TTL)
    return result


@app.get("/insights/sales-trend", dependencies=[Depends(require_token)])
def sales_trend(days_back: int = Query(7, ge=1, le=90)):
    key = f"vi:sales_trend:{days_back}"
    cached = cache_get(key)
    if cached:
        return cached
    result = {"days": vicidial.fetch_sales_trend(days_back=days_back)}
    cache_set(key, result, TTL)
    return result


@app.get("/insights/sources", dependencies=[Depends(require_token)])
def insights_sources(days_back: int = Query(30, ge=1, le=180)):
    key = f"vi:sources:{days_back}"
    cached = cache_get(key)
    if cached:
        return cached
    result = {"sources": vicidial.fetch_lead_sources(days_back=days_back)}
    cache_set(key, result, TTL)
    return result


@app.get("/insights/forecast", dependencies=[Depends(require_token)])
def insights_forecast():
    key = "vi:forecast"
    cached = cache_get(key)
    if cached:
        return cached
    result = vicidial.fetch_pipeline_forecast()
    cache_set(key, result, TTL)
    return result


@app.get("/insights/contact-velocity", dependencies=[Depends(require_token)])
def insights_contact_velocity(days_back: int = Query(7, ge=1, le=30)):
    key = f"vi:velocity:{days_back}"
    cached = cache_get(key)
    if cached:
        return cached
    result = vicidial.fetch_contact_velocity(days_back=days_back)
    cache_set(key, result, TTL)
    return result


@app.get("/insights/alerts", dependencies=[Depends(require_token)])
def insights_alerts(lang: str = Query("es", pattern="^(es|en)$")):
    # alerts are derived from other cached data — skip caching here to always be fresh
    momentum  = vicidial.fetch_agent_momentum(days_back=28)
    sources   = vicidial.fetch_lead_sources(days_back=30)
    forecast  = vicidial.fetch_pipeline_forecast()
    velocity  = vicidial.fetch_contact_velocity(days_back=7)
    campaigns = vicidial.fetch_campaign_performance(days_back=30)
    alerts = summary.generate_alerts(momentum, sources, forecast, velocity, campaigns, lang=lang)
    return {"lang": lang, "count": len(alerts), "alerts": alerts}


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

@app.get("/campaigns", dependencies=[Depends(require_token)])
def campaigns():
    key = "vi:campaigns"
    cached = cache_get(key)
    if cached:
        return cached
    result = {"campaigns": vicidial.fetch_campaigns()}
    cache_set(key, result, TTL)
    return result


@app.get("/campaigns/performance", dependencies=[Depends(require_token)])
def campaign_performance(days_back: int = Query(30, ge=1, le=180)):
    key = f"vi:campaign_perf:{days_back}"
    cached = cache_get(key)
    if cached:
        return cached
    result = {"campaigns": vicidial.fetch_campaign_performance(days_back=days_back)}
    cache_set(key, result, TTL)
    return result


# ---------------------------------------------------------------------------
# Weekly insight (rate-limited, never cached — AI call, expensive)
# ---------------------------------------------------------------------------

@app.get(
    "/insights/weekly",
    dependencies=[Depends(require_token), Depends(rate_limit_weekly)],
)
def weekly_insight(lang: str = Query("es", pattern="^(es|en)$")):
    agents = vicidial.fetch_agent_stats(days_back=7)
    dispos = vicidial.fetch_disposition_breakdown(days_back=7)
    leads  = vicidial.fetch_leads(days_back=30)
    top_leads_count = sum(1 for l in scoring.score_and_rank(leads) if l["score"] >= 60)
    text = summary.generate_summary(agents, dispos, top_leads_count, lang=lang)
    return {"lang": lang, "summary": text, "top_leads_count": top_leads_count}


# ---------------------------------------------------------------------------
# Chat (never cached — user-specific question)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str
    lang: str = "es"
    history: list[dict] = []


@app.post("/chat", dependencies=[Depends(require_token)])
def chat(req: ChatRequest):
    """Interactive AI chat against live Vicidial data. ~$0.001/call (Haiku)."""
    agents    = vicidial.fetch_agent_stats(days_back=7)
    cmpgns    = vicidial.fetch_campaign_performance(days_back=30)
    momentum  = vicidial.fetch_agent_momentum(days_back=28)
    answer = summary.chat_with_data(
        question=req.question,
        history=req.history,
        agents=agents,
        campaigns=list(cmpgns),
        momentum=momentum,
        lang=req.lang,
    )
    return {"answer": answer}


# ---------------------------------------------------------------------------
# Admin: manual prefetch trigger (authenticated)
# ---------------------------------------------------------------------------

@app.post("/prefetch/trigger", dependencies=[Depends(require_token)])
def trigger_prefetch():
    """Force an immediate cache refresh. Useful after deploying to a new client."""
    if settings.mock_mode:
        return {"status": "skipped", "reason": "mock_mode"}
    if not is_available():
        return {"status": "skipped", "reason": "redis_not_configured"}
    import threading
    from .prefetch import run_prefetch
    threading.Thread(target=run_prefetch, daemon=True).start()
    return {"status": "triggered"}
