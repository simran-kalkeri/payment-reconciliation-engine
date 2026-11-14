import json
import os
import subprocess
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from .contracts import local_start, timestamp
from .db import engine
from .evaluation import evaluate
from .generator import DEV_SEED, EVAL_SEED, generate
from .ingestion import ingest
from .matching import Rules
from .normalization import verify_staged_replay, work
from .operations import counts
from .reconcile import reconcile
from .reporting import export, json_file
from .storage import LocalStore, file_hash
from .workbench import history, list_issues, review, show


def verify(db, scope, day, cutoff, rules, ids, *, initial=None, runner=None):
    run = runner or (lambda *args: reconcile(db, *args)[0])
    before_result = initial or run(scope, day, cutoff, rules, ids, True)
    if before_result["status"] != "complete":
        raise ValueError("Rerun verification requires a complete reconciliation")
    before = counts(db)
    checked = verify_staged_replay(db, ids)
    after_result = run(scope, day, cutoff, rules, ids, True)
    after = counts(db)
    stable = (after_result["status"] == "complete" and before == after
              and before_result["result_hash"] == after_result["result_hash"]
              and before_result["result_id"] == after_result["result_id"])
    if not stable:
        raise RuntimeError("Rerun changed the published business result or durable counts")
    return dict(staged_rows_replayed=checked, before=before, after=after,
                before_run=before_result["run_id"], after_run=after_result["run_id"],
                before_hash=before_result["result_hash"], after_hash=after_result["result_hash"], unchanged=stable)


def isolated_runner(root, exports, compose_file):
    rules_dir = root / "matcher-rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    exports.mkdir(parents=True, exist_ok=True)
    if not os.getenv("RECON_MATCHER_URL"):
        raise ValueError("Set RECON_MATCHER_URL to the restricted Compose database connection")
    env = {**os.environ, "RECON_MATCHER_RULES_DIR": str(rules_dir.resolve()),
           "RECON_MATCHER_EXPORT_DIR": str(exports.resolve())}
    if os.name == "posix":
        env.setdefault("RECON_MATCHER_UID", str(os.getuid()))
        env.setdefault("RECON_MATCHER_GID", str(os.getgid()))
    base = ["docker", "compose", "-f", str(compose_file), "--profile", "isolated"]
    subprocess.run([*base, "build", "matcher"], env=env, check=True)

    def run(scope, day, cutoff, rules, ids, complete):
        config_path = rules_dir / "active.json"
        json_file(config_path, asdict(rules))
        cmd = [*base, "run", "--rm", "--no-deps", "-T", "matcher", scope, day.isoformat(), cutoff.isoformat(),
               "--rules", "/app/config/active.json", "--out", "/exports"]
        for file_id in ids:
            cmd.extend(("--file", str(file_id)))
        if complete:
            cmd.append("--sources-complete")
        response = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        result = json.loads(response.stdout)
        report = result["report"]
        return report, exports / f"run-{report['run_id']}"

    return run


def run_demo(out, frozen, *, retune=False, isolated=False):
    load_dotenv()
    out = Path(out)
    db = engine()
    store = LocalStore(os.getenv("RECON_RAW_DIR", str(out / "raw")))
    exports = out / "exports"
    if isolated:
        run = isolated_runner(out, exports, Path("compose.yaml").resolve())
    else:
        def run(scope, day, cutoff, rules, ids, complete):
            report, evidence = reconcile(db, scope, day, cutoff, rules, ids, complete)
            return report, export(exports, report, evidence)

    def prepare(name, seed):
        inputs, truth = out / "inputs" / name, out / "truth" / name
        manifest = generate(inputs, truth, seed)
        ids = []
        for item in manifest["files"]:
            path = inputs / item["name"]
            if file_hash(path) != item["sha256"]:
                raise RuntimeError("Generated file failed manifest verification")
            ids.append(ingest(db, store, path, item["kind"], item["source"], item["date_format"]))
        work(db, f"{name}-worker", file_ids=ids)
        return inputs, truth / "answer_key.json", manifest, ids

    def run_dates(scope, manifest, rules, ids):
        cutoff = timestamp(manifest["final_cutoff"])
        return [run(scope, date.fromisoformat(day), cutoff, rules, ids, True)
                for day in manifest["business_dates"]]

    tuning = []
    if retune:
        _, truth, manifest, ids = prepare("development", DEV_SEED)
        for score, margin in ((80, 6), (88, 8), (94, 10)):
            rules = Rules(score, margin)
            reports = run_dates(f"development-{score}-{margin}", manifest, rules, ids)
            summary = evaluate(truth, [directory / "result.json" for _, directory in reports],
                               out / "development" / f"{score}-{margin}")
            tuning.append(dict(rules=asdict(rules), metrics=summary))
        def rank(candidate):
            metrics = candidate["metrics"]
            return (sum(metrics["false_matches"].values()), metrics["missed_true_links"],
                    sum(metric["fp"] for metric in metrics["error_metrics"].values()),
                    -candidate["rules"]["minimum_score"], -candidate["rules"]["minimum_margin"])

        winner = min(tuning, key=rank)
        json_file(frozen, winner["rules"])
        json_file(out / "development" / "selection.json", {"seed": DEV_SEED, "candidates": tuning, "chosen": winner["rules"]})
    rules = Rules.read(frozen)
    input_dir, truth, manifest, ids = prepare("evaluation", EVAL_SEED)
    day = date.fromisoformat(manifest["business_dates"][0])
    # A cutoff at the following midnight after the deadline precedes next-day arrivals.
    early_cutoff = local_start(day + timedelta(days=2))
    early, early_path = run("evaluation", day, early_cutoff, rules, ids, True)
    first_review = list_issues(db, scope="evaluation", day=day, category="missing_settlement", include_inactive=True)
    if not first_review:
        raise RuntimeError("Expected a missing settlement in the early snapshot")
    issue = first_review[0]
    if issue["review_status"] == "open":
        review(db, issue["id"], issue["version"], "demo-reviewer", "Confirmed from the early source export", "resolve")
    reports = run_dates("evaluation", manifest, rules, ids)
    final_cutoff = timestamp(manifest["final_cutoff"])
    summary = evaluate(truth, [directory / "result.json" for _, directory in reports], out / "evaluation")
    before = counts(db)
    replay_ids = [ingest(db, store, input_dir / item["name"], item["kind"], item["source"], item["date_format"])
                  for item in manifest["files"]]
    if ids != replay_ids or counts(db) != before:
        raise RuntimeError("Identical file delivery created new records")
    evidence = verify(db, "evaluation", day, final_cutoff, rules, ids, initial=reports[0][0],
                      runner=lambda *args: run(*args)[0])
    evidence["identical_file_reingest"] = True
    json_file(out / "rerun.json", evidence)
    issue_history = history(db, issue["id"])
    reviewed = show(db, issue["id"])
    if reviewed["review_status"] != "resolved":
        raise RuntimeError("Review resolution did not survive later data and rerun")
    json_file(out / "review.json", {"exception": issue["id"], "current_status": reviewed["review_status"],
                                  "active": reviewed["active"],
                                  "history": [{**row, "created_at": row["created_at"].isoformat()} for row in issue_history]})
    return dict(file_ids=ids, early_report=str(early_path), early_hash=early["result_hash"],
                final_reports=[str(directory) for _, directory in reports], metrics=summary,
                rerun=evidence, matcher_mode="isolated_container" if isolated else "local_trusted_process")
