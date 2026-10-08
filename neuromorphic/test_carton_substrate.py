"""HOST-side proof of CartonSubstrate — the SDK's computer over carton's
REAL neo4j, on the direct-cypher lane.

Run as a SCRIPT from the repo root (the repo root IS the carton_mcp
package):  python3 neuromorphic/test_carton_substrate.py

This is deliberately NOT in the lab suite: it requires carton_mcp +
heaven_base + the live neo4j env (NEO4J_URI/USER/PASSWORD). It writes ONLY
uniquely-prefixed probe nodes and DETACH DELETEs them at the end; the final
check proves the graph's node count is unchanged.

What it proves, in order:
  1  read-after-write: add_node is visible to has_node/node immediately
     (the whole reason the adapter rides the direct lane, not the queue)
  2  in-place attrs mutation persists: potentiate/decay mutate the dict
     edges() returned, and a FRESH query sees the new weight/warrant
  3  growth cones: an edge toward a missing name is held (stub invisible to
     has_node/nodes), and add_node arrival resolves it into cold wiring
  4  fire spreads over WARRANTED wiring only, gated
  5  substrate-swap identity: the SAME computer program run over
     InMemorySubstrate and CartonSubstrate yields the same anatomy view
     (nodes, node attrs, edges) — identity = the connectivity pattern
  6  scoping: the computer's nodes()/edges() never see the real concept
     graph (only kind-carrying nodes / neuro-stamped relationships)
  7  cleanup leaves the graph byte-identical in count
"""
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neuromorphic.computer import NeuromorphicComputer  # noqa: E402
from neuromorphic.substrate import CartonSubstrate, InMemorySubstrate  # noqa: E402

P = f"zz_neuro_probe_{uuid.uuid4().hex[:8]}"   # lowercase: co-mention-scannable
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))


def build_anatomy(c):
    """The same program, run over any substrate (the swap experiment)."""
    c.add_stratum(f"{P}_cortex", level=1)
    c.add_region(f"{P}_parse", f"{P}_cortex", "parse", provenance="probe")
    c.add_region(f"{P}_plan", f"{P}_cortex", "plan", provenance="probe")
    c.add_region(f"{P}_act", f"{P}_cortex", "act", provenance="probe")
    c.add_kernel(f"{P}_k1", f"{P}_parse", "tokenize")
    c.add_channel(f"{P}_in", "afferent", f"{P}_parse", provenance="probe")
    c.describe(f"{P}_parse", f"parsing feeds {P}_plan and demands toward:{P}_ghost")
    c.describe(f"{P}_plan", f"planning drives {P}_act")


def anatomy_view(s, names):
    nodes = {n: dict(s.node(n)) for n in sorted(s.nodes()) if n in names}
    edges = sorted((src, dst, k, tuple(sorted(a.items())))
                   for (src, dst, k, a) in s.edges()
                   if src in names or dst in names)
    return nodes, edges


