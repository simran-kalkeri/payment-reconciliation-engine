import json
import time
from collections import Counter
from contextlib import contextmanager
from datetime import date

from psycopg import OperationalError
from sqlalchemy.exc import DBAPIError

from .contracts import InvalidRow, normalize, scope_id
from .db import digest, event, operation, query


def fingerprint(row):
    return digest({key: value.isoformat() if isinstance(value, date) else value for key, value in row.items()})


def load_row(conn, row):
    data = normalize(row.kind, row.source, json.loads(row.payload), row.date_format)
    signature = fingerprint(data)
    canonical = query(conn, """
        INSERT INTO canonical(kind,source,external_id,merchant,account,reference,currency,gross,net,fee,
                              business_date,deadline_at,available_at,fingerprint)
        VALUES (:kind,:source,:external_id,:merchant,:account,:reference,:currency,:gross,:net,:fee,
                :business_date,:deadline_at,:available_at,:fingerprint)
        ON CONFLICT (kind,source,external_id) DO NOTHING RETURNING id
    """, **data, fingerprint=signature).scalar_one_or_none()
    if canonical is not None:
        return canonical
    canonical, prior = query(conn, """
        SELECT id,fingerprint FROM canonical WHERE kind=:kind AND source=:source AND external_id=:external_id
    """, kind=data["kind"], source=data["source"], external_id=data["external_id"]).one()
    if prior != signature:
        raise InvalidRow("identity_conflict", "Source ID was previously accepted with different canonical values")
    return canonical


def batch(db, worker, size, file_ids=None, *, on_claim=None, before_commit=None, after_commit=None, run_id=None):
    counts = Counter()
    with db.begin() as conn:
        claimed = query(conn, """
            SELECT s.*,f.source,f.kind,f.date_format FROM staged_rows s JOIN input_files f ON f.id=s.file_id
            WHERE s.status='pending' AND f.status='staged'
              AND (CAST(:files AS bigint[]) IS NULL OR f.id=ANY(CAST(:files AS bigint[])))
            ORDER BY s.file_id,s.row_number LIMIT :size FOR UPDATE OF s SKIP LOCKED
        """, size=size, files=file_ids).all()
        if claimed and on_claim:
            on_claim(claimed)
        for row in claimed:
            outcome = dict(status="accepted", canonical=None, code=None, reason=None)
            try:
                outcome["canonical"] = load_row(conn, row)
            except InvalidRow as exc:
                outcome.update(status="rejected", code=exc.code, reason=str(exc))
                event("normalize", run_id=run_id, file_id=row.file_id, row_number=row.row_number, error=exc.code)
            query(conn, """
                UPDATE staged_rows SET status=:status,canonical_id=:canonical,rejection_code=:code,
                  rejection_reason=:reason,worker=:worker,attempts=attempts+1,processed_at=clock_timestamp()
                WHERE file_id=:file AND row_number=:row
            """, file=row.file_id, row=row.row_number, worker=worker, **outcome)
            counts[outcome["status"]] += 1
        if claimed and before_commit:
            before_commit()
    if claimed and after_commit:
        after_commit()
    return counts


def retry_db(call, attempts=4, pause=0.25):
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except DBAPIError as exc:
            code = getattr(exc.orig, "sqlstate", None)
            if not (exc.connection_invalidated or code in {"40001", "40P01", "57P01", "57P02", "57P03"}
                    or isinstance(exc.orig, OperationalError) and
                    (not code or code.startswith("08"))):
                raise
            event("worker", attempt=attempt, error=code or "database_unavailable")
            if attempt == attempts:
                raise
            time.sleep(pause * 2 ** (attempt - 1))


def work(db, worker="local", size=250, file_ids=None, watch=False, *, progress=None):
    scope_id(worker)
    if size < 1:
        raise ValueError("Batch size must be positive")
    with retrying_operation(db, worker) as run:
        counts = Counter()
        next_heartbeat = time.monotonic() + 5
        while True:
            processed = retry_db(lambda: batch(db, worker, size, file_ids, run_id=run))
            counts.update(processed)
            if processed and progress:
                progress(dict(counts))
            if time.monotonic() >= next_heartbeat:
                retry_db(lambda: heartbeat(db, run))
                next_heartbeat = time.monotonic() + 5
            if not processed:
                if not watch:
                    return dict(counts)
                time.sleep(1)


def heartbeat(db, run):
    with db.begin() as conn:
        query(conn, "UPDATE operations SET heartbeat_at=clock_timestamp() WHERE id=:run", run=run)


@contextmanager
def retrying_operation(db, worker):
    entry = None
    # An unsuccessful generator context cannot be entered again.
    def enter():
        nonlocal entry
        entry = operation(db, "worker", worker=worker)
        return entry.__enter__()

    run = retry_db(enter)
    try:
        yield run
    except BaseException as exc:
        if not entry.__exit__(type(exc), exc, exc.__traceback__):
            raise
    else:
        entry.__exit__(None, None, None)


def verify_staged_replay(db, file_ids, size=250):
    """Re-execute normalization and identity writes for accepted staged evidence."""
    checked = 0
    for file_id in sorted(set(file_ids)):
        cursor = 0
        while True:
            with db.begin() as conn:
                rows = query(conn, """
                    SELECT s.*,f.source,f.kind,f.date_format FROM staged_rows s
                    JOIN input_files f ON f.id=s.file_id WHERE s.file_id=:file AND s.row_number>:cursor
                    AND s.status IN ('accepted','rejected') AND f.status='staged'
                    ORDER BY s.row_number LIMIT :size
                """, file=file_id, cursor=cursor, size=size).all()
                if not rows:
                    break
                for row in rows:
                    try:
                        canonical = load_row(conn, row)
                    except InvalidRow as exc:
                        if row.status != "rejected" or exc.code != row.rejection_code:
                            raise
                    else:
                        if canonical != row.canonical_id:
                            raise RuntimeError("Staged replay changed the canonical identity")
                cursor = rows[-1].row_number
                checked += len(rows)
                # This command verifies identity writes without publishing any new data.
                conn.rollback()
    return checked
