# generate/

Everything that calls a model lives here. Outputs are pinned runs, each with a `manifest.json`:
- **relabelled real data** (PROACT's `atbench_steps`: real content, step labels located by rules or
  models) under `data/derived/<dataset>/<run>/`;
- **synthetic data** (`gen_inject`: content a model wrote) under `data/generated/<dataset>/<run>/`.

The ordinary converters in `ingest/convert/` turn runs into records, and never call a model themselves,
so rebuilding never spends money or changes labels. Design: [research/implementation-plan.md](../research/implementation-plan.md),
[research/mvp-plan.md](../research/mvp-plan.md).

## Modules

| Module | What it does |
| --- | --- |
| `config.py` | Reads `config/generation.yaml` |
| `llm.py` | Gemini client: JSON replies, on-disk cache (`data/cache/llm/`), throttling, retries, independent samples, fallbacks on overload or daily quota, and a data guard that refuses `eval_only` datasets |
| `prompts.py` | Versioned prompt templates: boundary judge, injection generator, QC judge, zero-shot reference |
| `run_folders.py` | Run folders and manifests. A run's `revision` hashes its main file, so its converted output goes stale when the run changes |
| `libraries.py` | Seed libraries from the split plan: train side (TOUCAN train contexts, InjecAgent grid side A, LLMail phase 1) and diagnostic side (TOUCAN test contexts, grid side B, LLMail phase 2) |
| `proact.py` | PROACT boundaries for ATBench runs (rule first, then agreeing judges), the human check sheet, its import, Gate P |
| `inject.py` | The `inject_on_context` family: plan groups, generate, deterministic checks, QC judge, write `groups.jsonl` |
| `review.py` | Human review of generated groups: sheets, import, Gate 1 / Gate 2, calibration entries |
| `__main__.py` | The `python -m generate` command (each step on its own) |
| [`tests/`](tests/README.md) | Tests that need no network |

## Running it

The automatic steps (libraries, PROACT, generation) run as stages of `python -m pipeline`. The
human-in-the-loop steps run here:

| Step | Command |
| --- | --- |
| PROACT check sheet: every test-side boundary + 100 train | `python -m generate proact-sheet --run proact-v1` |
| Import it, then Gate P (>= 85% agreement) | `python -m generate proact-import --run proact-v1` then `proact-gate` |
| Review sheet: every group (pilot) or `--sample 200` (scale) | `python -m generate review-sheet --run inject-mvp` |
| Import it, then Gate 1 / Gate 2 and calibration entries | `python -m generate review-import --run inject-mvp --sheet <filled csv>` then `review-gate` |

Each step also runs on its own: `python -m generate libraries | proact | inject ...` (see `--help`).
The PROACT sheet is `data/derived/atbench_steps/<run>/human_check.csv`, with transcripts beside it.
The review sheets are `data/generated/gen_inject/<run>/review_all.csv` or `review_sample.csv`, with
`review_groups.md` beside them.

## Free tier: what to expect

- **One model for now: Gemini 3.5 Flash-Lite**, for every role. PROACT's agreement comes from three
  independent samples of it (temperature 0.7, each cached separately), and the QC judge is the same
  model as the generator. Both are weaker than the plan's separate models; swap models in
  `config/generation.yaml` when a paid key is available.
- **Quotas are per model and small.** A daily-quota error stops the run with exit code 3 (or moves to a
  model in `llm.fallbacks`, empty for now); the same command resumes later from the cache.
- **Overload (503)** is retried with backoff. Every row records the model version that actually answered.
- **Data sent to Google may be used and read by humans.** Only licensed data is sent; `eval_only`
  datasets (ToolSafe, R-Judge, MCPTox) are refused by `llm.check_datasets`.
