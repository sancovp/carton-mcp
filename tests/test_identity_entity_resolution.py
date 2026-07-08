#!/usr/bin/env python3
"""
E2E for the ACTUAL-IDENTITY model (Isaac 2026-06-23): an identity is an Agent_Identity ENTITY node
(named '<TitleCase(handle)>_Identity') that HAS_COLLECTION its retrieval-map collection, and the SM gate
resolves the raw carton_identity handle to that entity so a lock attaches to a REAL node (the prior bug
was the gate locking a bare lowercase handle that matched nothing → _lock_into_sm_chain no-op'd).

Cases:
  (1) _identity_node_name: the pure handle→entity-name mapping ('gnosys' → 'Gnosys_Identity', etc.).
  (2) resolve_identity_entity (synthetic handle): MERGEs the entity is_a Agent_Identity + links
      HAS_COLLECTION to its collection (when it exists) + is idempotent.
  (3) the resolved entity is a USABLE gate actor: seed a 2-SM gating Core on a test subject →
      sm_chain_visit(entity, subject) ARMS → get_active_step(entity) returns the gating step.
  (4) read-only real-world sanity: 'gnosys' → 'Gnosys_Identity' AND the real Gnosys_Collection exists
      (so the live identity will resolve + link correctly), WITHOUT mutating the real identity.

Seeds via direct Cypher = ZERO SOMA :8091 contact. Self-cleaning ('Zztest_Ident_' prefix).
Run:
  NEO4J_URI=bolt://host.docker.internal:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=password \
    python3 tests/test_identity_entity_resolution.py
"""
import os
import sys
import traceback

os.environ.setdefault("NEO4J_URI", "bolt://host.docker.internal:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")
os.environ.setdefault("HEAVEN_DATA_DIR", "/tmp/heaven_data")

from carton_mcp import sm_gate
from carton_mcp.add_concept_tool import _get_module_connection

PFX = "Zztest_Ident_"
HANDLE = "zztest_ident_probe"                 # raw lowercase handle
ENTITY = "Zztest_Ident_Probe_Identity"        # expected canonical entity node
COLL = "Zztest_Ident_Probe_Collection"        # its retrieval-map collection
SUBJECT = f"{PFX}Subject"
SHOW_SM, GATE_SM = f"{PFX}Show_Sm", f"{PFX}Gate_Sm"
SHOW_STEP, GATE_STEP = f"{PFX}Show_Step", f"{PFX}Gate_Step"
# S2 two-layer parts (Isaac 2026-06-23): the entity carries its persona-config + access as graph parts.
BASE = ENTITY[: -len("_Identity")]            # 'Zztest_Ident_Probe'
FRAME_NODE = f"{BASE}_Frame"
RULES_NODE = f"{BASE}_Rules"
SKILLSET_HANDLE = "zztest_ident_skillset"     # raw skillset handle the caller passes
SKILLSET_NODE = "Zztest_Ident_Skillset"       # its Title_Cased node

NODES = [ENTITY, COLL, SUBJECT, SHOW_SM, GATE_SM, SHOW_STEP, GATE_STEP,
         f"{PFX}Core", f"{ENTITY}_Execution_State", FRAME_NODE, RULES_NODE, SKILLSET_NODE]


def _mk_run(conn):
    def run(query, params=None):
        rows = conn.execute_query(query, params or {})
        return [dict(r) if not isinstance(r, dict) else r for r in (rows or [])]
    return run


def _cleanup(run):
    for n in NODES:
        run("MATCH (n:Wiki {n:$n}) DETACH DELETE n", {"n": n})
    run("MATCH (n:Wiki) WHERE n.n STARTS WITH $p DETACH DELETE n", {"p": PFX})


