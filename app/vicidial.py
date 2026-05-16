"""
Vicidial data access layer.

Two backends with identical return shapes:
- mock_*  : deterministic fake data for local dev / pre-creds work
- real_*  : PyMySQL queries against the client's Vicidial database

The router (`fetch_leads`, `fetch_agent_stats`, `fetch_campaigns`) picks the
backend based on `settings.mock_mode`. When the client's admin sends real
creds, only `MOCK_MODE=false` and possibly column-name tweaks in the SQL
strings should change.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from .config import settings


# ---------- Public interface ---------------------------------------------------

def fetch_leads(days_back: int = 30) -> list[dict[str, Any]]:
    if settings.mock_mode:
        return _mock_leads(days_back)
    return _real_leads(days_back)


def fetch_agent_stats(days_back: int = 7) -> list[dict[str, Any]]:
    if settings.mock_mode:
        return _mock_agent_stats(days_back)
    return _real_agent_stats(days_back)


def fetch_campaigns() -> list[dict[str, Any]]:
    if settings.mock_mode:
        return _mock_campaigns()
    return _real_campaigns()


def fetch_campaign_performance(days_back: int = 30) -> list[dict[str, Any]]:
    if settings.mock_mode:
        return _mock_campaign_performance(days_back)
    return _real_campaign_performance(days_back)


def fetch_agent_momentum(days_back: int = 28) -> list[dict[str, Any]]:
    if settings.mock_mode:
        return _mock_agent_momentum(days_back)
    return _real_agent_momentum(days_back)


def fetch_lead_sources(days_back: int = 30) -> list[dict[str, Any]]:
    if settings.mock_mode:
        return _mock_lead_sources(days_back)
    return _real_lead_sources(days_back)


def fetch_pipeline_forecast() -> dict[str, Any]:
    if settings.mock_mode:
        return _mock_pipeline_forecast()
    return _real_pipeline_forecast()


def fetch_contact_velocity(days_back: int = 7) -> dict[str, Any]:
    if settings.mock_mode:
        return _mock_contact_velocity(days_back)
    return _real_contact_velocity(days_back)


def fetch_agent_campaign_matrix(days_back: int = 30) -> list[dict[str, Any]]:
    if settings.mock_mode:
        return _mock_agent_campaign_matrix(days_back)
    return _real_agent_campaign_matrix(days_back)


def fetch_disposition_breakdown(days_back: int = 7) -> list[dict[str, Any]]:
    if settings.mock_mode:
        return _mock_dispo_breakdown(days_back)
    return _real_dispo_breakdown(days_back)


def fetch_call_times_by_hour(days_back: int = 7) -> list[dict[str, Any]]:
    """Hourly distribution of calls + sale conversions, for the 'best time' chart."""
    if settings.mock_mode:
        return _mock_call_times(days_back)
    return _real_call_times(days_back)


def fetch_sales_trend(days_back: int = 7) -> list[dict[str, Any]]:
    """Daily sales count over the window, for the trend line chart."""
    if settings.mock_mode:
        return _mock_sales_trend(days_back)
    return _real_sales_trend(days_back)


# ---------- Mock backend -------------------------------------------------------

# A fixed pool so repeated calls return stable results during dev.
_MOCK_STATES = ["FL", "TX", "CA", "NY", "GA", "AZ", "NV", "IL", "NJ", "NC", "WA", "CO", "PA", "OH", "MI"]
_MOCK_DISPOS = ["SALE", "CALLBK", "NI", "NA", "DNC", "B"]
_MOCK_SOURCES = ["web_form", "purchased_list", "referral", "inbound", "social_media"]
_MOCK_FIRST_NAMES = ["Carlos", "María", "Juan", "Ana", "Pedro", "Sofía", "Luis", "Rosa",
                     "Miguel", "Carmen", "Jorge", "Elena", "Roberto", "Diana", "Fernando"]
_MOCK_LAST_NAMES  = ["García", "Rodríguez", "Martínez", "López", "González", "Pérez",
                     "Sánchez", "Torres", "Ramírez", "Flores", "Castro", "Moreno", "Herrera", "Vega", "Núñez"]
_MOCK_AGENTS = [
    # (user_id, full_name, skill_factor)  — skill_factor drives close_rate variance
    ("agent_maria",   "María González",    0.13),
    ("agent_juan",    "Juan Pérez",         0.11),
    ("agent_ana",     "Ana Rodríguez",      0.10),
    ("agent_carlos",  "Carlos Sánchez",     0.09),
    ("agent_lucia",   "Lucía Fernández",    0.09),
    ("agent_pedro",   "Pedro Martínez",     0.08),
    ("agent_sofia",   "Sofía López",        0.07),
    ("agent_diego",   "Diego Ramírez",      0.07),
    ("agent_valeria", "Valeria Torres",     0.06),
    ("agent_miguel",  "Miguel Herrera",     0.06),
    ("agent_camila",  "Camila Vargas",      0.05),
    ("agent_andres",  "Andrés Castro",      0.05),
    ("agent_isabela", "Isabela Moreno",     0.04),
    ("agent_rodrigo", "Rodrigo Núñez",      0.04),
    ("agent_elena",   "Elena Vega",         0.03),
]
_MOCK_CAMPAIGNS = [
    ("CC_FL",    "Tarjetas de Crédito - Florida"),
    ("LOAN_TX",  "Préstamos Personales - Texas"),
    ("REFI_CA",  "Refinanciamiento - California"),
    ("CC_NY",    "Tarjetas de Crédito - Nueva York"),
    ("LOAN_GA",  "Préstamos Personales - Georgia"),
]


def _mock_leads(days_back: int) -> list[dict[str, Any]]:
    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    leads: list[dict[str, Any]] = []
    for i in range(300):
        called_count = rng.choices([0, 1, 2, 3, 4, 5, 6, 7, 8], weights=[10, 20, 25, 15, 10, 8, 5, 4, 3])[0]
        last_dispo = "" if called_count == 0 else rng.choices(_MOCK_DISPOS, weights=[3, 12, 25, 35, 5, 20])[0]
        if last_dispo == "SALE":
            last_dispo = settings.dispo_sale
        elif last_dispo == "CALLBK":
            last_dispo = settings.dispo_callback

        last_call_duration = 0 if called_count == 0 else rng.choices(
            [10, 30, 45, 75, 120, 180, 300, 480],
            weights=[15, 20, 20, 15, 12, 10, 5, 3],
        )[0]
        entry_age_days = rng.choices([0, 1, 3, 7, 14, 30, 60, 90], weights=[15, 15, 15, 15, 15, 10, 8, 7])[0]
        last_call_offset_hours = 0 if called_count == 0 else rng.randint(1, max(1, days_back) * 24)

        last_agent_id = "" if called_count == 0 else rng.choice(_MOCK_AGENTS)[0]
        last_agent_name = "" if called_count == 0 else next(
            (n for u, n, _ in _MOCK_AGENTS if u == last_agent_id), ""
        )
        leads.append({
            "lead_id": 100000 + i,
            "first_name": rng.choice(_MOCK_FIRST_NAMES),
            "last_name": rng.choice(_MOCK_LAST_NAMES),
            "phone_number": f"1{rng.randint(2000000000, 9999999999)}",
            "state": rng.choice(_MOCK_STATES),
            "postal_code": f"{rng.randint(10000, 99999)}",
            "entry_date": (now - timedelta(days=entry_age_days)).isoformat(),
            "status": last_dispo or "NEW",
            "called_count": called_count,
            "last_local_call_time": (
                None if called_count == 0
                else (now - timedelta(hours=last_call_offset_hours)).isoformat()
            ),
            "last_call_duration_sec": last_call_duration,
            "last_call_dispo": last_dispo,
            "total_call_seconds": last_call_duration * max(called_count, 1),
            "campaign_id": rng.choice(_MOCK_CAMPAIGNS)[0],
            "last_agent": last_agent_id,
            "last_agent_name": last_agent_name,
            "source": rng.choices(_MOCK_SOURCES, weights=[30, 40, 10, 15, 5])[0],
            "language": rng.choices(["es", "en"], weights=[75, 25])[0],
        })
    return leads


def _mock_agent_stats(days_back: int) -> list[dict[str, Any]]:
    """
    Real backend maps to:
      calls_handled  → COUNT(*) FROM vicidial_agent_log
      talk_seconds   → SUM(talk_sec)
      pause_seconds  → SUM(pause_sec)
      login_seconds  → SUM(talk_sec + wait_sec + dispo_sec + pause_sec + dead_sec)
      callbacks_set  → COUNT(*) WHERE status = dispo_callback FROM vicidial_log
      avg_wait_sec   → AVG(wait_sec) FROM vicidial_agent_log
    """
    rng = random.Random(7)
    out: list[dict[str, Any]] = []
    weekdays = max(1, int(days_back * 5 / 7))
    for user, full_name, skill in _MOCK_AGENTS:
        calls = rng.randint(120, 280) * max(1, days_back // 7)
        rate = max(0.01, min(0.20, skill + rng.uniform(-0.015, 0.015)))
        sales = max(1, int(calls * rate))
        avg_talk = rng.randint(75, 220)
        talk_sec = calls * avg_talk

        # Efficiency fields
        hours_per_day = rng.uniform(6.5, 8.5)
        login_sec = int(hours_per_day * 3600 * weekdays)
        pause_sec = int(login_sec * rng.uniform(0.05, 0.20))
        utilization = round(min(0.95, talk_sec / login_sec), 3) if login_sec else 0.0
        avg_wait = int((login_sec - talk_sec - pause_sec) / max(calls, 1))
        dials_per_hr = round(calls / (login_sec / 3600), 1) if login_sec else 0.0

        callbacks_set = int(calls * rng.uniform(0.06, 0.18))
        callbacks_converted = int(callbacks_set * rng.uniform(0.20, 0.55))

        out.append({
            "user": user,
            "full_name": full_name,
            "calls_handled": calls,
            "sales": sales,
            "close_rate": round(sales / calls, 4),
            "talk_seconds": talk_sec,
            "avg_talk_sec": float(avg_talk),
            # Efficiency
            "login_seconds": login_sec,
            "pause_seconds": pause_sec,
            "utilization_rate": utilization,       # talk / login (higher = busier)
            "avg_wait_sec": max(0, avg_wait),       # dead time between calls
            "dials_per_hour": dials_per_hr,
            # Follow-up
            "callbacks_set": callbacks_set,
            "callbacks_converted": callbacks_converted,
            "callback_conversion_rate": round(callbacks_converted / callbacks_set, 3) if callbacks_set else 0.0,
        })
    out.sort(key=lambda a: a["close_rate"], reverse=True)
    return out


def _mock_campaigns() -> list[dict[str, Any]]:
    return [{"campaign_id": cid, "campaign_name": name, "active": "Y"} for cid, name in _MOCK_CAMPAIGNS]


def _mock_call_times(days_back: int) -> list[dict[str, Any]]:
    rng = random.Random(13)
    out: list[dict[str, Any]] = []
    # Peaks 10am-12pm and 2pm-4pm; quiet evenings.
    weights = {
        8: 30, 9: 60, 10: 110, 11: 130, 12: 100, 13: 75,
        14: 120, 15: 140, 16: 95, 17: 70, 18: 45, 19: 25, 20: 15,
    }
    for hour in range(8, 21):
        calls = int(weights.get(hour, 20) * max(1, days_back / 7) * rng.uniform(0.8, 1.2))
        # Conversion rate is highest mid-morning (10-11) and mid-afternoon (14-15)
        rate = 0.10 if hour in (10, 11, 14, 15) else 0.06 if hour in (9, 12, 13, 16) else 0.03
        sales = int(calls * rate)
        out.append({"hour": hour, "calls": calls, "sales": sales})
    return out


_EPOCH = date(2024, 1, 1)  # fixed reference point for trend calculation

def _mock_sales_trend(days_back: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for d in range(days_back - 1, -1, -1):
        dt = (now - timedelta(days=d)).date()
        # Seed per absolute date — same date always returns same values regardless of window
        rng = random.Random(dt.toordinal())
        is_weekend = dt.weekday() >= 5
        # Trend based on absolute days since epoch, not relative to window
        days_since_epoch = (dt - _EPOCH).days
        trend_boost = min(days_since_epoch // 15, 8)
        base = 4 if is_weekend else 18
        sales = base + trend_boost + rng.randint(-4, 6)
        calls = sales * rng.randint(8, 14)
        out.append({"date": dt.isoformat(), "sales": max(0, sales), "calls": max(0, calls)})
    return out


def _mock_campaign_performance(days_back: int) -> list[dict[str, Any]]:
    """
    Real backend maps to:
      leads_total      → COUNT(*) FROM vicidial_list WHERE campaign_id = X
      leads_contacted  → COUNT(DISTINCT lead_id) FROM vicidial_log WHERE campaign_id = X
      total_dials      → COUNT(*) FROM vicidial_log WHERE campaign_id = X
      total_sales      → COUNT(*) WHERE status = dispo_sale
      avg_handle_sec   → AVG(length_in_sec)
      best_hour        → HOUR(call_date) with MAX(conversion_rate)
    """
    rng = random.Random(99)
    out: list[dict[str, Any]] = []
    days_of_week = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    for cid, name in _MOCK_CAMPAIGNS:
        leads_total = rng.randint(800, 4000)
        leads_contacted = int(leads_total * rng.uniform(0.30, 0.72))
        contact_rate = round(leads_contacted / leads_total, 3)
        total_dials = int(leads_contacted * rng.uniform(1.8, 4.5))
        total_sales = max(1, int(total_dials * rng.uniform(0.03, 0.11)))
        conversion_rate = round(total_sales / total_dials, 3)
        dials_per_sale = round(total_dials / total_sales, 1)
        avg_handle_sec = rng.randint(90, 260)
        best_hour = rng.choice([10, 11, 14, 15, 16])
        best_day = rng.choice(days_of_week)
        active_agents = rng.randint(3, 12)
        cost_per_lead = round(rng.uniform(1.5, 8.0), 2)   # USD, if tracked
        out.append({
            "campaign_id": cid,
            "campaign_name": name,
            "leads_total": leads_total,
            "leads_contacted": leads_contacted,
            "contact_rate": contact_rate,           # answered / total leads
            "penetration_rate": contact_rate,       # alias — % of list worked
            "total_dials": total_dials,
            "total_sales": total_sales,
            "conversion_rate": conversion_rate,     # sales / dials
            "dials_per_sale": dials_per_sale,       # lower = more efficient
            "avg_handle_time_sec": avg_handle_sec,
            "best_hour": best_hour,                 # hour of day with peak conversion
            "best_day": best_day,
            "active_agents": active_agents,
            "cost_per_lead_usd": cost_per_lead,     # from list purchase price if known
        })
    out.sort(key=lambda c: c["conversion_rate"], reverse=True)
    return out


def _mock_agent_momentum(days_back: int) -> list[dict[str, Any]]:
    """Per-agent close-rate trend series.

    Granularity auto-selected: daily (days_back<=14) or weekly (>14).
    Real backend: same SQL as agent_stats bucketed by day / ISO-week.
    """
    if days_back <= 14:
        n_points = max(2, days_back)
        granularity = "daily"
    else:
        n_points = min(13, max(2, (days_back + 6) // 7))
        granularity = "weekly"

    rng = random.Random(31)
    out: list[dict[str, Any]] = []
    for i, (user, full_name, skill) in enumerate(_MOCK_AGENTS):
        if i % 5 == 0:        # rising star
            base = max(0.02, skill - 0.05)
            trajectory = [
                base + (skill - base) * (w + 1) / n_points + rng.uniform(-0.005, 0.005)
                for w in range(n_points)
            ]
            status = "rising_star"
        elif i % 5 == 1:      # falling
            trajectory = [
                skill + (0.04 * (n_points - w - 1) / n_points) + rng.uniform(-0.005, 0.005)
                for w in range(n_points)
            ]
            trajectory = [trajectory[0]] + [
                t * (1 - 0.15 * (j + 1) / n_points) for j, t in enumerate(trajectory[1:])
            ]
            status = "needs_attention"
        elif i % 5 == 2:      # cooling slightly
            trajectory = [skill + rng.uniform(-0.005, 0.005) for _ in range(n_points - 1)]
            trajectory.append(skill * 0.85 + rng.uniform(-0.005, 0.005))
            status = "cooling"
        elif i % 5 == 3:      # on streak this week
            trajectory = [skill + rng.uniform(-0.01, 0.01) for _ in range(n_points - 1)]
            trajectory.append(skill * 1.4 + rng.uniform(0, 0.01))
            status = "on_streak"
        else:                  # stable
            trajectory = [skill + rng.uniform(-0.01, 0.01) for _ in range(n_points)]
            status = "stable"

        current = round(max(0.01, trajectory[-1]), 4)
        prior_avg = round(sum(trajectory[:-1]) / max(1, len(trajectory) - 1), 4)
        change_pct = round(((current - prior_avg) / prior_avg) * 100, 1) if prior_avg else 0.0

        out.append({
            "user": user,
            "full_name": full_name,
            "current_close_rate": current,
            "prior_avg_close_rate": prior_avg,
            "change_pct": change_pct,
            "status": status,
            "weekly_series": [round(max(0.0, t), 4) for t in trajectory],
            "series_granularity": granularity,   # "daily" | "weekly"
        })
    return out


def _mock_lead_sources(days_back: int) -> list[dict[str, Any]]:
    """Per-source ROI analysis. Real backend: GROUP BY l.source_id FROM vicidial_list JOIN vicidial_log."""
    rng = random.Random(53)
    out = []
    # Each source has different cost + quality characteristics
    profiles = {
        "web_form":        {"cost": 4.5,  "contact": 0.65, "conv": 0.10, "vol": (800, 1500)},
        "purchased_list":  {"cost": 1.2,  "contact": 0.32, "conv": 0.04, "vol": (2000, 4000)},
        "referral":        {"cost": 0.0,  "contact": 0.78, "conv": 0.18, "vol": (80, 200)},
        "inbound":         {"cost": 0.0,  "contact": 0.95, "conv": 0.22, "vol": (200, 500)},
        "social_media":    {"cost": 6.0,  "contact": 0.55, "conv": 0.08, "vol": (300, 700)},
    }
    for source, p in profiles.items():
        leads_total = rng.randint(*p["vol"])
        contacted = int(leads_total * p["contact"] * rng.uniform(0.9, 1.1))
        sales = max(1, int(contacted * p["conv"] * rng.uniform(0.85, 1.15)))
        cost_per_lead = p["cost"]
        cost_total = round(leads_total * cost_per_lead, 2)
        cost_per_sale = round(cost_total / sales, 2) if sales else 0
        out.append({
            "source": source,
            "leads_total": leads_total,
            "leads_contacted": contacted,
            "contact_rate": round(contacted / leads_total, 3),
            "sales": sales,
            "conversion_rate": round(sales / contacted, 3) if contacted else 0.0,
            "cost_per_lead_usd": cost_per_lead,
            "cost_total_usd": cost_total,
            "cost_per_sale_usd": cost_per_sale,
        })
    out.sort(key=lambda s: s["cost_per_sale_usd"])
    return out


def _mock_pipeline_forecast() -> dict[str, Any]:
    """
    Forecast next 7 days using:
      callbacks_scheduled_next_7d × historical_callback_conversion_rate
    Real backend: SELECT FROM vicidial_callbacks WHERE callback_time BETWEEN NOW AND NOW+7d.
    """
    rng = random.Random(71)
    callbacks_next_7d = rng.randint(80, 160)
    historical_cb_conv = round(rng.uniform(0.18, 0.32), 3)
    expected_cb_sales = int(callbacks_next_7d * historical_cb_conv)

    fresh_leads_next_7d = rng.randint(400, 700)
    fresh_conv = round(rng.uniform(0.06, 0.10), 3)
    expected_fresh_sales = int(fresh_leads_next_7d * fresh_conv)

    expected_total = expected_cb_sales + expected_fresh_sales
    last_week_sales = rng.randint(60, 110)
    delta_pct = round(((expected_total - last_week_sales) / last_week_sales) * 100, 1)

    return {
        "callbacks_scheduled_next_7d": callbacks_next_7d,
        "historical_callback_conversion": historical_cb_conv,
        "expected_callback_sales": expected_cb_sales,
        "fresh_leads_next_7d": fresh_leads_next_7d,
        "expected_fresh_sales": expected_fresh_sales,
        "expected_total_sales": expected_total,
        "last_week_sales": last_week_sales,
        "delta_vs_last_week_pct": delta_pct,
        "funnel": {
            "new":        rng.randint(800, 1200),
            "contacted":  rng.randint(500, 800),
            "engaged":    rng.randint(150, 300),
            "callback":   callbacks_next_7d,
            "sold_7d":    last_week_sales,
        },
    }


def _mock_contact_velocity(days_back: int) -> dict[str, Any]:
    """
    Time-to-first-contact: hours from lead entry to first dial.
    Real backend: SELECT entry_date, MIN(call_date) FROM vicidial_list LEFT JOIN vicidial_log GROUP BY lead_id.
    """
    rng = random.Random(89)
    avg_hours = round(rng.uniform(3.5, 7.5), 1)
    median_hours = round(avg_hours * 0.7, 1)

    by_age = [
        {"age_bucket": "<24h",   "count": rng.randint(120, 200), "conversion_rate": round(rng.uniform(0.12, 0.18), 3)},
        {"age_bucket": "1-3d",   "count": rng.randint(150, 250), "conversion_rate": round(rng.uniform(0.07, 0.11), 3)},
        {"age_bucket": "3-7d",   "count": rng.randint(180, 300), "conversion_rate": round(rng.uniform(0.04, 0.07), 3)},
        {"age_bucket": "7-30d",  "count": rng.randint(200, 400), "conversion_rate": round(rng.uniform(0.02, 0.05), 3)},
        {"age_bucket": ">30d",   "count": rng.randint(100, 250), "conversion_rate": round(rng.uniform(0.01, 0.03), 3)},
    ]
    leads_stuck = rng.randint(15, 35)  # >48h since entry, no contact yet

    return {
        "avg_hours_to_first_contact": avg_hours,
        "median_hours_to_first_contact": median_hours,
        "leads_stuck_no_contact": leads_stuck,    # >48h since entry, no dial yet
        "stuck_threshold_hours": 48,
        "conversion_by_age": by_age,
        "alert": leads_stuck > 20,
    }


def _mock_agent_campaign_matrix(days_back: int) -> list[dict[str, Any]]:
    """Per (agent, campaign) breakdown. Real backend: GROUP BY user, campaign_id."""
    rng = random.Random(103)
    out = []
    for user, full_name, skill in _MOCK_AGENTS:
        for cid, cname in _MOCK_CAMPAIGNS:
            # Each agent has affinity for some campaigns
            affinity = rng.uniform(0.6, 1.4)
            calls = rng.randint(20, 100)
            rate = max(0.01, min(0.20, skill * affinity + rng.uniform(-0.01, 0.01)))
            sales = max(0, int(calls * rate))
            out.append({
                "user": user,
                "full_name": full_name,
                "campaign_id": cid,
                "campaign_name": cname,
                "calls": calls,
                "sales": sales,
                "close_rate": round(sales / calls, 4) if calls else 0.0,
            })
    return out


def _mock_dispo_breakdown(days_back: int) -> list[dict[str, Any]]:
    rng = random.Random(11)
    base = {
        settings.dispo_sale: rng.randint(40, 90),
        settings.dispo_callback: rng.randint(80, 160),
        "NI": rng.randint(200, 400),
        "NA": rng.randint(400, 700),
        "DNC": rng.randint(20, 50),
        "B": rng.randint(60, 120),
    }
    return [{"dispo": k, "count": v} for k, v in base.items()]


# ---------- Real backend (PyMySQL) --------------------------------------------

def _connect():
    return pymysql.connect(
        host=settings.vicidial_host,
        port=settings.vicidial_port,
        user=settings.vicidial_user,
        password=settings.vicidial_password,
        database=settings.vicidial_db,
        cursorclass=DictCursor,
        connect_timeout=10,
        read_timeout=30,
    )


def _real_leads(days_back: int) -> list[dict[str, Any]]:
    """
    Pull active leads with their most-recent call attempt joined.

    NOTE: column names below match Vicidial's stock schema. If the client's
    admin has customized vicidial_list, adjust here — never in app/main.py.
    """
    sql = """
        SELECT
            l.lead_id,
            l.phone_number,
            l.state,
            l.postal_code,
            l.entry_date,
            l.status,
            l.called_count,
            l.last_local_call_time,
            COALESCE(g.length_in_sec, 0)   AS last_call_duration_sec,
            COALESCE(g.status, '')         AS last_call_dispo,
            COALESCE(t.total_seconds, 0)   AS total_call_seconds,
            l.list_id,
            li.campaign_id
        FROM vicidial_list l
        LEFT JOIN vicidial_lists  li ON li.list_id = l.list_id
        LEFT JOIN (
            SELECT lead_id, MAX(call_date) AS last_call_date
            FROM vicidial_log
            WHERE call_date >= NOW() - INTERVAL %s DAY
            GROUP BY lead_id
        ) lc ON lc.lead_id = l.lead_id
        LEFT JOIN vicidial_log g
            ON g.lead_id = lc.lead_id AND g.call_date = lc.last_call_date
        LEFT JOIN (
            SELECT lead_id, SUM(length_in_sec) AS total_seconds
            FROM vicidial_log
            WHERE call_date >= NOW() - INTERVAL %s DAY
            GROUP BY lead_id
        ) t ON t.lead_id = l.lead_id
        WHERE l.status NOT IN ('DNC')
          AND (l.last_local_call_time IS NULL OR l.last_local_call_time >= NOW() - INTERVAL %s DAY)
        LIMIT 5000
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (days_back, days_back, days_back * 3))
            return cur.fetchall()


