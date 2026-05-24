"""
Background prefetch worker — keeps Redis warm so no user ever waits on MySQL.

Runs every 4 minutes via APScheduler (started in main.py lifespan).
Also triggered once at startup so cache is hot from the first request.

Only active when:
  - REDIS_URL is set
  - MOCK_MODE is false (mock data is instant; no point caching it)

Each cache key mirrors the endpoint + default params used by the dashboard.
TTL is settings.cache_ttl (300s) — prefetch interval (240s) < TTL so cache
is always refreshed before it expires.
"""
from __future__ import annotations

import logging

from . import vicidial, scoring
from .config import settings
from .redis_cache import cache_set

log = logging.getLogger(__name__)

TTL = settings.cache_ttl  # 300s default


def run_prefetch() -> None:
    if settings.mock_mode:
        return

    log.info("prefetch: starting full refresh")
    errors: list[str] = []

    def _try(label: str, key: str, fn):
        try:
            result = fn()
            cache_set(key, result, TTL)
        except Exception as exc:
            errors.append(label)
            log.error("prefetch: %s failed — %s", label, exc)

    # leads/priority (top_n=40, days_back=30)
    def _leads():
        leads = vicidial.fetch_leads(days_back=30)
        scored = scoring.score_and_rank(leads, top_n=40)
        return {"count": len(leads), "returned": min(40, len(leads)), "leads": scored}

    _try("leads:30:40", "vi:leads:30:40", _leads)

    # agents/leaderboard
    for days in [7, 30]:
        _try(
            f"agents:{days}",
            f"vi:agents:{days}",
            lambda d=days: {"agents": vicidial.fetch_agent_stats(days_back=d)},
        )

    # dispositions
    for days in [7, 30]:
        _try(
            f"dispos:{days}",
            f"vi:dispos:{days}",
            lambda d=days: {"dispositions": vicidial.fetch_disposition_breakdown(days_back=d)},
        )

    # call times
    _try("call_times:7",  "vi:call_times:7",  lambda: {"hours": vicidial.fetch_call_times_by_hour(days_back=7)})

    # sales trend
    _try("sales_trend:7", "vi:sales_trend:7", lambda: {"days": vicidial.fetch_sales_trend(days_back=7)})

    # campaigns
    _try("campaigns",          "vi:campaigns",          lambda: {"campaigns": vicidial.fetch_campaigns()})
    _try("campaign_perf:30",   "vi:campaign_perf:30",   lambda: {"campaigns": vicidial.fetch_campaign_performance(days_back=30)})

    # momentum
    _try("momentum:28", "vi:momentum:28", lambda: {"agents": vicidial.fetch_agent_momentum(days_back=28)})

    # lead sources
    _try("sources:30", "vi:sources:30", lambda: {"sources": vicidial.fetch_lead_sources(days_back=30)})

    # pipeline forecast
    _try("forecast", "vi:forecast", vicidial.fetch_pipeline_forecast)

    # contact velocity
    _try("velocity:7", "vi:velocity:7", lambda: vicidial.fetch_contact_velocity(days_back=7))

    # agent × campaign matrix
    _try("agent_campaign:30", "vi:agent_campaign:30", lambda: {"matrix": vicidial.fetch_agent_campaign_matrix(days_back=30)})

    if errors:
        log.warning("prefetch: finished with %d error(s): %s", len(errors), ", ".join(errors))
    else:
        log.info("prefetch: complete — all keys refreshed")
