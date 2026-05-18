"""
Weekly natural-language summary via Claude Haiku.

Spanish-first per user requirement (FL financial products → Spanish-speaking
agent base). The frontend can request EN explicitly via `lang=en`.

Cost: ~2k input + ~500 output tokens per call ≈ $0.002 with Haiku.
Even running this hourly would be ~$1.50/mo. Default cadence is daily.
"""
from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic

from .config import settings


_HAIKU_MODEL = "claude-haiku-4-5-20251001"


_PROMPT_ES = """Eres un analista de un call center de productos financieros (tarjetas de crédito y préstamos).

Recibes datos agregados de la última semana del dialer Vicidial. Genera un resumen ejecutivo en español, de 4 a 6 frases, dirigido al supervisor del centro. Tono directo, sin halagos. Cita números concretos.

Estructura:
1. Frase de titular sobre el rendimiento general (mejor o peor que la semana anterior si hay comparación).
2. Identifica el agente con mejor tasa de cierre y la métrica concreta.
3. Identifica un patrón en horarios o estados con mayor conversión.
4. Señala una alerta o riesgo (leads quemados, agentes con caída, dispo sospechosa).
5. Una recomendación accionable para mañana.

Datos:
{data}
"""

_PROMPT_EN = """You are a call center analyst for financial products (credit cards and loans).

You receive aggregated data from the last week of the Vicidial dialer. Write an executive summary in English, 4 to 6 sentences, addressed to the floor supervisor. Direct tone, no flattery. Cite concrete numbers.

Structure:
1. Headline sentence on overall performance (better or worse than prior week if comparable).
2. Identify the agent with the highest close rate and the concrete metric.
3. Identify a pattern in time-of-day or state with higher conversion.
4. Flag a risk (burnt leads, agents trending down, suspicious dispo).
5. One actionable recommendation for tomorrow.

Data:
{data}
"""


def _format_data(agent_stats: list[dict], dispo_breakdown: list[dict], top_leads_count: int) -> str:
    lines = ["AGENT PERFORMANCE (last 7 days):"]
    for a in agent_stats[:8]:
        lines.append(
            f"- {a['full_name']}: {a['calls_handled']} calls, {a['sales']} sales, "
            f"{round(a['close_rate']*100, 1)}% close rate, avg {a['avg_talk_sec']}s talk"
        )
    lines.append("\nDISPOSITION BREAKDOWN (last 7 days):")
    for d in dispo_breakdown:
        lines.append(f"- {d['dispo']}: {d['count']}")
    lines.append(f"\nHIGH-PRIORITY LEADS QUEUED FOR TOMORROW: {top_leads_count}")
    return "\n".join(lines)


def generate_summary(
    agent_stats: list[dict[str, Any]],
    dispo_breakdown: list[dict[str, Any]],
    top_leads_count: int,
    lang: str = "es",
) -> str:
    if not settings.anthropic_api_key:
        return _fallback_summary(agent_stats, dispo_breakdown, top_leads_count, lang)

    data_str = _format_data(agent_stats, dispo_breakdown, top_leads_count)
    template = _PROMPT_EN if lang == "en" else _PROMPT_ES
    prompt = template.format(data=data_str)

    client = Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


_ALERT_PROMPT_ES = """Eres analista de un call center de productos financieros. Genera 5-8 alertas accionables basadas en estos datos.

Devuelve ÚNICAMENTE un array JSON, sin texto extra, con esta forma exacta:
[
  {{
    "severity": "high|medium|low|positive",
    "type": "agent_trend|lead_source|forecast|contact_velocity|campaign|dialer",
    "title": "título corto, máx 60 caracteres",
    "message": "descripción concreta con números, máx 140 caracteres",
    "action": "qué hacer (opcional, máx 80 caracteres)"
  }}
]

Criterios:
- "high" rojo: pérdida de dinero, agente cayendo fuerte, ROI negativo
- "medium" ámbar: oportunidad o problema notable
- "positive" verde: rising star, racha, fuente con buen ROI
- Cita números reales de los datos. No inventes.
- Prioriza acciones, no descripciones.

Datos:
{data}
"""

