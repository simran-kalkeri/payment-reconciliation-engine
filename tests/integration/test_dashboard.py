import csv
import http.client
import json
from collections import Counter
from contextlib import closing
from hashlib import sha256
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep

import pytest

from reconciliation.contracts import FIELDS, local_start
from reconciliation.dashboard import DashboardServer
from reconciliation.generator import generate
from reconciliation.ingestion import ingest
from reconciliation.matching import Rules
from reconciliation.normalization import work
from reconciliation.operations import counts
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
    datasets = tmp_path / "datasets"
    with DashboardServer(database, 0, local_demo=local_demo, dataset_root=datasets) as server:
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
                assert send("/api/datasets", {})[0] == 401
                assert send("/api/session", {"key": "wrong"})[0] == 401
                status, _, headers = send("/api/session", {"key": server.access_key})
                assert status == 200 and "SameSite=Strict" in headers["Set-Cookie"]
                cookie = headers["Set-Cookie"].split(";", 1)[0]
            assert send("/api/reports", headers={"Host": "unrelated.example"})[0] == 403
            assert send("/api/reports", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
            assert send("/api/reports", headers={"Origin": "http://unrelated.example"})[0] == 403
            assert send("/api/datasets", {}, origin=False)[0] == 403
            if local_demo:
                status, dataset, _ = send("/api/datasets", {})
                assert status == 201
                route = f"/api/datasets/{dataset['id']}"
                bundle = datasets / dataset["id"]
                assert {file["name"] for file in dataset["files"]} == {"ledger.csv", "settlements.csv"}
                assert 10_008 <= sum(file["rows"] for file in dataset["files"]) <= 15_000
                for file in dataset["files"]:
                    status, content, headers = send(f"{route}/{file['name']}")
                    assert status == 200 and "attachment" in headers["Content-Disposition"]
                    assert sha256(content.encode("utf-8")).hexdigest() == file["sha256"]
                manifest = send(f"{route}/manifest.json")[1]
                assert manifest["files"] == dataset["files"]
                assert manifest["configuration"]["merchant_profiles"] is True
                answer = send(f"{route}/answer_key.json")[1]
                assert {label for row in answer["rows"] for label in row["labels"]} == {
                    "missing_settlement", "duplicate_settlement", "amount_mismatch", "late_settlement",
                    "reference_mismatch",
                }
                assert list((bundle / "truth").iterdir()) == [bundle / "truth" / "answer_key.json"]
                assert not (bundle / "inputs" / "answer_key.json").exists()
                settlement_file = next(file for file in dataset["files"] if file["kind"] == "settlement")
                assert settlement_file["date_format"] == "mixed"
                with (bundle / "inputs" / settlement_file["name"]).open(newline="", encoding="utf-8") as stream:
                    settlements = list(csv.DictReader(stream))
                assert len({row["available_at"][11:13] for row in settlements if "T" in row["available_at"]}) > 2
                assert len({row["fee"] for row in settlements}) > 7
                settlement_id = ingest(database, store, bundle / "inputs" / settlement_file["name"],
                                       settlement_file["kind"], settlement_file["source"], "mixed")
                assert work(database, file_ids=[settlement_id]) == {
                    "accepted": settlement_file["rows"] - 4, "rejected": 4,
                }
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


@pytest.mark.parametrize(("choose", "first_total", "second_total", "first_days", "second_days"), [
    ("minimum", 10_008, 10_010, 2, 3),
    ("maximum", 15_000, 14_998, 7, 6),
])
def test_dataset_regeneration_replaces_previous_bundle(
        tmp_path, monkeypatch, choose, first_total, second_total, first_days, second_days):
    monkeypatch.setattr("reconciliation.generator.randbelow", lambda size: 0 if choose == "minimum" else size - 1)
    root = tmp_path / "datasets"
    root.mkdir()
    (root / "unrelated").mkdir()
    with DashboardServer(None, 0, local_demo=True, dataset_root=root) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def send(path, *, generate=False):
            with_connection = http.client.HTTPConnection(server.host, timeout=10)
            try:
                with_connection.request(
                    "POST" if generate else "GET", path, body="{}" if generate else None,
                    headers={"Origin": server.origin, "Content-Type": "application/json"} if generate else {},
                )
                response = with_connection.getresponse()
                data = response.read()
                if response.getheader("Content-Type").startswith("application/json"):
                    data = json.loads(data)
                return response.status, data
            finally:
                with_connection.close()

        def check_dataset(dataset, expected_total, expected_days):
            route = f"/api/datasets/{dataset['id']}"
            actual = 0
            for file in dataset["files"]:
                status, payload = send(f"{route}/{file['name']}")
                assert status == 200
                rows = sum(1 for _ in csv.DictReader(StringIO(payload.decode("utf-8"))))
                assert rows == file["rows"]
                actual += rows
            assert actual == expected_total
            answer = send(f"{route}/answer_key.json")[1]
            assert len(dataset["business_dates"]) == expected_days
            assert answer["business_dates"] == dataset["business_dates"]
            assert {row["business_date"] for row in answer["rows"]} == set(dataset["business_dates"])
            assert actual - len(answer["invalid_rows"]) >= 10_000
            error_counts = Counter(label for row in answer["rows"] for label in row["labels"])
            assert error_counts.keys() == {
                "missing_settlement", "duplicate_settlement", "amount_mismatch", "late_settlement", "reference_mismatch",
            }
            assert error_counts == dataset["configuration"]["seeded_error_counts"]
            assert all(60 <= total <= 130 for total in error_counts.values())
            return error_counts

        try:
            assert send("/api/datasets/current") == (200, None)
            status, first = send("/api/datasets", generate=True)
            assert status == 201
            first_errors = check_dataset(first, first_total, first_days)
            first_route = f"/api/datasets/{first['id']}"

            def fail_generation(*args, **kwargs):
                raise OSError("Simulated disk error")

            with monkeypatch.context() as failure:
                failure.setattr("reconciliation.dashboard.generate_dashboard_dataset", fail_generation)
                assert send("/api/datasets", generate=True)[0] == 500
            assert send("/api/datasets/current")[1]["id"] == first["id"]
            assert send(first_route + "/ledger.csv")[0] == 200

            status, second = send("/api/datasets", generate=True)
            assert status == 201
            second_errors = check_dataset(second, second_total, second_days)
            assert all(first_errors[key] != second_errors[key] for key in first_errors)
            assert second["seed"] != first["seed"]
            hashes = {file["name"]: file["sha256"] for file in first["files"]}
            assert all(file["sha256"] != hashes[file["name"]] for file in second["files"])
            assert not second["cleanup_pending"]
            assert not (root / first["id"]).exists()
            assert (root / "unrelated").is_dir()
            assert send(first_route + "/answer_key.json")[0] == 404
            assert send("/api/datasets/current")[1]["id"] == second["id"]
            assert send(f"/api/datasets/{second['id']}/answer_key.json")[1]["seed"] == second["seed"]
        finally:
            server.shutdown()
            worker.join(5)


def test_dashboard_pipeline_runs_and_replays_generated_inputs(database, tmp_path, monkeypatch):
    entered_validation = Event()
    continue_validation = Event()

    def pause_at_validation(*args, **kwargs):
        entered_validation.set()
        if not continue_validation.wait(10):
            raise RuntimeError("Test did not release the worker")
        return work(*args, **kwargs)

    monkeypatch.setattr("reconciliation.dashboard_pipeline.work", pause_at_validation)

    def generate_test_dataset(inputs, truth, seed, previous_total, *, previous_config):
        days, seeded_count = (5, 40) if previous_config is None else (2, 45)
        seeded_counts = dict.fromkeys(
            ("missing_settlement", "duplicate_settlement", "amount_mismatch", "late_settlement", "reference_mismatch"),
            seeded_count,
        )
        return generate(inputs, truth, 242 + days, count=260, two_files=True, merchant_profiles=True,
                        business_days=days, seeded_counts=seeded_counts, ambiguous_cases=4)

    monkeypatch.setattr("reconciliation.dashboard.generate_dashboard_dataset", generate_test_dataset)
    root = tmp_path / "datasets"
    raw = tmp_path / "raw"
    with DashboardServer(database, 0, local_demo=True, dataset_root=root, raw_root=raw) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def send(path, *, post=False):
            with closing(http.client.HTTPConnection(server.host, timeout=10)) as connection:
                headers = {"Origin": server.origin, "Content-Type": "application/json"} if post else {}
                connection.request("POST" if post else "GET", path, body="{}" if post else None, headers=headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())

        def finished():
            deadline = monotonic() + 45
            while monotonic() < deadline:
                status, job = send("/api/pipeline")
                assert status == 200
                if job["status"] != "running":
                    return job
                sleep(0.05)
            pytest.fail(f"The reconciliation job did not finish. Last status: {job}")

        try:
            status, dataset = send("/api/datasets", post=True)
            assert status == 201
            route = f"/api/datasets/{dataset['id']}/reconcile"
            answer_key = root / dataset["id"] / "truth" / "answer_key.json"
            truth = answer_key.read_bytes()
            answer_key.unlink()

            assert send(route, post=True)[0] == 202
            assert entered_validation.wait(10)
            status, progress = send("/api/pipeline")
            assert status == 200 and progress["stage"] == "validate"
            assert progress["status"] == "running" and not progress["reports"]
            assert set(progress["steps"]) == {"read", "stage", "validate"}
            assert progress["matching_rules"] == json.loads(Path("config/frozen.json").read_text(encoding="utf-8"))
            assert send(route, post=True)[1] == progress
            assert send("/api/datasets", post=True)[0] == 409
            continue_validation.set()

            first = finished()
            assert first["status"] == "failed" and first["stage"] == "evaluate", first
            assert "valid answer key" in first["error"]
            assert "evaluation" not in first
            assert set(first["steps"]) == {"read", "stage", "validate", "match", "publish", "evaluate"}
            assert len(first["reports"]) == 5
            assert len(list(raw.glob("*/*"))) == 2
            assert len(send("/api/reports")[1]) == 5
            for item in first["reports"]:
                status, report = send(f"/api/reports/{item['result_id']}")
                assert status == 200 and report["scope"] == first["scope"]
                assert report["business_date"] == item["business_date"]
                assert report["ledger_matched"] > 0 and report["rejected_rows"] == 8
                assert item["exact_matches"] + item["diagnostic_matches"] + item["fuzzy_matches"] == report["ledger_matched"]
                assert all(report["conservation"].values())
            day = first["reports"][0]["business_date"]
            assert send(f"/api/issues?scope={first['scope']}&day={day}")[1]["issues"]
            before = counts(database)
            answer_key.write_bytes(truth)
            assert send(route, post=True)[0] == 202
            replay = finished()
            assert replay["status"] == "complete", replay
            assert replay["matching_rules"] == progress["matching_rules"]
            assert replay["match_phase"] == "done"
            assert replay["reports"] == first["reports"]
            assert counts(database) == before
            evaluation = replay["evaluation"]
            assert evaluation["seed"] == dataset["seed"]
            assert evaluation["business_dates"] == [item["business_date"] for item in first["reports"]]
            assert set(evaluation["error_metrics"]) == {
                "missing_settlement", "duplicate_settlement", "amount_mismatch", "late_settlement", "reference_mismatch",
            }
            assert evaluation["false_matches"] == {"exact": 0, "diagnostic": 0, "fuzzy": 0}
            assert evaluation["misses"]["reason_counts"]["Tied candidates"] == 4
            assert evaluation["missed_true_links"] == len(evaluation["misses"]["cases"])
            assert send(route, post=True)[0] == 202
            second_replay = finished()
            assert second_replay == replay
            assert counts(database) == before
            with server.pipeline.lock:
                server.pipeline.job = None
            assert send("/api/pipeline") == (200, replay)

            status, replacement = send("/api/datasets", post=True)
            assert status == 201
            assert send(f"/api/datasets/{replacement['id']}/reconcile", post=True)[0] == 202
            new_run = finished()
            assert new_run["status"] == "complete", new_run
            assert new_run["scope"] != replay["scope"]
            assert len(new_run["reports"]) == 2
            assert new_run["evaluation"]["error_metrics"] != evaluation["error_metrics"]
            assert len(send("/api/reports")[1]) == 7
        finally:
            continue_validation.set()
            server.shutdown()
            worker.join(5)
