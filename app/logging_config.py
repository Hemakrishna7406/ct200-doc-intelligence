"""Logging setup."""

from __future__ import annotations

import logging

from app.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # quiet the noisy access logs from uvicorn only if the user asked for it
    logging.getLogger("ct200").setLevel(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    )
