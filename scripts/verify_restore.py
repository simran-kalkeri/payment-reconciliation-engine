"""Verify a restored database and its separately restored content-addressed raw files."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from reconciliation.db import digest, engine, query
from reconciliation.operations import counts
from reconciliation.storage import LocalStore, file_hash


def verify(raw_dir):
    store = LocalStore(raw_dir)
    db = engine()
    checked_rows = 0
    with db.connect() as conn:
        staged = defaultdict(int, query(conn, "SELECT file_id,count(*) FROM staged_rows GROUP BY file_id").all())
        files = query(conn, "SELECT id,sha256,storage_key,row_count,status FROM input_files").all()
        for row in files:
            if file_hash(store.locate(row.storage_key)) != row.sha256 or staged[row.id] != row.row_count:
                raise RuntimeError(f"File {row.id} failed raw hash or staging count verification")
            checked_rows += row.row_count
        snapshots = query(conn, "SELECT id,result_hash,report,evidence FROM results").all()
        for row in snapshots:
            if digest({"report": row.report, **row.evidence}) != row.result_hash:
                raise RuntimeError(f"Result {row.id} failed business hash verification")
        missing_history = query(conn, """
            SELECT count(*) FROM exceptions e
            WHERE NOT EXISTS (SELECT 1 FROM exception_history h WHERE h.exception_id=e.id)
        """).scalar_one()
        if missing_history:
            raise RuntimeError("Restored exceptions are missing audit history")
        pending = query(conn, "SELECT count(*) FROM staged_rows WHERE status='pending'").scalar_one()
        review_summary = [dict(row) for row in query(conn, """
            SELECT review_status, active, count(*) FROM exceptions GROUP BY review_status,active
            ORDER BY review_status,active
        """).mappings()]
    return dict(raw_files_checked=len(files), staged_rows_checked=checked_rows,
                business_hashes_checked=len(snapshots), missing_history=missing_history, pending_rows=pending,
                durable_counts=counts(db), review_states=review_summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_dir", type=Path)
    print(json.dumps(verify(parser.parse_args().raw_dir), indent=2, sort_keys=True))
