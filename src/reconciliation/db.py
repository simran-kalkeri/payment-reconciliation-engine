import hashlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def database_url(*, migration=False):
    load_dotenv()
    url = (os.getenv("RECON_MIGRATION_URL") if migration else None) or os.getenv("RECON_DATABASE_URL")
    if not url or not url.startswith("postgresql+psycopg://"):
        raise ValueError("Set RECON_DATABASE_URL to a postgresql+psycopg:// URL")
    return url


def engine():
    return create_engine(database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 5})


def json_text(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def query(conn, sql, **params):
    return conn.execute(text(sql), params)


def event(stage, **fields):
    print(json_text({"timestamp": datetime.now(UTC).isoformat(), "stage": stage, **fields}),
          file=sys.stderr, flush=True)


@contextmanager
def operation(db, stage, **details):
    with db.begin() as conn:
        run = query(conn, """
            INSERT INTO operations(stage, status, detail) VALUES (:stage, 'running', CAST(:detail AS jsonb))
            RETURNING id
        """, stage=stage, detail=json_text(details)).scalar_one()
    try:
        yield run
    except BaseException as exc:
        event(stage, run_id=run, status="failed", error=type(exc).__name__)
        try:
            finish(db, run, "failed", type(exc).__name__)
        except Exception as log_error:
            event(stage, run_id=run, status="status_write_failed", error=type(log_error).__name__)
        raise
    else:
        finish(db, run, "done", None)
        event(stage, run_id=run, status="done")


def finish(db, run, status, error):
    with db.begin() as conn:
        query(conn, """
            UPDATE operations SET status=:status, error=:error, finished_at=clock_timestamp()
            WHERE id=:run
        """, run=run, status=status, error=error)
