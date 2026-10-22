"""Logging for the generation layer: console output plus a log file inside each run folder.

Every module logs under the "generate" logger (`generate.inject`, `generate.proact`, `generate.llm`).
`configure()` sets up the console once (called by `python -m generate` and `python -m pipeline`);
`run_log(folder)` adds a file handler for one run, so each run folder keeps its own `generate.log`.
"""
import logging
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT_LOGGER = "generate"
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"


def configure(level: int = logging.INFO) -> logging.Logger:
    """Send generation logs to the console (stderr), once.

    Args:
        level: Logging level for the console, e.g. logging.INFO or logging.DEBUG.

    Returns:
        The "generate" logger.
    """
    logger = logging.getLogger(ROOT_LOGGER)
    logger.setLevel(logging.DEBUG)
    console = next((h for h in logger.handlers if getattr(h, "_generate_console", False)), None)
    if console is None:
        console = logging.StreamHandler(sys.stderr)
        console._generate_console = True
        console.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))
        logger.addHandler(console)
    console.setLevel(level)
    return logger


@contextmanager
def run_log(folder: Path):
    """Also write every generation log line (DEBUG and up) to `<folder>/generate.log` while the block runs.

    Args:
        folder: The run folder.

    Yields:
        The path of the log file.
    """
    logger = logging.getLogger(ROOT_LOGGER)
    logger.setLevel(logging.DEBUG)
    path = Path(folder) / "generate.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logger.addHandler(handler)
    try:
        yield path
    finally:
        logger.removeHandler(handler)
        handler.close()


def level_from(verbose: bool, quiet: bool) -> int:
    """Map command-line flags to a console level.

    Args:
        verbose: Show per-call detail (cache hits, call times).
        quiet: Show warnings and errors only.

    Returns:
        logging.DEBUG, logging.WARNING or logging.INFO.
    """
    return logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
