import csv
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from .contracts import CATEGORIES


def build_report(ledgers, settlements, links, issues, pending, files, quality):
    matched_settlements = {row for row, _, _ in links.values()}
    matched_ledger = sum(row.gross for row in links)
    unmatched_ledger = sum(row.gross for row in ledgers if row not in links)
    matched_gross = sum(row.gross for row in matched_settlements)
    unmatched_gross = sum(row.gross for row in settlements if row not in matched_settlements)
    gross = sum(row.gross for row in settlements)
    net = sum(row.net for row in settlements)
    fee = sum(row.fee for row in settlements)
    issue_counts = Counter(issue["category"] for issue in issues)
    methods = Counter(method for _, method, _ in links.values())
    quality_counts = Counter(row["status"] for row in quality)
    expected = sum(row.gross for row in ledgers)
    input_count = sum(row["row_count"] for row in files)
    report = dict(
        unit="INR paise",
        source_population="All declared file rows, across business dates",
        financial_population="Ledger collection day; owned settlements follow the ledger, unowned use settlement day",
        input_rows=input_count,
        accepted_rows=quality_counts["accepted"],
        rejected_rows=quality_counts["rejected"],
        pending_rows=quality_counts["pending"],
        ledger_count=len(ledgers),
        settlement_count=len(settlements),
        ledger_matched=len(links),
        ledger_unmatched=len(ledgers) - len(links),
        settlement_matched=len(matched_settlements),
        settlement_unmatched=len(settlements) - len(matched_settlements),
        exact_matches=methods["exact"],
        fuzzy_matches=methods["fuzzy"],
        diagnostic_matches=methods["diagnostic"],
        pending_not_due=len(pending),
        pending_expected_gross=sum(row.gross for row in pending),
        expected_gross=expected,
        expected_gross_matched=matched_ledger,
        expected_gross_unmatched=unmatched_ledger,
        settlement_gross=gross,
        settlement_net=net,
        settlement_fees=fee,
        settlement_gross_matched=matched_gross,
        settlement_gross_unmatched=unmatched_gross,
        exception_counts={category: issue_counts[category] for category in CATEGORIES},
        data_quality_warnings=dict(sorted(Counter(row["rejection_code"] for row in quality
                                                 if row["status"] == "rejected").items())),
    )
    exposure = {
        "outstanding_expected": "missing_settlement",
        "unexplained_amount_discrepancy": "amount_mismatch",
        "duplicate_exposure": "duplicate_settlement",
        "late_settled_value": "late_settlement",
        "unresolved_review_exposure": "ambiguous_match",
    }
    report["exposure"] = {
        name: sum(issue["amount"] for issue in issues if issue["category"] == category)
        for name, category in exposure.items()
    }
    report["conservation"] = {
        "input_rows": input_count == sum(quality_counts.values()),
        "ledger_count": len(ledgers) == len(links) + report["ledger_unmatched"],
        "settlement_count": len(settlements) == len(matched_settlements) + report["settlement_unmatched"],
        "one_to_one": len(links) == len(matched_settlements),
        "expected_gross": expected == matched_ledger + unmatched_ledger,
        "settlement_gross": gross == matched_gross + unmatched_gross == net + fee,
    }
    if not all(report["conservation"].values()):
        raise RuntimeError("Report conservation check failed")
    return report


def json_file(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


def atomic_write(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", newline="",
                                     delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            temp.unlink()
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def render_report(report):
    from io import StringIO

    status = report["status"]
    rows = []
    for key, value in report.items():
        if isinstance(value, dict):
            rows.extend((f"{key}.{sub}", val) for sub, val in sorted(value.items()))
        elif isinstance(value, list):
            rows.append((key, json.dumps(value, sort_keys=True)))
        else:
            rows.append((key, value))
    csv_text = StringIO(newline="")
    writer = csv.writer(csv_text, lineterminator="\n")
    writer.writerow(("field", "value"))
    writer.writerows(rows)
    lines = [f"# {status.upper()} reconciliation for {report['business_date']}", "",
             "Monetary measures use INR paise. Exposure categories can overlap.", "",
             "| Field | Value |", "| --- | --- |"]
    lines.extend(f"| {key} | {str(value).replace('|', '&#124;').replace(chr(10), ' ')} |" for key, value in rows)
    return {"csv": csv_text.getvalue(), "md": "\n".join(lines) + "\n",
            "json": json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"}


def export(directory, report, evidence=None):
    # Store each attempt separately so an incomplete replay cannot replace a completed export.
    version = Path(directory) / f"run-{report['run_id']}"
    version.mkdir(parents=True, exist_ok=True)
    rendered = render_report(report)
    for extension in ("csv", "md"):
        atomic_write(version / f"report.{extension}", rendered[extension])
    if evidence is not None:
        json_file(version / "result.json", {"report": report, **evidence})
    atomic_write(version / "report.json", rendered["json"])
    return version
