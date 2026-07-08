---
name: skill-carton-jit-options-fix
description: "WHAT: the fix that makes only HAS_OPTION relationships become TreeShell children — replace the hardcoded GIINT child_types in _jit_node_from_carton with the HAS_OPTION relationship, so TreeShell options are explicitly programmed via CartON instead of inferred from structural relationships. WHEN: when JIT-loaded CartON nodes wrongly display structural relationships as navigable options, you want a JIT node to show only explicitly programmed HAS_OPTION children, or fixing _jit_node_from_carton."
---

'''Replace hardcoded GIINT child_types with HAS_OPTION relationship in _jit_node_from_carton so TreeShell options are explicitly programmed via CartON''' '''Replayable skill pattern - single_turn_process=context+action''' '''Integration between CartON knowledge graph and TreeShell navigation''' '''Skill category classification''' '''Personal domain category enum''' '''Integration between CartON and TreeShell''' '''How JIT-loaded CartON nodes get navigable children''' '''Only HAS_OPTION relationships become TreeShell children '''When JIT nodes display structural relationships as navigable options''' '''JIT nodes only show explicitly programmed options via HAS_OPTION''' '''JIT node builder in base TreeShell'''

---
## Skill Contents

- `reference.md` — detailed reference (read for full docs)
