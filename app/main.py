"""
FastAPI surface consumed by the Base44 dashboard.

Endpoints stay thin: pull from vicidial layer (mock or real), pass through
scoring/summary, return JSON. No business logic in this file.

Auth: bearer token required on every endpoint except /health.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from . import vicidial, scoring, summary
from .auth import rate_limit_weekly, require_token


app = FastAPI(title="vicidial-insights", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin] if settings.allowed_origin != "*" else ["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Open endpoint — used by Railway healthcheck and uptime monitors."""
    return {
        "status": "ok",
        "mock_mode": settings.mock_mode,
        "auth_configured": bool(settings.api_token),
        "supabase_configured": bool(settings.supabase_url and settings.supabase_service_key),
        "anthropic_configured": bool(settings.anthropic_api_key),
        "dispo_sale": settings.dispo_sale,
        "dispo_callback": settings.dispo_callback,
    }


@app.get("/leads/priority", dependencies=[Depends(require_token)])
def leads_priority(
    top_n: int = Query(40, ge=1, le=500),
    days_back: int = Query(30, ge=1, le=180),
):
    leads = vicidial.fetch_leads(days_back=days_back)
    return {
        "count": len(leads),
        "returned": min(top_n, len(leads)),
        "leads": scoring.score_and_rank(leads, top_n=top_n),
    }


@app.get("/agents/leaderboard", dependencies=[Depends(require_token)])
def agents_leaderboard(days_back: int = Query(7, ge=1, le=90)):
    return {"agents": vicidial.fetch_agent_stats(days_back=days_back)}


@app.get("/insights/dispositions", dependencies=[Depends(require_token)])
def dispositions(days_back: int = Query(7, ge=1, le=90)):
    return {"dispositions": vicidial.fetch_disposition_breakdown(days_back=days_back)}


@app.get("/insights/call-times", dependencies=[Depends(require_token)])
def call_times(days_back: int = Query(7, ge=1, le=90)):
    return {"hours": vicidial.fetch_call_times_by_hour(days_back=days_back)}


@app.get("/insights/sales-trend", dependencies=[Depends(require_token)])
def sales_trend(days_back: int = Query(7, ge=1, le=90)):
    return {"days": vicidial.fetch_sales_trend(days_back=days_back)}


@app.get(
    "/insights/weekly",
    dependencies=[Depends(require_token), Depends(rate_limit_weekly)],
)
def weekly_insight(lang: str = Query("es", pattern="^(es|en)$")):
    agents = vicidial.fetch_agent_stats(days_back=7)
    dispos = vicidial.fetch_disposition_breakdown(days_back=7)
    leads = vicidial.fetch_leads(days_back=30)
    top_leads_count = sum(1 for l in scoring.score_and_rank(leads) if l["score"] >= 60)
    text = summary.generate_summary(agents, dispos, top_leads_count, lang=lang)
    return {"lang": lang, "summary": text, "top_leads_count": top_leads_count}


@app.get("/campaigns", dependencies=[Depends(require_token)])
def campaigns():
    return {"campaigns": vicidial.fetch_campaigns()}


@app.get("/campaigns/performance", dependencies=[Depends(require_token)])
def campaign_performance(days_back: int = Query(30, ge=1, le=180)):
    return {"campaigns": vicidial.fetch_campaign_performance(days_back=days_back)}


@app.get("/agents/momentum", dependencies=[Depends(require_token)])
def agents_momentum(weeks_back: int = Query(4, ge=2, le=12)):
    return {"agents": vicidial.fetch_agent_momentum(weeks_back=weeks_back)}


@app.get("/insights/sources", dependencies=[Depends(require_token)])
def insights_sources(days_back: int = Query(30, ge=1, le=180)):
    return {"sources": vicidial.fetch_lead_sources(days_back=days_back)}


@app.get("/insights/forecast", dependencies=[Depends(require_token)])
def insights_forecast():
    return vicidial.fetch_pipeline_forecast()


@app.get("/insights/contact-velocity", dependencies=[Depends(require_token)])
def insights_contact_velocity(days_back: int = Query(7, ge=1, le=30)):
    return vicidial.fetch_contact_velocity(days_back=days_back)


@app.get("/agents/by-campaign", dependencies=[Depends(require_token)])
def agents_by_campaign(days_back: int = Query(30, ge=1, le=180)):
    return {"matrix": vicidial.fetch_agent_campaign_matrix(days_back=days_back)}


@app.get("/insights/alerts", dependencies=[Depends(require_token)])
def insights_alerts(lang: str = Query("es", pattern="^(es|en)$")):
    momentum  = vicidial.fetch_agent_momentum(weeks_back=4)
    sources   = vicidial.fetch_lead_sources(days_back=30)
    forecast  = vicidial.fetch_pipeline_forecast()
    velocity  = vicidial.fetch_contact_velocity(days_back=7)
    campaigns = vicidial.fetch_campaign_performance(days_back=30)
    alerts = summary.generate_alerts(momentum, sources, forecast, velocity, campaigns, lang=lang)
    return {"lang": lang, "count": len(alerts), "alerts": alerts}
