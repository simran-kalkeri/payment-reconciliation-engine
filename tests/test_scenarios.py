import csv
import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError

from reconciliation.contracts import FIELDS, local_start
from reconciliation.db import query
from reconciliation.ingestion import InvalidFile, ingest
from reconciliation.matching import Payment, Rules, match
from reconciliation.normalization import batch, retry_db, verify_staged_replay, work
from reconciliation.operations import counts, health
from reconciliation.reconcile import reconcile, snapshot
from reconciliation.reporting import export
from reconciliation.storage import LocalStore
from reconciliation.workbench import history, list_issues, review, show

pytestmark = pytest.mark.postgres
DAY = date(2025, 5, 12)
EARLY = local_start(DAY + timedelta(days=2))
LATE = local_start(DAY + timedelta(days=5))


def ledger(key="L", reference="ABCDEF2345678901", **updates):
    return dict(id=key, merchant="m1", account="acct", reference=reference, currency="INR", gross="100.00",
                collection_date="2025-05-12", deadline_date="2025-05-13") | updates


def settlement(key="S", reference="ABCDEF2345678901", **updates):
    return dict(id=key, merchant="m1", account="acct", reference=reference, currency="INR", net="99.65",
                fee="0.35", settlement_date="2025-05-13", available_at="2025-05-13T13:00:00+05:30") | updates


@pytest.fixture
def inputs(database, tmp_path):
    storage = LocalStore(tmp_path / "raw")

    def submit(kind, rows, *, filename=None, **options):
        source = "ledger-office" if kind == "ledger" else "upi-bank"
        path = tmp_path / (filename or f"{uuid4().hex}.csv")
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS[kind], lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return ingest(database, storage, path, kind, source, **options)

    return submit, storage


def run(database, ids, cutoff=LATE, **kwargs):
    return reconcile(database, "daily", DAY, cutoff, Rules(), ids, True, **kwargs)


def test_bad_row_keeps_valid_rows(database, inputs):
    submit, storage = inputs
    file_id = submit("ledger", [ledger("A"), ledger("B", gross="broken"), ledger("C")])
    assert work(database) == {"accepted": 2, "rejected": 1}
    with database.connect() as conn:
        row = query(conn, "SELECT payload,rejection_code,rejection_reason FROM staged_rows WHERE status='rejected'").one()
        raw_key = query(conn, "SELECT storage_key FROM input_files WHERE id=:id", id=file_id).scalar_one()
    assert json.loads(row.payload)["cells"]["gross"] == "broken"
    assert row.rejection_code == "invalid_amount" and "gross" in row.rejection_reason
    assert "broken" in storage.locate(raw_key).read_text()


@pytest.mark.parametrize("bad_csv", ['id,reference\nL,A\n', ",".join(FIELDS["ledger"]) + '\n"unterminated\n'])
def test_bad_file_never_loads(database, inputs, tmp_path, bad_csv):
    _, storage = inputs
    path = tmp_path / "bad.csv"
    path.write_text(bad_csv, encoding="utf-8")
    with pytest.raises(InvalidFile):
        ingest(database, storage, path, "ledger", "ledger-office", batch_size=1)
    with database.connect() as conn:
        assert query(conn, "SELECT status FROM input_files").scalar_one() == "rejected"
    assert work(database) == {}


class Interrupted(RuntimeError):
    pass


def interrupt(*_):
    raise Interrupted


def test_interrupted_ingestion_resumes_durable_batches(database, inputs):
    submit, _ = inputs
    rows = [ledger("A"), ledger("B"), ledger("C")]
    with pytest.raises(Interrupted):
        submit("ledger", rows, batch_size=1, after_batch=interrupt)
    assert counts(database)["staged_rows"] == 1
    assert work(database) == {}
    file_id = submit("ledger", rows, batch_size=2)
    assert file_id > 0
    assert counts(database)["input_files"] == 1
    assert work(database) == {"accepted": 3}


def test_worker_process_dies_after_claim(database, inputs):
    submit, _ = inputs
    submit("ledger", [ledger()])
    url = database.url.render_as_string(hide_password=False)
    with database.connect() as conn:
        schema = query(conn, "SELECT current_schema()").scalar_one()
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve()),
           "RECON_CHILD_URL": url, "RECON_CHILD_SCHEMA": schema}
    process = subprocess.run([sys.executable, "-c", """
import os
from sqlalchemy import create_engine
from reconciliation.normalization import batch
db = create_engine(os.environ['RECON_CHILD_URL'], connect_args={
    'options': '-c search_path=' + os.environ['RECON_CHILD_SCHEMA'],
})
batch(db, 'crash', 1, on_claim=lambda rows: os._exit(27))
"""], env=env, capture_output=True, timeout=20)
    assert process.returncode == 27, process.stderr.decode(errors="replace")
    assert counts(database)["canonical"] == 0
    assert work(database) == {"accepted": 1}


