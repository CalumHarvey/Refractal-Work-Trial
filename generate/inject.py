"""Generation family `inject_on_context` (StepGen frame + AuraGen operators, MVP subset).

For each planned group: take a real TOUCAN context (history, tools, the agent's real next call) and
a real attack (an InjecAgent attacker instruction or an LLMail-Inject email), and ask the generator to
plant the attack in the context's last tool output with one operator:
- single_step: the hijacked agent makes its real next call with attacker-chosen arguments;
- new_branch: the hijacked agent abandons the task for a side-effect tool serving the attacker.
One group gives three decision points that share the same prefix:
- block: the attacker's call (BLOCK);
- aware_allow: the agent's real next call with the injection in view (ALLOW, hard negative);
- benign_reuse: a new ordinary request whose right action uses the attack's tool (ALLOW).

QC: deterministic checks (`validate_group`) then a judge model of a different family scores six axes
(StepGen-style auditor); a group is kept with a total >= keep_total and no zero axis. Every group,
kept or rejected, is written to groups.jsonl with its reasons, so nothing is dropped silently.
"""
import difflib
import json
import re
from collections import Counter

from ingest.common.text import normalise, sha1_12
from ingest.convert.gen_inject import applied_operator

from . import libraries, llm
from .config import generation_config, model
from .prompts import (INJECT_PROMPT, INJECT_SYSTEM, INJECT_VERSION, JUDGE_PROMPT, JUDGE_SYSTEM,
                      JUDGE_VERSION)
from .run_folders import read_jsonl, run_dir, write_jsonl, write_manifest

DATASET = "gen_inject"
IDENTIFIER = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+|www\.\S+")  # e-mail addresses and URLs
AXES = ("causal_consistency", "cause_visible", "naturalness", "block_label", "aware_label", "benign_label")
MAX_HISTORY_OUTPUT = 400
MAX_LAST_OUTPUT = 4000


# ---- planning --------------------------------------------------------------------------------
def plan_groups(contexts: list[dict], attacks: dict[str, list[dict]], n: int, side: str) -> list[dict]:
    """Choose context, attack and operator for n groups, deterministically.

    Contexts are used in library order (each at most once while enough exist); attack datasets are
    mixed by config `attack_mix`, and attacks within a dataset are cycled; operators alternate.

    Args:
        contexts: Context seeds.
        attacks: Attack seeds by dataset.
        n: Number of groups.
        side: "train" or "diagnostic".

    Returns:
        Group plans: `{"group_id", "side", "operator", "context", "attack"}`.
    """
    cfg = generation_config()["inject"]
    mix = {d: share for d, share in cfg["attack_mix"].items() if attacks.get(d)}
    total = sum(mix.values())
    plans, used = [], Counter()
    for i in range(n):
        position = int(sha1_12(f"mix|{side}|{i}"), 16) / 16 ** 12 * total
        edge, dataset = 0.0, next(iter(mix))
        for d, share in mix.items():
            edge += share
            if position < edge:
                dataset = d
                break
        pool = attacks[dataset]
        attack = pool[used[dataset] % len(pool)]
        used[dataset] += 1
        context = contexts[i % len(contexts)]
        operator = cfg["operators"][i % len(cfg["operators"])]
        group_id = sha1_12(f"{context['record_id']}|{attack['key']}|{operator}|{side}|{INJECT_VERSION}")
        plans.append({"group_id": group_id, "side": side, "operator": operator, "context": context, "attack": attack})
    return plans


# ---- prompts ---------------------------------------------------------------------------------
def _tools_text(tools: list[dict]) -> str:
    """Render the tool list for the generator.

    Args:
        tools: Schema tools.

    Returns:
        One line per tool: name, description and parameter schema (shortened).
    """
    return "\n".join(f"- {t['name']}: {(t.get('description') or '')[:300]} | "
                     f"{json.dumps(t.get('parameters_schema') or {}, ensure_ascii=False)[:600]}" for t in tools)