def _real_agent_stats(days_back: int) -> list[dict[str, Any]]:
    sql = """
        SELECT
            a.user,
            COALESCE(u.full_name, a.user) AS full_name,
            COUNT(*)                       AS calls_handled,
            SUM(CASE WHEN a.status = %s THEN 1 ELSE 0 END) AS sales,
            SUM(a.talk_sec)                AS talk_seconds,
            ROUND(AVG(a.talk_sec), 1)      AS avg_talk_sec
        FROM vicidial_agent_log a
        LEFT JOIN vicidial_users u ON u.user = a.user
        WHERE a.event_time >= NOW() - INTERVAL %s DAY
        GROUP BY a.user, u.full_name
        ORDER BY sales DESC
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (settings.dispo_sale, days_back))
            rows = cur.fetchall()
            for r in rows:
                r["close_rate"] = round((r["sales"] or 0) / r["calls_handled"], 4) if r["calls_handled"] else 0.0
            return rows


def _real_campaigns() -> list[dict[str, Any]]:
    sql = "SELECT campaign_id, campaign_name, active FROM vicidial_campaigns"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def _real_call_times(days_back: int) -> list[dict[str, Any]]:
    sql = """
        SELECT
            HOUR(call_date) AS hour,
            COUNT(*) AS calls,
            SUM(CASE WHEN status = %s THEN 1 ELSE 0 END) AS sales
        FROM vicidial_log
        WHERE call_date >= NOW() - INTERVAL %s DAY
        GROUP BY HOUR(call_date)
        ORDER BY hour
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (settings.dispo_sale, days_back))
            return cur.fetchall()


