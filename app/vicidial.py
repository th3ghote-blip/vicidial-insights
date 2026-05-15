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
_MOCK_STATES = ["FL", "TX", "CA", "NY", "GA", "AZ", "NV", "IL"]
_MOCK_DISPOS = ["SALE", "CALLBK", "NI", "NA", "DNC", "B"]  # SALE/CALLBK/NotInt/NoAnswer/DNC/Busy
_MOCK_AGENTS = [
    ("agent_maria", "María González"),
    ("agent_juan", "Juan Pérez"),
    ("agent_ana", "Ana Rodríguez"),
    ("agent_carlos", "Carlos Sánchez"),
    ("agent_lucia", "Lucía Fernández"),
]
_MOCK_CAMPAIGNS = [
    ("CC_FL", "Tarjetas de Crédito - Florida"),
    ("LOAN_TX", "Préstamos Personales - Texas"),
    ("REFI_CA", "Refinanciamiento - California"),
]


def _mock_leads(days_back: int) -> list[dict[str, Any]]:
    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    leads: list[dict[str, Any]] = []
    for i in range(120):
        called_count = rng.choices([0, 1, 2, 3, 4, 5, 6, 7, 8], weights=[10, 20, 25, 15, 10, 8, 5, 4, 3])[0]
        last_dispo = "" if called_count == 0 else rng.choices(_MOCK_DISPOS, weights=[3, 12, 25, 35, 5, 20])[0]
        # Convert mock dispo into the *configured* sale/callback codes so tests stay aligned with prod.
        if last_dispo == "SALE":
            last_dispo = settings.dispo_sale
        elif last_dispo == "CALLBK":
            last_dispo = settings.dispo_callback

        last_call_duration = 0 if called_count == 0 else rng.choices(
            [10, 30, 45, 75, 120, 180, 300],
            weights=[20, 25, 20, 15, 10, 7, 3],
        )[0]
        entry_age_days = rng.choices([0, 1, 3, 7, 14, 30, 60, 90], weights=[15, 15, 15, 15, 15, 10, 8, 7])[0]
        last_call_offset_hours = 0 if called_count == 0 else rng.randint(1, max(1, days_back) * 24)

        leads.append({
            "lead_id": 100000 + i,
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
        })
    return leads


def _mock_agent_stats(days_back: int) -> list[dict[str, Any]]:
    rng = random.Random(7)
    out: list[dict[str, Any]] = []
    for user, full_name in _MOCK_AGENTS:
        calls = rng.randint(80, 220) * max(1, days_back // 7)
        sales = max(1, int(calls * rng.uniform(0.02, 0.12)))
        talk_sec = calls * rng.randint(60, 180)
        out.append({
            "user": user,
            "full_name": full_name,
            "calls_handled": calls,
            "sales": sales,
            "close_rate": round(sales / calls, 4),
            "talk_seconds": talk_sec,
            "avg_talk_sec": round(talk_sec / calls, 1),
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
        # Weekday boost: M-F higher than S-S
        is_weekend = date.weekday() >= 5
        base = 6 if is_weekend else 12
        sales = base + rng.randint(-3, 5)
        out.append({"date": date.isoformat(), "sales": max(0, sales)})
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
