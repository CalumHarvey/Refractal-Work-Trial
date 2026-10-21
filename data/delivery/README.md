# data/delivery/

One folder per delivery to Jev (`python -m deliver`, or the pipeline's `deliver` stage):

| File | Holds |
| --- | --- |
| `<run>/<split>/batch-0001.json` and so on | The exact request bodies: each trace's events and expected finding, in Jev's formats |
| `<run>/<split>/responses.jsonl` | Jev's reply per batch (a stub reply in a dry run) |
| `<run>/selected_index.jsonl` | What was sent, linking each trace back to its record (never sent) |
| `<run>/manifest.json` | Selection (splits, kinds, datasets), counts, endpoint, dry-run flag, the build it came from |

A delivery of every split writes a few hundred MB of request bodies. Delete old runs when they are no longer needed.