_ALERT_PROMPT_EN = """You are a call center analyst. Generate 5-8 actionable alerts from this data.

Return ONLY a JSON array, no extra text, with this exact shape:
[
  {{
    "severity": "high|medium|low|positive",
    "type": "agent_trend|lead_source|forecast|contact_velocity|campaign|dialer",
    "title": "short title, max 60 chars",
    "message": "concrete message with numbers, max 140 chars",
    "action": "what to do (optional, max 80 chars)"
  }}
]

Criteria:
- "high" red: money being lost, agent crashing, negative ROI
- "medium" amber: notable opportunity or problem
- "positive" green: rising star, hot streak, source with good ROI
- Cite real numbers from the data. Don't invent.
- Prioritize action, not description.

Data:
{data}
"""


def _format_alert_data(
    momentum: list[dict],
    sources: list[dict],
    forecast: dict,
    velocity: dict,
    campaigns: list[dict],
) -> str:
    lines = ["AGENT MOMENTUM (last 4 weeks):"]
    for a in momentum:
        lines.append(
            f"- {a['full_name']}: now {round(a['current_close_rate']*100,1)}%, "
            f"prior avg {round(a['prior_avg_close_rate']*100,1)}%, change {a['change_pct']:+.1f}%, status: {a['status']}"
        )
    lines.append("\nLEAD SOURCES (cost per sale, ascending = best):")
    for s in sources:
        lines.append(
            f"- {s['source']}: {s['leads_total']} leads, {s['sales']} sales, "
            f"conv {round(s['conversion_rate']*100,1)}%, cost/lead ${s['cost_per_lead_usd']}, cost/sale ${s['cost_per_sale_usd']}"
        )
    lines.append("\nFORECAST (next 7 days):")
    lines.append(
        f"- Expected sales: {forecast['expected_total_sales']} "
        f"(callbacks: {forecast['expected_callback_sales']}, fresh: {forecast['expected_fresh_sales']})"
    )
    lines.append(f"- Last week sales: {forecast['last_week_sales']}, delta: {forecast['delta_vs_last_week_pct']:+.1f}%")
    lines.append(f"\nCONTACT VELOCITY: avg {velocity['avg_hours_to_first_contact']}h to first contact, "
                 f"{velocity['leads_stuck_no_contact']} leads stuck >{velocity['stuck_threshold_hours']}h with no contact")
    lines.append("\nCAMPAIGN PERFORMANCE:")
    for c in campaigns:
        lines.append(
            f"- {c['campaign_name']}: penetration {round(c['penetration_rate']*100,1)}%, "
            f"conv {round(c['conversion_rate']*100,1)}%, dials/sale {c['dials_per_sale']}"
        )
    return "\n".join(lines)


def generate_alerts(
    momentum: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    forecast: dict[str, Any],
    velocity: dict[str, Any],
    campaigns: list[dict[str, Any]],
    lang: str = "es",
) -> list[dict[str, Any]]:
    """Generate actionable alerts via Haiku. Falls back to rule-based if no API key."""
    if not settings.anthropic_api_key:
        return _fallback_alerts(momentum, sources, forecast, velocity, lang)

    data_str = _format_alert_data(momentum, sources, forecast, velocity, campaigns)
    template = _ALERT_PROMPT_EN if lang == "en" else _ALERT_PROMPT_ES
    prompt = template.format(data=data_str)

    try:
        client = Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        alerts = json.loads(text)
        # Validate shape
        return [a for a in alerts if isinstance(a, dict) and "severity" in a and "title" in a]
    except Exception:
        return _fallback_alerts(momentum, sources, forecast, velocity, lang)


