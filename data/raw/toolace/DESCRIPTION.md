# ToolACE: function-calling dialogs (benign)

**Snapshot:** `6bda777c88d21e5a204703c1ee45597a8fa4f734/` · downloaded 2026-10-21 · README and `data.json`, 37 MB (checksums in `manifest.json`)
**Source:** Hugging Face [`Team-ACE/ToolACE`](https://huggingface.co/datasets/Team-ACE/ToolACE)
**Paper:** *ToolACE: Winning the Points of LLM Function Calling* (ICLR 2025)
**Licence:** Apache-2.0

## What it is
- **Data:** 11,300 dialogs over synthetic APIs (the paper's pool has 26k).
- **`system`** holds the tool list as JSON. **`conversations`** are turns `user` / `assistant` / `tool`.
- **Call syntax:** assistant calls are written as `[Tool Name(arg="v"), Other(x=1)]`.

## Use in this project
Converted (mappings 0.6.7) into 3,000 ALLOW step records: one per call turn, first call as the planned action, stable sample.
- 766 dialogs have no parsable tool list and 269 call turns could not be parsed; both are skipped.
- **Caveat:** the APIs are synthetic and the dialogs short, so it is kept as a minor share.
