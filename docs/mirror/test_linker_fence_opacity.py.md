# doc(m): test_linker_fence_opacity.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_linker_fence_opacity.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

The function-level regression suite for STEP-3 LINKER FENCE-OPACITY: `add_concept_tool.auto_link_description` must leave every `<CartonObj ...>...</CartonObj>` span (open tag + body) BYTE-IDENTICAL while still wiki-linkifying the prose around it. It pins the two corruptions that were observed live before the fix: (a) the open tag's `name=`/Title_Case words got linkified, and (b) JSON array brackets got EATEN because `[x]` is markdown-link syntax. 4 tests. One of the four lib-gate files of the `edit-carton-kv` dev-flow.

## How to run

- `python3 test_linker_fence_opacity.py` (own runner `:76-90`, summary line includes whether `ahocorasick` was available) or pytest.
- Runs against the INSTALLED package (`auto_link_description` uses relative imports — `:8,14`); `HEAVEN_DATA_DIR` defaulted (not forced) to `/tmp/heaven_data` (`:13`).
- Degrades gracefully: if `ahocorasick` is not importable, the two tests that assert prose DID get linked skip their assertions (`:16-20, 44-46, 59-61`) — fence-opacity itself is still fully tested.

## Test infrastructure

- `_FENCE` — `:22-27` — a fence with the corruption-prone shapes: `name=`/`schema=` Title_Case attrs, a quoted-strings array `["clone","install"]`, a bare-ref array `[A_Unit, B_Unit]`, nested JSON.
- `_CACHE` — `:28` — the concept cache fed to the linker, deliberately INCLUDING names that appear inside the fence (`Cave_Repo`, `Unit_Registry`, `A_Unit`, `B_Unit`) so the linker would link them if opacity failed.

## What the suite proves (invariants asserted)

- `test_fence_is_byte_identical` — `:31` — with linkable names both in prose and inside the fence, the ENTIRE fence span survives verbatim in the output; specifically the open tag is not linkified, `["clone", "install"]` and `[A_Unit, B_Unit]` brackets are not eaten, and `"repo": Cave_Repo` stays a bare ref (no markdown link).
- `test_prose_still_links_outside_fence` — `:44` — (aho only) the prose OUTSIDE the fence DID get linked (`_itself.md)` present in `out` minus the fence) — i.e. opacity is masking, not a global disable — and no linkified text bled into the fence.
- `test_no_fence_still_links_normally` — `:59` — (aho only) plain prose with no fences still links — guard against the masking wrapper breaking the normal path.
- `test_multiple_fences_all_preserved` — `:67` — two fences with prose between: both byte-identical, numeric array `[1, 2, 3]` preserved in the second.

## Data contracts

- `auto_link_description(desc, base_path, concept_name, concept_cache=...) -> str` is the ONE chokepoint over every linker caller (per the `edit-carton-kv` dev-flow); this suite is the spec of its fence-opacity obligation.

## Deps

- `carton_mcp.add_concept_tool.auto_link_description`; optional `ahocorasick` (prose-link assertions only); stdlib `os`.

## Defects / dead code

- Without `ahocorasick` installed the suite still reports all-PASS while only half the contract (opacity, not linking) was exercised — the summary line flags `ahocorasick=no` but the exit code does not distinguish.
- `:41`'s `assert "_itself.md" not in _FENCE` is a static sanity check of the test's own constant, not of the code under test.
