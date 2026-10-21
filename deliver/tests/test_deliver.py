"""Tests for delivery to Jev: selection, packaging, the placeholder client and a dry-run delivery."""
import json

import pytest

from deliver import client, delivery, package, selection
from ingest.assembly import jev_format


def _write(path, rows):
    """Write rows as JSONL.

    Args:
        path: Target file.
        rows: Rows to write.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def jev_dir(monkeypatch, tmp_path):
    """A small data/jev with one split of three traces (real, relabelled real, synthetic).

    Args:
        monkeypatch: pytest's monkeypatch fixture.
        tmp_path: pytest's temporary directory.

    Returns:
        The temporary data/jev folder.
    """
    root = tmp_path / "jev"
    kinds = [("t1", "toucan", "real", "ALLOW"), ("t2", "atbench_steps", "relabelled_real", "BLOCK"),
             ("t3", "gen_inject", "synthetic", "BLOCK")]
    _write(root / "train" / "index.jsonl", [{"trace_id": t, "dataset": d, "data_kind": k, "decision": dec,
                                             "record_id": f"{d}:x"} for t, d, k, dec in kinds])
    _write(root / "train" / "events.jsonl", [{"trace_id": t, "event_id": f"{t}-e{i}", "schema": jev_format.SCHEMA}
                                             for t, *_ in kinds for i in range(2)])
    _write(root / "train" / "findings.jsonl", [{"trace_id": t, "schema": jev_format.FINDING_SCHEMA, "decision": dec.lower()}
                                               for t, _, _, dec in kinds])
    (root / "manifest.json").write_text(json.dumps({"build_fingerprint": "fp", "input_schema": jev_format.SCHEMA,
                                                    "finding_schema": jev_format.FINDING_SCHEMA}), encoding="utf-8")
    for module in (selection, package, delivery):
        monkeypatch.setattr(module, "JEV", root)
    monkeypatch.setattr(delivery, "build_fingerprint", lambda: "fp")
    monkeypatch.setattr(delivery, "ROOT", tmp_path)
    return root


def test_selection_by_kind_and_dataset(jev_dir):
    """Kinds, include and exclude lists pick the right traces.

    Args:
        jev_dir: The temporary data/jev_format.

    Raises:
        AssertionError: If the wrong traces are selected.
    """
    pick = lambda **kw: [r["trace_id"] for r in selection.select(selection.Selection(splits=("train",), **kw))["train"]]  # noqa: E731
    assert pick(kinds=("real", "relabelled_real", "synthetic")) == ["t1", "t2", "t3"]
    assert pick(kinds=("real", "relabelled_real")) == ["t1", "t2"]
    assert pick(kinds=("synthetic",)) == ["t3"]
    assert pick(kinds=("real", "relabelled_real", "synthetic"), exclude=("toucan",)) == ["t2", "t3"]
    assert pick(kinds=("real", "relabelled_real", "synthetic"), include=("gen_inject",)) == ["t3"]
    with pytest.raises(ValueError):
        selection.Selection(splits=("train",), kinds=("made_up",))


def test_packaging_keeps_only_jev_formats(jev_dir):
    """Items carry events and the expected finding only; local fields never leave.

    Args:
        jev_dir: The temporary data/jev_format.

    Raises:
        AssertionError: If an item is malformed or leaks a local field.
    """
    items = package.items("train", ["t2", "t1"])
    assert [i["trace_id"] for i in items] == ["t2", "t1"] and len(items[0]["events"]) == 2
    assert items[0]["expected_finding"]["schema"] == jev_format.FINDING_SCHEMA
    body = json.dumps(package.request_body("train", items))
    assert "record_id" not in body and "data_kind" not in body and "atbench" not in body
    assert [len(b) for b in package.batches(list(range(5)), 2)] == [2, 2, 1]
    with pytest.raises(ValueError):
        package.items("train", ["missing"])


def test_dry_run_delivery_writes_requests_and_sends_nothing(jev_dir, monkeypatch):
    """A dry run writes batch files, a local index and a manifest, and never opens a connection.

    Args:
        jev_dir: The temporary data/jev_format.
        monkeypatch: pytest's monkeypatch fixture.

    Raises:
        AssertionError: If something is sent or a file is missing.
    """
    monkeypatch.setattr(client.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network used in a dry run"))
    manifest = delivery.run("r1", selection.Selection(splits=("train",), kinds=("real", "relabelled_real")), dry_run=True)
    folder = jev_dir.parent / selection.deliver_config()["output_dir"] / "r1"
    assert manifest["sent"]["train"]["traces"] == 2 and manifest["dry_run"] is True
    assert (folder / "train" / "batch-0001.json").exists() and (folder / "manifest.json").exists()
    assert [json.loads(line)["trace_id"] for line in open(folder / "selected_index.jsonl")] == ["t1", "t2"]


def test_stale_build_is_refused(jev_dir, monkeypatch):
    """Delivery refuses data/jev built from other config or code.

    Args:
        jev_dir: The temporary data/jev_format.
        monkeypatch: pytest's monkeypatch fixture.

    Raises:
        AssertionError: If a stale build is delivered.
    """
    monkeypatch.setattr(delivery, "build_fingerprint", lambda: "changed")
    with pytest.raises(delivery.StaleBuild):
        delivery.run("r2", dry_run=True)


def test_client_sends_with_auth_header(monkeypatch):
    """A real send POSTs JSON with the configured auth header; a missing key is an error.

    Args:
        monkeypatch: pytest's monkeypatch fixture.

    Raises:
        AssertionError: If the request is malformed.
    """
    api = {"endpoint": "https://jev_format.invalid/x", "api_key_env": "JEV_TEST_KEY", "auth_header": "Authorization",
           "auth_scheme": "Bearer", "timeout_seconds": 5, "dry_run": False}
    seen = {}

    class Reply:
        """Fake HTTP response."""
        status = 200

        def read(self):
            """Return the body.

            Returns:
                Bytes of a JSON reply.
            """
            return b'{"accepted": 1}'

        def __enter__(self):
            """Enter the context.

            Returns:
                self.
            """
            return self

        def __exit__(self, *exc):
            """Leave the context.

            Args:
                *exc: Exception info.

            Returns:
                False.
            """
            return False

    def fake_urlopen(request, timeout):
        """Capture the request.

        Args:
            request: The urllib request.
            timeout: Timeout in seconds.

        Returns:
            A fake reply.
        """
        seen.update(url=request.full_url, auth=request.get_header("Authorization"), body=json.loads(request.data))
        return Reply()

    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.delenv("JEV_TEST_KEY", raising=False)
    with pytest.raises(client.JevError):
        client.JevClient(api).send({"split": "train", "traces": []})
    monkeypatch.setenv("JEV_TEST_KEY", "k123")
    assert client.JevClient(api).send({"split": "train", "traces": [1]}) == {"accepted": 1}
    assert seen["auth"] == "Bearer k123" and seen["body"]["split"] == "train"


def test_threat_categories_only_on_block():
    """Failure modes map to threat categories on blocked traces; allowed traces carry none.

    Raises:
        AssertionError: If categories are wrong.
    """
    assert jev_format.threat_categories([16, 22, "principal_misuse", 99]) == ["cross_domain_prompt_injection",
                                                                      "excessive_agency", "principal_misuse"]
    trace = {"trace_id": "t", "target_event_id": "t-e1",
             "expected": [{"event_id": "t-e1", "decision": "allow", "source": "decision", "target": "planned_action"}]}
    rec = {"labels": {"failure_modes": [16]}}
    assert jev_format.to_finding(rec, trace)["threat_categories"] == []
    trace["expected"][0]["decision"] = "block"
    assert jev_format.to_finding(rec, trace)["threat_categories"] == ["cross_domain_prompt_injection"]
