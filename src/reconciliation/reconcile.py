from dataclasses import asdict
from datetime import UTC

from sqlalchemy import text

from .contracts import BUSINESS_TZ, scope_id
from .db import digest, event, json_text, operation, query
from .exceptions import publish_issues
from .matching import MATCHER_VERSION, Payment, classify
from .reporting import build_report


def file_contract(conn, ids):
    return [dict(row) for row in query(conn, """
        SELECT id,source,kind,schema_version,date_format,sha256,status,row_count,error FROM input_files
        WHERE id=ANY(CAST(:ids AS bigint[])) ORDER BY kind,source,sha256,date_format
    """, ids=ids).mappings()]


def inputs(conn, ids, cutoff):
    rows = query(conn, """
        SELECT id,kind,source,external_id,merchant,account,reference,currency,gross,business_date,
               deadline_at,available_at,net,fee
        FROM canonical c WHERE ((c.kind='ledger' AND c.business_date<=:local_day) OR c.available_at<=:cutoff)
        AND EXISTS (
          SELECT 1 FROM canonical_membership m WHERE m.canonical_id=c.id AND m.file_id=ANY(CAST(:ids AS bigint[]))
        )
    """, ids=ids, cutoff=cutoff, local_day=cutoff.astimezone(BUSINESS_TZ).date()).mappings()
    ledger, settlement = [], []
    for row in rows:
        payment = Payment(**row)
        (ledger if payment.kind == "ledger" else settlement).append(payment)
    return ledger, settlement


