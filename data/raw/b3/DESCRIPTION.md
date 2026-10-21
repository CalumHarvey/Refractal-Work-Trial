# b3 (Backbone Breaker Benchmark), public subset

**Snapshot:** `584a18215a5e4a084fd5840ea13e89b4bd5ba331/` · downloaded 2026-10-21 · 61 files, 0.76 MB (checksums in `manifest.json`)
**Source:** Hugging Face [`Lakera/b3-agent-security-benchmark-weak`](https://huggingface.co/datasets/Lakera/b3-agent-security-benchmark-weak)
**Paper:** *Breaking Agent Backbones: Evaluating the Security of Backbone LLMs in AI Agents* (Lakera and UK AISI, arXiv 2510.22620)
**Licence: conflicting.** The README says MIT and the Hugging Face tag says "other", but the `LICENSE` file is a custom licence: academic, non-commercial research only, with no redistribution for other purposes. It is treated as research-only, so the build's licence gate leaves it out. Ask the authors (contact in README) before wider use.

## What it is
- `selected_attacks_low-quality.csv`: 630 rows = 210 crowdsourced attacks × 3 defence levels (0, 1, 2), 63 rows per snapshot. Columns: `app_name`, `app_slug`, `level`, `attack`, `attack_index`, `original_llm`.
- `threat_snapshots/`: 10 apps × 2 defence variants. Each holds the app and state description, the tools available, the task type, the attack vector and objective, the scoring spec (`expected_output`), the system prompt and the prompt templates.
- `tool_specs/`: 50 tool definitions.

The public subset deliberately leaves out the top-scoring attacks. The full 194,331-attack collection is not public.

## Things to know
- **Attacks only:** no model outcomes and no benign rows.
- **Only 10 contexts:** split by snapshot.
- **The three levels are variants of one attack,** differing only in system prompt or self-judge.
