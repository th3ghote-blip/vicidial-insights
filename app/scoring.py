"""
Rule-based lead scoring.

Score range: 0-100. Higher = call sooner / route to top closer.
The recommendation enum drives the dashboard's per-lead suggestion.

This is intentionally rule-based, not ML — it's transparent, the client's
admin can audit it, and we don't have labeled training data yet. Once we
have ~3 months of real conversion outcomes we can swap this for a model
trained on the same features.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .config import settings


class Recommendation(str, Enum):
    CALL_NOW = "call_now"           # high engagement, fresh signal
    ROUTE_TO_CLOSER = "route_closer" # warm but not yet closing — needs A-team
    CALLBACK_DUE = "callback_due"   # explicit CB scheduled
    REST = "rest"                   # too soon to recall, let cool off
    DNC_REVIEW = "dnc_review"       # called too many times no answer


def _hours_since(iso_ts: str | None) -> float:
    if not iso_ts:
        return 9999.0
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return 9999.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


def score_lead(lead: dict[str, Any]) -> dict[str, Any]:
    called = int(lead.get("called_count") or 0)
    last_dur = int(lead.get("last_call_duration_sec") or 0)
    last_dispo = (lead.get("last_call_dispo") or lead.get("status") or "").upper()
    hours_since_last = _hours_since(lead.get("last_local_call_time"))
    hours_since_entry = _hours_since(lead.get("entry_date"))

    score = 50.0
    reasons: list[str] = []

    # Disposition signals
    if last_dispo == settings.dispo_callback.upper():
        score += 25
        reasons.append("callback scheduled")
    if last_dispo == settings.dispo_sale.upper():
        # Already sold — not a calling target
        return {
            **lead,
            "score": 0,
            "recommendation": Recommendation.REST.value,
            "reasons": ["already converted"],
        }
    if last_dispo == "DNC":
        return {
            **lead,
            "score": 0,
            "recommendation": Recommendation.REST.value,
            "reasons": ["do not call"],
        }
    if last_dispo == "NI":
        score -= 20
        reasons.append("not interested on last call")

    # Engagement signal — long previous conversation = warm
    if last_dur >= 120:
        score += 20
        reasons.append("engaged on previous call (>2min)")
    elif last_dur >= 60:
        score += 10
        reasons.append("moderate engagement (>1min)")
    elif 0 < last_dur < 15 and called >= 1:
        score -= 10
        reasons.append("hung up quickly")

    # Lead age — fresh leads convert faster on financial products
    if hours_since_entry < 24:
        score += 15
        reasons.append("fresh lead (<24h)")
    elif hours_since_entry < 72:
        score += 5
    elif hours_since_entry > 24 * 60:  # 60 days
        score -= 5

    # Recency cooldown — don't recall someone we just dialed
    if hours_since_last < 4 and called >= 1:
        score -= 15
        reasons.append("just called, let it rest")

    # Excessive attempts — flag for DNC review, low priority
    if called >= 6 and last_dispo in {"NA", "B", ""}:
        return {
            **lead,
            "score": 5,
            "recommendation": Recommendation.DNC_REVIEW.value,
            "reasons": [f"{called} attempts with no contact"],
        }

    # Clamp
    score = max(0.0, min(100.0, score))

    rec: Recommendation
    if last_dispo == settings.dispo_callback.upper() and hours_since_last >= 1:
        rec = Recommendation.CALLBACK_DUE
    elif score >= 75 and last_dur >= 60:
        rec = Recommendation.ROUTE_TO_CLOSER
    elif score >= 60:
        rec = Recommendation.CALL_NOW
    else:
        rec = Recommendation.REST

    return {
        **lead,
        "score": round(score, 1),
        "recommendation": rec.value,
        "reasons": reasons,
    }


def score_and_rank(leads: list[dict[str, Any]], top_n: int | None = None) -> list[dict[str, Any]]:
    scored = [score_lead(l) for l in leads]
    scored.sort(key=lambda l: l["score"], reverse=True)
    return scored[:top_n] if top_n else scored
