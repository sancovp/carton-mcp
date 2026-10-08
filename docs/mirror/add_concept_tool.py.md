# doc(m): add_concept_tool.py

**Module:** `carton-mcp/add_concept_tool.py` • **Mirrors:** the module 1:1 (IMPL — what the code IS) • **Projected from the HALO SEEM store:** 4 sealed boundaries land here

## Features whose sealed boundary lands in this module

### Carton_Queue_Ingest — feature boundary (no Giint_Feature node declared)

- **user action:** a concept is written through the CartON front door, add_concept_tool_func, which POSTs it to SOMA and queues the graded node, and the observation worker must land that node in the graph and act on the verdict the payload carries
- **doc(v):** `knowledge/carton-mcp/docs/vision_extracted/add_concept.md`
- **outputs to:** `['dead_letter_lane_fires']`
- **sealed:** v4, key `d240df2fbf17db8b`, commit `b80684b69`, valid from 2026-10-01T07:39:36
- **ranges in this module** (layer order):
 - `L0 enqueue` · `add_concept_tool.py:3383-3456` — the queue payload built by the front door after the SOMA POST: raw_concept with is_soup, is_code, is_system_type, unmet_dchains, fired_chains, release_effects, fillable_requests, composed_triples, compose_suggestions and the merged properties, handed to submit_queue_entry
 - `L0 enqueue` · `add_concept_tool.py:838-864` — get_observation_queue_dir and submit_queue_entry: the ONE writer of the queue directory inside carton, local file when KUZU_QUERY_URL is empty, POST to the box enqueue route otherwise; Isaac 2026-09-26: the queue only exists inside carton and is never used by anything that is not carton or SOMA
- **also passes through:** `observation_worker_daemon.py`

### Carton_Soma_Verdict_Relay — feature boundary of `Carton_Soma_Verdict_Relay`

- **user action:** the agent calls the carton add_concept or get_concept MCP tool and must read, in the result it gets back, what SOMA graded and, last, the exact fill or drop SOMA asks of it, plus one line pointing at the soma-help skill and every CRITICAL line of the verdict
- **doc(v):** `knowledge/carton-mcp/docs/vision/add_concept_tool.py.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v15, key `60e8dc465f987672`, commit `b80684b69`, valid from 2026-10-01T07:39:39
- **ranges in this module** (layer order):
 - `L1 relay` · `add_concept_tool.py:2915-3068` — the SOMA call: marks SOMA consulted, posts the observation through soma_validate, splits the DEATH block off the verdict into _soma_death, reads the concept status= grade underscore-insensitively, and on an exception keeps the error text as _soma_error so the result says the write was not graded
 - `L1 relay` · `add_concept_tool.py:122-132` — soma_critical_lines: every verdict line starting CRITICAL, verbatim and in order, or empty
 - `L1 relay` · `add_concept_tool.py:3070-3100` — the contradiction rejection return: line 1 REJECTED, CartON did not store it, and the DO pointer; the DEATH block; CONTRADICTION with SOMA reason and that it would decohere the geometry even as soup; CRITICAL; the SOMA help line; DO CONTRADICTION last
 - `L1 relay` · `add_concept_tool.py:3502-3528` — the saved result return: line 1 the concept, CartON Files queued, Neo4j queued, and that the DO lines at the end are the instructions; the DEATH block; the SOMA line; MEREO, FILL and SOUP lines; D2 with every untraced name or the 100 percent case; CB region and coordinate; the PROMPTER block; CRITICAL; the SOMA help line; the DO lines last ⟵ RELEASE
 - `L1 relay` · `add_concept_tool.py:166-182` — split_soma_death_block lifts the DEATH block out of a verdict or a result with soma_prolog.soup_system_type_scream extract and without, returning the block and the rest; soma_prolog not importable logs a warning and lifts nothing
 - `L1 relay` · `add_concept_tool.py:135-163` — soma_isa_fill_lines: the lines of the system_type_isa_fills block of a SOMA verdict that name the written concept, matched without underscores or case, without their bullet, in verdict order
 - `L1 relay` · `add_concept_tool.py:3326-3341` — the grade: soma_grade_flags from the status= grade, the d-chain count, the soup gaps and the core requirements, then the SOMA line and soma_result_lines numbered lines and DO lines
 - `L1 relay` · `add_concept_tool.py:185-375` — SOMA_HELP_POINTER, SOMA_INSTRUCTIONS_POINTER and the result organizer: soma_concept_status reads the status= grade, soma_grade_flags and soma_grade_line give the SOMA line (MEREO and SOUP say the write is not validly the type it claims and its execution failed, MEREO adding that CartON keeps the write so it can be seen; SYSTEM_TYPE for SOMA status system_type, an instance with exactly the shape of its system type (card 726), and for code with no pending d-chain; CODE with the d-chain count; or the SOMA error), soma_result_lines turns the verdict into numbered MEREO[n], FILL[n] and SOUP[n] lines in SOMA own words, the requirement sentences one type states about one concept collapsed into one line keeping every param and its kind and ending that the subject is not validly the type, its execution failed; the two SOMA sentence regexes accept the clause SOMA appends after Provide it; one DO line per instruction naming its lines by token, each saying the part is important to fill next only if it is inside the meaning the writer meant, else drop the claim or leave it (Isaac 2026-09-29); identical instructions share one DO line
 - `L1 relay` · `add_concept_tool.py:3159-3160` — the D2 coverage: _compute_d2_coverage over the verbatim description gives the percent of declared relationships the description names and the names it does not; the result shows it as the D2 line
 - `L1 relay` · `add_concept_tool.py:3187-3194` — the pending d-chain count: the first unmet=N of the verdict, shown on the SOMA line
 - `L1 relay` · `add_concept_tool.py:3357-3378` — the SOMA region the concept is placed in (system_type, code, mereo_error, soup or unvalidated) and the Crystal Ball placement: cb_encoded is the coordinate and the PROMPTER block comes back when cb_guidance asks; the result shows CB region and coordinate
 - `L1 relay` · `add_concept_tool.py:3102-3122` — the mereo_error branch: on a status= grade of mereo_error it reads the mereo_errors line naming the concept, logs that the concept is not validly the type it claims and its execution failed, that CartON keeps the write so it can be seen, and that defining it is important to fill next only if it is inside the meaning the writer meant (Isaac 2026-09-29), records the verdict in the rejection ledger through record_soma_rejection, and falls through to the queue write
 - `L2 transport` · `add_concept_tool.py:95-119` — soma_validate: one POST to SOMA_URL /event; the result string is the whole verdict
 - `L2 transport` · `add_concept_tool.py:388-522` — the Crystal Ball fan-out the placement hop calls, card 767: _cb_place posts the said sentence to the CB store, or the flow verb when guidance is asked, and never raises; a failure goes through _cb_note to the pure cb_failure_note, which says a transport failure once per 10 minute window and counts the repeats, carries the said-at time in CARTON_CB_SAID_AT so the child processes of one CLI answer stay quiet, and always says any other failure with its traceback from _cb_trace; _cb_reached clears the outage when CB answers
- **also passes through:** `server_fastmcp.py`, `base/soma-prolog/soma_prolog/core.py`, `test_soma_critical_relay.py`, `test_cb_failure_note.py`, `.claude/skills/soma-help/SKILL.md`

### Domain_Axis_Front_Door — feature boundary of `Giint_Feature_Domain_Axis_Front_Door`

- **user action:** a writer calls add_concept naming a domain or subdomain that is not yet a domain node and supplies domain_about, domain_part_of or subdomain_about, and that node must be written first as is_a Domain with has_about and part_of its parent, while a write without them lands as said and SOMA grades the node against that same subject
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['carton_queue_ingest']`
- **sealed:** v2, key `5d3dfdafe92d8173`, commit `b80684b69`, valid from 2026-10-01T07:39:37
- **ranges in this module** (layer order):
 - `L1 front_door` · `add_concept_tool.py:2714-2716` — add_concept_tool_func takes domain_about, domain_part_of and subdomain_about, optional, after every existing param
 - `L1 front_door` · `add_concept_tool.py:2742-2747` — their docstring entries: nothing is refused
 - `L1 front_door` · `add_concept_tool.py:2841-2848` — THE RELEASE: after the merged-label redirect and the Hwss_Domain confinement and before relationship_dict is built, land_domain_axis writes each planned domain node first through add_concept_tool_func itself, is_a Domain, part_of its parents, property has_about, and returns the DOMAIN AXIS lines ⟵ RELEASE
 - `L1 front_door` · `add_concept_tool.py:3507-3507` — the saved result carries the DOMAIN AXIS lines in its information middle, after the SOMA lines and before D2, so the DO lines stay last
