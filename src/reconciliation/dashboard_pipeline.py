"""Run the engine on the dashboard's current synthetic inputs."""

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from threading import Lock, Thread

from sqlalchemy.exc import SQLAlchemyError

from .contracts import timestamp
from .db import event, query
from .ingestion import InvalidFile, ingest
from .matching import Rules
from .normalization import work
from .reconcile import reconcile
from .storage import file_hash


class PipelineError(ValueError):
    pass


MATCH_PHASES = {
    "exact": "Matching exact references and amounts",
    "diagnostic": "Checking amount mismatches",
    "fuzzy": "Scoring similar references",
}


def input_counts(db, file_ids):
    with db.connect() as conn:
        return dict(query(conn, """
            SELECT status,count(*) FROM input_quality
            WHERE file_id=ANY(CAST(:ids AS bigint[])) GROUP BY status
        """, ids=file_ids).all())


class DashboardPipeline:
    def __init__(self, db, store):
        self.db = db
        self.store = store
        self.lock = Lock()
        self.job = None

    def snapshot(self):
        with self.lock:
            return deepcopy(self.job)

    def start(self, dataset, inputs):
        # The dashboard holds its dataset lock while accepting a job or replacing inputs.
        with self.lock:
            if self.job and self.job["status"] == "running":
                return deepcopy(self.job)
            self.job = dict(dataset_id=dataset["id"], scope=f"dataset-{dataset['id']}",
                            status="running", stage="read", steps={"read": "Checking both CSVs…"}, reports=[])
            started = deepcopy(self.job)
            Thread(target=self.run, args=(dataset, inputs, started["scope"]), daemon=True).start()
            return started

    def step(self, name, detail):
        with self.lock:
            self.job["stage"] = name
            self.job["steps"][name] = detail

    def finish(self, error=None):
        with self.lock:
            self.job.update(status="failed" if error else "complete", error=error)

    def run(self, dataset, inputs, scope):
        try:
            self.process(dataset, inputs, scope)
        except PipelineError as exc:
            self.finish(str(exc))
        except InvalidFile:
            self.finish("A CSV could not be read by the ingestion pipeline. Generate a fresh dataset and try again.")
        except SQLAlchemyError as exc:
            event("dashboard-pipeline", scope=scope, error=type(exc).__name__)
            self.finish("PostgreSQL could not complete this run. Check that it is running and migrated, then retry.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            event("dashboard-pipeline", scope=scope, error=type(exc).__name__)
            self.finish("Could not read the dataset or configuration. Check the local files or generate a fresh dataset.")
        except Exception as exc:
            event("dashboard-pipeline", scope=scope, error=type(exc).__name__)
            self.finish("The reconciliation stopped unexpectedly. Check the dashboard terminal, then retry.")
        else:
            self.finish()

    def process(self, dataset, inputs, scope):
        manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
        files = manifest["files"]
        if (files != dataset["files"] or len(files) != 2
                or {item["name"] for item in files} != {"ledger.csv", "settlements.csv"}):
            raise PipelineError("The dataset manifest does not match the generated inputs.")
        for item in files:
            if file_hash(inputs / item["name"]) != item["sha256"]:
                raise PipelineError("A CSV has changed since generation. Generate a fresh dataset and try again.")
        days = sorted({date.fromisoformat(day) for day in manifest["business_dates"]})
        cutoff = timestamp(manifest["final_cutoff"])
        rules = Rules.read(Path("config/frozen.json"))
        if not days:
            raise PipelineError("The dataset manifest has no business dates.")
        self.step("read", "Verified both CSVs against the manifest.")

        file_ids = []
        for item in files:
            name = item["name"]
            self.step("stage", f"Extracting {name} into PostgreSQL…")
            file_ids.append(ingest(self.db, self.store, inputs / name, item["kind"], item["source"],
                                   item["date_format"], expected_sha=item["sha256"]))
        self.step("stage", "Both files staged and raw copies saved.")

        prior = input_counts(self.db, file_ids)
        total = sum(prior.values())
        validated = total - prior.get("pending", 0)
        if total != sum(item["rows"] for item in files):
            raise PipelineError("The staged row count does not match the dataset manifest.")

        def validation_progress(processed):
            self.step("validate", f"{validated + sum(processed.values()):,} of {total:,} rows checked.")

        validation_progress({})
        work(self.db, scope, file_ids=file_ids, progress=validation_progress)
        counts = input_counts(self.db, file_ids)
        if counts.get("pending"):
            raise PipelineError("Some rows are still being processed. Retry after the worker finishes.")
        self.step("validate", f"{counts.get('accepted', 0):,} accepted, {counts.get('rejected', 0):,} quarantined.")

        for index, day in enumerate(days, 1):
            date_detail = f"Day {index} of {len(days)} ({day})"
            self.step("match", f"{date_detail} · Loading validated transactions…")

            def match_progress(phase):
                if phase == "publish":
                    self.step("match", f"{date_detail} · Exact and fuzzy passes complete.")
                    self.step("publish", f"{date_detail} · Saving the report and exception queue…")
                else:
                    self.step("match", f"{date_detail} · {MATCH_PHASES[phase]}…")

            report, _ = reconcile(self.db, scope, day, cutoff, rules, file_ids, True, progress=match_progress)
            if report["status"] != "complete":
                raise PipelineError(f"Could not publish the report for {day}. Retry once the inputs are ready.")
            with self.lock:
                self.job["reports"].append({key: report[key] for key in (
                    "result_id", "business_date", "ledger_matched", "ledger_unmatched", "settlement_unmatched",
                )})
        self.step("publish", f"{len(days)} daily reports and their exceptions are ready.")
