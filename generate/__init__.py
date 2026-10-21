"""Generation and annotation layer: everything that calls a model lives here.

Outputs are written as pinned runs (with a manifest): synthetic data under data/generated/<dataset>/<run>/,
relabelled real data (PROACT) under data/derived/<dataset>/<run>/; the
ordinary step-1 converters in ingest/convert/ turn them into records. Converters never call a model,
so rebuilding never spends money or changes labels. See generate/README.md.
"""
