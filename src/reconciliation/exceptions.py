from .db import json_text, query


def state(row):
    return {key: row[key] for key in ("active", "review_status", "version", "result_id")}


def history_event(conn, exception_id, actor, action, previous, current, reason):
    query(conn, """
        INSERT INTO exception_history(exception_id,actor,action,previous_state,new_state,reason)
        VALUES (:id,:actor,:action,CAST(:previous AS jsonb),CAST(:current AS jsonb),:reason)
    """, id=exception_id, actor=actor, action=action, previous=json_text(previous) if previous else None,
          current=json_text(current), reason=reason)


def publish_issues(conn, scope, day, result_id, issues):
    old = {(row["category"], row["subject"]): row for row in query(conn, """
        SELECT * FROM exceptions WHERE scope=:scope AND business_date=:day ORDER BY id FOR UPDATE
    """, scope=scope, day=day).mappings()}
    for issue in issues:
        prior = old.pop((issue["category"], issue["subject"]), None)
        if prior is None:
            new = query(conn, """
                INSERT INTO exceptions(scope,business_date,category,subject,merchant,amount,result_id,evidence)
                VALUES (:scope,:day,:category,:subject,:merchant,:amount,:result,CAST(:evidence AS jsonb))
                RETURNING *
            """, **{**issue, "evidence": json_text(issue["evidence"])}, scope=scope, day=day,
                  result=result_id).mappings().one()
            history_event(conn, new["id"], "engine", "detected", None, state(new), "First detected in a current result")
        else:
            changed = (prior["merchant"], prior["amount"], prior["evidence"]) != (
                issue["merchant"], issue["amount"], issue["evidence"])
            action = "reactivated" if not prior["active"] else "updated" if changed else None
            new = query(conn, """
                UPDATE exceptions SET active=true,result_id=:result,merchant=:merchant,amount=:amount,
                  evidence=CAST(:evidence AS jsonb),version=version+:increment WHERE id=:id RETURNING *
            """, id=prior["id"], result=result_id, merchant=issue["merchant"], amount=issue["amount"],
                  evidence=json_text(issue["evidence"]), increment=int(action is not None)).mappings().one()
            if action:
                history_event(conn, new["id"], "engine", action, state(prior), state(new),
                              "Evidence changed in a current result")
    for prior in old.values():
        if prior["active"]:
            new = query(conn, """
                UPDATE exceptions SET active=false,result_id=:result,version=version+1 WHERE id=:id RETURNING *
            """, id=prior["id"], result=result_id).mappings().one()
            history_event(conn, new["id"], "engine", "cleared", state(prior), state(new),
                          "Anomaly absent from the new current result")
