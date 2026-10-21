"""Deterministic output: records, rejects, report, samples and manifest for one dataset run.

Layout: one folder per dataset, `data/processed/<dataset>/`, holding only the latest run. The
versions that produced it are recorded in its manifest.json (and in every record), not in the
path. A run is written to `<dataset>.tmp/` and swapped in only when complete, so a failed run
leaves the previous output untouched.
"""
import hashlib
import json
import os
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .paths import PROCESSED, ROOT, mappings_version, schema_version

SAMPLES_PER_RULE = 20


def dumps(obj) -> str:
    """Serialise an object as compact JSON with sorted keys.

    Identical objects always give identical bytes, which keeps records.jsonl deterministic.

    Args:
        obj: Any JSON-serialisable value.

    Returns:
        The JSON text, without whitespace between separators.
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def code_fingerprint(exclude: tuple[str, ...] = ("assembly", "build.py", "tests")) -> str:
    """Fingerprint the converter code that produced an output.

    The project is not a git repository, so the processed manifest records a hash of the
    `ingest/` sources instead of a commit id. Step-2 code (ingest/assembly/, ingest/build.py) and tests are
    excluded by default, so editing it does not mark step-1 outputs stale.

    Args:
        exclude: Paths under ingest/ (first path part) to leave out; pass () to hash everything.

    Returns:
        The first 16 hex characters of a SHA-256 over every included `ingest/**/*.py` path and its bytes.
    """
    h = hashlib.sha256()
    for p in sorted((ROOT / "ingest").rglob("*.py")):
        if "__pycache__" in p.parts or p.relative_to(ROOT / "ingest").parts[0] in exclude:
            continue
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def manifest_path(dataset: str) -> Path:
    """Locate a dataset's processed manifest.

    Args:
        dataset: Dataset name, e.g. "atbench".

    Returns:
        `data/processed/<dataset>/manifest.json` (it may not exist yet).
    """
    return PROCESSED / dataset / "manifest.json"


def swap_in(staging: Path, final: Path) -> None:
    """Replace `final` with the completed `staging` folder.

    The old folder is first renamed aside, then the new one renamed into place, then the old one
    deleted, so at every moment either the old or the new output exists in full.

    Args:
        staging: The completed `<dataset>.tmp/` folder.
        final: The dataset's processed folder.

    Returns:
        None.
    """
    previous = final.with_name(final.name + ".old")
    if previous.exists():
        shutil.rmtree(previous)
    if final.exists():
        os.replace(final, previous)
    os.replace(staging, final)
    if previous.exists():
        shutil.rmtree(previous)


class Output:
    """Collects one dataset run's records, rejects and samples, then writes the processed folder.

    Attributes:
        final: The dataset's processed folder, `data/processed/<dataset>/`.
        dir: The staging folder files are written to, `data/processed/<dataset>.tmp/`.
        records: Valid records, written to records.jsonl.
        rejects: `{"original_id", "reasons"}` entries, written to rejects.jsonl.
        samples: Up to SAMPLES_PER_RULE records per rule id, written to samples/<rule>.jsonl.
    """

    def __init__(self, dataset: str):
        """Prepare an empty staging folder for one dataset run.

        The existing output is not touched until `write` completes. Leftovers of an interrupted run
        (`<dataset>.tmp/`, `<dataset>.old/`) are cleared first; if only `.old` survived an
        interrupted swap, it is restored as the dataset's output before anything else happens.

        Args:
            dataset: Dataset name, e.g. "atbench".
        """
        self.final: Path = PROCESSED / dataset
        self.dir: Path = PROCESSED / f"{dataset}.tmp"
        previous = PROCESSED / f"{dataset}.old"
        if previous.exists():
            if self.final.exists():
                shutil.rmtree(previous)
            else:
                os.replace(previous, self.final)  # an interrupted swap: put the last good output back
        if self.dir.exists():
            shutil.rmtree(self.dir)
        (self.dir / "samples").mkdir(parents=True)
        self.records: list[dict] = []
        self.rejects: list[dict] = []
        self.samples: dict[str, list[dict]] = defaultdict(list)

    def add(self, rec: dict, rule_ids: list[str]) -> None:
        """Keep a valid record and use it as a sample for the rules that fired on it.

        Args:
            rec: A built record that passed validation.
            rule_ids: Ids of the rules that set labels on it (see `run.rules_fired`); the record is
                kept as a sample for each rule that has fewer than SAMPLES_PER_RULE samples.

        Returns:
            None.
        """
        self.records.append(rec)
        for rid in rule_ids:
            if len(self.samples[rid]) < SAMPLES_PER_RULE:
                self.samples[rid].append(rec)

    def reject(self, original_id: str, reasons: list[str]) -> None:
        """Record a raw item that could not become a valid record.

        Args:
            original_id: The item's id in the raw dataset.
            reasons: Every conversion or validation problem found.

        Returns:
            None.
        """
        self.rejects.append({"original_id": original_id, "reasons": reasons})

    def write(self, report: dict, raw_manifest: dict) -> None:
        """Write every output file for the run, then swap the result into place.

        Writes records.jsonl (sorted by record_id), rejects.jsonl, samples/<rule>.jsonl,
        report.json and manifest.json (raw source and checksums, versions, code fingerprint,
        counts and the SHA-256 of records.jsonl) to the staging folder, and only then replaces
        `data/processed/<dataset>/` with it.

        Args:
            report: The run report produced by `run.run`.
            raw_manifest: The raw snapshot's manifest.json, parsed.

        Returns:
            None.
        """
        self.records.sort(key=lambda r: r["record_id"])
        with open(self.dir / "records.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for rec in self.records:
                f.write(dumps(rec) + "\n")
        with open(self.dir / "rejects.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for rej in sorted(self.rejects, key=lambda r: r["original_id"]):
                f.write(dumps(rej) + "\n")
        for rid, recs in sorted(self.samples.items()):
            with open(self.dir / "samples" / f"{rid}.jsonl", "w", encoding="utf-8", newline="\n") as f:
                for rec in recs:
                    f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        (self.dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        records_sha = hashlib.sha256((self.dir / "records.jsonl").read_bytes()).hexdigest()
        manifest = {
            "dataset": raw_manifest["dataset"],
            "raw_source": raw_manifest["source"],
            "raw_revision": raw_manifest["revision"],
            "raw_files": raw_manifest["files"],
            "schema_version": schema_version(),
            "mappings_version": mappings_version(),
            "code_fingerprint": code_fingerprint(),
            "records": len(self.records),
            "rejects": len(self.rejects),
            "records_sha256": records_sha,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (self.dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        swap_in(self.dir, self.final)
        self.dir = self.final
