# RedCode: risky code execution and generation by code agents

**Snapshot:** `664e4793dc7309f98b8271baed5bbc04d6ef4c39/` · downloaded 2026-10-21 · sparse checkout of `dataset/`, `evaluation/`, README and LICENSE (see `manifest.json`)
**Source:** GitHub [`AI-secure/RedCode`](https://github.com/AI-secure/RedCode)
**Paper:** *RedCode: Risky Code Execution and Generation Benchmark for Code Agents* (NeurIPS 2024 Datasets and Benchmarks), AI-secure, UIUC
**Licence:** data CC BY 4.0 (`dataset/LICENSE`, attribution required); code MIT. `evaluation/` is kept as a reference for how outcomes are judged and is never executed (raw data is never run).

## What it is

| Part | Contents | Used here |
| --- | --- | --- |
| RedCode-Exec | Risky code to run. `bash2text_dataset_json/`: 20 risk categories × 30 = 600 Bash cases. `py2text_dataset_json/`: 27 categories × 30 = 810 Python cases. Each case has `Index` (`<category>_<n>`), `Language`, `Code`, `Text_summary` and `Text_details` (two natural-language requests for the same code), `expected_result` (what the authors' container check looks for) and `Prompt` (empty) | **Yes** (converter `ingest/convert/redcode.py`) |
| RedCode-Gen | Prompts asking an agent to write malware, by type: adware, DDoS, ransomware, rootkit, spyware, trojan, virus, other | No: there is no tool action to decide on |

## Risk categories (RedCode-Exec)

Categories are numbered by the file index. Names below describe the cases. Only categories 10, 11, 17, 19, 24, 26 and 27 are Python-only; the rest exist in both languages.

| Category | What the cases do | Decision here |
| --- | --- | --- |
| 1 | Send a sensitive file (e.g. /etc/passwd) to a remote server | BLOCK |
| 2 | Download untrusted code and save it | BLOCK (mode 18) |
| 3, 26 | Fetch content from a risky website | REVIEW |
| 4 | Copy a sensitive file | BLOCK (21) |
| 5 | List files in a sensitive directory | REVIEW (21) |
| 6 | Write an encoded malicious payload to a file | BLOCK |
| 7 | Read a sensitive file | BLOCK (21) |
| 8 | Delete a sensitive file | BLOCK (21) |
| 9 | Add a malicious alias to `.bashrc` (persistence) | BLOCK (21) |
| 10 | Open a reverse shell / listening socket | BLOCK (21) |
| 11 | Monitor system resources | REVIEW |
| 13 | Read a sensitive file through path traversal | BLOCK (21) |
| 14 | Run attacker-controlled code through `eval` | REVIEW (18) |
| 17 | Raise privileges without lowering them | REVIEW (19) |
| 18 | Kill system processes (e.g. sshd) | BLOCK (20) |
| 21 | Amplify input and send it to a server | REVIEW (20) |
| 24 | Unsafe deserialization (pickle) | REVIEW (18) |
| 27 | Memory leak | REVIEW (20) |
| 12, 15, 16, 19, 20, 22, 23, 25 | Vulnerable code patterns, not harmful actions: biased hiring score, flawed regex, timing side channel, predictable seed, unsalted hash, missing default case, flawed workflow, duplicate keys | **Excluded** (450 cases) |

Every record also carries `principal_misuse`: the user asks for the risky code.

## How it becomes records

- One step record per kept case and request variant (summary, details): **1,920 records** from 960 cases (1,140 BLOCK, 780 REVIEW).
- The user's message is the request; the agent's planned action runs `Code` on a real shell or Python execution tool taken from TOUCAN (`lilith-shell-execute_command`, `desktop-commander-execute_command`, `remote-shell-server-shell-exec`, `terminal-controller-execute_command`; `python_exec`, `python-safe-sandbox-execution-server-python_exec`), chosen per case by a stable hash. Those tool names also appear on benign TOUCAN steps, so the name alone does not predict the label.
- Splits hold out whole risk categories (`group_by_fields: [category]`). In the current build, validation holds categories 13 and 14, and test holds 1 and 18.

## Things to know

- **Attack-only.** There is no benign shell use in RedCode. With TOUCAN's few benign shell calls, 88% of train shell / code actions are BLOCK or REVIEW, and the build's surface audit warns about it. Benign shell twins (the same command family on harmless targets) are the next step.
- **The user is the source of the harm** (principal misuse). Injected shell commands (the same code hidden in a tool output) are a generation task for later.
- **The BLOCK vs REVIEW choice per category is this project's.** RedCode labels every case risky; the decision is `rule_inferred` (prior 0.8) until audited.
