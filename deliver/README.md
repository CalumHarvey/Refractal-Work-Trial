# deliver/

The last stage: chooses what goes to Jev, packages it in Jev's formats, and sends it through the
(placeholder) Jev API. It reads `data/jev/`, which `ingest/build.py` writes, and refuses to run if that
folder is out of date.

| Module | What it does |
| --- | --- |
| `selection.py` | `Selection`: which splits, data kinds (`real`, `relabelled_real`, `synthetic`) and datasets to send; applied to each split's local index |
| `package.py` | Builds one item per trace: its events (`refractal.agent-trace.v1`) and expected finding (`refractal.agent-trace-finding.v1`). Record ids, dataset names, kinds and weights never leave |
| `client.py` | `JevClient`: POSTs batches as JSON with the key from `JEV_API_KEY`. In a dry run nothing is sent |
| `delivery.py` | One delivery run: check `data/jev/` is current, select, package, batch, send, record |
| `__main__.py` | The `python -m deliver` command; its selection flags are shared with `python -m pipeline` |
| [`tests/`](tests/README.md) | Tests |

## Choosing what to send

Defaults are in [config/deliver.yaml](../config/deliver.yaml); flags override them for one run:

| Command | Sends |
| --- | --- |
| `python -m deliver` | Train, validation and test; every kind; dry run |
| `python -m deliver --kinds real relabelled_real` | No synthetic data |
| `python -m deliver --kinds synthetic --splits train` | Synthetic training data only |
| `python -m deliver --exclude toolace` | Every dataset except ToolACE |
| `python -m deliver --send` | For real, to `api.endpoint` |

## Output

`data/delivery/<run>/` holds:
- `<split>/batch-0001.json` and so on: the exact request bodies;
- `<split>/responses.jsonl`: one reply per batch;
- `selected_index.jsonl`: what was sent, for joining Jev's results back to records;
- `manifest.json`: the selection, counts, endpoint, dry-run flag and the build it came from.

## Placeholders to replace

The endpoint, the request body shape (`{"split", "traces": [{"trace_id", "events", "expected_finding"}]}`)
and the response handling are placeholders until Jev's ingestion API is defined. The finding's field names
are Jev's. The shape of `verdicts` and the threat category names are assumptions, set in config/build.yaml `jev`.
