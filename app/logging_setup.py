import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.masking import mask_sensitive


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "run_id"):
            payload["run_id"] = record.run_id
        if hasattr(record, "case_id"):
            payload["case_id"] = record.case_id
        if hasattr(record, "thread_id"):
            payload["thread_id"] = record.thread_id
        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "data"):
            payload["data"] = record.data
        return json.dumps(payload, ensure_ascii=True)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).isoformat()
        run_id = getattr(record, "run_id", "")
        case_id = getattr(record, "case_id", "")
        thread_id = getattr(record, "thread_id", "")
        event = getattr(record, "event", "")
        return f"[{timestamp}] [{record.levelname}] run_id={run_id} case_id={case_id} thread_id={thread_id} event={event} message={record.getMessage()}"


def setup_logger(
    name: str = "loan_agentic",
    run_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    case_id: Optional[str] = None,
    log_dir: str = "runs",
) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    json_formatter = JsonFormatter()

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(json_formatter)
    logger.addHandler(console)

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    if run_id:
        case_prefix = case_id or "case"
        txt_path = Path(log_dir) / f"{case_prefix}_{run_id}.txt"
        jsonl_path = Path(log_dir) / f"{case_prefix}_{run_id}.jsonl"

        text_handler = logging.FileHandler(txt_path, encoding="utf-8")
        text_handler.setFormatter(TextFormatter())
        logger.addHandler(text_handler)

        jsonl_handler = logging.FileHandler(jsonl_path, encoding="utf-8")
        jsonl_handler.setFormatter(json_formatter)
        logger.addHandler(jsonl_handler)

    logger.propagate = False

    if run_id and thread_id:
        logger = logging.LoggerAdapter(logger, {"run_id": run_id, "thread_id": thread_id, "case_id": case_id or ""})
    return logger


def log_event(
    logger: logging.Logger,
    message: str,
    run_id: str,
    thread_id: str,
    event: str,
    case_id: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    safe_data = mask_sensitive(data or {})
    logger.info(
        message,
        extra={
            "run_id": run_id,
            "thread_id": thread_id,
            "case_id": case_id or "",
            "event": event,
            "data": safe_data,
        },
    )