- **also passes through:** `server_fastmcp.py`, `carton_domain_axis.py`, `base/soma-prolog/soma_prolog/util_deps/prolog_interop.py`, `test_carton_domain_axis.py`, `base/soma-prolog/tests/test_domain_slot_targets_are_domains.py`

### Soma_Down_Warning — feature boundary of `Soma_Down_Warning`

- **user action:** any carton process imports carton_mcp.add_concept_tool while SOMA refuses the connection, and the line it logs must tell the reader the one sanctioned restart, whether to run it now, and how to confirm SOMA is back
- **doc(v):** `docs/vision/add_concept_tool.py.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v5, key `0327c5474677d5de`, commit `b80684b69`, valid from 2026-10-01T07:39:38
- **ranges in this module** (layer order):
 - `L0 entry` · `add_concept_tool.py:643-647` — THE ENTRY AND THE RELEASE, one import-time block: when the availability probe says SOMA is down, log ONE error line built by soma_down_warning, passing the pids that serve the URL port when SOMA_URL is local and None when it names another host. It fires once per process at import, which is why every CLI that imports carton printed it on every call during the 2026-09-25 outage ⟵ RELEASE
 - `L0 entry` · `add_concept_tool.py:55-55` — SOMA_URL, env-overridable, default http://localhost:8091/event: the one URL both the probe and the validation POST use, and the URL the warning names, where the old line hardcoded port 8091
 - `L1 probe` · `add_concept_tool.py:524-551` — _check_soma_available: a GET to SOMA_URL with a 2s timeout; an HTTP error means up, a TIMEOUT means up-but-busy, and only a FAST failure (refused or unreachable) returns False. So the warning can only ever describe a refused connection: a saturated SOMA times out, reads as up, and never reaches it
 - `L2 decide` · `add_concept_tool.py:553-640` — THE DECISION (issue 865): RESTART_SOMA_SCRIPT, the one sanctioned restart; soma_url_is_local; soma_argv_port, which reads a process argv the way restart-soma.sh does, a python argv naming soma_prolog.api and its --port (8091 when absent), never the bash wrapper; local_soma_pids, the /proc scan filtered to the URL port so a live SOMA on 8091 says nothing about a daemon expected elsewhere; and the pure soma_down_warning with its three texts: no process, run restart-soma.sh NOW in the background and confirm with sophia-status that the SOMA block reads UP, because nothing on this box restarts SOMA (issue 687); a live process that refuses, booting or socketless, do NOT restart it now because the script kills the live process first and every boot re-mints the registered types, run sophia-status and restart only if it still reads DOWN after the script 180s bound; another host, restart it where it runs. No text tells anyone to run python3 -m soma_prolog.api, the wrong-code start that left 13 hours of writes ungraded
- **also passes through:** `test_soma_down_warning.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
