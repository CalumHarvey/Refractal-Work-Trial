"""Metrics for BLOCK-vs-ALLOW predictions."""
import numpy as np


def auroc(y: np.ndarray, p: np.ndarray) -> float | None:
    """Area under the ROC curve (rank formulation, ties averaged).

    Args:
        y: 0 / 1 targets.
        p: Scores.

    Returns:
        AUROC, or None if only one class is present.
    """
    pos, neg = int(y.sum()), int(len(y) - y.sum())
    if not pos or not neg:
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sorted_p = p[order]
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def summarise(y: np.ndarray, p: np.ndarray, threshold: float = 0.5) -> dict:
    """Standard metrics at a threshold.

    Args:
        y: 0 / 1 targets (1 = BLOCK).
        p: Probabilities of BLOCK.
        threshold: Decision threshold.

    Returns:
        n, positives, accuracy, BLOCK precision / recall / F1, false-positive rate on ALLOW, and AUROC
        (None where undefined).
    """
    pred = p >= threshold
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if recall is not None else None)
    return {"n": int(len(y)), "positives": int(y.sum()), "accuracy": (tp + tn) / len(y) if len(y) else None,
            "precision": precision, "recall": recall, "f1": f1,
            "fpr": fp / (fp + tn) if fp + tn else None, "auroc": auroc(y, p)}


def mean_sd(values: list) -> dict:
    """Mean and standard deviation of the defined values.

    Args:
        values: Numbers or None.

    Returns:
        `{"mean", "sd", "n"}` (None when no value is defined).
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return {"mean": None, "sd": None, "n": 0}
    return {"mean": float(np.mean(vals)), "sd": float(np.std(vals)), "n": len(vals)}
