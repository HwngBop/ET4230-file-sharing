"""Structured transfer logging to stderr and a rotating JSON Lines file."""

import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler


class EventFormatter(logging.Formatter):
    def format(self, record):
        event = {
            "timestamp": datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="seconds"),
            "client_ip": None,
            "client_port": None,
            "command": None,
            "filename": None,
            "file_size": None,
            "status": None,
        }
        event.update(getattr(record, "event", {}))
        event["message"] = record.getMessage()
        return json.dumps(event, ensure_ascii=True)


def configure_logging(log_file):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("file_server")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8"),
    ]
    for handler in handlers:
        handler.setFormatter(EventFormatter())
        logger.addHandler(handler)
    return logger
