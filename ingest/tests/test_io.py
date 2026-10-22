import json

import pytest

from ingest.common import io

RAW_MANIFEST = {"dataset": "demo", "source": "test", "revision": "abc", "files": []}


@pytest.fixture
def processed(tmp_path, monkeypatch):
    """Fixture: point the processed folder at a temporary directory.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: pytest's monkeypatch fixture.

    Returns:
        The temporary processed folder.
    """
    monkeypatch.setattr(io, "PROCESSED", tmp_path)
    return tmp_path


def _run(records):
    """Write one complete run of the "demo" dataset.

    Args:
        records: Records to write (dicts with a record_id).

    Returns:
        None.
    """
    out = io.Output("demo")
    for rec in records:
        out.add(rec, [])
    out.write({"report": True}, RAW_MANIFEST)


def _ids(folder):
    """Read the record ids in a processed folder.

    Args:
        folder: A dataset's processed folder.

    Returns:
        The record_id of each line in records.jsonl.
    """
    return [json.loads(line)["record_id"] for line in (folder / "records.jsonl").read_text().splitlines()]


def test_run_replaces_previous_output(processed):
    """A second run fully replaces the first, leaving no staging or backup folder.

    Args:
        processed: The temporary processed folder.

    Raises:
        AssertionError: If old files survive or a .tmp/.old folder is left behind.
    """
    _run([{"record_id": "a"}, {"record_id": "b"}])
    (processed / "demo" / "stray.txt").write_text("from an older layout")
    _run([{"record_id": "c"}])
    assert _ids(processed / "demo") == ["c"]
    assert not (processed / "demo" / "stray.txt").exists()
    assert sorted(p.name for p in processed.iterdir()) == ["demo"]


def test_failed_run_keeps_previous_output(processed):
    """A run that never reaches write() leaves the previous output untouched.

    Args:
        processed: The temporary processed folder.

    Raises:
        AssertionError: If the previous records changed.
    """
    _run([{"record_id": "a"}])
    out = io.Output("demo")
    out.add({"record_id": "z"}, [])  # ... then the run crashes before write()
    assert _ids(processed / "demo") == ["a"]


def test_interrupted_swap_is_recovered(processed):
    """If a swap was interrupted after moving the old output aside, the next run restores it first.

    Args:
        processed: The temporary processed folder.

    Raises:
        AssertionError: If the old output is not back in place.
    """
    _run([{"record_id": "a"}])
    (processed / "demo").rename(processed / "demo.old")  # state after an interrupted swap
    io.Output("demo")
    assert _ids(processed / "demo") == ["a"] and not (processed / "demo.old").exists()


def test_retry_io_waits_out_a_transient_lock(monkeypatch):
    """A file briefly locked (EINVAL, as OneDrive causes) is retried; other errors are raised at once.

    Args:
        monkeypatch: pytest's monkeypatch fixture.

    Raises:
        AssertionError: If a transient error is not retried or a real one is swallowed.
    """
    import errno

    import pytest

    from ingest.common import io

    monkeypatch.setattr(io.time, "sleep", lambda s: None)
    calls = []

    def flaky():
        """Fail twice with EINVAL, then succeed.

        Returns:
            "ok" on the third call.

        Raises:
            OSError: On the first two calls.
        """
        calls.append(1)
        if len(calls) < 3:
            raise OSError(errno.EINVAL, "Invalid argument")
        return "ok"

    assert io.retry_io(flaky) == "ok" and len(calls) == 3

    def missing():
        """Fail with a non-transient error.

        Raises:
            FileNotFoundError: Always.
        """
        raise FileNotFoundError(errno.ENOENT, "missing")

    with pytest.raises(FileNotFoundError):
        io.retry_io(missing)


def test_read_jsonl_keeps_unicode_line_separators(tmp_path):
    """A U+2028 inside a JSON string does not split the row (str.splitlines would).

    Args:
        tmp_path: pytest's temporary directory.

    Raises:
        AssertionError: If the row is split.
    """
    from ingest.common import io

    path = tmp_path / "x.jsonl"
    path.write_text(io.dumps({"text": "a\u2028b"}) + "\n" + io.dumps({"n": 2}) + "\n", encoding="utf-8")
    assert io.read_jsonl(path) == [{"text": "a\u2028b"}, {"n": 2}]