def reconcile(db, scope, day, cutoff, rules, file_ids, sources_complete, *, before_publish=None, progress=None):
    scope_id(scope)
    if cutoff.tzinfo is None:
        raise ValueError("Cutoff requires a UTC offset")
    cutoff = cutoff.astimezone(UTC)
    ids = sorted(set(file_ids))
    rule_data = {"version": MATCHER_VERSION, "rules": asdict(rules)}
    config_hash = digest(rule_data)
    with operation(db, "reconcile", scope=scope, business_date=day.isoformat()) as run:
        with db.begin() as conn:
            query(conn, "SELECT pg_advisory_xact_lock(hashtextextended(:key,0))", key=f"{scope}/{day}")
            files = file_contract(conn, ids)
            quality = [dict(row) for row in query(conn, """
                SELECT file_id,row_number,status,rejection_code FROM input_quality
                WHERE file_id=ANY(CAST(:ids AS bigint[])) ORDER BY file_id,row_number
            """, ids=ids).mappings()]
            names = {row["id"]: {key: row[key] for key in ("kind", "source", "sha256", "schema_version", "date_format")}
                     for row in files}
            header = dict(scope=scope, business_date=day.isoformat(), cutoff=cutoff.isoformat(),
                          inputs=list(names.values()), matcher_version=MATCHER_VERSION, config_hash=config_hash,
                          grace_hours=rules.grace_hours,
                          source_completeness_attested=sources_complete)
            problems = []
            if not sources_complete:
                problems.append("source_completeness_not_attested")
            if cutoff.astimezone(BUSINESS_TZ).date() < day:
                problems.append("cutoff_before_business_date")
            if len(files) != len(ids) or {row["kind"] for row in files} != {"ledger", "settlement"}:
                problems.append("missing_declared_file_or_kind")
            if any(row["status"] != "staged" for row in files):
                problems.append("file_rejected_or_still_loading")
            if len(quality) != sum(row["row_count"] for row in files) or any(
                    row["status"] == "pending" for row in quality):
                problems.append("normalization_incomplete")
            if problems:
                event("reconcile", run_id=run, status="incomplete", reasons=problems)
                query(conn, "UPDATE operations SET detail=detail || CAST(:detail AS jsonb) WHERE id=:run",
                      detail=json_text({"outcome": "incomplete", "reasons": problems}), run=run)
                return dict(**header, status="incomplete", run_id=run, reasons=problems,
                            files=files, input_rows=len(quality),
                            accepted_rows=sum(row["status"] == "accepted" for row in quality),
                            rejected_rows=sum(row["status"] == "rejected" for row in quality),
                            pending_rows=sum(row["status"] == "pending" for row in quality)), None
            context_hash = digest(header)
            ledger, settlement = inputs(conn, ids, cutoff)
            focal, scoped, links, issues, pending = classify(day, cutoff, ledger, settlement, rules, progress=progress)
            if progress:
                progress("publish")
            for row in quality:
                if row["status"] != "rejected":
                    continue
                source_file = names[row["file_id"]]
                subject = digest({"input": source_file, "row": row["row_number"]})
                issues.append(dict(category="data_quality", subject=subject, merchant=None, amount=None,
                                   evidence={**source_file, "row_number": row["row_number"],
                                             "rejection_code": row["rejection_code"]}))
            issues.sort(key=lambda item: (item["category"], item["subject"]))
            report = dict(**header, status="complete", context_hash=context_hash,
                          **build_report(focal, scoped, links, issues, pending, files, quality))
            evidence = dict(matches=[dict(method=method, **proof) for _, method, proof in links.values()],
                            exceptions=issues,
                            pending_ledger=sorted(row.key for row in pending))
            evidence["matches"].sort(key=lambda row: row["ledger"])
            result_hash = digest({"report": report, **evidence})
            existing = query(conn, "SELECT id,result_hash FROM results WHERE context_hash=:context",
                             context=context_hash).one_or_none()
            if existing is not None:
                if existing.result_hash != result_hash:
                    raise RuntimeError("Deterministic replay differs from its published result")
                result_id = existing.id
            else:
                if before_publish:
                    before_publish()
                query(conn, """
                    INSERT INTO matcher_configs(hash,version,rules) VALUES (:hash,:version,CAST(:rules AS jsonb))
                    ON CONFLICT DO NOTHING
                """, hash=config_hash, version=MATCHER_VERSION, rules=json_text(rule_data["rules"]))
                result_id = query(conn, """
                    INSERT INTO results(scope,business_date,cutoff,context_hash,result_hash,config_hash,report,evidence)
                    VALUES (:scope,:day,:cutoff,:context,:result_hash,:config,CAST(:report AS jsonb),
                            CAST(:evidence AS jsonb)) RETURNING id
                """, scope=scope, day=day, cutoff=cutoff, context=context_hash, result_hash=result_hash,
                    config=config_hash, report=json_text(report), evidence=json_text(evidence)).scalar_one()
                if links:
                    conn.execute(text("""
                        INSERT INTO matches(result_id,ledger_id,settlement_id,method,evidence)
                        VALUES (:result,:left,:right,:method,CAST(:evidence AS jsonb))
                    """), [dict(result=result_id, left=left.id, right=right.id, method=method,
                                evidence=json_text(proof)) for left, (right, method, proof) in links.items()])
                prior = query(conn, """
                    SELECT r.cutoff FROM current_results c JOIN results r ON r.id=c.result_id
                    WHERE c.scope=:scope AND c.business_date=:day
                """, scope=scope, day=day).scalar_one_or_none()
                if prior is None or prior <= cutoff:
                    query(conn, """
                        INSERT INTO current_results(scope,business_date,result_id) VALUES (:scope,:day,:result)
                        ON CONFLICT (scope,business_date) DO UPDATE SET result_id=excluded.result_id
                    """, scope=scope, day=day, result=result_id)
                    publish_issues(conn, scope, day, result_id, issues)
            query(conn, "UPDATE operations SET detail=detail || CAST(:detail AS jsonb) WHERE id=:run",
                  detail=json_text({"outcome": "complete", "result_id": result_id, "reused": existing is not None}),
                  run=run)
    return dict(**report, run_id=run, result_id=result_id, result_hash=result_hash), evidence


def snapshot(db, result_id):
    with db.connect() as conn:
        row = query(conn, """
            SELECT report,evidence,result_hash,
              (SELECT min(id) FROM operations WHERE detail->>'result_id'=CAST(:result AS text)) AS run_id
            FROM results WHERE id=:result
        """, result=result_id).one_or_none()
        if row is None:
            raise ValueError("Unknown result ID")
    return dict(**row.report, result_id=result_id, run_id=row.run_id, result_hash=row.result_hash), row.evidence
