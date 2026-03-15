"""Structured logging helpers for the VoIP application."""

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """Return a named logger with a consistent format.

    The format includes timestamp, logger name, level, and message which
    makes it easy to follow the SIP/RTP flow in console output.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter(
            fmt="%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger
