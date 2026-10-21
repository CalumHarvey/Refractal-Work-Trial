# When2Call: when to call a tool, ask, or decline

**Snapshot:** `0582f7749df63a96fdc3070932e83e72396ace53/` · downloaded 2026-10-21 · 5 files, 63 MB (checksums in `manifest.json`)
**Source:** Hugging Face [`nvidia/When2Call`](https://huggingface.co/datasets/nvidia/When2Call)
**Paper:** *When2Call* (NAACL 2025)
**Licence:** CC BY 4.0, marked ready for commercial use

## What it is
- **Multiple-choice test set** (`test/when2call_test_mcq.jsonl`): 3,652 items built from BFCL v2 Live. Each has a question, the tools (JSON strings) and four candidate replies: `direct`, `tool_call`, `request_for_info`, `cannot_answer`. One is marked `correct_answer`: tool_call 1,295, cannot_answer 1,295, request_for_info 1,062.
- **Other files:** `llm_judge` (a 300-item subset), `train_sft` (15,000 text-only replies) and `train_pref` (9,000 chosen/rejected pairs). None of these are used.

## Use in this project
Converted (mappings 0.6.7) from the multiple-choice set:
- The **correct reply becomes an ALLOW** (3,652): a tool call, or a final answer that asks or declines.
- Where asking or declining was right, the **candidate tool call becomes a REVIEW** contrast (2,357):
  - `hallucination` when the call invents missing arguments (asking was right);
  - `misinterpretation` when no listed tool fits (declining was right).
- Items are grouped by question and by exact tool set, because BFCL reuses tool sets across paraphrased items.
