"""Markers for LFPOOP join A's release-effect handlers (card 780 / issue 1127).

Run as a script from the repo root: python3 test_lfpoop_join_effects.py

Isaac 2026-10-01 23:47, verbatim: each d-chain conclusion surfaces a release_effect whose handler runs
the next hop ... and writes the next partial with add_concept. The crown: the three handlers, each fed
the node the one before it wrote, carry a module call graph to its derived AB3 states. The graph
connection, the carton writer and the sealed hops are the only things faked; the partial chain itself
is HALO's real seem_ab3 and lfpoop's real learn_rollup.
"""

import ast
import json
import sys
from pathlib import Path

import carton_mcp.lfpoop_join_effects as mod
from sanctuary_system import seem_ab3

FAILURES = []
HERE = Path(__file__).resolve().parent
VAULT_MODULE = HERE.parents[1] / "base/soma-prolog/gnosys-vault/gnosys_vault/lfpoop_join.py"

FUNCTIONS = [{"name": "load", "file": "pkg/io.py", "start": 10, "end": 20},
             {"name": "parse", "file": "pkg/io.py", "start": 22, "end": 40},
             {"name": "render", "file": "pkg/ui.py", "start": 5, "end": 15},
             {"name": "paint", "file": "pkg/ui.py", "start": 17, "end": 30}]
EDGES = [{"caller": "load", "callee": "parse", "weight": 3},
         {"caller": "parse", "callee": "load", "weight": 1},
         {"caller": "render", "callee": "paint", "weight": 3}]
HOPS = {"read_flow": [("pkg/io.py", 1, 25)], "draw_flow": [("pkg/ui.py", 1, 40)]}
CALL_GRAPH = "Lfpoop_Join_Module_Call_Graph_Pkg_Mod_Py"


