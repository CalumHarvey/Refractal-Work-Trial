# MVP: proving the generation pipeline works

*21 October 2026. A design plan only; no code has been written. It builds on [data-framework.md](data-framework.md) and [implementation-plan.md](implementation-plan.md).*

---

## 1. What the MVP has to prove

The framework rests on one bet. **Synthetic step records composed from licensed real seeds make a decision model better on real data it has never seen, by removing the shortcuts real data teaches.** The MVP tests that bet and the plumbing it depends on, and nothing else.

| # | Hypothesis | Evidence that would confirm it |
| --- | --- | --- |
| H1 | **Plumbing.** Generated records pass through the existing pipeline with provenance; they inherit their seeds' splits; the licence gate holds. | A build with 0 enforced leakage keys, 0 licence violations and 0 followers with conflicting seeds; every generated record traceable to its seeds |
| H2 | **Label quality.** Labels set by construction are correct. | A human audit of a random sample finds ≥ 90% correct decisions, and 100% of BLOCKs have their cause visible in `input` |
| H3 | **Transfer.** Adding generated data improves results on **real** held-out data. | Pre-registered gains over the real-only baseline on Tier 1 and Tier 2 (§5), with no worse false-positive rate on real benign data |
| H4 | **Shortcut removal.** Generated pairs remove the tool-identity shortcut. | The tool-name-only baseline drops to near chance on the mixed training data; the model's errors stop tracking "non-user tool" |

If H3 fails, the framework needs rethinking before anything else is built. The MVP is designed to fail fast and cheaply if that is the outcome.

---

## 2. The slice: one category, one family, end to end