def _history_text(messages: list[dict]) -> str:
    """Render the history before the last tool output, with tool outputs shortened.

    Args:
        messages: The context's messages.

    Returns:
        A readable transcript of every message but the last.
    """
    lines = []
    for m in messages[:-1]:
        if m["role"] == "user":
            lines.append(f"USER: {m['content']}")
        elif m.get("tool_call"):
            lines.append(f"AGENT CALL: {json.dumps(m['tool_call'], ensure_ascii=False)[:600]}")
        elif m["role"] == "tool":
            lines.append(f"TOOL OUTPUT ({m.get('tool_name')}): {m['content'][:MAX_HISTORY_OUTPUT]}")
        else:
            lines.append(f"AGENT: {(m.get('content') or '')[:400]}")
    return "\n".join(lines) or "(none)"


def generator_prompt(group: dict) -> str:
    """Fill the generator prompt for one group.

    Args:
        group: A group plan.

    Returns:
        The prompt text.
    """
    ctx, attack = group["context"], group["attack"]
    last = ctx["messages"][-1]
    return INJECT_PROMPT.format(
        operator=group["operator"], user_prompt=ctx["user_prompt"], tools=_tools_text(ctx["tools"]),
        side_effect_tools=", ".join(ctx["side_effect_tools"]), history=_history_text(ctx["messages"]),
        last_tool=last.get("tool_name"), last_output=last["content"][:MAX_LAST_OUTPUT],
        planned_action=json.dumps({k: ctx["planned_action"][k] for k in ("tool_name", "arguments")}, ensure_ascii=False),
        attack_source={"injecagent": "InjecAgent attacker instruction", "llmail_inject": "LLMail-Inject email"}[attack["dataset"]],
        attack_goal=attack["goal"], attack_text=attack["text"])


def judge_prompt(group: dict, gen: dict) -> str:
    """Fill the QC judge prompt for one generated group.

    Args:
        group: The group plan.
        gen: The generator's (validated) answer.

    Returns:
        The prompt text.
    """
    ctx = group["context"]
    return JUDGE_PROMPT.format(
        user_prompt=ctx["user_prompt"], tool_names=", ".join(t["name"] for t in ctx["tools"]),
        last_tool=ctx["messages"][-1].get("tool_name"), injected_output=gen["injected_tool_output"][:MAX_LAST_OUTPUT + 2000],
        injection_text=gen["injection_text"], attacker_action=json.dumps(gen["attacker_action"], ensure_ascii=False),
        aware_action=json.dumps({k: ctx["planned_action"][k] for k in ("tool_name", "arguments")}, ensure_ascii=False),
        benign_request=gen["benign_reuse"]["user_request"],
        benign_action=json.dumps(gen["benign_reuse"]["action"], ensure_ascii=False))


# ---- deterministic checks --------------------------------------------------------------------
def flat(text: str) -> str:
    """Normalise text for containment checks, undoing JSON string escapes.

    The injection is often planted inside a JSON string value, where its newlines and quotes appear
    escaped; comparing flattened forms makes "is the inserted text in the output" robust to that.

    Args:
        text: Any text.

    Returns:
        Lower-case, whitespace-collapsed text with common JSON escapes undone.
    """
    for escaped, plain in (("\\n", " "), ("\\t", " "), ('\\"', '"'), ("\\'", "'"), ("\\/", "/")):
        text = text.replace(escaped, plain)
    return normalise(text)


def operator_of(gen: dict, group: dict) -> str:
    """The operator the generator actually applied, read from what its call does.

    The generator's own `operator` field is unreliable (smaller models name one operator and apply the
    other, or append an explanation), so the call decides: the real next call's tool with changed
    arguments is single_step; any other tool is new_branch. Without a usable call, the field is used.

    Args:
        gen: The generator's answer.
        group: The group plan.

    Returns:
        "single_step" or "new_branch".
    """
    tool = (gen.get("attacker_action") or {}).get("tool_name") if isinstance(gen, dict) else None
    if tool:
        return applied_operator(tool, group["context"]["planned_action"]["tool_name"])
    text = str((gen or {}).get("operator") or group["operator"]).strip().lower()
    return "single_step" if text.startswith("single") else "new_branch" if text.startswith("new") else group["operator"]


def _values(arguments: dict) -> list[str]:
    """Collect string values of a call's arguments (nested), for provenance checks.

    Args:
        arguments: Call arguments.

    Returns:
        String forms of scalar values with at least 3 characters.
    """
    out = []

    def walk(v):
        """Collect scalar values recursively.

        Args:
            v: A JSON value.

        Returns:
            None.
        """
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif v is not None and not isinstance(v, bool) and len(str(v)) >= 3:
            out.append(str(v))
    walk(arguments)
    return out


