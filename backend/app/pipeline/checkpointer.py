"""LangGraph checkpoint storage. Checkpoints make runs resumable and enable human-review interrupts.

SQLite for now; a Postgres saver (``langgraph-checkpoint-postgres``) slots in here when the
deployment moves to Postgres.
"""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def open_sqlite_checkpointer(path: Path) -> tuple[SqliteSaver, sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False is safe: SqliteSaver serialises access with its own lock.
    conn = sqlite3.connect(path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver, conn