def _fallback_alerts(momentum, sources, forecast, velocity, lang) -> list[dict]:
    """Deterministic alerts when no LLM. Same shape as Haiku output."""
    alerts = []
    es = lang != "en"

    # Falling agents
    falling = [a for a in momentum if a["status"] == "needs_attention"]
    for a in falling[:2]:
        alerts.append({
            "severity": "high", "type": "agent_trend",
            "title": (f"{a['full_name']} cayendo" if es else f"{a['full_name']} falling"),
            "message": (f"Cierre bajó {abs(a['change_pct']):.1f}% (de {a['prior_avg_close_rate']*100:.1f}% a {a['current_close_rate']*100:.1f}%)"
                        if es else
                        f"Close rate dropped {abs(a['change_pct']):.1f}% (from {a['prior_avg_close_rate']*100:.1f}% to {a['current_close_rate']*100:.1f}%)"),
            "action": ("Coaching y revisar grabaciones" if es else "Coaching session + review recordings"),
        })

    # Rising stars
    rising = [a for a in momentum if a["status"] in ("rising_star", "on_streak")]
    for a in rising[:2]:
        alerts.append({
            "severity": "positive", "type": "agent_trend",
            "title": (f"{a['full_name']} en alza" if es else f"{a['full_name']} on the rise"),
            "message": (f"+{a['change_pct']:.1f}% cierre, ahora en {a['current_close_rate']*100:.1f}%"
                        if es else
                        f"+{a['change_pct']:.1f}% close rate, now at {a['current_close_rate']*100:.1f}%"),
            "action": ("Asignar leads premium" if es else "Route premium leads to them"),
        })

    # Lead source ROI
    if sources:
        worst = max(sources, key=lambda s: s["cost_per_sale_usd"])
        best = min(sources, key=lambda s: s["cost_per_sale_usd"])
        if worst["cost_per_sale_usd"] > best["cost_per_sale_usd"] * 3 and worst["cost_per_sale_usd"] > 0:
            alerts.append({
                "severity": "high", "type": "lead_source",
                "title": (f"Fuente {worst['source']} ineficiente" if es else f"Source {worst['source']} burning cash"),
                "message": (f"Costo/venta ${worst['cost_per_sale_usd']} vs ${best['cost_per_sale_usd']} en {best['source']}"
                            if es else
                            f"Cost/sale ${worst['cost_per_sale_usd']} vs ${best['cost_per_sale_usd']} on {best['source']}"),
                "action": (f"Reducir presupuesto, mover a {best['source']}" if es else f"Cut budget, shift to {best['source']}"),
            })

    # Contact velocity
    if velocity.get("alert"):
        alerts.append({
            "severity": "medium", "type": "contact_velocity",
            "title": (f"{velocity['leads_stuck_no_contact']} leads sin contactar" if es
                      else f"{velocity['leads_stuck_no_contact']} leads not yet contacted"),
            "message": (f"Más de {velocity['stuck_threshold_hours']}h sin primer intento. Conversión cae 60% después de 24h"
                        if es else
                        f">{velocity['stuck_threshold_hours']}h since entry. Conversion drops 60% after 24h"),
            "action": ("Reasignar a agentes ociosos" if es else "Reassign to idle agents"),
        })

    # Forecast
    if forecast["delta_vs_last_week_pct"] > 5:
        alerts.append({
            "severity": "positive", "type": "forecast",
            "title": (f"Pronóstico: +{forecast['delta_vs_last_week_pct']}% próxima semana" if es
                      else f"Forecast: +{forecast['delta_vs_last_week_pct']}% next week"),
            "message": (f"{forecast['expected_total_sales']} ventas esperadas vs {forecast['last_week_sales']} la semana pasada"
                        if es else
                        f"{forecast['expected_total_sales']} sales expected vs {forecast['last_week_sales']} last week"),
        })
    elif forecast["delta_vs_last_week_pct"] < -5:
        alerts.append({
            "severity": "high", "type": "forecast",
            "title": (f"Pronóstico: {forecast['delta_vs_last_week_pct']}% próxima semana" if es
                      else f"Forecast: {forecast['delta_vs_last_week_pct']}% next week"),
            "message": (f"Solo {forecast['expected_total_sales']} ventas vs {forecast['last_week_sales']} esperadas"
                        if es else
                        f"Only {forecast['expected_total_sales']} sales vs {forecast['last_week_sales']} expected"),
            "action": ("Aumentar dialer o agendar más callbacks" if es else "Increase dial rate or schedule more callbacks"),
        })

    return alerts


