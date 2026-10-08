![](https://raw.githubusercontent.com/sancovp/carton-mcp/refs/heads/main/carton_small.png)
[![Part of STARSYSTEM](https://img.shields.io/badge/Part%20of-STARSYSTEM-blue)](https://github.com/sancovp/starsystem-metarepo)

# Carton MCP

<!-- SCALABLE-PUBLISHING:AUTOGEN START (managed block — do not edit between these markers) -->

![License](https://img.shields.io/badge/license-Other-blue.svg) ![Stars](https://img.shields.io/github/stars/sancovp/carton-mcp.svg?style=social) ![Updated](https://img.shields.io/badge/updated-2026_10_08-lightgrey.svg)

⭐ 1 stars • 🕑 Updated 2026-10-08

[Marketplace](https://github.com/sancovp/sancrev-marketplace) • [Docs](https://sancovp.github.io/aisaac/)

📦 Auto-published from the monorepo • [CHANGELOG](./CHANGELOG.md) • [sancovp/carton-mcp](https://github.com/sancovp/carton-mcp)

<!-- SCALABLE-PUBLISHING:AUTOGEN END -->

**A knowledge-graph platform for agent cognition — exposed to any LLM agent over MCP.**

Carton gives an agent a persistent, queryable mind: concepts stored as a Neo4j graph with Chroma
vector search, **38 MCP tools** over it, and four layers most "agent memory" projects don't have —
**retrieval state machines** (themselves stored as graph data, gating every retrieval call), a
**formal inference layer** that computes automorphism groups over the ontology, **collections and
identity frames** that let one graph be read from many points of view, and a **tree-shell
projection** that turns regions of the graph into navigable, executable interfaces.

It runs locally over stdio, or as an **authenticated network service** (bearer-gated streamable HTTP)
with **per-tenant quota metering** — so the same graph works as a personal second brain or as a
hosted multi-tenant backend.

---

## What it actually does

**Concept storage with automatic structure.** Write a concept in plain language; Carton discovers
mentions of other concepts in the text, creates bidirectional relationships and their inverses,
tracks concepts referenced-but-not-yet-written, and can bulk-create them. Every concept lives as
both a Neo4j node and a markdown file — the graph is queryable, the files are readable and
version-controllable.

**Retrieval state machines — and they are graph data** (`sm_gate.py`). A state machine in Carton is
authored *through Carton's own tools* (`add_concept` + `set_properties`): states are concepts,
transitions are weighted edges, each step carries a required pattern and an instruction. Once an
actor is locked at a step, **every retrieval call is gated** against that step — a matching call
passes and advances the cursor, a non-matching one is refused. Retrieval becomes a controllable
process with a per-actor cursor, not flat lookup, and the machine that controls it is stored in the
same graph as everything else.

**A formal inference layer** (`aut_deducer.py`). Computes `Aut_formal(C)` — the automorphism group
of an ontology class's definition — reading slot structure from both the Neo4j graph and the OWL
world, and cross-checking group order by explicit permutation enumeration. It carries its own
soundness restriction on every output (`Aut_true ⊆ Aut_formal` — the ontology cannot distinguish
what it cannot express) and is strictly read-only.

**Points of view** (`observe_from_identity_pov`, `equip_frame`, collections). The same graph is
readable from different identities and frames, so one substrate serves many agents and many
contexts without forking the data.

**Executable projection** (the treeshell integration). Regions of the graph project into navigable
tree interfaces — the graph stops being a passive store and becomes something an agent *operates*.
See the `skill-carton-treeshell-bijection-syntax` and `skill-treeshell-carton-integration-architecture`
skills in `.claude/skills/`.

**Vector + graph together.** Chroma (`chroma_client.py`, `chroma_daemon.py`) handles semantic
retrieval; Neo4j handles structure. `query_graph_from_rag_result` bridges them — semantic search
lands you in the graph, then you traverse.

**Visualization** (`carton_viz/`) — a server for seeing the graph you've built.

## The MCP surface (38 tools · 13 prompts)

| group | tools |
|---|---|
| **Concepts** | `add_concept` · `get_concept` · `edit_carton_obj` · `rename_concept` · `split_content_concept` · `set_properties` · `validate_carton_obj` |
| **Graph query** | `query_wiki_graph` (read-only Cypher) · `get_concept_network` (1–3 hop) · `query_by_properties` · `remove_relationship` · `get_recent_concepts` |
| **Semantic** | `chroma_query` · `query_graph_from_rag_result` |
| **State machines** | `create_branching_sm` · `substrate_projector` |
| **Collections & POV** | `create_collection` · `list_collections` · `activate_collection` · `add_to_collection` · `equip_frame` · `observe_from_identity_pov` |
| **Missing-concept management** | `calculate_missing_concepts` · `list_missing_concepts` · `create_missing_concepts` |
| **Observation & history** | `add_observation_batch` · `get_history_info` · `carton_management` |
| **Reasoning surfaces** | `query_cb_math` · `youknow_sparql` |

*(Selected — the full surface is 38 tools. Also `add_document_concept`, `run_experiment`,
`discover_patterns`, `scientific_method`, `deep_dive`, `krr_engineer_domain`, and more.)*

Plus **13 MCP prompts** — capturing verbatim user thoughts, updating concepts without destroying
their relationships, tracking how a thought evolved into an insight, and driving the observation
and research loops.

## Deployment

**Local (default):** stdio transport. Point your MCP client at the server; nothing else to run.

**Network:** set `CARTON_TRANSPORT` + `CARTON_API_KEY` and Carton serves streamable HTTP behind a
bearer gate (`network_gateway.py`). Three laws are enforced in code, not documentation:

- **Fail closed** — a network transport without an API key refuses to start. There is no
  unauthenticated network Carton.
- **SSE is refused** — long agent sessions produced broken pipes; the transport resolver rejects it
  outright rather than letting a caller opt into a known failure.
- **Binds localhost by default** — exposing it is an explicit act.

**Metering:** set `CARTON_MAX_NODES` and the quota gate (`carton_quota.py`) enforces at the write
chokepoint, before anything reaches the queue. It **refuses growth, not refinement** — at quota,
existing concepts still edit; only new nodes are rejected, with an actionable message. Unset, it is
a byte-identical no-op that runs zero queries.

## Architecture

```
Agent (any MCP client)
        │  stdio  ·  or bearer-gated streamable HTTP
        ▼
   Carton MCP  ──  quota gate  ──  state-machine gates  ──  inference layer
        │
        ├── Neo4j (:Wiki namespace)  — structure, relationships, traversal
        ├── Chroma                    — semantic retrieval
        └── markdown files            — human-readable, version-controllable
```

**Dual storage** means the graph is never a black box: every concept is simultaneously a queryable
node and a file you can read in a text editor or diff in git.

## Installation

```bash
pip install carton-mcp
```

Configure Neo4j (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) and `HEAVEN_DATA_DIR`. A Claude Desktop
config template ships as `claude_desktop_config_template.json`.

## Repository notes

- `.claude/skills/` — 20+ skills documenting the real dev-flows (schema, daemon operation, treeshell
  integration, memory-ontology design, queue formats). These are the operating manual.
- `.claude/rules/` — the enforced laws (transport, quota, gateway, dev-flows).
- `docs/vision/` — the design corpus this was built from.

## License

MIT — see LICENSE.
