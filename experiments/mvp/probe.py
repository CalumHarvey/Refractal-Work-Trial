"""A small, fixed probe of data value: hashed n-gram features + weighted logistic regression (numpy).

The probe is deliberately simple and identical across arms, so differences between arms measure the
training data, not the model. Features come only from `input` (what production sees): the planned
action (tool name, argument names and values), the user request, and the most recent messages,
each in its own namespace so the probe can tell "the action mentions X" from "the context mentions X".
"""
import hashlib
import json
import re

import numpy as np

DIM = 2 ** 18
_TOKEN = re.compile(r"[a-z0-9_@.\-]+")


def _tokens(text: str, limit: int = 400) -> list[str]:
    """Lower-case word tokens of a text.

    Args:
        text: Any text.
        limit: Maximum number of tokens kept.

    Returns:
        Tokens, at most `limit`.
    """
    return _TOKEN.findall(text.lower())[:limit]


def _ngrams(tokens: list[str]) -> list[str]:
    """Unigrams and bigrams.

    Args:
        tokens: Tokens.

    Returns:
        The tokens followed by adjacent pairs joined with "_".
    """
    return tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]


def features(inp: dict, tool_name_only: bool = False) -> list[str]:
    """Turn a record's input into namespaced string features.

    Args:
        inp: The record's `input`.
        tool_name_only: Only the planned tool's name (the shortcut baseline).

    Returns:
        Feature strings.
    """
    action = inp.get("planned_action") or {}
    name = action.get("tool_name", "")
    if tool_name_only:
        return [f"tool={name.lower()}"]
    out = [f"tool={name.lower()}"]
    out += [f"argkey={k.lower()}" for k in (action.get("arguments") or {})]
    out += [f"act:{t}" for t in _ngrams(_tokens(json.dumps(action.get("arguments") or {}, ensure_ascii=False)))]
    out += [f"user:{t}" for t in _ngrams(_tokens(inp.get("user_prompt") or "", 120))]
    for i, m in enumerate(reversed(inp.get("messages") or [])):
        if i >= 3:
            break
        body = m.get("content") or ""
        if m.get("tool_call"):
            body += " " + json.dumps(m["tool_call"], ensure_ascii=False)
        out += [f"ctx{i}:{m['role']}:{t}" for t in _tokens(body, 300)]
    return out


def _index(feature: str) -> int:
    """Hash a feature string into the feature space.

    Args:
        feature: A feature string.

    Returns:
        An index in [0, DIM).
    """
    return int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "little") % DIM


class SparseMatrix:
    """Binary sparse rows in CSR form (indptr / indices), enough for logistic regression.

    Attributes:
        indptr: Row boundaries into `indices`.
        indices: Column indices of the active features.
        rows: Number of rows.
    """

    def __init__(self, feature_lists: list[list[str]]):
        """Hash and store feature lists.

        Args:
            feature_lists: One list of feature strings per row.
        """
        indptr, indices = [0], []
        for feats in feature_lists:
            cols = sorted({_index(f) for f in feats})
            indices.extend(cols)
            indptr.append(len(indices))
        self.indptr = np.asarray(indptr, dtype=np.int64)
        self.indices = np.asarray(indices, dtype=np.int64)
        self.rows = len(feature_lists)
        lengths = np.diff(self.indptr)
        self._row_of = np.repeat(np.arange(self.rows), lengths)
        self._scale = 1.0 / np.sqrt(np.maximum(lengths, 1))  # rows normalised to unit length

    def dot(self, w: np.ndarray) -> np.ndarray:
        """Compute X @ w.

        Args:
            w: Weight vector of length DIM.

        Returns:
            One score per row.
        """
        out = np.zeros(self.rows)
        np.add.at(out, self._row_of, w[self.indices])
        return out * self._scale

    def t_dot(self, r: np.ndarray) -> np.ndarray:
        """Compute X.T @ r.

        Args:
            r: One value per row.

        Returns:
            A vector of length DIM.
        """
        out = np.zeros(DIM)
        np.add.at(out, self.indices, (r * self._scale)[self._row_of])
        return out


class LogisticProbe:
    """L2-regularised logistic regression trained with full-batch Adam.

    Attributes:
        w: Feature weights.
        b: Bias.
    """

    def __init__(self, l2: float = 1e-4, epochs: int = 60, lr: float = 0.05):
        """Configure the probe.

        Args:
            l2: L2 penalty.
            epochs: Full-batch steps.
            lr: Adam learning rate.
        """
        self.l2, self.epochs, self.lr = l2, epochs, lr
        self.w, self.b = np.zeros(DIM), 0.0

    def fit(self, X: SparseMatrix, y: np.ndarray, weights: np.ndarray) -> "LogisticProbe":
        """Fit on weighted examples.

        Args:
            X: Features.
            y: 0 / 1 targets.
            weights: Per-example weights.

        Returns:
            self.
        """
        m_w, v_w, m_b, v_b = np.zeros(DIM), np.zeros(DIM), 0.0, 0.0
        total = weights.sum()
        for t in range(1, self.epochs + 1):
            p = 1.0 / (1.0 + np.exp(-(X.dot(self.w) + self.b)))
            r = weights * (p - y) / total
            g_w, g_b = X.t_dot(r) + self.l2 * self.w, r.sum()
            m_w, v_w = 0.9 * m_w + 0.1 * g_w, 0.999 * v_w + 0.001 * g_w ** 2
            m_b, v_b = 0.9 * m_b + 0.1 * g_b, 0.999 * v_b + 0.001 * g_b ** 2
            corr1, corr2 = 1 - 0.9 ** t, 1 - 0.999 ** t
            self.w -= self.lr * (m_w / corr1) / (np.sqrt(v_w / corr2) + 1e-8)
            self.b -= self.lr * (m_b / corr1) / (np.sqrt(v_b / corr2) + 1e-8)
        return self

    def predict_proba(self, X: SparseMatrix) -> np.ndarray:
        """Probability of BLOCK.

        Args:
            X: Features.

        Returns:
            One probability per row.
        """
        return 1.0 / (1.0 + np.exp(-(X.dot(self.w) + self.b)))
