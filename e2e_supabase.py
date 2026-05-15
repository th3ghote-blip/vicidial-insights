"""End-to-end: mock Vicidial → score → write to Supabase → read back."""
from app import vicidial, scoring, summary, cache

print("=== ping ===")
print(cache.ping())

print("\n=== pull from mock vicidial ===")
leads = vicidial.fetch_leads(30)
agents = vicidial.fetch_agent_stats(7)
dispos = vicidial.fetch_disposition_breakdown(7)
print(f"leads={len(leads)} agents={len(agents)} dispos={len(dispos)}")

print("\n=== score and rank ===")
scored = scoring.score_and_rank(leads)
top = [s for s in scored if s["score"] >= 60]
print(f"scored={len(scored)} high-priority(score>=60)={len(top)}")

print("\n=== write snapshots to supabase ===")
n_leads = cache.write_lead_snapshots(scored)
print(f"  wrote {n_leads} lead_score_snapshots")
n_agents = cache.write_agent_snapshots(agents, period_days=7)
print(f"  wrote {n_agents} agent_stats_snapshots")
n_dispos = cache.write_dispo_snapshots(dispos, period_days=7)
print(f"  wrote {n_dispos} disposition_snapshots")

print("\n=== generate + write weekly summary (es, fallback — no API key set) ===")
text = summary.generate_summary(agents, dispos, top_leads_count=len(top), lang="es")
cache.write_summary(text, lang="es", top_leads_count=len(top))
print(f"  wrote 1 weekly_summary")
print(f"  preview: {text[:140]}...")

print("\n=== read back ===")
recent_agents = cache.latest_agent_snapshots(limit=5)
print(f"  latest_agent_snapshots returned {len(recent_agents)} rows")
if recent_agents:
    a = recent_agents[0]
    print(f"  sample: {a['full_name']} sales={a['sales']} close_rate={a['close_rate']}")

recent_summaries = cache.latest_summaries(lang="es", limit=3)
print(f"  latest_summaries(es) returned {len(recent_summaries)} rows")

ping_after = cache.ping()
print(f"\n=== ping after writes ===\n{ping_after}")

print("\nALL OK")
