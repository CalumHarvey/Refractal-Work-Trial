# Implementing the data framework on the current codebase

*21 October 2026. A design plan only; no code has been written. It maps [data-framework.md](data-framework.md) onto what exists in `ingest/`, `config/` and `label-schema/`.*

---

## 1. What exists today

| Layer | Code | What it does | Properties worth keeping |
| --- | --- | --- | --- |
| **Raw** | `data/raw/<dataset>/<commit>/manifest.json` | Pinned, untouched downloads | Immutable; never executed |
| **Step 1** | `ingest/run.py` + `ingest/convert/<dataset>.py` (`iter_source`, `to_record`, `RULES`, `report_extras`) | Raw → `data/processed/<dataset>/` records, rejects and report | Deterministic; atomic swap; rule ids checked against `dataset_mappings.yaml`; `--status` staleness check |
| **Records** | `ingest/common/record.py` (`Record.set` / `add_modes`) | Every label is set together with `{origin, rule}` | Provenance cannot be skipped |
| **Step 2** | `ingest/build.py` + `ingest/assembly/` (`load`, `dedup`, `split`, `weights`, `confidence`, `backfill`, `audit`, `export`, `jev`) | Licence gate → dedup → group split → weights → audit → `data/training/` and `data/jev/` | Group split by connected components; holdout pulls in any group it touches; audits for leakage, near-duplicates, shortcuts and markers |
| **Spec** | `label-schema/` + `config/build.yaml` | Schema, rule priors, calibration registry, licence gate, source roles | Confidence is resolved from the rule at load time |

The schema already provides several hooks the framework needs:
- `source.dataset` includes `synthetic` and `redteam`;
- `source.generator_model` and `step_index` exist;
- `input.principal.granted_scopes` is a field for permissions and policy;
- message `trust` already includes `memory`, `retrieved` and `tool_metadata`;
- `dataset_mappings.yaml` has an `attack_content_pool` section, and `RuleSet(section="attack_content_pool")` handles it.

So most of the framework is **new sources and config**, not new machinery. Four places need real design changes (§2).

---

## 2. Five design decisions

### 2.1 Generated and derived data become ordinary raw sources

Everything the framework produces is written to disk as a **pinned, immutable snapshot**, the same way a download is. The existing `run.py` then converts it with an ordinary converter:

| New raw root | Holds | Produced by |
| --- | --- | --- |
| `data/derived/<name>/<run>/` | Deterministic transforms of processed records: PROACT step splits, ToolRosetta renderings | A derive step reading `data/processed/` |
| `data/generated/<family>/<run>/` | LLM-generated trajectories and branches, with judge scores | The generation layer (§2.2) |
| `data/annotations/<task>/<run>/` | Cached model judgements: PROACT boundaries, QC judge scores | The annotation layer (§2.2) |

Each has a `manifest.json` with:
- its **parents**: the processed-dataset manifests or seed-library hashes it was built from;
- the generator or judge model and its terms;
- the prompt version, sampling settings and date.

This keeps every existing guarantee: deterministic step 1, rule-id sync, atomic outputs, and `--status`. `paths.raw_snapshot` and the `--status` check need extending to these roots. `--status` must also follow the **parent chain**, so a derived source goes stale when the processed dataset it came from changes.

### 2.2 Model calls live outside the converters

Converters never call an LLM. All model work (boundary location, generation, judge QC) runs in a separate **generation and annotation layer** that only writes cached artefacts. That layer is a new package (for example `generate/`), a sibling of `ingest/`. Converters read those artefacts deterministically, so rebuilding never re-spends money or changes labels. This is the same separation `backfill.py` already makes, where rule-based backfill is a separate stage from conversion.

### 2.3 Real data is split once, and generated data follows its seeds

Today, splits are decided at step 2 by connected components over group ids. Two problems appear once generation is added:

