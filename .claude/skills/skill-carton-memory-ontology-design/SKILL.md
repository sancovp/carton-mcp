---
name: skill-carton-memory-ontology-design
description: "WHAT: where the memory-tier ontology (Memory_Tier, Memory_Tier_0..3, UltraMap, Hypercluster) lives now — it MOVED to SOMA's OWL; do NOT design it in CartON. WHEN: you need to find/edit the memory-tier ontology types, or you're tempted to re-add a CartON memory-ontology bootstrap."
---

# skill-carton-memory-ontology-design

## STATUS: the carton-side how-to is REMOVED — the intent lives in SOMA now (2026-06-17)

This skill used to instruct authoring `HyperCluster` / `Memory_Tier` / `UltraMap` /
`Carton_Ontology_Entity` types via CartON's `bootstrap_memory_ontology_types`. **That path is DEAD:**
`bootstrap_memory_ontology_types` (and `bootstrap_ontology_types`) in `carton_utils.py` are commented
out / DISABLED, and the memory-tier ontology was **MOVED to SOMA's OWL** (`base/soma-prolog/soma_prolog/
starsystem.owl`: `Memory_Tier` + `Memory_Tier_0..3` + `UltraMap` + an enriched `Hypercluster`, commit
dc9abc6). This is the carton->SOMA unification: ontology/type definitions live in SOMA, not in a carton
bootstrap.

## What to do now (the preserved intent)
- **To find or edit the memory-tier ontology** → it is OWL classes/restrictions in
  `base/soma-prolog/soma_prolog/starsystem.owl`. Edit it there; SOMA reflects vaulted/declared types
  back into CartON.
- **Do NOT re-add** `bootstrap_memory_ontology_types` or any carton-side ontology-type creation — that is
  exactly the removed machinery.
- Memory_Tier instances (the actual tier files / MEMORY.md) are still a CartON projection — see
  `skill-memory-as-carton-projection`.

(The original how-to is preserved in git history + /tmp/heaven_data/_deprecated_skills if needed.)
