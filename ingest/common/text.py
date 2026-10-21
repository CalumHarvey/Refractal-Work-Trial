"""Text normalisation and hashing shared by every converter, so keys line up across datasets."""
import hashlib
import json
import re

_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Normalise text for hashing: lowercase, trim and collapse whitespace.

    Args:
        text: Any text.

    Returns:
        The normalised text (the mappings' `normalise`).
    """
    return _WS.sub(" ", text.strip().lower())


def sha1_12(text: str) -> str:
    """Short SHA-1 of a string.

    Args:
        text: Text to hash, used as-is (not normalised).

    Returns:
        The first 12 hex characters of its SHA-1.
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def task_key(namespace: str, instruction: str) -> str:
    """Build the cross-dataset task key from an instruction.

    The same function is used for every dataset, so the same task reached through different
    datasets gets the same key and lands in the same split.

    Args:
        namespace: Key prefix, e.g. "agentdojo:banking".
        instruction: The user's instruction text.

    Returns:
        "<namespace>:instr:<first 12 hex of sha1(normalise(instruction))>".
    """
    return f"{namespace}:instr:{sha1_12(normalise(instruction))}"


def content_hash(text: str) -> str:
    """Hash text for deduplication across datasets.

    Args:
        text: Any text.

    Returns:
        The full SHA-1 hex digest of the normalised text.
    """
    return hashlib.sha1(normalise(text).encode("utf-8")).hexdigest()


def unquote(text: str) -> str:
    """Unwrap a string that was JSON-encoded inside a string.

    Some sources JSON-encode text a second time, so the stored value is a quoted string with
    escaped inner quotes; this removes one level of encoding.

    Args:
        text: Possibly quoted text.

    Returns:
        The decoded string if `text` is a JSON string literal, otherwise `text` unchanged.
    """
    s = text.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        try:
            value = json.loads(s)
            if isinstance(value, str):
                return value
        except json.JSONDecodeError:
            pass
    return text
