---
name: understand-carton-queue-formats
description: "WHAT: the three CartON queue file formats and when to use each. WHEN: writing files into carton_queue, or queued observations land in failed."
---

**In full:** WHAT: the three CartON observation queue file formats and when to use each one (raw_concept flat format, observation format, batch format) for files written to the carton_queue directory that the observation worker daemon processes. WHEN: when writing or generating files into carton_queue/ from a hook or script, choosing a queue file format, or debugging why queued observations land in the failed/ folder.

The queue is `$HEAVEN_DATA_DIR/carton_queue/`, drained by the observation worker of the machine it sits
on. Every entry is one JSON file. The worker takes `sorted(glob('*.json'))` — the top-level files only —
in batches, parses each with `parse_queue_file_to_concepts`, writes the batch in one go, then moves each
file to `processed/` (written) or `failed/` (dead-lettered, `error_message` inside), or leaves it in place
when there was no graph connection to try. `drain_once(queue_dir, connection)` in
`observation_worker_daemon.py` is that whole batch; the daemon's loop calls it once a tick.

## Write an entry through the write path, never by hand

- The write path is `add_concept` — CartON's SDK, called in process on the box or through the box's door
  (`carton_api.call_carton("add_concept", {...})` with `CARTON_URL` + `CARTON_KEY`). The operation runs
  on the box and writes the entry into the box's own queue through `add_concept_tool.submit_queue_entry`,
  which is `write_queue_entry`: nothing off the box ever writes a queue file.
- `write_queue_entry` names the file `YYYYmmdd_HHMMSS_ffffff_<uuid8><suffix>.json` from a stamp the
  process never lets go backwards, so entries written one after another drain in that order. It writes
  under a `.part` name and renames, so the worker never reads half a file.
- Whether an entry has landed, on the box: `add_concept_tool.queue_status([...])` → `queued` · `processed`
  · `failed` · `absent`, plus `waiting` (the top-level backlog). Read the graph only after `processed`.

## The three formats

**raw_concept — one concept.** Detected by `"raw_concept": true` or a `concept_name` key.

```json
{"raw_concept": true, "concept_name": "X", "description": "...",
 "relationships": [{"relationship": "is_a", "related": ["Y"]}],
 "desc_update_mode": "append", "source": "agent", "properties": {"status": "open"}}
```

Carried keys: `description`, `relationships`, `timestamp`, `desc_update_mode`
(append/prepend/replace/edit), `old_str_for_edit_case`, `removed_fences`, `skip_ontology_healing`,
`is_code`, `gen_target`, `is_system_type`, `is_soup`, `soup_reason`, `source`, `target_descs`,
`release_effects`, `fillable_requests`, `composed_triples`, `compose_suggestions`, `properties`.
A relationship type given twice keeps the last.

**concepts list — several concepts in one file.** Detected by a non-empty `"concepts"` list.

```json
{"concepts": [{"name": "A", "description": "...", "relationships": [...], "properties": {...}},
              {"name": "B", "relationships": [{"type": "is_a", "target": "Y"}]}],
 "source": "agent"}
```

Each item carries every key a raw_concept file does, read off the item; `source` falls back to the
file's own. Relationships take `{"relationship", "related"}` or `{"type", "target"}`, and a type given
twice is merged. Use it to land many concepts, properties included, in one entry.

**observation — tagged parts under a wrapper.** Any other dict: every key outside
`OBSERVATION_NON_TAG_KEYS` (`add_concept_tool.py`) is a tag holding a list of parts. A part with
relationships must carry `is_a`, `part_of`, `has_personal_domain` (one of `PERSONAL_DOMAINS`) and
`has_actual_domain`, or the whole file is dead-lettered before parse with the gap named. The worker adds
`has_tag` and `part_of <timestamp>_Observation` to each part and writes the wrapper. Parts carry
`description`, `relationships`, `desc_update_mode` and the file's `source` — no properties.

A file matching none of these, or unreadable JSON, is dead-lettered with that reason. A
`{"timeline_merge": ...}` file is not a concept entry: it runs after the batch's concepts are written.

## Properties in an entry

A property value is a str, int, float or bool, or a flat list of those. `None` unsets the key. A dict, or
a list holding one, refuses that concept's whole property set (its node still lands) — JSON-encode it and
store the string. Reserved keys (`n`, `d`, `t`, `c`, `region`, `source`, …) are refused.
