"""Postgres connection pool. DATABASE_URL (environment or .env) names the database.

The app connects as the database owner, so row-level security (on, with no policies, for every
table) does not apply to it; it only keeps the tables closed to Supabase's public Data API.
"""

import atexit
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from .env import load_env

Conn = psycopg.Connection[DictRow]
_pool: ConnectionPool[Conn] | None = None
_lock = threading.Lock()


def url():
    load_env()
    u = os.environ.get("DATABASE_URL")
    if not u:
        raise SystemExit("DATABASE_URL is not set. Add it to .env; CONTRIBUTING.md says where to find it.")
    return u


def _pool_now() -> ConnectionPool[Conn]:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(
                url(), connection_class=Conn, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=True
            )
        return _pool


@contextmanager
def tx() -> Iterator[Conn]:
    """A pooled connection in a transaction: committed when the block exits, rolled back on error."""
    with _pool_now().connection() as conn:
        yield conn


def reset():
    """Close the pool, so the next call reconnects (tests point DATABASE_URL at a fresh database)."""
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


atexit.register(reset)  # close pool threads before interpreter shutdown, not during it