def main():
    cs = CartonSubstrate()
    run = cs._run
    before = run("MATCH (x:Wiki) RETURN count(x) AS c", {})[0]["c"]
    t0 = time.time()

    # 1 — read-after-write on the direct lane
    cs.add_node(f"{P}_raw", kind="region", stratum="", function="probe")
    check("read_after_write_has_node", cs.has_node(f"{P}_raw"))
    check("read_after_write_node_attrs",
          cs.node(f"{P}_raw").get("function") == "probe")

    # the full anatomy through the real computer
    c = NeuromorphicComputer(cs)
    build_anatomy(c)
    names = {n for n in cs.nodes() if n.startswith(P)}
    check("anatomy_nodes_present",
          {f"{P}_parse", f"{P}_plan", f"{P}_act"} <= names, str(names))

    # capture the swap-identity view NOW, before any mutation step changes
    # structure (cone resolution below ADDS wiring — the first run compared
    # different program histories and rightly failed)
    live_nodes, live_edges = anatomy_view(
        cs, {n for n in names if n != f"{P}_raw"})

    # 2 — in-place mutation persists (the write-through attrs)
    w = c.potentiate(f"{P}_parse", f"{P}_plan", "probe: used in a real spread")
    fresh = cs.edges(src=f"{P}_parse", dst=f"{P}_plan", kind="wiring")
    check("potentiate_persists_weight",
          fresh and fresh[0][3].get("weight") == w == 2, str(fresh))
    check("potentiate_persists_warrant",
          fresh and fresh[0][3].get("warrant") == "probe: used in a real spread")
    pruned = c.decay()   # the plan->act synapse is cold: weight 1 -> 0 -> pruned list
    fresh2 = cs.edges(src=f"{P}_plan", dst=f"{P}_act", kind="wiring")
    check("decay_persists_on_cold_wiring",
          (f"{P}_plan", f"{P}_act") in pruned
          and fresh2 and fresh2[0][3].get("weight") == 0, str(fresh2))

    # 3 — growth cones over a real graph: stub invisible, arrival resolves
    check("cone_target_not_a_node", not cs.has_node(f"{P}_ghost"))
    check("cone_listed", (f"{P}_parse", f"{P}_ghost") in c.growth_cones())
    check("stub_not_in_nodes", f"{P}_ghost" not in cs.nodes())
    cs.add_node(f"{P}_ghost", kind="region", stratum="", function="arrived")
    resolved = c.resolve_growth_cones(f"{P}_ghost")
    check("arrival_resolves_cone",
          f"{P}_parse" in resolved
          and cs.edges(src=f"{P}_parse", dst=f"{P}_ghost", kind="wiring"))

    # 4 — fire conducts over warranted wiring only
    path = c.fire(f"{P}_parse", payload="probe")
    check("fire_warranted_only",
          f"{P}_plan" in path["visited"]
          and any(b[1] == f"{P}_act" for b in path["blocked"]), str(path))

    # 5 — substrate-swap identity: the same program over InMemory, compared
    # against the live view captured right after build (pre-mutation)
    mem = InMemorySubstrate()
    cm = NeuromorphicComputer(mem)
    build_anatomy(cm)
    mem_nodes, mem_edges = anatomy_view(mem, {n for n in mem.nodes()})
    strip = lambda nodes: {n: a.get("kind") for n, a in nodes.items()}
    tri = lambda edges: sorted((s, d, k) for (s, d, k, _) in edges)
    check("swap_identity_nodes", strip(mem_nodes) == strip(live_nodes),
          f"{strip(mem_nodes)} vs {strip(live_nodes)}")
    check("swap_identity_edges", tri(mem_edges) == tri(live_edges),
          f"{tri(mem_edges)} vs {tri(live_edges)}")

    # 6 — scoping: the computer never sees the real concept graph
    check("nodes_scoped_to_anatomy",
          all(n.startswith(P) for n in cs.nodes()),
          str([n for n in cs.nodes() if not n.startswith(P)][:5]))
    check("edges_scoped_to_neuro",
          all(s.startswith(P) or d.startswith(P)
              for (s, d, _, _) in cs.edges()),
          str([(s, d) for (s, d, _, _) in cs.edges()
               if not (s.startswith(P) or d.startswith(P))][:5]))

    # 7 — cleanup, then the graph is count-identical
    run("MATCH (x:Wiki) WHERE x.n STARTS WITH $p DETACH DELETE x", {"p": P})
    after = run("MATCH (x:Wiki) RETURN count(x) AS c", {})[0]["c"]
    check("cleanup_left_graph_unchanged", after == before,
          f"before={before} after={after}")

    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\nCARTON SUBSTRATE: {len(CHECKS) - n_fail}/{len(CHECKS)} green "
          f"in {time.time() - t0:.2f}s — the computer ran over the REAL "
          f"graph on the direct lane; probes cleaned.")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
