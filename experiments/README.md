# experiments/

Experiments that measure what the data is worth. These are not candidate production models.

| Folder | Holds |
| --- | --- |
| [`mvp/`](mvp/README.md) | The MVP experiment: arms with and without PROACT and synthetic data, a fixed probe, three evaluation tiers, and pre-registered criteria. Results go to `mvp/results/<timestamp>/` |
| [`tests/`](tests/README.md) | Tests for the experiment code |

Run it with `python -m experiments.mvp.run`, or as the last stage of `python -m pipeline --experiment`.