def test_failure_before_commit_rolls_back_canonical_and_completion(database, inputs):
    submit, _ = inputs
    submit("ledger", [ledger()])
    with pytest.raises(Interrupted):
        batch(database, "worker", 1, before_commit=interrupt)
    assert counts(database)["canonical"] == 0
    with database.connect() as conn:
        assert query(conn, "SELECT status,attempts FROM staged_rows").one() == ("pending", 0)
    assert work(database) == {"accepted": 1}


def test_lost_commit_acknowledgement_can_retry(database, inputs):
    submit, _ = inputs
    submit("ledger", [ledger()])
    with pytest.raises(Interrupted):
        batch(database, "worker", 1, after_commit=interrupt)
    assert work(database) == {}
    assert counts(database)["canonical"] == 1
    with database.connect() as conn:
        assert query(conn, "SELECT status,attempts FROM staged_rows").one() == ("accepted", 1)


def test_two_workers_claim_disjoint_rows(database, inputs):
    submit, _ = inputs
    submit("ledger", [ledger("A"), ledger("B")])
    locked, released = Event(), Event()

    def hold(rows):
        assert rows[0].row_number == 1
        locked.set()
        assert released.wait(15)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(batch, database, "first", 1, on_claim=hold)
        try:
            assert locked.wait(15)
            second = pool.submit(batch, database, "second", 2)
            assert second.result(15) == {"accepted": 1}
        finally:
            released.set()
        assert first.result(15) == {"accepted": 1}
    with database.connect() as conn:
        assert query(conn, "SELECT worker,attempts FROM staged_rows ORDER BY row_number").all() == [
            ("first", 1), ("second", 1)]


def test_identical_file_and_already_staged_replay(database, inputs):
    submit, _ = inputs
    rows = [ledger("A"), ledger("B", gross="broken")]
    first = submit("ledger", rows)
    work(database)
    before = counts(database)
    assert submit("ledger", rows) == first
    assert verify_staged_replay(database, [first]) == 2
    assert counts(database) == before


def test_temporary_database_unavailability_retries_actual_connection(database, capsys):
    # Reserve a local port without listening so Psycopg receives an actual connection refusal.
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        port = unavailable.getsockname()[1]
        offline = create_engine(database.url.set(host="127.0.0.1", port=port), connect_args={"connect_timeout": 2})
        attempts = []

        def probe():
            attempts.append(True)
            target = offline if len(attempts) < 3 else database
            with target.connect() as conn:
                return query(conn, "SELECT 1").scalar_one()

        try:
            assert retry_db(probe, attempts=3, pause=0) == 1
            assert len(attempts) == 3
            assert capsys.readouterr().err.count("database_unavailable") == 2
        finally:
            offline.dispose()


def test_ambiguous_fuzzy_never_links(database, inputs):
    submit, _ = inputs
    ids = [submit("ledger", [ledger("A", "A123456789012345"), ledger("B", "B123456789012345")]),
           submit("settlement", [settlement(reference="C123456789012345")])]
    work(database)
    report, evidence = run(database, ids)
    assert report["fuzzy_matches"] == 0 and report["exception_counts"]["ambiguous_match"] == 2
    assert len(evidence["exceptions"][0]["evidence"]["candidates"]) == 2


def test_redelivery_conflict_and_genuine_duplicates(database, inputs):
    submit, _ = inputs
    first = settlement("S")
    extra = settlement("S2", available_at="2025-05-13T15:00:00+05:30")
    ids = [submit("ledger", [ledger()]), submit("settlement", [first, extra]),
           submit("settlement", [first, settlement("S", net="20")])]
    work(database)
    report, evidence = run(database, ids)
    assert counts(database)["canonical"] == 3
    assert report["rejected_rows"] == 1 and report["data_quality_warnings"] == {"identity_conflict": 1}
    assert report["settlement_count"] == 2 and report["exposure"]["duplicate_exposure"] == 10000
    duplicate = next(row for row in evidence["exceptions"] if row["category"] == "duplicate_settlement")
    assert duplicate["evidence"]["extras"] == ["upi-bank:S2"]