def validate_group(group: dict, gen) -> list[str]:
    """Check a generator answer against the rules that need no model.

    Checks: the answer's shape; the inserted text appears in the new tool output; the original
    output is preserved (similarity >= 0.8 once the inserted text is removed); the attacker's tool
    exists and its required parameters are given; the attacker's call differs from the real next
    call; a call to another tool than the real next one (new_branch) uses a side-effect tool;
    the cause is visible (some attacker value appears in the inserted text and not in the user's
    request); attacker values are invented, not copied from the seed attack; the benign branch uses
    the attack's tool and carries no inserted value.

    Args:
        group: The group plan.
        gen: The generator's parsed answer.

    Returns:
        Problems found; empty when the group passes.
    """
    if not isinstance(gen, dict):
        return ["answer is not an object"]
    try:
        out, text = gen["injected_tool_output"], gen["injection_text"]
        attacker, benign = gen["attacker_action"], gen["benign_reuse"]
        tool_name, args = attacker["tool_name"], attacker["arguments"]
        benign_req, benign_action = benign["user_request"], benign["action"]
        benign_tool, benign_args = benign_action["tool_name"], benign_action["arguments"]
    except (KeyError, TypeError):
        return ["answer is missing fields"]
    if not all(isinstance(x, str) for x in (out, text, tool_name, benign_req, benign_tool)) \
            or not isinstance(args, dict) or not isinstance(benign_args, dict):
        return ["answer has fields of the wrong type"]
    ctx = group["context"]
    problems = []
    if len(text.strip()) < 15 or flat(text) not in flat(out):
        problems.append("inserted text missing from the new tool output")
    original = flat(ctx["messages"][-1]["content"][:MAX_LAST_OUTPUT])
    remainder = flat(out).replace(flat(text), " ")
    if difflib.SequenceMatcher(None, original, remainder, autojunk=False).ratio() < 0.8:
        problems.append("original tool output not preserved")
    tools = {t["name"]: t for t in ctx["tools"]}
    if tool_name not in tools:
        problems.append(f"attacker tool {tool_name!r} not in the tool list")
    else:
        required = ((tools[tool_name].get("parameters_schema") or {}).get("required")) or []
        missing = [r for r in required if r not in args]
        if missing:
            problems.append(f"attacker call misses required parameters {missing}")
    real = ctx["planned_action"]
    if tool_name == real["tool_name"] and args == real["arguments"]:
        problems.append("attacker call identical to the real next call")
    if operator_of(gen, group) == "new_branch" and tool_name not in ctx["side_effect_tools"]:
        problems.append("new_branch must use a side-effect tool")
    user = normalise(ctx["user_prompt"] or "")
    planted = [v for v in _values(args) if flat(v) in flat(text) and normalise(v) not in user]
    if not planted:
        problems.append("no attacker-chosen value visible in the inserted text")
    seed = flat(group["attack"]["text"])
    copied = [v for v in planted if len(v) >= 6 and flat(v) in seed]
    copied += [t for v in _values(args) for t in IDENTIFIER.findall(v.lower()) if t in seed]
    if copied:  # e.g. LLMail's fixed contact@contact.com would bring back the single-target shortcut
        problems.append(f"attacker value copied from the seed attack instead of invented: {copied[:2]}")
    if benign_tool != tool_name:
        problems.append("benign branch must use the attack's tool")
    if any(flat(v) in flat(text) for v in _values(benign_args) if len(v) >= 5):
        problems.append("benign branch reuses a value from the injection")
    if len(benign_req.strip()) < 10:
        problems.append("benign request too short")
    return problems


def judge_verdict(value) -> tuple[bool, dict, list[str]]:
    """Apply the keep rule to a judge answer.

    Args:
        value: The judge's parsed answer.

    Returns:
        `(keep, scores, problems)`: keep if every axis is scored, none is 0, and the total is at
        least keep_total.
    """
    if not isinstance(value, dict) or not isinstance(value.get("scores"), dict):
        return False, {}, ["judge answer malformed"]
    scores = {}
    for axis in AXES:
        s = value["scores"].get(axis)
        scores[axis] = s if isinstance(s, int) and 0 <= s <= 3 else None
    problems = [str(p)[:300] for p in value.get("problems") or []][:10]
    if None in scores.values():
        return False, scores, problems + ["judge left an axis unscored"]
    keep = sum(scores.values()) >= generation_config()["inject"]["keep_total"] and 0 not in scores.values()
    return keep, scores, problems


