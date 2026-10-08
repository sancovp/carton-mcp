When you AUTHOR a CartON retrieval state-machine — a gated jump or SM gate over a concept's retrieval —
via a dragonbones `State_Machine` EntityChain or a nested `🐉🦴` annotation in treeshell, OR you edit the
SM capability — `knowledge/carton-mcp/sm_gate.py` (`create_sm_chain` / `create_sm_chain_live`, the shared
keystone factory), `automation/dragonbones/dragonbones/compiler.py` (the `is_a State_Machine` routing,
~line 443), `knowledge/carton-mcp/substrate_projector.py` (`project_state_machine`, the SOMA
effect-d-chain handler, ~line 1283), `base/soma-prolog/gnosys-vault/gnosys_vault/state_machine.py`
(`dchain_state_machine_compile`, the vaulted-type effect d-chain), or
`base/heaven-tree-repl/heaven_tree_repl/node_sync.py` (`_sm_graph_to_factory`, the treeshell inline path)
— FIRST use the `dragonbones-carton-retrieval-state-machines` skill and follow its full coherence set and
test path.

The shared keystone is `create_sm_chain_live` in `sm_gate.py`: it builds the 2-SM gating stack (auto
show-SM order-0 plus gating-SM order-1, wiring `NEXT_STEP` between consecutive steps).

THE TWO ENTRY SURFACES REACH IT DIFFERENTLY:
- The DRAGONBONES surface is add_concept → SOMA effect d-chain → factory-on-release. `compiler.py`
  add_concepts the `State_Machine` concept itself: the gate rides as the `sm_gates` 🏷 PROPERTY, and each
  gating step is its OWN `Traversal_Step` concept PART_OF the SM, carrying `required_pattern` / `text` /
  `next` as its own 🏷 properties. There is NO `<sm_spec>` JSON in `n.d`. On the carton save, SOMA's
  `dchain_state_machine_compile` fires and surfaces
  `release_effect('carton_mcp.substrate_projector:project_state_machine', C)`; the carton daemon
  dispatches `project_state_machine`, which reads `sm_gates`, walks the `Traversal_Step` graph from neo4j
  and calls `create_sm_chain_live` on release.
- The TREESHELL surface is a direct factory call. `node_sync._sm_graph_to_factory` — the inline `🐉🦴`
  annotation path, dispatched by `sync_db_graphs_to_carton` — calls `create_sm_chain_live` DIRECTLY. It is
  a treeshell node-sync path, not a dragonbones EntityChain, so it is not under the dragonbones
  add_concept-only rule.

Never edit one layer only. End every change with the unit, dragonbones and treeshell tests AND the live
MCP E2E: `pip install --no-deps`, `reconnect_mcp`, `restart-sse-treeshell`.

Whether a LIVE agent emits ECs end-to-end is DYNAMIC STATUS that lives in CARTON. Read
`Dragonbones_Ec_Emission_Phase` (`is_a Status_Phase_Table`) for the current phase; do NOT trust any
inline status here. CoR: *let me retrieve `get_concept('Dragonbones_Ec_Emission_Phase')` and read its live
`current_phase` / `output_style_ec_injection`, not propagate prose.*
