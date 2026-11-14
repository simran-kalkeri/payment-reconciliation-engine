from .db import query
from .exceptions import history_event, state


def list_issues(db, *, scope=None, day=None, category=None, status=None, merchant=None,
                min_amount=None, max_amount=None, include_inactive=False, limit=100, after=0):
    with db.connect() as conn:
        return [dict(row) for row in query(conn, """
            SELECT id,scope,business_date,category,subject,merchant,amount,active,review_status,version,result_id
            FROM exceptions WHERE id>:after AND (:inactive OR active)
            AND (CAST(:scope AS text) IS NULL OR scope=:scope)
            AND (CAST(:day AS date) IS NULL OR business_date=:day)
            AND (CAST(:category AS text) IS NULL OR category=:category)
            AND (CAST(:status AS text) IS NULL OR review_status=:status)
            AND (CAST(:merchant AS text) IS NULL OR merchant=:merchant)
            AND (CAST(:min_amount AS bigint) IS NULL OR amount>=:min_amount)
            AND (CAST(:max_amount AS bigint) IS NULL OR amount<=:max_amount)
            ORDER BY id LIMIT :limit
        """, scope=scope, day=day, category=category, status=status, merchant=merchant, min_amount=min_amount,
            max_amount=max_amount, inactive=include_inactive, limit=limit, after=after).mappings()]


def show(db, exception_id):
    with db.connect() as conn:
        issue = query(conn, "SELECT * FROM exceptions WHERE id=:id", id=exception_id).mappings().one_or_none()
        if issue is None:
            raise ValueError("Unknown exception ID")
        evidence = issue["evidence"]
        if issue["category"] == "data_quality":
            source_rows = query(conn, """
                SELECT f.source,f.kind,f.sha256,f.storage_key,s.row_number,s.payload,s.rejection_code,s.rejection_reason
                FROM staged_rows s JOIN input_files f ON f.id=s.file_id
                WHERE f.source=:source AND f.kind=:kind AND f.sha256=:sha256
                  AND f.date_format=:date_format AND f.schema_version=:schema_version AND s.row_number=:row_number
            """, **evidence).mappings()
        else:
            keys = {evidence[key] for key in ("ledger", "settlement", "original") if key in evidence}
            keys.update(evidence.get("extras", []))
            keys.update(candidate[key] for candidate in evidence.get("candidates", []) for key in ("ledger", "settlement"))
            source_rows = query(conn, """
                SELECT f.source,f.kind,f.sha256,f.storage_key,s.row_number,s.payload,c.external_id
                FROM staged_rows s JOIN input_files f ON f.id=s.file_id JOIN canonical c ON c.id=s.canonical_id
                WHERE concat(c.source, ':', c.external_id)=ANY(CAST(:keys AS text[]))
                ORDER BY f.id,s.row_number
            """, keys=sorted(keys)).mappings()
        return dict(**issue, source_rows=[dict(row) for row in source_rows])


def history(db, exception_id):
    with db.connect() as conn:
        if query(conn, "SELECT id FROM exceptions WHERE id=:id", id=exception_id).scalar_one_or_none() is None:
            raise ValueError("Unknown exception ID")
        return [dict(row) for row in query(conn, """
            SELECT * FROM exception_history WHERE exception_id=:id ORDER BY id
        """, id=exception_id).mappings()]


def review(db, exception_id, expected_version, actor, reason, action):
    actor, reason = actor.strip(), reason.strip()
    if not actor or not reason or action not in {"resolve", "reopen"}:
        raise ValueError("Specify an actor, a nonempty reason and a valid action")
    status, required = ("resolved", "open") if action == "resolve" else ("open", "resolved")
    with db.begin() as conn:
        prior = query(conn, "SELECT * FROM exceptions WHERE id=:id FOR UPDATE", id=exception_id).mappings().one_or_none()
        if prior is None:
            raise ValueError("Unknown exception ID")
        if prior["version"] != expected_version or prior["review_status"] != required:
            raise ValueError("Exception version or review state changed. Reload it before retrying.")
        current = query(conn, """
            UPDATE exceptions SET review_status=:status,version=version+1 WHERE id=:id RETURNING *
        """, id=exception_id, status=status).mappings().one()
        history_event(conn, exception_id, actor, action, state(prior), state(current), reason)
        return dict(current)
