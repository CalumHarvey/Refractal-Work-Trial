# MVP experiment

Tests the bet in [research/mvp-plan.md](../../research/mvp-plan.md): synthetic step records composed
from licensed real seeds make a decision model better on real data it has never seen.

**The probe** (`probe.py`) is deliberately simple and identical across arms: hashed unigram and bigram
features from `input` only (planned action, user request, the last three messages, each in its own
namespace), and an L2 logistic regression trained with full-batch Adam in numpy. Differences between
arms measure the training data, not the model. Seeds are bootstrap resamples of each arm's training
rows. The plan's DeBERTa-style encoder can replace it later; the arms, sets and criteria stay.

**Arms** (`data.ARMS`): A0 real only; A + PROACT steps; B + all generated records; C + generated BLOCK
branches only; D = B without LLMail-seeded records. Label: ALLOW = 0, BLOCK or REVIEW = 1.

**Evaluation sets** (`data.eval_sets`):

| Tier | Set | Why |
| --- | --- | --- |
| 1 | `injecagent_bxb` | Unseen user tasks and unseen attacks (grid B x B) |
| 1 | `injecagent_bxb_hard_negatives` | Real agents ignoring the injection: false positives under attack |
| 1 | `atbench_steps_test` | ATBench test runs unrolled by PROACT: a second licensed maker |
| 1 | `redcode_heldout_categories` | RedCode risk categories never seen in training (shell / code execution) |
| 1 | `benign_heldout` | Held-out TOUCAN / ToolACE / When2Call ALLOW: over-defence |
| 2 | `tier2_toolsafe_*`, `tier2_mcptox_*` | Unlicensed, internal only, never trained on or sent to Gemini. R-Judge is labelled per run, not per step, so it is not scored yet |
| 3 | `diagnostic_generated` | Generated from held-out seeds; never a headline number |

**Baselines:** a tool-name-only probe (the shortcut) per arm, scored on validation; optionally a
Gemini zero-shot reference on licensed sets (`--reference N`).

**Criteria** (`run.criteria`), fixed before running: (1) B beats A on Tier 2 AgentDojo BLOCK F1 by more
than the seed spread; (2) B's false-positive rate on held-out benign and on hard negatives is no worse
than A's (+0.01); (3) the tool-name baseline trained on B's mix is near chance (AUROC <= 0.6);
(4) C has a higher false-positive rate on hard negatives than B; (5) A beats A0 on ATBench test steps.

```bash
.venv/Scripts/python -m experiments.mvp.run --seeds 3
```

Results go to `experiments/mvp/results/<timestamp>/report.md` and `report.json`.
