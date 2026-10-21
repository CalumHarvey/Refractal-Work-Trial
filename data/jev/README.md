# data/jev/

Written by `ingest/build.py` (step 2) in the same build as data/training/; replaced whole on every build.
The same splits in Jev's formats. `deliver` (python -m deliver) selects from here and sends to Jev.

| File | Holds | Sent to Jev? |
| --- | --- | --- |
| `<split>/events.jsonl` | Input events, `refractal.agent-trace.v1`, one per line; a record's planned action is its trace's last event | Yes |
| `<split>/findings.jsonl` | The expected finding per trace, `refractal.agent-trace-finding.v1` (decision, verdicts, data_classes, threat_categories, shell_impacts) | Yes |
| `<split>/index.jsonl` | Local link from each trace back to its record: record_id, dataset, data kind, the record's decision, weight, verdict confidences | **No** |
| `manifest.json` | Build fingerprint, schemas, Jev settings, per-split summary, file checksums | No |