def test_late_arrival_preserves_report_and_review_history(database, inputs):
    submit, _ = inputs
    ids = [submit("ledger", [ledger()]), submit("settlement", [
        settlement(settlement_date="2025-05-14", available_at="2025-05-14T11:00:00+05:30")])]
    work(database)
    early, _ = run(database, ids, EARLY)
    issue = list_issues(database, category="missing_settlement")[0]
    assert show(database, issue["id"])["source_rows"]
    with pytest.raises(ValueError, match="nonempty"):
        review(database, issue["id"], issue["version"], "reviewer", "  ", "resolve")
    resolved = review(database, issue["id"], issue["version"], "reviewer", "Initial statement reviewed", "resolve")
    with pytest.raises(ValueError, match="version"):
        review(database, issue["id"], issue["version"], "reviewer", "stale", "reopen")
    final, _ = run(database, ids)
    assert final["exception_counts"]["late_settlement"] == 1
    old, _ = snapshot(database, early["result_id"])
    assert old["exception_counts"]["missing_settlement"] == 1
    prior = show(database, issue["id"])
    assert not prior["active"] and prior["review_status"] == resolved["review_status"]
    before = counts(database)
    replay, _ = run(database, ids)
    assert replay["result_hash"] == final["result_hash"] and counts(database) == before
    assert [row["action"] for row in history(database, issue["id"])] == ["detected", "resolve", "cleared"]
    with pytest.raises(DBAPIError), database.begin() as conn:
        query(conn, "DELETE FROM exception_history")


def test_fee_reconstruction_and_incomplete_reporting(database, inputs, tmp_path):
    submit, _ = inputs
    ids = [submit("ledger", [ledger()]), submit("settlement", [settlement()])]
    incomplete, evidence = run(database, ids)
    assert incomplete["status"] == "incomplete" and evidence is None
    assert counts(database)["results"] == 0
    directory = export(tmp_path / "report", incomplete)
    assert "INCOMPLETE" in (directory / "report.md").read_text()
    assert not (directory / "result.json").exists()
    assert health(database)["queue"]["backlog"] == 2
    work(database)
    report, _ = run(database, ids)
    assert report["exact_matches"] == 1 and report["exception_counts"]["amount_mismatch"] == 0
    assert report["settlement_gross"] == 10000 and report["settlement_fees"] == 35
    assert all(report["conservation"].values())


def test_merchant_currency_and_future_arrival_are_excluded(database, inputs):
    submit, _ = inputs
    ids = [submit("ledger", [ledger()]), submit("settlement", [
        settlement("OTHER", merchant="m2"), settlement("USD", currency="USD"),
        settlement("FUTURE", available_at="2025-05-20T12:00:00+05:30")])]
    work(database)
    report, _ = run(database, ids)
    assert report["ledger_matched"] == 0 and report["data_quality_warnings"] == {"unsupported_currency": 1}
    left = Payment(1, "ledger", "led", "1", "m", "a", "ABC", "INR", 100, DAY, EARLY)
    right = replace(left, id=2, kind="settlement", source="bank", currency="USD", available_at=EARLY)
    assert not match([left], [right], Rules())[0]


def test_overlapping_exceptions_stay_separate(database, inputs):
    submit, _ = inputs
    ids = [submit("ledger", [ledger()]), submit("settlement", [
        settlement(net="95", settlement_date="2025-05-14", available_at="2025-05-14T13:00:00+05:30")])]
    work(database)
    report, _ = run(database, ids)
    assert report["exposure"] == dict(outstanding_expected=0, unexplained_amount_discrepancy=465,
                                      duplicate_exposure=0, late_settled_value=10000, unresolved_review_exposure=0)
    assert report["diagnostic_matches"] == 1 and report["settlement_count"] == 1


def test_concurrent_publication_creates_one_snapshot(database, inputs):
    submit, _ = inputs
    ids = [submit("ledger", [ledger()]), submit("settlement", [settlement()])]
    work(database)
    held, release = Event(), Event()

    def block():
        held.set()
        assert release.wait(15)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, database, ids, before_publish=block)
        try:
            assert held.wait(15)
            second = pool.submit(run, database, ids)
        finally:
            release.set()
        a, b = first.result(15)[0], second.result(15)[0]
    assert a["run_id"] != b["run_id"] and a["result_id"] == b["result_id"]
    assert counts(database)["results"] == counts(database)["matches"] == 1
