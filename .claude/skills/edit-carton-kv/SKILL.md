---
name: edit-carton-kv
description: "WHAT: the development-flow for changing the CartON KV / CartonObj capability — the embedded-structured-KV-in-concept-descriptions feature (a <CartonObj name=..>{ JSON-with-bare-refs }</CartonObj> fence in n.d): the carton_kv parser/normalizer, edit_carton_obj (surgical single-leaf body edits + remove_fence), validate_carton_obj (schema + did-you-mean refs), the auto_link_description fence-opacity, fence-preservation (carry_forward_fences), ref-expansion, and the is_schema schema registry. It is the COMPLETE distributed edit-set (lib ↔ utils wrappers ↔ MCP tools ↔ the linker ↔ the daemon's live parse path ↔ the schema graph) + deploy + the only valid E2E test. WHEN: when editing carton_kv.py, the edit_carton_obj / validate_carton_obj / get_concept-expand MCP tools, the auto_link_description fence-opacity masking, the daemon fence/desc-mode parse path (parse_queue_file_to_concepts / batch_create_concepts_neo4j), or the is_schema schema-registry; or adding ANY new CartonObj capability (any of)."
---

# edit-carton-kv — dev-flow for the CartON KV (CartonObj) capability

> CartON KV = structured key/value objects embedded INSIDE a concept's description (`n.d`) as
> `<CartonObj name=X schema=Y>{ JSON-with-bare-refs }</CartonObj>` fences (a bare Title_Underscore
> token = a carton concept REF; a quoted string = literal data). The capability is DISTRIBUTED across
> a pure stdlib library, neo4j-bound wrappers, MCP tools, the auto-linker, the observation daemon's live
> parse path, and the schema graph — AND it runs as the INSTALLED package, not the source. Editing one
> place desyncs it (the canonical failure: the `remove_fence` fix landing in a path the daemon never
> calls, while the ACTIVE path still dropped it). This skill is the complete edit-set + the only valid
> test. Never edit one place only.
>
> Canonical source (monorepo ONLY — never `/home/GOD/carton_mcp`, never site-packages, never
> `/home/GOD/core`): `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/`. Read each file FULLY before
> editing (line refs below are grounded against the current code on read; re-verify them — code drifts).

## Part 1 — How you edit (the ONION: lib first, then wrapper, then MCP tool)

Every capability is a PURE `carton_kv.py` LIBRARY function FIRST (stdlib only, no neo4j / no MCP — so it
is unit-testable standalone), THEN a `carton_utils.py` graph-bound WRAPPER if it needs neo4j, THEN a thin
`server_fastmcp.py` MCP TOOL that interprets/formats. **Never add an MCP tool without the lib fn under it,
and never put graph logic in the lib.**

- **`carton_kv.py`** — the pure core. Fence find/parse/normalize: `find_carton_objs` / `get_carton_obj`
  (`carton_kv.py:208` / `:259`), the string-context-aware span scanner `scan_json_span` (`:83`), bare-ref
  ↔ strict-JSON converters `refs_to_strict_json` / `body_from_obj` / `parse_fence_body` (`:122` / `:166` /
  `:180`). The minimal-diff splice basis `replace_carton_obj_body` (`:292`) and the op-applier
  `apply_carton_obj_op` (`:451`, ops `get`/`set`/`append`/`remove` — `_VALID_OPS` at `:424`). Whole-fence
  delete `remove_carton_obj` (`:305`). Fence-preservation core `carry_forward_fences` (`:318`).
  Ref-expansion core `expand_refs_in_description` (`:398`). Schema/ref pure parts `extract_refs` /
  `deref_for_validation` / `validate_against_schema` (`:527` / `:547` / `:559`).
- **`carton_utils.py`** — the neo4j-bound wrappers: `edit_carton_obj` (`:48`), `check_kv_refs` (the fuzzy
  did-you-mean, `:154`), `register_kv_schemas` (`:180`), `validate_carton_obj` (`:223`), `expand_carton_refs`
  (`:262`). The canonical wiki-link strip primitives `strip_wiki_links` / `deep_strip_wiki_links` (`:14` /
  `:36`) and the shared read-strip site `_execute_neo4j_query` (`:1119`, strip at `:1134`).
- **`server_fastmcp.py`** — the MCP tools (thin): `edit_carton_obj` (`:403` — interprets the `value` STRING
  into a ref / JSON / literal at `:438-449`), `validate_carton_obj` (`:463`), `get_concept` (`:1265` — gained
  `expand_refs`/`depth`, applies expansion at `:1326-1329`), `get_concept_network` (`:1233`).
- **`add_concept_tool.py`** — `auto_link_description` (`:386`, the fence-opacity wrapper) over `_auto_link_core`
  (`:423`, the real linker).
- **`observation_worker_daemon.py`** — `batch_create_concepts_neo4j` (`:119`, the n.d write), the ONE live
  parse path `parse_queue_file_to_concepts` (below; `process_queue_file` is DEAD CODE), `linker_thread` (`:1155`).

