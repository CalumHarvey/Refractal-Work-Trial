# label-schema/

The specification every converter implements.

| File | Holds |
| --- | --- |
| [`SCHEMA.md`](SCHEMA.md) | The guide to the record format: anatomy, input, labels, provenance and confidence, splitting, Jev export, dataset mappings, examples, open items and changelog. A copy of the Claude Doc "Agent Decision Record Schema"; keep both in sync when the schema changes |
| `agent_decision_record.schema.json` | The JSON Schema every record is validated against (`schema_version` 0.7.0) |
| `dataset_mappings.yaml` | Per dataset: how source fields become input and labels, as named rules with origins and confidence priors; shared tables; the calibration registry (`mappings_version` 0.7.0) |
| [`examples/`](examples/README.md) | Worked example records that validate against the schema |

A change to the schema or mappings changes their version, which makes every processed dataset stale.
