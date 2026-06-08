# Flight Config → CartON Mirroring (Future Work)

## Context
Session 2026-01-13: Fixed carton UNWIND batching (222x speedup) and starlog→carton mirroring.
This is the next step to mirror flight configs to Neo4j.

## Plan

### 1. Modify starship_mcp
File: `/home/GOD/starship_mcp/starship_mcp/starship_mcp.py`
- In `internal_add_flight_config()` - add `mirror_to_carton()` call after creating config

### 2. Modify starlog fly()
File: `/home/GOD/starlog_mcp/starlog_mcp/starlog_mcp.py`
- In `internal_fly()` - optionally query Neo4j for flight configs

### 3. Add Neo4j env vars to starship strata config
File: `~/.config/strata/servers.json`
- Add NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD to starship (same as starlog fix)

### Concept structure for flights:
```
name: Flight_Config_{name}
relationships:
  - is_a: Flight_Config
  - has_category: {category}
  - part_of: Starship_Flight_Registry
description: {config_data summary}
```

## Priority: Low
Main carton fixes are done. This is enhancement.