def _real_sales_trend(days_back: int) -> list[dict[str, Any]]:
    sql = """
        SELECT
            DATE(call_date) AS date,
            COUNT(*) AS sales
        FROM vicidial_log
        WHERE call_date >= NOW() - INTERVAL %s DAY
          AND status = %s
        GROUP BY DATE(call_date)
        ORDER BY date
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (days_back, settings.dispo_sale))
            rows = cur.fetchall()
            for r in rows:
                if hasattr(r["date"], "isoformat"):
                    r["date"] = r["date"].isoformat()
            return rows


def _real_campaign_performance(days_back: int) -> list[dict[str, Any]]:
    sql = """
        SELECT
            c.campaign_id,
            c.campaign_name,
            COUNT(DISTINCT l.lead_id)                             AS leads_total,
            COUNT(DISTINCT g.lead_id)                             AS leads_contacted,
            COUNT(g.uniqueid)                                     AS total_dials,
            SUM(CASE WHEN g.status = %s THEN 1 ELSE 0 END)       AS total_sales,
            ROUND(AVG(g.length_in_sec))                           AS avg_handle_time_sec,
            HOUR(MAX(CASE WHEN g.status = %s THEN g.call_date END)) AS best_hour
        FROM vicidial_campaigns c
        LEFT JOIN vicidial_lists li ON li.campaign_id = c.campaign_id
        LEFT JOIN vicidial_list  l  ON l.list_id = li.list_id
        LEFT JOIN vicidial_log   g  ON g.lead_id = l.lead_id
            AND g.call_date >= NOW() - INTERVAL %s DAY
        GROUP BY c.campaign_id, c.campaign_name
        ORDER BY total_sales DESC
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (settings.dispo_sale, settings.dispo_sale, days_back))
            rows = cur.fetchall()
            for r in rows:
                lt = r.get("leads_total") or 1
                td = r.get("total_dials") or 1
                ts = r.get("total_sales") or 0
                lc = r.get("leads_contacted") or 0
                r["contact_rate"] = round(lc / lt, 3)
                r["penetration_rate"] = r["contact_rate"]
                r["conversion_rate"] = round(ts / td, 3)
                r["dials_per_sale"] = round(td / max(ts, 1), 1)
            return rows


