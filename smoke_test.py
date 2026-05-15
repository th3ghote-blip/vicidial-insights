"""One-shot smoke test against the mock backend. Not part of the deployed app."""
from app import vicidial, scoring, summary
from app.config import settings
from fastapi.testclient import TestClient
from app.main import app

print(f"mock_mode = {settings.mock_mode}")
print(f"dispo_sale = {settings.dispo_sale}, dispo_callback = {settings.dispo_callback}")
print(f"api_token configured = {bool(settings.api_token)}")

leads = vicidial.fetch_leads(30)
print(f"\n[mock] fetched {len(leads)} leads")

ranked = scoring.score_and_rank(leads, top_n=5)
print("\n[scoring] top 5:")
for l in ranked:
    print(
        f"  lead {l['lead_id']}: score={l['score']:>5} "
        f"rec={l['recommendation']:<14} "
        f"called={l['called_count']} dispo={l['last_call_dispo'] or '-':<6} "
        f"reasons={l['reasons']}"
    )

agents = vicidial.fetch_agent_stats(7)
print(f"\n[agents] {len(agents)} agents, leader: {agents[0]['full_name']} @ {agents[0]['close_rate']*100:.1f}%")

dispos = vicidial.fetch_disposition_breakdown(7)
print(f"\n[dispos] {dispos}")

s = summary.generate_summary(agents, dispos, top_leads_count=12, lang="es")
print(f"\n[summary ES]\n{s}")

print("\n--- HTTP endpoint smoke tests ---")
client = TestClient(app)

# /health stays open
r = client.get("/health")
print(f"  GET /health  no-auth        -> {r.status_code}  auth_configured={r.json().get('auth_configured')}")
assert r.status_code == 200

# protected endpoints reject without auth
protected = ["/leads/priority", "/agents/leaderboard", "/insights/dispositions", "/insights/weekly", "/campaigns"]
for path in protected:
    r = client.get(path)
    print(f"  GET {path:<32} no-auth     -> {r.status_code}  (expect 401)")
    assert r.status_code == 401, f"{path} should be 401 unauthed"

# wrong token rejected
r = client.get("/leads/priority", headers={"Authorization": "Bearer wrong"})
print(f"  GET /leads/priority           bad-token   -> {r.status_code}  (expect 401)")
assert r.status_code == 401

# correct token accepted
hdrs = {"Authorization": f"Bearer {settings.api_token}"}
for path in protected:
    r = client.get(path, headers=hdrs)
    body = r.json() if r.status_code == 200 else r.text
    keys = list(body.keys()) if isinstance(body, dict) else type(body).__name__
    print(f"  GET {path:<32} authed      -> {r.status_code}  keys={keys}")
    assert r.status_code == 200, f"{path} should be 200 authed: {body}"

# rate limiter — fire 32 calls, expect last 2 to 429
print("\n--- rate limit on /insights/weekly (cap = 30/hour) ---")
codes = []
for i in range(32):
    r = client.get("/insights/weekly", headers=hdrs)
    codes.append(r.status_code)
print(f"  first 5: {codes[:5]}  last 5: {codes[-5:]}  total OK={codes.count(200)}  total 429={codes.count(429)}")
# Cap is 30/hour; one slot was already used by the authed-loop call above.
assert codes.count(200) <= 30, f"limiter let through more than 30: {codes.count(200)}"
assert codes.count(429) >= 1, "rate limiter never triggered"

print("\nALL OK")
