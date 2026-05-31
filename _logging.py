"""Centralized logging setup for the server and its supervisor.

One RotatingFileHandler writes to server.log for both this project's logger
and uvicorn's. Importing and calling configure() is safe to do multiple times
in the same process (logging.config.dictConfig replaces the prior config).
"""

import logging
import logging.config
from pathlib import Path

_HERE = Path(__file__).parent
LOG_FILE = _HERE / "server.log"

LOG_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_FILE),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "default",
        },
    },
    "loggers": {
        "remote-pc-mcp": {"handlers": ["file"], "level": "INFO", "propagate": False},
        "uvicorn": {"handlers": ["file"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["file"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["file"], "level": "INFO", "propagate": False},
    },
}


def configure() -> None:
    logging.config.dictConfig(LOG_CONFIG)


def get_logger(name: str = "remote-pc-mcp") -> logging.Logger:
    return logging.getLogger(name)
