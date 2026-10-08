"""PROVE payload_key distinguishes a SHAPE change, not just a NAME change.

THE DEFECT (measured 2026-08-21): payload_key hashed only the sorted set of observation
NAMES, on the reasoning that "a signature change DOES add or remove an arg node, which
changes the name set". That is false for every change that alters an EXISTING arg:
optional->required, adding has_target_type, adding accepts_unnamed. The name set is
byte-identical, so already_written() said "skip", the write never happened, and the boot
register still printed rc=0 / REGISTERED SUCCESSFULLY over an unchanged record. A real
ontology deploy was silently a no-op because of it.

Pure-function test: no daemon, no CartON, no network.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carton_vault_payload import payload_key

def obs(name, rels, desc="d"):
    return {"source": "vault", "name": name, "description": desc,
            "relationships": [{"relationship": k,
                               "related": [{"value": v, "type": "concept_ref"}]} for k, v in rels]}

# the arg node BEFORE: optional, primitive target
before = [obs("starsystem", [("has_optional_part", "starsystem__arg__giint_project")]),
          obs("starsystem__arg__giint_project", [("is_a", "code_arg"), ("instantiates", "string_value")])]
# AFTER: required + declares its ontological target. IDENTICAL NAME SET.
after  = [obs("starsystem", [("has_required_part", "starsystem__arg__giint_project")]),
          obs("starsystem__arg__giint_project", [("is_a", "code_arg"), ("instantiates", "string_value"),
                                                 ("has_target_type", "giint_project")])]
# description-only edit: must NOT change the key (the original intent, preserved)
desc_only = [obs("starsystem", [("has_optional_part", "starsystem__arg__giint_project")], desc="NEW PROSE"),
             obs("starsystem__arg__giint_project", [("is_a", "code_arg"), ("instantiates", "string_value")],
                 desc="ALSO NEW PROSE")]

names_before = sorted(o["name"] for o in before)
names_after  = sorted(o["name"] for o in after)

ok = {}
ok["name_sets_are_identical"] = (names_before == names_after)          # the premise of the defect
ok["shape_change_changes_key"] = (payload_key(before) != payload_key(after))
ok["description_change_keeps_key"] = (payload_key(before) == payload_key(desc_only))
ok["same_input_is_stable"] = (payload_key(after) == payload_key(list(reversed(after))))

print(f"name sets identical : {names_before == names_after}")
print(f"key(before)         : {payload_key(before)}")
print(f"key(after)          : {payload_key(after)}")
print(f"key(desc_only)      : {payload_key(desc_only)}")
print("\nCHECKS:")
for k, v in ok.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}")
print("ALL_PASS" if all(ok.values()) else "SOME_FAILED")
