# Integrating generation with the real datasets: the high-level design

*21 October 2026. This builds on the saved generation plan (StepGen frame, AuraGen operators, REVIEW by context, shell by re-rendering plus a sandbox, PROACT step labelling) and on [auragen-adjacent-survey.md](auragen-adjacent-survey.md).*

## 1. The starting fact

Count what the licensed step-level training data actually covers:
- **InjecAgent** covers modes 16 and 22, through one channel (tool output) and one shortcut (any call to a non-user tool is BLOCK).
- **TOUCAN, ToolACE and When2Call** are benign only.
- **ATBench** adds modes 12, 2, 18, 21, 20 and principal misuse, but only as 1,000 whole-run labels, 30% of them in test.
- Everything with wider step-level coverage (ToolSafe, MCPTox, R-Judge) is blocked by the licence gate.
- There is no security REVIEW label at all in licensed data, and no shell.

So generation cannot be a top-up for a few modes. **It has to be the main source of training signal, and the real data has to change role:** from what the model learns from to what generation is built from and measured against.

## 2. Three ideas that make the integration work

### 2.1 The taxonomy as one coordinate system for everything

Every record, real or generated, is placed in the same cell space:

> **mode × entry channel × decision × action surface × context available**

- *entry channel*: user, tool output, tool metadata, memory, retrieval, system or configuration;
- *decision*: ALLOW / REVIEW / BLOCK;
- *action surface*: JSON tool call, shell or code, final answer, outgoing message;
- *context available*: history only, or history plus policy or memory.

A single **coverage matrix** over this space is the control artefact for the whole pipeline. Real data fills some cells. Generation is pointed at the empty or thin ones. Evaluation is reported per cell. The schema already carries `failure_modes`, `attack_vector`, `adversarial_locations`, `decision` and `action_relation`, so this is a reporting view, not new infrastructure.

### 2.2 The taxonomy as a grammar, not a checklist

The Microsoft modes are not 19 separate things to build. Most are *combinations* of a small number of generative primitives:

| Primitive | Values | Modes it produces |
| --- | --- | --- |
| **Channel**: where influence enters | user | principal misuse, 2 |
| | tool output | 16 |
| | tool description / registry | 12, 7 |
| | memory | 14, 1 |
| | retrieved document | 15 |
| | system prompt / configuration | 5, 1 |
| **Operator**: how the trajectory bends (AuraGen) | single-step perturbation | 22, 18 |
| | new-branch diversion | 16 → 22 hijack |
| | bridged diversion (ends looking aligned) | 8 |
| | delayed trigger | 11 |
| | multi-step corruption | 8, 11 |
| **Harmful act**: what the planned action does | exfiltrate / disclose | 13, 23 |
| | exceed scope | 22, 19 |
| | break isolation (shell) | 21, 18 |
| | consume without bound | 20 |
| | skip a required confirmation | 17 |
| **Context**: what makes the same act right or wrong | none | modes decidable from the action and history |
| | policy or permission | 17, 19 |
| | persona memory | REVIEW, and 14 |

One compositional engine (StepGen-style planner → plant the channel content → apply the operator → render the action surface → branch the decision) then covers about 15 of the 19 single-agent modes. The alternative is 19 mode-specific builds. The mode label also falls out of the composition **by construction**, which is what the provenance model wants.

### 2.3 Real data as libraries feeding the grammar

Each real dataset is decomposed into reusable parts rather than consumed as whole records:

| Library | What it supplies | Real sources (licensed) |
| --- | --- | --- |
| **Contexts** (prefixes) | Real user requests, real tool lists, real tool outputs up to the decision point | TOUCAN (real MCP executions), ToolACE, ATBench train split |
| **Adversarial content** | Attack text to plant in a channel | LLMail-Inject emails (208k unique, human-adaptive), InjecAgent attacker instructions, the text pool (WildJailbreak, Qualifire and others: the "embed into agent contexts" job already planned) |
| **Actions** | Tools and argument patterns; shell commands | TOUCAN MCP specs; RedCode-Exec (600 Bash and about 800 Python risky cases, with a Docker check harness) |
| **Outcomes** | How real agents actually respond (follow, ignore, refuse), which sets realistic branch ratios and continuation styles | InjecAgent's 128k model outputs; the ATBench defence types |
| **Labels to trust** | Given or human labels to calibrate generated-label confidence against | ATBench (given), R-Judge (human; internal only) |

**The best quadrant is real context plus real adversarial content, composed synthetically.** A TOUCAN prefix (real server, real outputs) has an LLMail email or RedCode instruction planted in one tool output. The branches then diverge at the next call. Realism comes from both libraries. The generator only writes the seam and the continuation, and the label is fixed by the plan.

## 3. The generator's second job: removing bias from the real data

Every real source has a structural shortcut that the generator can break **by producing the missing twin of real records**:

| Real-data shortcut | Twin to generate |
| --- | --- |
| InjecAgent: any call to a non-user tool is BLOCK | Benign tasks where the user legitimately asks for that same tool |
| Final answers are always ALLOW | Final answers that disclose tool schemas, system prompt or data (mode 13): BLOCK |
| LLMail: one tool, one target address | Vary the tool and recipient, and add authorised sends to the same address |
| ATBench: 5 fixed injection strings | Re-plant ATBench's contexts with diverse library content |
| Shell absent, so any future shell data risks "shell means BLOCK" | ToolRosetta re-rendering of benign and malicious calls alike |