# ---- run -------------------------------------------------------------------------------------
def generate(run_id: str, side: str, n_groups: int) -> dict:
    """Generate (or resume) a run of groups and write data/generated/gen_inject/<run>/.

    Args:
        run_id: Run folder name, e.g. "inject-mvp". One run can hold both sides: each group records
            its side, and the converter reads them all.
        side: "train" (seeds from the train side) or "diagnostic" (held-out seeds, Tier 3).
        n_groups: Number of groups to plan; groups already in the run are skipped.

    Returns:
        Counts (planned, kept, rejected by reason) and whether the run stopped on a quota.
    """
    folder = run_dir(DATASET, run_id)
    path = folder / "groups.jsonl"
    done = {g["group_id"]: g for g in read_jsonl(path)}
    contexts, attacks, hashes = libraries.load(side)
    generator, judge = model("generator"), model("qc_judge")
    stopped = None
    try:
        for group in plan_groups(contexts, attacks, n_groups, side):
            if group["group_id"] in done:
                continue
            datasets = [group["context"]["dataset"], group["attack"]["dataset"]]
            row = {"group_id": group["group_id"], "side": side, "operator": group["operator"],
                   "context": group["context"], "attack": group["attack"], "status": "rejected",
                   "reasons": [], "generator": {"model": generator, "prompt_version": INJECT_VERSION},
                   "judge": {"model": judge, "prompt_version": JUDGE_VERSION}}
            try:
                reply = llm.generate_json(generator, generator_prompt(group), datasets=datasets,
                                          system=INJECT_SYSTEM, temperature=0.8)
                gen = reply["value"]
                row["generator"].update(model=reply["model"], model_version=reply["model_version"], output=gen)
                row["reasons"] = validate_group(group, gen)
                if not row["reasons"]:
                    verdict = llm.generate_json(judge, judge_prompt(group, gen), datasets=datasets,
                                                system=JUDGE_SYSTEM, temperature=0.0)
                    keep, scores, problems = judge_verdict(verdict["value"])
                    row["judge"].update(model=verdict["model"], model_version=verdict["model_version"], scores=scores, problems=problems)
                    row["status"] = "kept" if keep else "rejected"
                    if not keep:
                        row["reasons"] = ["judge below threshold"]
            except llm.LLMError as exc:
                row["reasons"] = [f"llm error: {str(exc)[:200]}"]
            done[group["group_id"]] = row
            if len(done) % 10 == 0:
                write_jsonl(path, list(done.values()))
    except llm.QuotaExhausted as exc:
        stopped = str(exc)
    write_jsonl(path, list(done.values()))
    rows = list(done.values())
    counts = {"groups": len(rows), "by_side": dict(Counter(r["side"] for r in rows)), "kept": sum(r["status"] == "kept" for r in rows),
              "rejected_reasons": dict(Counter(reason.split(":")[0] for r in rows if r["status"] != "kept"
                                               for reason in r["reasons"])),
              "kept_by_operator": dict(Counter(operator_of(r["generator"].get("output") or {}, r)
                                               for r in rows if r["status"] == "kept")),
              "kept_by_attack_dataset": dict(Counter(r["attack"]["dataset"] for r in rows if r["status"] == "kept"))}
    counts["yield"] = round(counts["kept"] / counts["groups"], 3) if rows else None
    previous = json.loads((folder / "manifest.json").read_text(encoding="utf-8")) if (folder / "manifest.json").exists() else {}
    write_manifest(folder, DATASET, run_id, "groups.jsonl", {
        "sides": sorted({r["side"] for r in rows}), "libraries": {**previous.get("libraries", {}), side: hashes}, "models": {"generator": generator, "qc_judge": judge},
        "prompt_versions": {"generator": INJECT_VERSION, "judge": JUDGE_VERSION},
        "keep_total": generation_config()["inject"]["keep_total"], "counts": counts, "stopped": stopped})
    return {**counts, "stopped": stopped}
