"""
Supabase cache / historical snapshot layer.

We hit PostgREST directly with httpx instead of the supabase-py SDK because:
- supabase-py 2.10 rejects new-format `sb_secret_` keys
- We only do bulk inserts and recent-window selects — no auth, no realtime, no storage
- Fewer deps, no async/sync glue

Auth: pass `apikey` AND `Authorization: Bearer <key>` headers per PostgREST spec.
Service-role key bypasses RLS — required for the worker to write across all rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .config import settings


def _headers() -> dict[str, str]:
    return {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
        # Per his Supabase memory: inserts return empty by default — opt in if we ever need the row back.
        "Prefer": "return=minimal",
    }


def _base_url() -> str:
    return f"{settings.supabase_url.rstrip('/')}/rest/v1"


def is_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)


def _post(table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    if not is_configured():
        raise RuntimeError("Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_KEY")
    r = httpx.post(
        f"{_base_url()}/{table}",
        headers=_headers(),
        json=rows,
        timeout=30.0,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Supabase insert into {table} failed: {r.status_code} {r.text}")


def _get(table: str, params: dict[str, str]) -> list[dict[str, Any]]:
    r = httpx.get(
        f"{_base_url()}/{table}",
        headers={k: v for k, v in _headers().items() if k != "Prefer"},
        params=params,
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


# ---------- Writers (called by nightly job) -----------------------------------

def write_lead_snapshots(scored_leads: list[dict[str, Any]]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "snapshot_at": now,
            "lead_id": l["lead_id"],
            "score": l["score"],
            "recommendation": l["recommendation"],
            "reasons": l.get("reasons", []),
            "state": l.get("state"),
            "campaign_id": l.get("campaign_id"),
            "called_count": l.get("called_count"),
            "last_dispo": l.get("last_call_dispo") or l.get("status"),
            "last_call_at": l.get("last_local_call_time"),
        }
        for l in scored_leads
    ]
    _post("lead_score_snapshots", rows)
    return len(rows)


def write_agent_snapshots(stats: list[dict[str, Any]], period_days: int) -> int:
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "snapshot_at": now,
            "period_days": period_days,
            "user": s["user"],
            "full_name": s.get("full_name"),
            "calls_handled": s["calls_handled"],
            "sales": s["sales"],
            "close_rate": s["close_rate"],
            "talk_seconds": s["talk_seconds"],
            "avg_talk_sec": s["avg_talk_sec"],
        }
        for s in stats
    ]
    _post("agent_stats_snapshots", rows)
    return len(rows)


def write_dispo_snapshots(dispos: list[dict[str, Any]], period_days: int) -> int:
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"snapshot_at": now, "period_days": period_days, "dispo": d["dispo"], "count": d["count"]}
        for d in dispos
    ]
    _post("disposition_snapshots", rows)
    return len(rows)


def write_summary(text: str, lang: str, top_leads_count: int) -> None:
    _post("weekly_summaries", [{
        "lang": lang,
        "summary_text": text,
        "top_leads_count": top_leads_count,
    }])


# ---------- Readers (called by trend endpoints) -------------------------------

def latest_agent_snapshots(limit: int = 50) -> list[dict[str, Any]]:
    return _get("agent_stats_snapshots", {
        "select": "*",
        "order": "snapshot_at.desc",
        "limit": str(limit),
    })


def latest_summaries(lang: str, limit: int = 4) -> list[dict[str, Any]]:
    return _get("weekly_summaries", {
        "select": "*",
        "lang": f"eq.{lang}",
        "order": "generated_at.desc",
        "limit": str(limit),
    })


def ping() -> dict[str, Any]:
    """Cheap connectivity check — counts rows in lead_score_snapshots."""
    r = httpx.get(
        f"{_base_url()}/lead_score_snapshots",
        headers={**{k: v for k, v in _headers().items() if k != "Prefer"}, "Prefer": "count=exact", "Range": "0-0"},
        params={"select": "id"},
        timeout=10.0,
    )
    return {
        "status_code": r.status_code,
        "content_range": r.headers.get("content-range"),
        "ok": r.status_code in (200, 206),
    }
