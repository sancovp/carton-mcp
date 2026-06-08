# YOUKNOW Integration Plan

**STATUS: ✅ IMPLEMENTED (2026-01-13)**

## Overview

YOUKNOW is an ontological linter/validator at `/tmp/youknow-kernel`. It validates entities have proper UARL relationships.

## Integration Point

Add `hide_youknow` parameter to `add_concept()`:

```python
def add_concept(
    concept_name: str,
    concept: str,
    relationships: list,
    hide_youknow: bool = False  # NEW
):
```

## Behavior

- `hide_youknow=False` (default): YOUKNOW validates, **warns** if invalid (doesn't block)
- `hide_youknow=True`: Skip validation, silent add to soup

## YOUKNOW Validation

```python
from youknow_kernel.core import YOUKNOW
from youknow_kernel.models import PIOEntity, ValidationLevel

youknow = YOUKNOW()

# Convert CartON concept to PIOEntity
entity = PIOEntity(
    name=concept_name,
    description=concept,
    is_a=[r["related"] for r in relationships if r["relationship"] == "is_a"],
    # ... map other relationships
)

# Validate
result = youknow.validate_entity(concept_name)
if not result.valid:
    # WARN, don't block
    logger.warning(f"YOUKNOW: {result.message}")
```

## Two-Layer System

- **Soup**: Concepts with weak relationships (has_type, auto_related_to) - always allowed
- **Ontology**: UARL-valid concepts that trace to PythonClass

YOUKNOW tells you what's in soup vs what could be ontology.

## For Ontology Engineer Agents

Force `hide_youknow=False` at agent config level - they must see all warnings.

## Config Location

`/tmp/heaven_data/carton/.youknow_config.json`:
```json
{
  "enabled": true,
  "warn_level": "all"
}
```

## Dependencies

- `pip install -q /tmp/youknow-kernel`
- Import: `from youknow_kernel.core import YOUKNOW`
