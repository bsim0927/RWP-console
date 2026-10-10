"""Test databases: throwaway Postgres databases built from supabase/migrations, on a local server only.

A session template is created once by replaying every migration; each test that asks for the `db`
fixture gets a fresh copy of it, so tests can write freely and never see each other's data.

The server comes from TEST_DATABASE_URL (default: the local Supabase stack, `make db-start`). The
tests refuse any non-local host, so they can never touch the real project, whatever .env says.
"""

import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from sg import db as sgdb

ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"

# Code that reaches the database without the fixture fails fast instead of falling back to the
# DATABASE_URL in .env (sg.env never overrides a variable that is already set).
os.environ["DATABASE_URL"] = "postgresql://no-test-database@127.0.0.1:1/none"


def _url_for(name):
    parts = urlsplit(ADMIN_URL)
    return urlunsplit(parts._replace(path=f"/{name}"))


def _admin():
    host = urlsplit(ADMIN_URL).hostname
    if host not in LOCAL_HOSTS:
        pytest.exit(f"TEST_DATABASE_URL points at {host}; tests only run against a local Postgres", returncode=2)
    try:
        return psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.fail(
            f"No test Postgres at {ADMIN_URL} ({e.__class__.__name__}). Start one with `make db-start` (Docker).",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def _template():
    name = f"rwp_test_tpl_{uuid.uuid4().hex[:8]}"
    with _admin() as a:
        a.execute(f'create database "{name}"')
    try:
        with psycopg.connect(_url_for(name), autocommit=True) as c:
            for m in sorted(MIGRATIONS.glob("*.sql")):
                c.execute(m.read_text())
        yield name
    finally:
        with _admin() as a:
            a.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture
def db(_template, monkeypatch):
    """A fresh database with every migration applied (seed included), wired into sg.db for the test."""
    name = f"rwp_test_{uuid.uuid4().hex[:8]}"
    with _admin() as a:
        a.execute(f'create database "{name}" template "{_template}"')
    monkeypatch.setenv("DATABASE_URL", _url_for(name))
    sgdb.reset()
    try:
        yield _url_for(name)
    finally:
        sgdb.reset()
        with _admin() as a:
            a.execute(f'drop database if exists "{name}" with (force)')