def check(marker, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {marker}" + (f"  -- {detail}" if not condition and detail else ""))
    if not condition:
        FAILURES.append(marker)


class Store:
    """A graph connection over a dict of node name to properties, recording every query."""

    def __init__(self, nodes):
        self.nodes = nodes
        self.queries = []

    def execute_query(self, query, params=None):
        self.queries.append((query, params or {}))
        node = self.nodes.get((params or {}).get("n"))
        if "SET" in query:
            if node is not None:
                node.update({k: v for k, v in params.items() if k != "n"})
            return [{"n": params["n"]}] if node is not None else []
        return [{"p": dict(node)}] if node is not None else []


class Dead:
    def execute_query(self, query, params=None):
        raise RuntimeError("store is unreachable")


def run_chain():
    store = Store({})
    writes = []

    def fake_write(name, is_a, properties, part_of, shared_connection=None):
        writes.append({"name": name, "is_a": is_a, "properties": properties, "part_of": part_of})
        store.nodes[name] = dict(properties)
        return f"{name}: written"

    mod.write_concept, mod.sealed_hops = fake_write, (lambda: HOPS)
    graph = {"functions": [dict(f, file=f"/root/{f['file']}") for f in FUNCTIONS], "edges": EDGES}
    mod.os.environ["DOCMIRROR_MONOREPO"] = "/root"
    out0 = mod.write_call_graph("/root/pkg/mod.py", "pkg", graph, store)
    outs = [out0]
    for handler in (mod.write_rollup_wiring, mod.write_learned_ring_set, mod.write_ab3_states):
        outs.append(handler(writes[-1]["name"], store) if writes else "nothing written")
    return store, writes, outs


def t_the_handlers_carry_a_ca_call_graph_to_its_ab3_states():
    saved_root = mod.os.environ.get("DOCMIRROR_MONOREPO")
    try:
        store, writes, outs = run_chain()
    finally:
        if saved_root is None:
            mod.os.environ.pop("DOCMIRROR_MONOREPO", None)
        else:
            mod.os.environ["DOCMIRROR_MONOREPO"] = saved_root
    check("write_call_graph writes the Module_Call_Graph partial CA produced, typed as the vaulted atom",
          len(writes) >= 1 and writes[0]["is_a"] == "Lfpoop_Join_Module_Call_Graph"
          and writes[0]["name"] == CALL_GRAPH
          and writes[0]["properties"].get("has_module") == "pkg/mod.py", writes[:1])
    check("write_rollup_wiring writes the Rollup_Wiring partial, typed as the vaulted atom",
          len(writes) >= 2 and writes[1]["is_a"] == "Lfpoop_Join_Rollup_Wiring"
          and writes[1]["name"] == seem_ab3.partial_name("Rollup_Wiring", "pkg/mod.py"), writes[:2])
    check("its required fields ride as has_ string properties, which carton bridges to SOMA triples",
          len(writes) >= 2 and writes[1]["properties"].get("has_call_graph") == CALL_GRAPH
          and writes[1]["properties"].get("has_module") == "pkg/mod.py", writes[:2])
    check("write_learned_ring_set writes the Learned_Ring_Set partial of that wiring",
          len(writes) == 3 and writes[2]["is_a"] == "Lfpoop_Join_Learned_Ring_Set"
          and writes[2]["properties"].get("has_wiring") == writes[1]["name"], writes)
    r_name = writes[2]["name"] if len(writes) == 3 else None
    got = json.loads((store.nodes.get(r_name) or {}).get("ab3_states") or "null")
    cg = {"has_module": "pkg/mod.py", "functions": json.dumps(FUNCTIONS), "edges": json.dumps(EDGES)}
    _, rings = seem_ab3.ring_set_partial(*seem_ab3.wiring_partial(CALL_GRAPH, cg))
    want = seem_ab3.ab3_states(rings, HOPS)
    check("write_ab3_states records on the ring set exactly the states HALO derives", got == want,
          f"got {got} want {want}")
    check("write_ab3_states writes no further partial, so no d-chain fires again", len(writes) == 3, writes)
    check("every handler answers with a line for the dispatch log", all(isinstance(o, str) for o in outs), outs)


def t_a_dead_store_is_returned_never_raised():
    for fn in (mod.write_rollup_wiring, mod.write_learned_ring_set, mod.write_ab3_states):
        try:
            out = fn("Lfpoop_Join_X", Dead())
            check(f"{fn.__name__} returns a failure line on a dead store",
                  isinstance(out, str) and "failed" in out, out)
        except Exception as e:
            check(f"{fn.__name__} returns a failure line on a dead store", False, f"raised {e!r}")


def t_a_missing_node_is_reported():
    out = mod.write_rollup_wiring("Lfpoop_Join_Absent", Store({}))
    check("a handler fired on a node the store does not hold says so", "no node" in out, out)


def _dchain_handlers():
    tree = ast.parse(VAULT_MODULE.read_text())
    consts = {n.targets[0].id: n.value.value for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
              and isinstance(n.targets[0], ast.Name)}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_release"]
    return consts.get("_EFFECTS"), [c.args[0].value for c in calls]


def t_every_dchain_conclusion_names_a_handler_here():
    effects, names = _dchain_handlers()
    check("the vault module releases into this module", effects == "carton_mcp.lfpoop_join_effects", effects)
    check("the vault module names three handlers", len(names) == 3, names)
    for name in names:
        check(f"{name} is a callable handler here", callable(getattr(mod, name, None)))


def _grade_exempt_set():
    tree = ast.parse((HERE / "observation_worker_daemon.py").read_text())
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == "_GRADE_EXEMPT_EFFECTS" and isinstance(n.value, ast.Set)):
            return {e.value for e in n.value.elts if isinstance(e, ast.Constant)}
    return set()


def t_the_daemon_dispatches_each_handler_on_an_instance():
    exempt = _grade_exempt_set()
    _, names = _dchain_handlers()
    for name in names:
        check(f"{name} is grade-exempt, so the daemon dispatches it on a partial INSTANCE",
              f"carton_mcp.lfpoop_join_effects:{name}" in exempt)


def main():
    saved = (getattr(mod, "write_concept", None), getattr(mod, "sealed_hops", None))
    try:
        t_the_handlers_carry_a_ca_call_graph_to_its_ab3_states()
        t_a_dead_store_is_returned_never_raised()
        t_a_missing_node_is_reported()
    finally:
        mod.write_concept, mod.sealed_hops = saved
    t_every_dchain_conclusion_names_a_handler_here()
    t_the_daemon_dispatches_each_handler_on_an_instance()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        sys.exit(1)
    print("all markers passed")


if __name__ == "__main__":
    main()