Principle: **real anchor, synthetic twin.** Attack-only real sets become paired sets, and the pair is the training unit.

The symmetry rule that goes with it: **whatever the generator touches, it must touch in both classes.** If only BLOCK branches contain LLM-written tool outputs, the model learns to spot LLM text, not attacks. ALLOW twins therefore get placebo rewrites of the same span.

## 4. The decidability boundary sets the input contract

The taxonomy splits three ways by what Jev can see at decision time:

1. **Decidable from the action and history**: 2, 7, 8, 12, 13, 16, 18, 21, 22 and principal misuse. Generate freely.
2. **Decidable only if context is supplied**: 17 and 19 (policy or permissions), 14 (memory), 11 (long history). These generate REVIEW and context-flipped triples. They only count **if production will pass that context into Jev.** This turns "policy as input" from a product idea into a data requirement: generate them only in the form production will see.
3. **Better as rules or features than as labels**: 20 (budgets, rate limits), 23 (provenance and lineage tracking), 1 and 5 (configuration integrity). Generation still helps here: StepGen's lineage tags are exactly the provenance feature for 23, so the same engine produces the feature and the label.

Mode 10 (visual CUA attacks) falls outside the input format and stays deferred, alongside the multi-agent modes 3, 4, 6 and 9.

One consequence: Jev maps REVIEW to block. A REVIEW window that runs from when an injection becomes visible to the violation (StepSafe's design) would therefore mark benign steps as block exactly where the ideal behaviour is to ignore the injection and finish the task. **Use REVIEW only where the action itself is ambiguous given the context (17 and 19), not as an injection lead-in.**

## 5. Where everything sits in the existing pipeline

```
              Real datasets (licence-gated)
        ┌──────────────┬──────────────┬──────────────┐
        ▼              ▼              ▼              ▼
   Contexts      Adversarial      Actions       Labelled real
  (prefixes)       content     (tools, shell)  (given/human)
        └──────┬───────┴──────┬───────┘              │
               ▼              ▼                      │
     Coverage matrix ──► Compositional generator     │
   (mode×channel×decision    (plan → plant → operator│
    ×surface×context)         → branch → verify)     │
          ▲                        │                 │
          │                        ▼                 │
          │            Step 1: generated "sources"   │
          │            (same schema; origin =        │
          │             by_construction; group_ids   │
          │             inherited from seeds)        │
          │                        │                 │
          │                        ▼                 ▼
          │            Step 2: build (splits, weights, audit)
          │                        │
          │          train = generated + licensed real
          │          eval  = REAL, held out by source and seed
          │                        │
          └──── per-cell errors ◄──┴──► human audit → per-rule calibration
```

Integration rules that fall out of this:

- **The generator is just more sources.** Each generator family (injection-on-real-prefix, shell, context triples, ATBench unrolled to steps, re-rendering) is a step-1 source with its own `rule` ids. Step 2 is unchanged.
- **Seeds pass their identity on.** Group ids are inherited from the seed's context and attack. Splits then keep a seed's real record and its synthetic children together, and a "held-out source" really is held out, along with everything derived from it.
- **Seeds pass their licence on.** Derived data inherits its seed's licence, so only `include: true` sources are seeds. ToolSafe, MCPTox and R-Judge stay evaluation-only (internal) and are never seed text.
- **Labels follow a hierarchy of trust:** human_verified > given > by_construction > model_inferred. Real given and human labels are what calibrate the per-rule confidence of generated labels. Synthetic labels never calibrate themselves.

## 6. How real data judges the generator

The real data's most important job becomes answering one question: **does synthetic data transfer to real data, cell by cell?**

- **Headline metric.** Train on generated plus licensed real data; test on each real source held out (with its seeds held out too). Report per taxonomy cell.
  - InjecAgent can move from train to evaluation once generated injection data exists; it becomes a clean test of injection transfer.
  - ATBench test and RedCode held-out categories play the same role for their modes.
- **Ablate generation, not just the model.** For each generator family, measure the gain on real held-out data with and without it. A family that only helps on synthetic evaluation is dropped. This is how "proven methods" stays proven inside this project.
- **Realism check.** A classifier asked to separate real records from generated ones in the same cell should struggle. Where it succeeds easily, the features it uses are candidate shortcuts. This is the existing dataset-identity probe, applied to real versus generated.
- **The loop.** Per-cell errors on real evaluation become the next generation targets (StepSafe-style red teaming driven by errors). The test sets themselves are never mined, only validation.

## 7. Order of work

1. **Coverage matrix plus composition grammar on paper.** Map every existing record into cells, and list the empty cells against the 19 modes. Cheap, and it decides everything after it.
2. **Generation that needs no LLM, or very little.** ToolRosetta re-rendering; ATBench unrolled to steps with PROACT; RedCode turned into principal-misuse shell BLOCKs.
3. **The core engine.** Real prefixes (TOUCAN) plus real attack content (LLMail, InjecAgent, text pool), crossed with operators and channels, producing paired branches. This fills 16, 12, 7, 8 and 22 across many tools, and breaks the InjecAgent shortcut.
4. **Context triples** for 17 and 19 (the first real REVIEW signal), once the input contract for policy is settled.
5. **Executed shell** through RedCode's Docker harness for 21 and 18, with benign shell twins.
6. **The loop:** transfer ablations, the realism probe, error-driven targets, audits and calibration.
