"""Logging setup shared by every service entrypoint.

Why: with 5 processes writing logs, you need one format you can grep/ship. JSON mode
emits one object per line (with session_id etc. when bound) for log aggregators.
"""

import sys

from loguru import logger

from app.config import Settings


def setup_logging(settings: Settings, service: str) -> None:
    logger.remove()
    logger.configure(extra={"service": service})
    if settings.log_format == "json":
        logger.add(sys.stderr, level=settings.log_level, serialize=True)
    else:
        logger.add(
            sys.stderr,
            level=settings.log_level,
            format="{time:HH:mm:ss.SSS} | {level:<7} | {extra[service]} | {message}",
        )