def _real_agent_momentum(days_back: int) -> list[dict[str, Any]]:
    """
    SELECT a.user, COALESCE(u.full_name, a.user) AS full_name,
           YEARWEEK(a.event_time, 3) AS iso_week,
           COUNT(*) AS calls,
           SUM(CASE WHEN a.status = %s THEN 1 ELSE 0 END) AS sales
    FROM vicidial_agent_log a LEFT JOIN vicidial_users u ON u.user = a.user
    WHERE a.event_time >= NOW() - INTERVAL %s DAY
    GROUP BY a.user, iso_week
    Then post-process in Python: compute daily/weekly close_rate series, classify status.
    """
    raise NotImplementedError("Real Vicidial momentum requires creds — currently mock-only.")


def _real_lead_sources(days_back: int) -> list[dict[str, Any]]:
    raise NotImplementedError("Needs vicidial_list.source_id + cost mapping table from client.")


def _real_pipeline_forecast() -> dict[str, Any]:
    """SELECT COUNT(*) FROM vicidial_callbacks WHERE callback_time BETWEEN NOW() AND NOW() + INTERVAL 7 DAY"""
    raise NotImplementedError("Needs vicidial_callbacks access.")


def _real_contact_velocity(days_back: int) -> dict[str, Any]:
    raise NotImplementedError("Needs vicidial_list + vicidial_log join with MIN(call_date).")


def _real_agent_campaign_matrix(days_back: int) -> list[dict[str, Any]]:
    raise NotImplementedError("Needs GROUP BY (user, campaign_id) on vicidial_log.")


def _real_dispo_breakdown(days_back: int) -> list[dict[str, Any]]:
    sql = """
        SELECT status AS dispo, COUNT(*) AS count
        FROM vicidial_log
        WHERE call_date >= NOW() - INTERVAL %s DAY
        GROUP BY status
        ORDER BY count DESC
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (days_back,))
            return cur.fetchall()