def main():
    conn = _get_module_connection()
    if conn is None:
        print("FATAL: no neo4j", file=sys.stderr)
        sys.exit(1)
    run = _mk_run(conn)
    _cleanup(run)
    results = {}
    try:
        # (1) PURE NAME MAPPING
        results["1_name_mapping"] = (
            sm_gate._identity_node_name("gnosys") == "Gnosys_Identity"
            and sm_gate._identity_node_name("starship_pilot") == "Starship_Pilot_Identity"
            and sm_gate._identity_node_name("Gnosys_Identity") == "Gnosys_Identity"
            and sm_gate._identity_node_name("  GNO_sys  ") == "Gno_Sys_Identity"
            and sm_gate._identity_node_name("") == ""
            and sm_gate._identity_node_name(None) == "")

        # (2) RESOLVE (synthetic): entity MERGE'd is_a Agent_Identity + HAS_COLLECTION when coll exists + idempotent.
        run("MERGE (c:Wiki {n:$c}) SET c.d=$d", {"c": COLL, "d": "the probe identity collection"})
        run("MERGE (t:Wiki {n:'Agent_Identity'})", {})
        ent1 = sm_gate.resolve_identity_entity(HANDLE, run)
        ent2 = sm_gate.resolve_identity_entity(HANDLE, run)   # idempotent re-run
        isa = run("MATCH (e:Wiki {n:$e})-[:IS_A]->(t:Wiki {n:'Agent_Identity'}) RETURN count(*) AS c", {"e": ENTITY})
        hasc = run("MATCH (e:Wiki {n:$e})-[:HAS_COLLECTION]->(c:Wiki {n:$c}) RETURN count(*) AS c", {"e": ENTITY, "c": COLL})
        results["2_resolve_entity"] = (
            ent1 == ENTITY and ent2 == ENTITY
            and bool(isa) and isa[0]["c"] == 1          # exactly one IS_A (idempotent, no dup)
            and bool(hasc) and hasc[0]["c"] == 1)       # exactly one HAS_COLLECTION

        # (3) the resolved entity is a USABLE gate actor: seed a 2-SM gating Core → arm → active step.
        sm_gate.create_sm_chain(SUBJECT, [
            {"name": SHOW_SM, "steps": [{"id": SHOW_STEP, "required_pattern": None, "text": "show", "next": None}]},
            {"name": GATE_SM, "steps": [{"id": GATE_STEP, "required_pattern": "query_wiki_graph",
                                         "text": "run query next", "next": None}]},
        ], run, sm_chain_name=f"{PFX}Core",
           domain="System", subdomain="Identity_Entity_Resolution", personal_domain="cave")
        visit = sm_gate.sm_chain_visit(ENTITY, SUBJECT, run)
        active = sm_gate.get_active_step(ENTITY, run)
        results["3_entity_is_gate_actor"] = (
            bool(visit.get("require_next"))
            and active is not None and active.get("id") == GATE_STEP
            and active.get("required_pattern") == "query_wiki_graph")
        # release the lock so it doesn't leak
        sm_gate.gate_call(ENTITY, "query_wiki_graph(MATCH (n) RETURN n)", run)

        # (4) READ-ONLY real-world sanity (no mutation of the real identity).
        real_coll = run("MATCH (c:Wiki {n:'Gnosys_Collection'}) RETURN count(c) AS c", {})
        results["4_real_world_sanity"] = (
            sm_gate._identity_node_name("gnosys") == "Gnosys_Identity"
            and bool(real_coll) and real_coll[0]["c"] >= 1)

        # (5) S2 TWO-LAYER PARTS: passing frame/rules/skillset records them as graph parts on the entity,
        #     idempotently. The frame/rules text lands on the '<Base>_Frame'/'<Base>_Rules' node .d;
        #     skillset links the Title_Cased skillset node. (synthetic entity, self-cleaning.)
        sm_gate.resolve_identity_entity(HANDLE, run, frame="SYSTEM PROMPT TEXT",
                                        rules="rule one; rule two", skillset=SKILLSET_HANDLE)
        sm_gate.resolve_identity_entity(HANDLE, run, frame="SYSTEM PROMPT TEXT",
                                        rules="rule one; rule two", skillset=SKILLSET_HANDLE)  # idempotent
        hf = run("MATCH (e:Wiki {n:$e})-[:HAS_FRAME]->(f:Wiki {n:$fn}) RETURN count(*) AS c, f.d AS d",
                 {"e": ENTITY, "fn": FRAME_NODE})
        hr = run("MATCH (e:Wiki {n:$e})-[:HAS_RULES]->(r:Wiki {n:$rn}) RETURN count(*) AS c, r.d AS d",
                 {"e": ENTITY, "rn": RULES_NODE})
        hs = run("MATCH (e:Wiki {n:$e})-[:HAS_SKILLSET]->(s:Wiki {n:$sn}) RETURN count(*) AS c",
                 {"e": ENTITY, "sn": SKILLSET_NODE})
        results["5_two_layer_parts"] = (
            bool(hf) and hf[0]["c"] == 1 and hf[0]["d"] == "SYSTEM PROMPT TEXT"   # one HAS_FRAME, text stored
            and bool(hr) and hr[0]["c"] == 1 and hr[0]["d"] == "rule one; rule two"  # one HAS_RULES, text
            and bool(hs) and hs[0]["c"] == 1)                                     # one HAS_SKILLSET -> Title node

        # (6) resolve_identity_entity_live: the SELF-CONTAINED entry equip_persona (S3) calls — it opens
        #     its OWN neo4j connection from env (no injected run). Proves the live path writes the parts.
        live_ent = sm_gate.resolve_identity_entity_live(HANDLE, frame="LIVE FRAME", skillset=SKILLSET_HANDLE)
        hf2 = run("MATCH (e:Wiki {n:$e})-[:HAS_FRAME]->(f:Wiki {n:$fn}) RETURN f.d AS d",
                  {"e": ENTITY, "fn": FRAME_NODE})
        results["6_resolve_live"] = (
            live_ent == ENTITY and bool(hf2) and hf2[0]["d"] == "LIVE FRAME")   # _live's own conn wrote it
    except Exception:
        print("EXCEPTION during test:\n" + traceback.format_exc(), file=sys.stderr)
    finally:
        _cleanup(run)

    print("\n=== ACTUAL-IDENTITY model E2E (handle → Agent_Identity entity; entity = gate actor) ===")
    ok = True
    for k in ["1_name_mapping", "2_resolve_entity", "3_entity_is_gate_actor", "4_real_world_sanity",
              "5_two_layer_parts", "6_resolve_live"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<24} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E IDENTITY-RESOLUTION: {'PASS' if ok else 'FAIL'}  (test nodes removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
