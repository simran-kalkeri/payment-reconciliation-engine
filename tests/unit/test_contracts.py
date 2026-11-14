import ast
from pathlib import Path

import pytest

from reconciliation.contracts import InvalidRow, amount, local_date, timestamp
from reconciliation.evaluation import explain_misses, metrics
from reconciliation.generator import generate


@pytest.mark.parametrize("text,minor", [("0", 0), ("0.01", 1), ("12.3", 1230), ("10000.25", 1000025)])
def test_minor_units_are_exact(text, minor):
    assert amount(text, "amount") == minor


@pytest.mark.parametrize("text", ["1.001", "-1", "NaN", "1e2", "1,200.00", "99999999999999"])
def test_unsupported_amounts_are_rejected(text):
    with pytest.raises(InvalidRow):
        amount(text, "amount")


def test_declared_dates_and_timezone():
    assert local_date("03/02/2025", "dmy").isoformat() == "2025-02-03"
    assert local_date("03-FEB-2025", "named").isoformat() == "2025-02-03"
    with pytest.raises(ValueError):
        local_date("03/02/2025", "iso")
    assert timestamp("2025-05-14T00:00:00+05:30").isoformat() == "2025-05-13T18:30:00+00:00"
    with pytest.raises(ValueError):
        timestamp("2025-05-14T00:00:00")


def test_generator_repeats_exact_bytes_and_separates_truth(tmp_path):
    for label in ("a", "b"):
        generate(tmp_path / label / "inputs", tmp_path / label / "truth", 11, 48, 2)
    for file in (tmp_path / "a").rglob("*"):
        if file.is_file():
            assert file.read_bytes() == (tmp_path / "b" / file.relative_to(tmp_path / "a")).read_bytes()
    assert not (tmp_path / "a" / "inputs" / "answer_key.json").exists()
    with pytest.raises(ValueError):
        generate(tmp_path / "nested", tmp_path / "nested" / "truth", 11, 48, 2)


def test_zero_denominators_are_undefined():
    assert metrics(set(), set()) == dict(tp=0, fp=0, fn=0, support=0, precision=None, recall=None)


def test_explain_misses_distinguishes_fuzzy_rules_from_missing_evidence():
    misses = [
        {"ledger": "A", "true_settlement": "X", "reason": "below_score_or_reciprocal_margin"},
        {"ledger": "B", "true_settlement": "Y", "reason": "below_score_or_reciprocal_margin"},
        {"ledger": "C", "true_settlement": "Z", "reason": "no_eligible_or_retained_candidate"},
        {"ledger": "D", "true_settlement": "W", "reason": "different_link"},
    ]
    evidence = {
        "A": {"candidates": [{"ledger": "A", "settlement": "X", "score": 93},
                             {"ledger": "other", "settlement": "X", "score": 93}]},
        "B": {"candidates": [{"ledger": "B", "settlement": "Y", "score": 75}]},
    }
    result = explain_misses({"missed_true_links": misses, "abstentions": evidence,
                             "all_incorrect_links": [{"ledger": "D", "method": "fuzzy"}]}, 80, 6)
    assert result["reason_counts"] == {
        "Tied candidates": 1, "Reference score too low": 1,
        "No candidate retained": 1, "Wrong settlement linked": 1,
    }
    assert "93/100" in result["cases"][0]["detail"] and "6 points" in result["cases"][0]["detail"]
    assert "75/100" in result["cases"][1]["detail"] and "80" in result["cases"][1]["detail"]
    assert "can't identify" in result["cases"][2]["detail"]


def test_isolated_matcher_imports_only_runtime_files():
    root = Path(__file__).resolve().parents[2]
    allowed = {Path(line).stem for line in (root / ".dockerignore").read_text().splitlines()
               if line.startswith("!src/reconciliation/") and line.endswith(".py")}
    assert {"matcher_entry", "matching", "reconcile"} <= allowed
    assert not allowed & {"cli", "demo", "evaluation", "generator"}
    for name in allowed:
        tree = ast.parse((root / "src" / "reconciliation" / f"{name}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.module in allowed
            if isinstance(node, ast.ImportFrom) and node.module == "reconciliation":
                assert {item.name for item in node.names} <= allowed