## Part 2 — What you must ALSO edit (the coherence edit-set — ALL of it, every time)

1. **ONION DISCIPLINE.** A new capability lands lib (`carton_kv.py`) + a unit test FIRST; add a
   `carton_utils.py` wrapper only if it touches neo4j; expose a `server_fastmcp.py` MCP tool only as a thin
   interpret/format shim. Do not skip a layer; do not leak graph logic down into the pure lib.

2. **LINKER FENCE-OPACITY (one chokepoint covers all callers).** `auto_link_description`
   (`add_concept_tool.py:386`) MASKS each whole `<CartonObj>…</CartonObj>` span with a Private-Use sentinel
   char (`chr(0xE000+i)`, `:412`) BEFORE calling `_auto_link_core`, then restores each fence VERBATIM
   (`:418-419`). This single hook covers `linker_thread` (`observation_worker_daemon.py:1155`) and every other
   linker caller. Root cause it fixed: `_auto_link_core` has bracket-strip regexes (`add_concept_tool.py:466-467`,
   `re.sub(r"\[…\]", …)` / `re.sub(r"[\[\]]", "", …)`) that EAT JSON array brackets (`["clone","install"]`),
   plus it would linkify Title_Case words in the open tag. Any storage/linker change MUST preserve this masking
   — and the opacity test (`test_linker_fence_opacity.py`) must stay green.

3. **DAEMON WRITE PATH + THE ONE LIVE PARSE PATH (load-bearing).** `n.d` is written by
   `batch_create_concepts_neo4j` (`observation_worker_daemon.py:119`) — the `SET n.d = CASE … END` at
   `:254-281` implements `desc_update_mode` (append/prepend/replace/skip), and the fence-preservation guard
   runs there at `:229-247` (calls `carry_forward_fences` with `removed_fences`).
   There is exactly **ONE live parse path**: `parse_queue_file_to_concepts` (`:444`), called from the
   worker's main loop (the UNWIND batch at `:1383` calls it → `batch_create_concepts_neo4j` at `:1398`);
   it forwards `removed_fences` at **`:486`**, and `batch_create_concepts_neo4j` reads `removed_fences`
   into the concept row at **`:161`**. Every fence/desc-mode change lands HERE.
   `process_queue_file` (`:598`) is **DEAD CODE — it has ZERO callers** (verified 2026-06-10: only its def
   plus comments reference it). Do NOT maintain it "in lockstep"; do not route new behavior through it.
   The canonical bug this history guards: the `remove_fence` fix originally landed only in
   `process_queue_file` (which the daemon never calls), so the ACTIVE path still dropped `removed_fences`
   and the guard carried a removed fence back. The cure is to put fence/desc-mode handling in
   `parse_queue_file_to_concepts`, the path the daemon actually runs. (Regression guard:
   `test_parse_queue_file_forwards_removed_fences` in `test_carton_kv_schema.py` targets
   `parse_queue_file_to_concepts` specifically.)

4. **FENCE-INTEGRITY TRIO/QUARTET (keep coherent together).** Four guards make a fence un-corruptible; change
   one → re-check all four: (a) OPACITY — the linker can't corrupt a fence (item 2); (b) `edit_carton_obj`
   (`carton_utils.py:48`) — surgical single-leaf body edit, byte-identical prose+siblings via offset splice
   (`replace_carton_obj_body`), NEVER regenerate; (c) FENCE-PRESERVATION — an ordinary prose `replace` write
   carries any fence absent-by-name in the new desc FORWARD verbatim (`carry_forward_fences`, run in the daemon
   at `:229-247`); (d) whole-fence DELETION ONLY via the explicit `edit_carton_obj op=remove_fence` (handled in
   the wrapper at `carton_utils.py:95-104`, which queues `removed_fences=[name]` + `desc_update_mode='replace'`).

5. **SCHEMA GRAPH (SOUP, not SOMA).** An `is_schema=true` fence auto-types its concept `IS_A Carton_Kv_Schema`
   (+ optional `WHAT_FOR`/`HOW` edges) via `register_kv_schemas` (`carton_utils.py:180`), invoked from the
   daemon write path at `observation_worker_daemon.py:343-350` (gated on the cheap `'CartonObj' in desc`
   substring); a `schema=<Concept>` reference fence adds `USES_KV_SCHEMA`/`USED_BY_KV` edges (MATCH-both, so an
   undefined schema is NEVER stubbed). `validate_carton_obj` (`carton_utils.py:223`) resolves the `schema=Concept`
   attr → loads that concept's `is_schema` json-schema body → validates (reporting WHICH key failed via
   `validate_against_schema`); an unresolved bare ref returns FUZZY did-you-mean (`check_kv_refs`,
   `carton_utils.py:154`) and the write GUARD in `edit_carton_obj` (`:118-129`) REFUSES — it never MERGEs a stub
   (the cure for the auto-stub disease at the daemon's relationship-stub MERGE, `observation_worker_daemon.py:322-336`,
   the `ON CREATE SET target.d='AUTO CREATED: stub…'` at `:326-328`).