1. **Seeds must be chosen before the split exists.** Generation needs to know which seeds are train-side before step 2 has run.
2. **Composed records chain groups together.** A generated record that combines a TOUCAN context (group A) with an LLMail attack (group B) joins A and B into one component. When one attack text is reused across many hosts, real groups collapse into a giant component, and the splits of existing real records change.

Design:
- **Step 2a, the split plan.** A new `build --plan-splits` runs the existing split on **real records only** and writes `data/splits/<plan id>.json` (`record_id → split` and `group → split`). It is pinned in `config/build.yaml`, like a raw snapshot. The attack content pool is split here too (LLMail by phase, InjecAgent attacks by the grid).
- **Seed libraries read the plan** and expose train-side items only, plus a separate held-out-seed library used only for Tier 3.
- **Generated and derived records become followers.** A new source role, `role: derived` in `config/build.yaml`, takes its split from its seeds instead of joining the grouping. `assign_all` skips followers when building components, then assigns each one the split of its seeds. If a record's seeds disagree (for example a train context with a held-out attack), the build **rejects** it. That should never happen if the seed libraries are correct, so it acts as the guard.
- Followers still carry their seeds' `group_ids`. The existing `leakage()` audit then reports any seed key appearing across splits.

### 2.4 Licences pass from seeds to derived data

- **A third licence state.** `licences` in `config/build.yaml` gains `include: eval_only`, alongside `true` and `false`, for R-Judge, ToolSafe and MCPTox.
- **Derived sources declare their seeds.** Each generated or derived source declares `seeds_from: [...]`. The licence gate (`config.licensed_datasets`) admits it only if every seed dataset is `include: true`, and refuses the build otherwise.
- **The seed-library builder enforces the same rule**, so unlicensed text can never reach a prompt.

### 2.5 Coverage matrix as a build report that drives generation

- **The coverage report.** A new assembly report, next to `audit.run`, counts records per cell: failure mode × attack vector (channel) × decision × **action surface** × **context available**, by split.
- **Two new derived fields.** Action surface is derived from the planned action (JSON tool call / shell or code / final answer / outgoing message). Context available comes from whether `principal.granted_scopes`, memory messages or policy text are present. Both live in `assembly/derive.py`, never in stored records.
- **Targets live in config.** `config/generation.yaml` holds the per-cell minimums: about 200 per audited rule, and the 1:4 risky:benign mix. The generation layer reads the gap between targets and the coverage report to decide what to generate.

---

## 3. Framework components mapped to code

