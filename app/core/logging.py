import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .masking import mask_sensitive


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "run_id"):
            payload["run_id"] = record.run_id
        if hasattr(record, "thread_id"):
            payload["thread_id"] = record.thread_id
        if hasattr(record, "agent"):
            payload["agent"] = record.agent
        if hasattr(record, "payload"):
            payload["payload"] = mask_sensitive(record.payload)
        return json.dumps(payload, ensure_ascii=True)


def get_logger(name: str = "loan_journey") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_event(
    logger: logging.Logger,
    event: str,
    message: str,
    run_id: str,
    thread_id: str,
    agent: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    level: int = logging.INFO,
) -> None:
    logger.log(
        level,
        message,
        extra={
            "event": event,
            "run_id": run_id,
            "thread_id": thread_id,
            "agent": agent,
            "payload": payload or {},
        },
    )
