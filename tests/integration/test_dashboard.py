import csv
import http.client
import json
from datetime import date, timedelta
from threading import Thread

import pytest

from reconciliation.contracts import FIELDS, local_start
from reconciliation.dashboard import DashboardServer
from reconciliation.ingestion import ingest
from reconciliation.matching import Rules
from reconciliation.normalization import work
from reconciliation.reconcile import reconcile
from reconciliation.storage import LocalStore

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("local_demo", [False, True])
def test_dashboard_reads_reports_and_reviews_with_existing_audit(database, tmp_path, local_demo):
    day = date(2025, 5, 12)
    fields = {"id": "L1", "merchant": "merchant-1", "account": "a", "reference": "TEST123", "currency": "INR",
              "gross": "10.00", "collection_date": day.isoformat(), "deadline_date": day.isoformat()}
    store = LocalStore(tmp_path / "raw")
    files = []
    for kind in ("ledger", "settlement"):
        file = tmp_path / f"{kind}.csv"
        with file.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS[kind])
            writer.writeheader()
            if kind == "ledger":
                writer.writerow(fields)
        files.append(ingest(database, store, file, kind, kind))
    work(database)
    early, _ = reconcile(database, "local", day, local_start(day), Rules(), files, True)
    report, _ = reconcile(database, "local", day, local_start(day + timedelta(days=2)), Rules(), files, True)
    with DashboardServer(database, 0, local_demo=local_demo) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        cookie = None

        def send(path, body=None, *, origin=True, headers=None):
            request = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            fields = {"Host": server.localhost if local_demo else server.host, **(headers or {})}
            if cookie:
                fields["Cookie"] = cookie
            if body is not None:
                fields["Content-Type"] = "application/json"
                if origin:
                    fields.setdefault("Origin", f"http://{fields['Host']}")
            request.request("GET" if body is None else "POST", path,
                            body=None if body is None else json.dumps(body), headers=fields)
            response = request.getresponse()
            payload = response.read().decode()
            values = dict(response.getheaders())
            request.close()
            if values["Content-Type"].startswith("application/json"):
                payload = json.loads(payload)
            return response.status, payload, values

        try:
            assert send("/")[0] == 200
            assert send("/", headers={"Sec-Fetch-Site": "cross-site"})[0] == 200
            if local_demo:
                assert server.access_url == f"http://{server.localhost}/"
                assert send("/api/reports")[0] == 200
            else:
                assert send("/api/reports")[0] == 401
                assert send("/api/session", {"key": "wrong"})[0] == 401
                status, _, headers = send("/api/session", {"key": server.access_key})
                assert status == 200 and "SameSite=Strict" in headers["Set-Cookie"]
                cookie = headers["Set-Cookie"].split(";", 1)[0]
            assert send("/api/reports", headers={"Host": "unrelated.example"})[0] == 403
            assert send("/api/reports", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
            assert send("/api/reports", headers={"Origin": "http://unrelated.example"})[0] == 403
            versions = send("/api/reports?scope=local&day=2025-05-12")[1]
            assert [(item["id"], item["current"]) for item in versions] == [
                (report["result_id"], True), (early["result_id"], False)]
            status, body, headers = send(f"/api/reports/{report['result_id']}.csv")
            assert status == 200 and "expected_gross,1000" in body and "attachment" in headers["Content-Disposition"]
            status, queue, _ = send("/api/issues?scope=local&day=2025-05-12&status=open")
            assert status == 200 and len(queue["issues"]) == 1
            case = queue["issues"][0]
            path = f"/api/issues/{case['id']}"
            assert send(path)[1]["issue"]["source_rows"][0]["source"] == "ledger"
            decision = {"actor": "Test reviewer", "reason": "Checked source file", "action": "resolve",
                        "version": case["version"]}
            assert send(path + "/review", decision, origin=False)[0] == 403
            assert send(path + "/review", decision, headers={"Origin": "http://unrelated.example"})[0] == 403
            assert send(path + "/review", {**decision, "reason": " "})[0] == 400
            assert send(path + "/review", decision)[1]["review_status"] == "resolved"
            assert send(path + "/review", decision)[0] == 409
            assert send(path + "/review", {**decision, "action": "reopen",
                                         "version": case["version"] + 1})[1]["review_status"] == "open"
            assert [row["action"] for row in send(path)[1]["history"]] == ["detected", "resolve", "reopen"]
        finally:
            server.shutdown()
            worker.join(5)
