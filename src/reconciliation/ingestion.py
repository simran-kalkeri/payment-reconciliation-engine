import csv
from itertools import islice

from sqlalchemy import text

from .contracts import DATE_FORMATS, FIELDS, SCHEMA_VERSION, scope_id
from .db import event, json_text, operation, query


class InvalidFile(ValueError):
    pass


def extract(path, kind):
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        header = next(reader, [])
        if len(header) != len(FIELDS[kind]) or set(header) != set(FIELDS[kind]):
            raise InvalidFile("Header must contain exactly the required columns")
        for number, cells in enumerate(reader, 1):
            yield {"row": number, "payload": json_text({
                "cells": dict(zip(header, cells)),
                "extra": cells[len(header):],
            })}


def ingest(db, storage, path, kind, source, date_format="iso", batch_size=500, *, after_batch=None, expected_sha=None):
    scope_id(source)
    if kind not in FIELDS or date_format not in DATE_FORMATS or batch_size < 1:
        raise ValueError("Invalid file kind, date format, or batch size")
    sha, key = storage.capture(path)
    if expected_sha is not None and sha != expected_sha:
        raise InvalidFile("Captured file does not match its manifest hash")
    with db.begin() as conn:
        identity = dict(source=source, kind=kind, date_format=date_format, sha=sha, schema=SCHEMA_VERSION)
        query(conn, """
            INSERT INTO input_files(source, kind, schema_version, date_format, sha256, storage_key)
            VALUES (:source,:kind,:schema,:date_format,:sha,:key) ON CONFLICT DO NOTHING
        """, **identity, key=key)
        file_id, status = query(conn, """
            SELECT id,status FROM input_files
            WHERE source=:source AND kind=:kind AND schema_version=:schema
              AND date_format=:date_format AND sha256=:sha
        """, **identity).one()
    if status == "staged":
        return file_id
    if status == "rejected":
        raise InvalidFile(f"File {file_id} was previously rejected")

    with operation(db, "ingest", file_id=file_id) as run:
        try:
            rows = extract(storage.locate(key), kind)
            count = 0
            while batch := list(islice(rows, batch_size)):
                with db.begin() as conn:
                    status = query(conn, "SELECT status FROM input_files WHERE id=:id FOR UPDATE",
                                   id=file_id).scalar_one()
                    if status == "staged":
                        return file_id
                    if status != "loading":
                        raise InvalidFile(f"File {file_id} was rejected during ingestion")
                    conn.execute(text("""
                        INSERT INTO staged_rows(file_id,row_number,payload) VALUES (:file,:row,:payload)
                        ON CONFLICT DO NOTHING
                    """), [{"file": file_id, **row} for row in batch])
                    count = batch[-1]["row"]
                    query(conn, """
                        UPDATE input_files SET row_count=greatest(row_count,:count),updated_at=clock_timestamp()
                        WHERE id=:id
                    """, id=file_id, count=count)
                if after_batch:
                    after_batch()
            with db.begin() as conn:
                query(conn, """
                    UPDATE input_files SET status='staged',row_count=:count,updated_at=clock_timestamp()
                    WHERE id=:id AND status='loading'
                """, id=file_id, count=count)
        except (InvalidFile, csv.Error, UnicodeError) as exc:
            reason = str(exc) if isinstance(exc, InvalidFile) else "Invalid CSV structure or UTF-8 encoding"
            with db.begin() as conn:
                query(conn, """
                    UPDATE input_files SET status='rejected',error=:reason,updated_at=clock_timestamp()
                    WHERE id=:id AND status='loading'
                """, id=file_id, reason=reason)
            event("ingest", run_id=run, file_id=file_id, error="invalid_file")
            raise InvalidFile(f"File {file_id}: {reason}") from exc
    return file_id
