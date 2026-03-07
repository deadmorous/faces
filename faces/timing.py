"""Lightweight performance timing helpers."""

import logging
import time
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger("faces.perf")


@contextmanager
def timed(label: str) -> Generator[None, None, None]:
    """Log elapsed wall-clock time for a labelled block."""
    t0 = time.perf_counter()
    yield
    elapsed = time.perf_counter() - t0
    logger.info("[perf] %s: %.3fs", label, elapsed)