6. **REF-EXPANSION IS RENDER-ONLY.** `expand_refs_in_description` (`carton_kv.py:398`) / `expand_carton_refs`
   (`carton_utils.py:262`) replace bare refs in the RETURNED output only (recursive to `depth` N, cycle-guarded);
   the STORED `n.d` is NEVER mutated. `get_concept` (`server_fastmcp.py:1265`) calls it only when
   `expand_refs=True and depth>0` (`:1326-1329`); `depth=0` (default) returns raw tokens unchanged. If you add an
   expansion entry point, keep it render-only and never let it write back.

7. **DEPLOY (the running code is the INSTALLED package, NOT the source).** After editing the source:
   `pip install --no-deps /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp` (per `pip-install-our-packages-no-deps`;
   NEVER `--force-reinstall`). THEN:
   - If a DAEMON-path file changed (`observation_worker_daemon.py`, or `carton_kv.py`/`carton_utils.py` used by the
     daemon) → restart the SINGLE `observation_worker_daemon` WITH ENV (`NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`
     + `HEAVEN_DATA_DIR` + `GIINT_TREEKANBAN_BOARD`) — the daemon does NOT inherit env from Claude Code (see
     `daemon-needs-env-vars`). Find the PID with the bracket trick `pgrep -af 'observation_worker_[d]aemon'`
     (per `pkill-pgrep-bracket-trick-no-self-match`); kill by PID then relaunch. NEVER `pkill+launch` in one bash
     command (self-match → exit 144).
   - If ONLY `server_fastmcp.py` changed (MCP surface, no daemon path) → just `reconnect_mcp carton`. NEVER
     `pkill` an MCP — only `reconnect_mcp` (per `mcp-reconnect-is-user-only`).

8. **DAEMON HYGIENE.** Multiple `observation_worker_daemon`s auto-respawn (`ensure_worker_running`). Before
   gating ANY daemon-path change, ensure a SINGLE FRESH post-install daemon (`pgrep -af 'observation_worker_[d]aemon'`
   should show exactly one, started after your pip install).

## Part 3 — How you test it (the ONLY valid E2E gate — "lib tests passed" is NOT the gate)

**Lib gate (necessary, NOT sufficient):** run the 4 lib test files, all green —
`python3 test_carton_kv.py`, `python3 test_carton_kv_schema.py`, `python3 test_edit_carton_obj.py`,
`python3 test_linker_fence_opacity.py` (from the repo dir; the latter three import the INSTALLED package, so
pip-install FIRST).

**The REAL E2E gate — through the MCP surface (after pip-install + daemon-restart-if-needed + `reconnect_mcp carton`):**
1. `add_concept` a concept whose description carries a `<CartonObj>` fence with bare refs → read the RAW `n.d`
   from neo4j (`query_wiki_graph` `MATCH (c:Wiki {n:$n}) RETURN c.d`) and confirm the fence is BYTE-INTACT
   (opacity: open tag not linkified, JSON array brackets not eaten).
2. `edit_carton_obj` SET one leaf + REMOVE one leaf → confirm ONLY those changed; prose + sibling fences
   byte-identical (re-read raw `n.d`). Allow for the async daemon (the edit queues a replace; wait for the
   queue to drain).
3. `validate_carton_obj` against a GOOD and a BAD payload → good = VALID; bad-key = the exact key reported.
4. Edit/add a fence introducing an UNKNOWN bare ref → the write is REFUSED with did-you-mean, AND
   `query_wiki_graph` shows NO stub node was created for that name.
5. `get_concept` with `expand_refs=True` at `depth=0` (raw), `depth=1`, `depth=2`, and a deliberate cycle →
   expansion is render-only; re-read raw `n.d` and confirm the STORED description is UNCHANGED.

A `(success)` from a tool, "it imported", or "the lib tests passed" is NOT the gate. The raw `n.d` in neo4j +
the absence of a stub node + the unchanged-after-expansion `n.d` are the gate.

## The invariant

The CartON KV capability is distributed across `carton_kv` lib ↔ `carton_utils` wrappers ↔ `server_fastmcp`
MCP tools ↔ the `add_concept_tool` linker (fence-opacity) ↔ the `observation_worker_daemon`'s ONE live parse
path (`parse_queue_file_to_concepts` + `batch_create_concepts_neo4j`; `process_queue_file` is dead code with
zero callers) ↔ the SOUP schema graph — and it runs as the INSTALLED package, not the source. Edit one place
only and it desyncs (the canonical failure: the `remove_fence` fix landed in the dead path while the live one
dropped it). Do the whole Part-2 set + deploy (Part-2 #7) + the Part-3 E2E gate, every time.

(Knowledge/dev-flow skill — no subagent dispatch, so no RELIABILITY block.)
