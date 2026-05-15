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
from datetime import datetime, timedelta, timezone
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


def _mock_sales_trend(days_back: int) -> list[dict[str, Any]]:
    rng = random.Random(17)
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for d in range(days_back - 1, -1, -1):
        date = (now - timedelta(days=d)).date()
        is_weekend = date.weekday() >= 5
        # Slight upward trend over time + weekend dip + noise
        trend_boost = int((days_back - d) / days_back * 8)
        base = 4 if is_weekend else 18
        sales = base + trend_boost + rng.randint(-4, 6)
        calls = sales * rng.randint(8, 14)  # ~8-14 calls per sale
        out.append({"date": date.isoformat(), "sales": max(0, sales), "calls": max(0, calls)})
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