| Framework component | Where it lives | New or changed | Notes |
| --- | --- | --- | --- |
| Licence roles (train / eval-only / excluded) | `config/build.yaml` `licences`, `assembly/config.licensed_datasets` | Changed | Adds `eval_only` and seed-licence propagation |
| **ATBench 70/30** | Existing source config | None | |
| **InjecAgent grid split** | `assembly/split.py` | New split method `grid` | Two axes (task, attack) are each hashed into A/B. A×A train, A×B and B×A validation, B×B test. Today `ratios: {train: 1.0}`, because the full cross makes one component. The existing exclusion of R-Judge's InjecAgent cases stays as it is. |
| **RedCode by category** | New `ingest/convert/redcode.py`; `group_by_fields: [category]` | New converter | Risk category from the file index. Safety-only categories (bias) are filtered by a rule, not dropped silently. |
| TOUCAN / ToolACE / When2Call | Existing | None | |
| **LLMail by phase, attack pool** | New `ingest/convert/llmail_inject.py` in **pool mode** (`RuleSet(section="attack_content_pool")`), granularity `text` | New | Pool records never enter decision splits (existing `hygiene.separation`). The split plan assigns phase 1 to train seeds and phase 2 to Tier 3 seeds. |
| InjecAgent attacker instructions as seeds | A pool view over the processed InjecAgent records | New view | Grid side A only |
| **PROACT unrolling** | Annotation task `boundaries/atbench` → `data/derived/atbench_steps/` → converter `atbench_steps.py` | New | Rules: `as.safe_all_allow`, `as.boundary_marker` (`rule_inferred`, from `_injected_instruction` / tool markers), `as.boundary_judges` (`model_inferred`, 2–3 judges agree), `as.no_single_boundary` (run kept trajectory-only). Group ids copied from the parent run, so these records are followers of ATBench's split. Test-side boundaries are queued for human audit. |
| **ToolRosetta re-rendering** | Derive step → `data/derived/rendered/` → converter `rendered.py` | New | Deterministic. Seeds are licensed train-side step records of **both** decisions. A round-trip parse is a converter rule, and a failed round trip becomes a reject. |
| **Seed libraries** | `generate/libraries.py` (contexts, adversarial content, actions, outcomes) | New | Read the split plan and processed records, apply the licence rule, and write hashed library files that generation manifests point to |
| **G1–G3 core engine** | `generate/` families: `inject_on_context` (StepGen planner + AuraGen operators + branches) | New | Output: whole groups (unsafe branch, refuse, aware-ALLOW, benign reuse), each with its plan, lineage tags and anchor location. Converter `gen_inject.py` emits one step record per decision point, with `source.dataset = synthetic`, `generator_model` set, and rule ids per operator and branch. |
| **G4 context triples** | `generate/` family `context_triples`; uses `input.principal.granted_scopes` and `system_prompt` | New | Blocked on the Jev input contract: `jev.py` must export scopes and policy (§5) |
| **G5 executed shell** | A separate, sandboxed runner → `data/generated/shell_exec/` → converter | New | **Constraint:** the raw-data rules forbid running anything from `data/raw/`. RedCode's harness (MIT code) must be reviewed and copied into the project, or rewritten, before anything is executed. |
| **QC: rule validator** | `ingest/common/validate.problems` plus generated-source rules | Extended | Exactly one anchor per group; the cause is visible (an `adversarial_locations` entry points into `input`); branches share the prefix byte for byte |
| **QC: judge filter** | Annotation task `qc/<family>`; the converter reads the scores | New | Below-threshold records are **rejects with a reason**, never silent drops, which is the existing reject discipline |
| **QC: placebo rewrite** | Generation step (both classes rewritten) | New | Its effect is measured by the realism probe below |
| Dedup | `assembly/dedup.py` | None | `input_key` already works across sources. ORIGIN_RANK already prefers given over generated. |
| Weights and mix | `assembly/weights.py` | Extended | Per-family share caps and the risky:benign target, alongside the existing per-source reweighting |
| Audit: shortcuts | `assembly/audit.py` `FEATURES` | Extended | Add action surface, command length and generator family to the shortcut features. Marker scan includes generator markers. |
| **Audit: realism probe** | `assembly/audit.py` | New | Real versus generated within the same cell, using the same lexical approach as `shortcuts` |
| Human audit and calibration | `dataset_mappings.yaml` `calibration.rules` | Existing process | New rule ids get priors and enter the ~200-per-rule audit queue |
| Coverage matrix | New assembly report + `config/generation.yaml` | New | §2.5 |
| **Tier 1** | The existing `test` split | None | |
| **Tier 2** | New `build --eval-internal` → `data/eval_internal/` | New | Built only from `eval_only` sources. Never written into `data/training/` or `data/jev/`. Reports leave-one-source-out results. |
| **Tier 3** | New split name `diagnostic` (added to `SPLITS`) | Changed | Followers of held-out seeds land here. Exported separately and never pooled with test. |
| Jev export | `assembly/jev.py` | Extended | Per-split export including `diagnostic`. Scopes and policy as a `context_read` event once the contract is agreed. REVIEW → block unchanged. |

---

## 4. Schema and mappings changes

Each item below is a label-schema change. When it is made, `label-schema/SCHEMA.md` and the Claude Doc "Agent Decision Record Schema" must be updated in the same turn (standing rule).

