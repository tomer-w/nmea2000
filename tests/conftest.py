# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring
"""Shared pytest configuration for this suite."""

import logging
import sys
import time

import pytest

from nmea2000 import device as device_module

# How much faster than real time the address-claim clock runs in tests
CLAIM_CLOCK_SPEEDUP = 100


@pytest.fixture
def fast_claim_clock(monkeypatch):
    """Run N2KDevice's address-claim clock 100 times faster than real time.

    Claiming takes the standard's 1 s scan plus 250 ms settle; this makes
    it about 13 ms, without changing what the claimer does.
    """
    start = time.monotonic_ns()

    def now_ms() -> int:
        elapsed = time.monotonic_ns() - start
        return (start + elapsed * CLAIM_CLOCK_SPEEDUP) // 1_000_000

    monkeypatch.setattr(device_module, "_now_ms", now_ms)


@pytest.fixture(autouse=True, scope="session")
def configure_pytest_logging():
    """Configure root and nmea2000 loggers to emit debug output to stdout."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)
    # Explicitly set the 'nmea2000' logger and all its children to DEBUG
    nmea_logger = logging.getLogger("nmea2000")
    nmea_logger.setLevel(logging.DEBUG)
    for name, logger in logging.root.manager.loggerDict.items():  # pylint: disable=no-member
        if name.startswith("nmea2000.") and isinstance(logger, logging.Logger):
            logger.setLevel(logging.DEBUG)
            # Ensure each logger has a StreamHandler to sys.stdout
            if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
                handler = logging.StreamHandler(sys.stdout)
                handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                    )
                )
                logger.addHandler(handler)
