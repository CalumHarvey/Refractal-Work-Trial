# data/cache/

`llm/<model>/<xx>/<key>.json`: every Gemini reply, one file per request, keyed by a hash of the model,
prompts, temperature and sample index. Re-running a generation or PROACT step reuses these files, so it
is free and gives the same answers.

Safe to delete, but the next run then makes (and pays for) every call again.
