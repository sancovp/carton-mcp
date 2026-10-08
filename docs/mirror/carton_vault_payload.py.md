# doc(m): carton_vault_payload.py

**Module:** `carton-mcp/carton_vault_payload.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Soma_Boot_Register — feature boundary (no Giint_Feature node declared)

- **user action:** SOMA boots, and its boot thread must bring the foundation and gnosys-vault types into its store exactly once: register what is missing, post nothing for a registration the reflection and the record already hold, and register a fresh or isolated store into itself
- **doc(v):** `base/soma-prolog/docs/vision/_soma_boot_register.md`
- **outputs to:** `['foundation_types', 'register_gnosys_vault_fires']`
- **sealed:** v7, key `2472be6229c7cfc2`, commit `a0bd99755`, valid from 2026-09-30T22:02:19
- **ranges in this module** (layer order):
  - `L4 existence` · `carton_vault_payload.py:202-303` — _reflection_state reads a payload as absent, present_not_code or present_code in soma_triples under soma_prolog.names.normalize_name: every relationship and every primitive value must be there as the atom text SOMA stores or it is absent and gets sent; present_not_code names each observation with no is_a row at code or higher, because vaulting makes a thing code; payload_digest, resent_unchanged and mark_resent record a not-code re-send against its exact content; an unanswerable check is absent
  - `L4 existence` · `carton_vault_payload.py:306-350` — already_written is True only when the reflection holds the payload at code or higher and the record holds its names; a flag fresher than FLAG_TTL_DAYS stands in for the record, otherwise the record is asked; anything else drops the flag
  - `L4 existence` · `carton_vault_payload.py:452-562` — add_vault_payload: present at code and in the record returns carton_vault skipped and posts nothing; present but not code with content already re-sent once returns posted nothing naming it; otherwise one atomic SOMA event, the reflection read again so names still not code are recorded and carried on the report as present but not code, then one validated CartON write per observation  ⟵ RELEASE
- **also passes through:** `base/soma-prolog/soma_prolog/api.py`, `base/soma-prolog/scripts/register_foundation.py`, `base/soma-prolog/gnosys-vault/scripts/register_gnosys_vault.py`, `base/soma-prolog/soma_prolog/vault.py`, `base/soma-prolog/soma_prolog/soma_store.py`, `base/soma-prolog/soma_prolog/names.py`, `base/soma-prolog/soma_prolog/util_deps/prolog_interop.py`, `test_carton_vault_payload.py`, `base/soma-prolog/tests/test_boot_holds_normal_queue.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
