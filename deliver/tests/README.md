# deliver/tests/

Tests for delivery to Jev, run against a small temporary `data/jev/`; nothing is sent.

| File | Covers |
| --- | --- |
| `test_deliver.py` | Selection by kind, include and exclude; packaging only Jev formats (no record ids, datasets or kinds leave); batching; a dry run writing request files without opening a connection; refusing a stale build; the client's auth header and a missing key; threat categories only on blocked traces |
