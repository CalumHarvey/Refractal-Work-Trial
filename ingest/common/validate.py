"""Record validation: the JSON Schema plus invariants the schema cannot express."""
import re
from functools import lru_cache

from jsonschema import Draft202012Validator

from .paths import schema

_GROUP_KEY = re.compile(r"^[a-z0-9_]+:\S")


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    """Build the record schema validator (cached after the first call).

    Returns:
        A Draft 2020-12 validator for agent_decision_record.schema.json.
    """
    return Draft202012Validator(schema())


def problems(rec: dict) -> list[str]:
    """Check a record against the schema and the invariants the schema cannot express.

    Invariants: every non-null label has provenance and vice versa; failure_modes match their
    provenance entries; text and outcome records have no decision; step records have a planned
    action; hard_negative is only true on ALLOW; group_ids look like "<namespace>:<id>"; null
    failure modes are flagged for backfill.

    Args:
        rec: A built record.

    Returns:
        Every problem found, as readable strings; an empty list means the record is valid.
        Invariants are only checked once the schema passes.
    """
    out = [f"schema: {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:200]}"
           for e in _validator().iter_errors(rec)]
    if out:
        return out  # invariants below assume a schema-valid shape

    labels, prov = rec["labels"], rec["provenance"]
    for name, value in labels.items():
        if name == "failure_modes" or value is None:
            continue
        if name not in prov:
            out.append(f"provenance missing for non-null label {name}")

    modes = labels["failure_modes"]
    entries = prov.get("failure_modes")
    if modes is None and entries:
        out.append("failure_modes provenance present but label is null")
    elif modes == [] and [e["mode"] for e in entries or []] != [None]:
        out.append("empty failure_modes needs exactly one provenance entry with mode null")
    elif modes:
        got = sorted(map(str, (e["mode"] for e in entries or [])))
        if got != sorted(map(str, modes)):
            out.append(f"failure_modes {modes} do not match provenance modes {got}")

    for name in prov:
        if name != "failure_modes" and labels.get(name) is None:
            out.append(f"provenance for {name} but the label is null")

    if rec["granularity"] in ("text", "outcome") and labels["decision"] is not None:
        out.append(f"{rec['granularity']} record must have decision null")
    if rec["granularity"] == "step" and rec["input"].get("planned_action") is None:
        out.append("step record without planned_action")
    if labels["hard_negative"] is True and labels["decision"] not in ("ALLOW", None):
        out.append("hard_negative true on a non-ALLOW record")

    for axis, key in rec["source"]["group_ids"].items():
        if key is not None and not _GROUP_KEY.match(key):
            out.append(f"group_ids.{axis} '{key}' is not '<namespace>:<id>'")

    if rec["labels"]["failure_modes"] is None and "failure_modes" not in rec["needs_backfill"] \
            and rec["granularity"] != "outcome":
        out.append("failure_modes null but not flagged for backfill")
    return out
