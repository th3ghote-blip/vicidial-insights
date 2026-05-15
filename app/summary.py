"""
Weekly natural-language summary via Claude Haiku.

Spanish-first per user requirement (FL financial products → Spanish-speaking
agent base). The frontend can request EN explicitly via `lang=en`.

Cost: ~2k input + ~500 output tokens per call ≈ $0.002 with Haiku.
Even running this hourly would be ~$1.50/mo. Default cadence is daily.
"""
from __future__ import annotations

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
