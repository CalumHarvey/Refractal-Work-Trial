"""Generation configuration (config/generation.yaml)."""
from functools import lru_cache

import yaml

from ingest.common.paths import GENERATION_CONFIG_FILE


@lru_cache(maxsize=1)
def generation_config() -> dict:
    """Load the generation configuration (cached after the first call).

    Returns:
        The parsed contents of config/generation.yaml.
    """
    return yaml.safe_load(GENERATION_CONFIG_FILE.read_text(encoding="utf-8"))


def model(role: str) -> str:
    """Look up the model configured for a single-model role.

    Args:
        role: A key of `models`, e.g. "generator" or "qc_judge".

    Returns:
        The model name.

    Raises:
        KeyError: If the role is not configured.
    """
    return generation_config()["models"][role]
