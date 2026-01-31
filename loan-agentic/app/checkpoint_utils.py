import atexit
import sqlite3
from pathlib import Path
from typing import Any, Union

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver


def get_sqlite_checkpointer(path: Union[str, Path], logger: Any = None):
    resolved = Path(path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn_str = f"sqlite:///{resolved.as_posix()}"
    try:
        ctx_or_cp = SqliteSaver.from_conn_string(conn_str)
        # Newer langgraph-checkpoint-sqlite returns a context manager
        if hasattr(ctx_or_cp, "__enter__") and hasattr(ctx_or_cp, "__exit__"):
            cp = ctx_or_cp.__enter__()
            atexit.register(ctx_or_cp.__exit__, None, None, None)
            return cp
        return ctx_or_cp
    except (sqlite3.OperationalError, OSError, ValueError) as exc:
        if logger:
            logger.warning(f"SQLite checkpointer unavailable, using in-memory. Reason: {exc}")
        return InMemorySaver()


def list_checkpoints(checkpointer: Any, thread_id: str):
    return [checkpoint for checkpoint in checkpointer.list(thread_id)]


def load_final_state(checkpointer: Any, thread_id: str):
    checkpoint = checkpointer.get_latest(thread_id)
    return checkpoint.state if checkpoint else {}