_CHAT_SYSTEM_ES = """Eres un asistente analítico de call center con acceso en tiempo real a los datos de rendimiento del equipo.

Responde preguntas sobre agentes, campañas, leads, tendencias y métricas. Sé directo y cita números exactos de los datos. Máximo 3-4 frases por respuesta salvo que se pida más detalle. Nunca inventes datos que no estén en el contexto.

Datos actuales:
{data}
"""

_CHAT_SYSTEM_EN = """You are a call centre analytics assistant with real-time access to this Vicidial operation's performance data.

Answer questions about agents, campaigns, leads, trends and metrics. Be direct, cite exact numbers from the data. Max 3-4 sentences per answer unless more detail is requested. Never invent data not present in the context.

Current data:
{data}
"""


def _format_chat_context(agents: list[dict], campaigns: list[dict], momentum: list[dict]) -> str:
    lines = ["AGENTS (last 7 days):"]
    for a in agents[:12]:
        lines.append(
            f"- {a['full_name']}: {a['sales']} sales, "
            f"{round(a['close_rate']*100, 1)}% close rate, "
            f"{a['calls_handled']} calls, {a['avg_talk_sec']}s avg talk, "
            f"{a['dials_per_hour']:.1f} dials/hr"
        )
    lines.append("\nCAMPAIGNS (last 30 days):")
    for c in campaigns[:8]:
        lines.append(
            f"- {c['campaign_name']}: {c['total_sales']} sales, "
            f"{round(c['conversion_rate']*100, 1)}% conv, "
            f"{c['active_agents']} agents, {c['dials_per_sale']:.1f} dials/sale"
        )
    lines.append("\nAGENT MOMENTUM TREND:")
    for m in momentum[:10]:
        lines.append(
            f"- {m['full_name']}: {m['status']}, "
            f"change {m['change_pct']:+.1f}%, "
            f"now {round(m['current_close_rate']*100, 1)}% (was {round(m['prior_avg_close_rate']*100, 1)}%)"
        )
    return "\n".join(lines)


def chat_with_data(
    question: str,
    history: list[dict[str, str]],
    agents: list[dict],
    campaigns: list[dict],
    momentum: list[dict],
    lang: str = "es",
) -> str:
    """Interactive Q&A against live data via Haiku. ~$0.001/call."""
    if not settings.anthropic_api_key:
        return (
            "IA no configurada. Configure ANTHROPIC_API_KEY en Railway."
            if lang == "es"
            else "AI not configured. Set ANTHROPIC_API_KEY in Railway."
        )

    data_str = _format_chat_context(agents, campaigns, momentum)
    system = (_CHAT_SYSTEM_EN if lang == "en" else _CHAT_SYSTEM_ES).format(data=data_str)

    # Keep last 10 turns to stay within context budget
    messages: list[dict] = [*history[-10:], {"role": "user", "content": question}]

    client = Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=400,
        system=system,
        messages=messages,
    )
    return msg.content[0].text.strip()


def _fallback_summary(
    agent_stats: list[dict],
    dispo_breakdown: list[dict],
    top_leads_count: int,
    lang: str,
) -> str:
    """Used when no API key set (local dev)."""
    top_agent = agent_stats[0] if agent_stats else None
    sales = sum(d["count"] for d in dispo_breakdown if d["dispo"] == settings.dispo_sale)
    total = sum(d["count"] for d in dispo_breakdown)
    rate = round(sales / total * 100, 1) if total else 0.0

    if lang == "en":
        return (
            f"Last 7 days: {sales} sales out of {total} contacts ({rate}% conversion). "
            f"Top closer: {top_agent['full_name']} at {round(top_agent['close_rate']*100, 1)}% close rate. "
            f"{top_leads_count} high-priority leads queued for tomorrow. "
            "(LLM summary disabled — set ANTHROPIC_API_KEY to enable.)"
        )
    return (
        f"Últimos 7 días: {sales} ventas de {total} contactos ({rate}% conversión). "
        f"Mejor cerrador: {top_agent['full_name']} con {round(top_agent['close_rate']*100, 1)}% de cierre. "
        f"{top_leads_count} leads de alta prioridad en cola para mañana. "
        "(Resumen IA desactivado — configure ANTHROPIC_API_KEY para activarlo.)"
    )