**Category: prompt injection through tool output (mode 16 leading to 22).** It is the only category where all three conditions hold:
- real licensed evaluation data exists (InjecAgent);
- an unlicensed transfer set exists for internal checks (ToolSafe's AgentDojo and ASB steps, R-Judge);
- a known shortcut exists for generation to break (InjecAgent's "non-user tool means BLOCK").

| In the MVP | Out of the MVP (later phases) |
| --- | --- |
| G1 planner (simplified) + G2 with **two operators**: single-step perturbation and new-branch diversion | Multi-step and bridged-branch operators |
| One channel: **tool output** | Tool description, memory, retrieval and user channels |
| G3 branches: **BLOCK, aware-ALLOW, benign tool reuse** | The refuse branch (the target is ignoring the injection, not refusing) |
| QC: rule validator + one judge (StepGen's six-axis auditor) | Placebo rewrite (measured instead, see H4); SVM filter |
| Seeds: **TOUCAN train-server contexts**; **InjecAgent A-side attacker instructions**; a **small LLMail phase-1 sample** (about 1–2k unique, judge-confirmed emails) | Text pool; RedCode; ATBench contexts |
| Splits: InjecAgent **grid**; TOUCAN by server; generated records follow their seeds | Split-plan files for every dataset |
| | PROACT, ToolRosetta, G4 context triples, G5 executed shell, coverage-driven targeting |

The MVP deliberately leaves out the hardest pieces (REVIEW, shell, executed environments). It tests the core composition engine, whose success or failure decides the value of everything else.

---

## 3. Minimum plumbing (a subset of implementation-plan Phase 0)

| Needed | Minimal version |
| --- | --- |
| Frozen real splits | Run the existing build on real data once, after adding the InjecAgent grid, and save `record_id → split` and `group → split`. That file is the split plan. |
| InjecAgent grid split | New `grid` method: tasks and attacks are each hashed into A/B. A×A train, A×B and B×A validation, B×B test. |
| Follower role | `role: derived` in `config/build.yaml`. These records skip grouping and take their seeds' split; conflicting seeds become a reject. |
| Seed lineage | `source.derived_from` (schema change, so update `SCHEMA.md` and the Claude Doc). `meta.generation` holds the family, operator, branch and judge scores. |
| Generated raw root | `data/generated/inject_on_context/<run>/` with a manifest (seed-file hashes, model, prompt version) |
| One converter | `gen_inject`: one step record per decision point, rule ids per operator and branch, rejects for failed QC |
| Licence check | Seeds only from `include: true` datasets (TOUCAN, InjecAgent, LLMail as content) |
| Tier 2 | A separate evaluation-only run over processed ToolSafe and R-Judge; never written to `data/training/` |

Everything else in the implementation plan waits.

---

## 4. Generation: pilot first, then scale

**Pilot: about 50 groups.**
- Tune prompts and the planner on train-side seeds only.
- Audit **every** pilot group by hand. Each group is one shared prefix with three branches.
- **Gate 1** (all must hold to continue):
  - ≥ 90% correct decisions in the audit;
  - 100% of BLOCKs pass the "cause visible in input" check;
  - ≥ 20% end-to-end yield;
  - no branch whose prefix differs from the others.

**Scale: about 1,000 planned groups.**
- At StepGen's roughly 30% yield, that gives about 300 kept groups, which is about 1,000–1,500 step records (BLOCK, aware-ALLOW, benign reuse, and the ALLOW steps of each prefix).
- That is about 10k model calls (plan, rollout, branches, judge): small enough to repeat.
- Audit a random 150–200 records, then set the rule priors in `calibration.rules`.
- **Gate 2:**
  - audit precision ≥ 0.9;
  - the shortcut audit shows tool name no longer predicts the label in the generated data;
  - the realism probe cannot separate real from generated records in the same cell with very high accuracy. If it can, inspect the features it relies on before training.

**Mix, matched to the 1:4 guidance:** generated BLOCKs are paired with at least as many aware-ALLOW and benign-reuse records, so the generated set is not BLOCK-heavy.

---

## 5. Experiment that tests H3 and H4

**Model.** Use the cheapest credible learner, held fixed across arms: a small encoder classifier (e.g. DeBERTa-v3-base or similar) over the serialised `input` → ALLOW/BLOCK, 3 random seeds per arm. It is a probe of data value, not a candidate for Jev.

Two reference points are added:
- a **tool-name-only** logistic regression (the shortcut baseline);
- a **frontier LLM zero-shot judge** (the ceiling reference that TraceSafe and ATBench suggest).

**Training arms.** Each is the same model trained on a different mix:

| Arm | Training data | What it isolates |
| --- | --- | --- |
| **A · Real only** | Current licensed train: InjecAgent A×A, TOUCAN / ToolACE / When2Call train | Baseline |
| **B · Real + generated** | A + all generated records | The framework's claim |
| **C · Real + generated BLOCKs only** | A + generated BLOCK branches, without aware-ALLOW and benign reuse | Whether the **pairing**, not just more attacks, is what helps |
| **D · Real + generated, InjecAgent attacks only** | B without the LLMail seeds | Whether **diverse real attack text** matters |

Arms A and B are essential; C and D are cheap extra runs on the same generated data that explain *why* any gain happens.

**Evaluation sets:**

| Set | Tier | Why it matters |
| --- | --- | --- |
| InjecAgent **B×B** (unseen user tasks *and* unseen attacks) | 1 | Licensed, real, step-level, ALLOW and BLOCK |
| InjecAgent B×B **hard negatives**: real agent outputs that ignored the injection and made the user's call | 1 | False positives under attack |
| **Held-out TOUCAN servers** (benign) | 1 | Over-defence on real benign traffic |
| **ToolSafe AgentDojo / ASB steps** | 2 (internal) | A maker never seen in training. AgentDojo attacks use ordinary user-type tools (send money, send email), so the "non-user tool" shortcut **cannot** work there. This is the sharpest test. |
| **R-Judge** (human labels; excluding its InjecAgent cases already handled) | 2 (internal) | Human-labelled reference |

**Expected failure of the baseline.** InjecAgent B×B may be easy for arm A, because the shortcut works on InjecAgent's own test as well. So **Tier 2 AgentDojo and the hard negatives are where H3 is decided**, not B×B alone.

**Success criteria (fixed before running):**
1. **Tier 2 AgentDojo.** B beats A on BLOCK recall at equal false-positive rate, or on macro-F1, by more than the seed-to-seed spread (3 seeds each). A meaningful target is +5 points.
2. **False positives do not rise.** B's false-positive rate on held-out TOUCAN servers and on B×B hard negatives is no worse than A's (within 1 point).
3. **Shortcut reliance falls (H4).** On B's training mix, the tool-name-only baseline is near chance. A's errors on AgentDojo cluster on "user-type tool used by the attacker"; B's do not.
4. **Pairing helps.** C underperforms B on false-positive rate. This confirms that the shared-prefix twins, not just extra BLOCKs, carry the benefit.

**Kill rule.** If B does not beat A on Tier 2, inspect before scaling: audit errors, realism-probe features, and generated-data diversity. Do not proceed to other modes until the core composition is shown to transfer.

---

## 6. What the MVP leaves you with

- A tested follower-split and lineage mechanism, the basis for every later generator.
- A calibrated rule prior for one generator family, plus the audit workflow.
- A number for **synthetic-to-real transfer**: the field's main open question for agent tool-call guards, and the framework's key risk.
- Reusable seed libraries (TOUCAN contexts, InjecAgent A-side and LLMail attacks) for the next families.

## 7. The next step after a successful MVP

**The cheapest second proof is shell through ToolRosetta re-rendering**, which needs no LLM. It means:
- a RedCode converter (category split);
- re-rendering both classes of the MVP data into shell form;
- evaluation on RedCode held-out categories and a shell-rendered copy of the Tier 1 benign data.

It tests a second focus category and the action-surface shortcut at low cost. After that, the order is PROACT on ATBench, then G4 context triples once the Jev input contract is agreed.

---

## 8. Rough sizing

| Block | Effort |
| --- | --- |
| Plumbing (grid split, follower role, `derived_from`, generated root, converter, Tier 2 eval run) | 3–5 days |
| LLMail sample extraction (phase 1, judge-confirmed, deduped) | 1 day |
| Pilot generation, prompt tuning and full pilot audit | 3–4 days |
| Scaled generation, 150–200-record audit, calibration | 2–3 days |
| Training arms A–D × 3 seeds, evaluation and write-up | 3–4 days |
| **Total** | **about 2–3 weeks**, plus a modest generation bill (about 10k calls) |

**Open decisions before starting:**
- which LLM generates and judges, and whether its terms allow training on outputs;
- the probe model and compute;
- whether Tier 2 internal use of ToolSafe and R-Judge is acceptable until the authors reply.
