"""Unit test for _normalize_observation_domain_edges (issue #198 data half).

Script mode (python3 test_observation_domain_normalization.py), no network/graph —
the helper is a pure in-place dict transform in server_fastmcp.py.
"""
import os, sys
os.environ.setdefault("HEAVEN_DATA_DIR", "/tmp/test_obs_norm_heaven")


from carton_mcp.server_fastmcp import _normalize_observation_domain_edges as norm

results = []

def check(name, cond, detail=""):
    results.append(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))

# T1: actual-only concept gains a has_domain dict with the same targets, actual preserved
obs = {"daily_action": [{"name": "X", "relationships": [
    {"relationship": "is_a", "related": ["T"]},
    {"relationship": "has_actual_domain", "related": ["Infrastructure"]}]}], "confidence": 1}
norm(obs)
rels = obs["daily_action"][0]["relationships"]
hd = [r for r in rels if r["relationship"] == "has_domain"]
ha = [r for r in rels if r["relationship"] == "has_actual_domain"]
check("T1a has_domain added", len(hd) == 1 and hd[0]["related"] == ["Infrastructure"])
check("T1b has_actual_domain preserved", len(ha) == 1 and ha[0]["related"] == ["Infrastructure"])

# T2: existing has_domain dict is MERGED into, never duplicated (issue #204 collapse)
obs = {"insight_moment": [{"name": "Y", "relationships": [
    {"relationship": "has_domain", "related": ["Soma"]},
    {"relationship": "has_actual_domain", "related": ["Soma", "Carton_Schema"]}]}]}
norm(obs)
rels = obs["insight_moment"][0]["relationships"]
hd = [r for r in rels if r["relationship"] == "has_domain"]
check("T2a exactly ONE has_domain dict", len(hd) == 1, str(rels))
check("T2b merged w/o dupes", hd[0]["related"] == ["Soma", "Carton_Schema"], str(hd))

# T3: no has_actual_domain -> untouched
obs = {"implementation": [{"name": "Z", "relationships": [{"relationship": "is_a", "related": ["T"]}]}]}
before = [dict(r) for r in obs["implementation"][0]["relationships"]]
norm(obs)
check("T3 no-actual untouched", obs["implementation"][0]["relationships"] == before)

# T4: scalar/meta keys and malformed entries never explode
obs = {"confidence": 0.9, "hide_youknow": False, "struggle_point": [
    {"name": "W"},  # no relationships key
    "not-a-dict",
    {"name": "V", "relationships": [{"relationship": "has_actual_domain", "related": []}]}]}
norm(obs)
check("T4 robust to missing/malformed", True)

n = sum(results)
print(f"\n{n}/{len(results)} passed")
print("ALL_PASS" if n == len(results) else "FAILURES")
sys.exit(0 if n == len(results) else 1)
