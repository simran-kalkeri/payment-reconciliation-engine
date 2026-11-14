from .db import query


def health(db):
    with db.connect() as conn:
        queue = dict(query(conn, """
            SELECT count(*) FILTER (WHERE s.status='pending' AND f.status='staged') AS backlog,
              coalesce(extract(epoch FROM clock_timestamp()-min(s.created_at)
                  FILTER (WHERE s.status='pending' AND f.status='staged'))::bigint,0) AS oldest_pending_seconds,
              count(*) FILTER (WHERE s.status='rejected') AS rejected_rows
            FROM staged_rows s JOIN input_files f ON f.id=s.file_id
        """).mappings().one())
        operations = [dict(row) for row in query(conn, """
            SELECT stage,count(*) FILTER (WHERE status='failed') AS failures,
              count(*) FILTER (WHERE detail->>'outcome'='incomplete') AS incomplete,
              count(*) FILTER (WHERE status='running') AS running,
              extract(epoch FROM max(finished_at-started_at))::bigint AS max_duration_seconds
            FROM operations GROUP BY stage ORDER BY stage
        """).mappings()]
        workers = [dict(row) for row in query(conn, """
            SELECT id,detail->>'worker' AS worker,
              heartbeat_at >= clock_timestamp()-interval '30 seconds' AS live,
              extract(epoch FROM clock_timestamp()-heartbeat_at)::bigint AS heartbeat_age_seconds
            FROM operations WHERE stage='worker' AND status='running' ORDER BY id
        """).mappings()]
        return dict(database="ready", queue=queue, workers=workers, operations=operations)


def file_status(db):
    with db.connect() as conn:
        return [dict(row) for row in query(conn, """
            SELECT f.id,f.kind,f.source,f.sha256,f.status,f.error,f.row_count,
              count(*) FILTER (WHERE s.status='pending') AS pending,
              count(*) FILTER (WHERE s.status='accepted') AS accepted,
              count(*) FILTER (WHERE s.status='rejected') AS rejected
            FROM input_files f LEFT JOIN staged_rows s ON f.id=s.file_id GROUP BY f.id ORDER BY f.id
        """).mappings()]


def counts(db):
    with db.connect() as conn:
        return dict(query(conn, """
            SELECT (SELECT count(*) FROM input_files) AS input_files,
              (SELECT count(*) FROM staged_rows) AS staged_rows,
              (SELECT count(*) FROM canonical) AS canonical,
              (SELECT count(*) FROM results) AS results,
              (SELECT count(*) FROM matches) AS matches,
              (SELECT count(*) FROM exceptions) AS exceptions,
              (SELECT count(*) FROM exception_history) AS history,
              (SELECT count(*) FROM exceptions WHERE review_status='resolved') AS resolved
        """).mappings().one())
