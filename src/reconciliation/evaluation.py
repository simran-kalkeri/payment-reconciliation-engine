"""Offline scoring. This module opens truth and published result exports only."""

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

from .contracts import timestamp
from .reporting import json_file

CATEGORIES = ("missing_settlement", "duplicate_settlement", "amount_mismatch", "late_settlement",
              "reference_mismatch")


def metrics(expected, predicted):
    tp, fp, fn = len(expected & predicted), len(predicted - expected), len(expected - predicted)
    return dict(tp=tp, fp=fp, fn=fn, support=tp + fn,
                precision=tp / (tp + fp) if tp + fp else None,
                recall=tp / (tp + fn) if tp + fn else None)


def evaluate(truth_path, result_paths, output):
    truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    results = [json.loads(Path(path).read_text(encoding="utf-8")) for path in result_paths]
    if not results or any(row["report"]["status"] != "complete" for row in results):
        raise ValueError("Evaluate one or more complete result exports")
    reports = {row["report"]["business_date"]: row["report"] for row in results}
    if len(reports) != len(results) or not reports.keys() <= set(truth["business_dates"]):
        raise ValueError("Use exactly one result per evaluated date")
    if len({row["config_hash"] for row in reports.values()}) != 1:
        raise ValueError("All evaluated dates must use the same matcher configuration")
    keys = ("kind", "source", "date_format", "sha256")
    expected_inputs = {tuple(row[key] for key in keys) for row in truth["files"]}
    if any({tuple(row[key] for key in keys) for row in report["inputs"]} != expected_inputs
           for report in reports.values()):
        raise ValueError("Result input hashes do not agree with the evaluation manifest")
    cutoffs = {day: timestamp(report["cutoff"]) for day, report in reports.items()}
    available_truth = {}
    expected = {name: set() for name in CATEGORIES}
    for row in truth["rows"]:
        if row["business_date"] not in cutoffs:
            continue
        cutoff = cutoffs[row["business_date"]]
        left = row["ledger"]
        if row["available_at"] is None or timestamp(row["available_at"]) > cutoff:
            if cutoff >= timestamp(row["deadline"]) + timedelta(hours=reports[row["business_date"]]["grace_hours"]):
                expected["missing_settlement"].add(left)
            continue
        available_truth[left] = row["settlement"]
        for category in set(row["labels"]) & {"amount_mismatch", "reference_mismatch"}:
            expected[category].add(left)
        if timestamp(row["settlement_day_start"]) >= (
                timestamp(row["deadline"]) + timedelta(hours=reports[row["business_date"]]["grace_hours"])):
            expected["late_settlement"].add(left)
        extras = tuple(sorted(item["settlement"] for item in row["extras"] if timestamp(item["available_at"]) <= cutoff))
        if extras:
            expected["duplicate_settlement"].add((left, row["settlement"], extras))

    predictions = [row for result in results for row in result["matches"]]
    exceptions = [row for result in results for row in result["exceptions"]]
    predicted = {name: set() for name in CATEGORIES}
    abstentions = {}
    for row in exceptions:
        category, subject = row["category"], row["subject"]
        if category == "duplicate_settlement":
            ev = row["evidence"]
            predicted[category].add((subject, ev["original"], tuple(sorted(ev["extras"]))))
        elif category in CATEGORIES:
            predicted[category].add(subject)
        elif category == "ambiguous_match":
            abstentions[subject] = row["evidence"]
    wrong, misses = [], []
    matched = {row["ledger"]: row["settlement"] for row in predictions}
    for row in predictions:
        correct = available_truth.get(row["ledger"])
        if row["settlement"] != correct:
            wrong.append(dict(**row, true_settlement=correct,
                              likely_reason=("No eligible true settlement at this cutoff" if correct is None else
                                             "A competing reference was chosen instead of the true settlement")))
    for ledger, settlement in available_truth.items():
        if matched.get(ledger) != settlement:
            reason = abstentions.get(ledger, {}).get("reason", "different_link" if ledger in matched else
                                                    "no_eligible_or_retained_candidate")
            misses.append(dict(ledger=ledger, true_settlement=settlement, reason=reason))
    false_by_pass = Counter(row["method"] for row in wrong)
    breakdown = {name: metrics(expected[name], predicted[name]) for name in CATEGORIES}
    summary = dict(seed=truth["seed"], business_dates=sorted(reports), cutoffs={day: val.isoformat()
                   for day, val in cutoffs.items()}, config_hash=next(iter(reports.values()))["config_hash"],
                   excluded_invalid_rows=len(truth["invalid_rows"]), error_metrics=breakdown,
                   false_matches={name: false_by_pass[name] for name in ("exact", "diagnostic", "fuzzy")},
                   true_links=len(available_truth), predicted_links=len(predictions), missed_true_links=len(misses),
                   abstentions=len(abstentions), deliberate_ambiguities_retained=len(
                       set(truth["deliberate_ambiguity"]) & abstentions.keys()),
                   missed_link_reasons=dict(Counter(row["reason"] for row in misses)))
    output = Path(output)
    json_file(output / "metrics.json", summary)
    json_file(output / "mistake-analysis.json", {
        "false_fuzzy_matches": [row for row in wrong if row["method"] == "fuzzy"],
        "all_incorrect_links": wrong, "missed_true_links": misses, "abstentions": abstentions,
    })
    return summary
