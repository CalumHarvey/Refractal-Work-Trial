# generate/tests/

Tests for the generation layer. They need no network: the Gemini call is replaced by a fake, and the cache
is pointed at a temporary folder.

| File | Covers |
| --- | --- |
| `test_generate.py` | Injection checks (including JSON-escaped injections and seed values that must be rewritten), the judge keep rule, deterministic group planning, the LLM cache, fallbacks on overload and quota, the data guard for evaluation-only datasets, PROACT's rule boundaries and judge agreement (independent samples count, fallback duplicates do not) |