| Change | Why |
| --- | --- |
| `source.derived_from`: a list of `{record_id, dataset, role}` (context / attack / action / parent) | Lineage for split-following, licence propagation and per-seed ablations |
| `source.dataset` enum: keep `synthetic`; add `derived` (or reuse dataset names with a `derived_from`) | Distinguishes transforms from generation in reports |
| `meta.generation`: `{family, run, operator, branch, judge_scores, prompt_version}` | Audit and ablation by family or operator, without touching `input` |
| `meta.lineage`: argument → `user` / `tool` / `system` | StepGen's lineage tags; also the future mode-23 provenance feature. **Not** in `input` unless production can compute it. |
| No change to `input` for G4 | `principal.granted_scopes` and `system_prompt` already exist |
| `dataset_mappings.yaml` | New `datasets` entries (redcode, atbench_steps, rendered, gen_*); LLMail under `attack_content_pool`; rule priors per family and operator; `future_work.embed_into_agent_contexts` → status active. Bump `mappings_version`. |

---

## 5. Order of commands

```
1  ingest/run.py                      real datasets → data/processed/          (as today; + redcode, llmail pool)
2  ingest/build.py --plan-splits      real-only split plan → data/splits/       (new; pinned in build.yaml)
3  generate libraries                 train-side seed libraries                 (new; reads plan + licences)
4  generate annotate / derive / gen   cached model work → data/annotations, data/derived, data/generated
5  ingest/run.py <derived|gen_*>      converters for the new raw roots          (as today)
6  ingest/build.py                    followers inherit splits; coverage report; audits → data/training, data/jev
7  ingest/build.py --eval-internal    Tier 2 → data/eval_internal               (new)
8  human audit → calibration.rules    per-rule confidence                       (existing process)
```

`--status` at steps 1, 5 and 6 tells you what is stale. The coverage report from step 6 sets the targets for the next round of step 4.

---

## 6. Phases (matching the framework's order of work)

| Phase | Work | Code impact |
| --- | --- | --- |
| **0 · Foundations** | Split plan + follower role; `eval_only` licences; InjecAgent grid method; `diagnostic` split; coverage report; schema `derived_from` / `meta.generation` | Changes confined to `assembly/` and config; no generation yet. Rebuilding should leave existing real splits unchanged, apart from InjecAgent moving to the grid. |
| **1 · No-LLM data** | RedCode converter; ToolRosetta derive + converter; LLMail pool converter | New converters only |
| **2 · PROACT** | Boundary annotation task + `atbench_steps` converter; human audit of test boundaries | First use of the annotation layer |
| **3 · Core engine** | Seed libraries; `inject_on_context` family (G1–G3 + QC) | The `generate/` package appears |
| **4 · Context triples** | Agree the Jev input contract for scopes and policy; G4 family; `jev.py` export of context | Needs a product decision first |
| **5 · Executed shell** | Review and copy RedCode's harness; sandbox runner; G5 converter | Needs a sandbox decision first |
| **6 · Loop** | Generator-family ablations, realism probe, error-driven targets | Reporting plus config |

---

## 7. Risks and open decisions

- **Running RedCode code.** The raw-data rules forbid executing anything from `data/raw/`. G5 needs a reviewed, vendored harness and an isolated sandbox.
- **Generator terms and cost.** Each generator's terms must allow training on its outputs; record them in the generation manifest. StepGen-style yields of about 30% mean roughly three times the generation calls per kept group.
- **Storage.** `data/` sits in OneDrive. Generated runs and annotation caches add to the sync load (LLMail is already 2.45 GB), so consider keeping `data/generated` and `data/annotations` outside the synced folder, with manifests pointing to them.
- **The Jev input contract** for scopes, policy and memory decides whether modes 14, 17 and 19 count at all.
- **Split stability.** Moving InjecAgent to the grid changes current train counts (all InjecAgent is train today), so the step head's training share must be re-balanced.
- **Text-pool licences** must be checked before they are added to seed libraries.
