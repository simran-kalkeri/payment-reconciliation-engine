import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import ProgrammingError

from reconciliation.db import query
from reconciliation.generator import generate
from reconciliation.ingestion import ingest
from reconciliation.normalization import work
from reconciliation.storage import LocalStore

pytestmark = pytest.mark.postgres


def test_restricted_runtime_executes_with_no_truth_modules_and_no_truth_table_access(database, tmp_path):
    root = Path(__file__).resolve().parents[2]
    role = f"matcher_{uuid4().hex}"
    with database.begin() as conn:
        schema = query(conn, "SELECT current_schema()").scalar_one()
        query(conn, f'CREATE ROLE "{role}"')
        query(conn, "CREATE TABLE evaluation_truth(secret text)")
        grants = (root / "scripts" / "matcher-grants.sql").read_text().splitlines()
        for line in grants:
            if line.startswith("GRANT"):
                sql = line.replace("recon_matcher", role).replace("SCHEMA public", f'SCHEMA "{schema}"')
                query(conn, sql)
    try:
        with pytest.raises(ProgrammingError), database.begin() as conn:
            query(conn, f'SET LOCAL ROLE "{role}"')
            query(conn, "SELECT secret FROM evaluation_truth")
        with pytest.raises(ProgrammingError), database.begin() as conn:
            query(conn, f'SET LOCAL ROLE "{role}"')
            query(conn, "SELECT payload FROM staged_rows")

        data, truth = tmp_path / "inputs", tmp_path / "truth"
        manifest = generate(data, truth, 22, 48, 2)
        ids = [ingest(database, LocalStore(tmp_path / "raw"), data / row["name"], row["kind"],
                      row["source"], row["date_format"]) for row in manifest["files"]]
        work(database)
        shutil.rmtree(truth)
        runtime = tmp_path / "runtime"
        for line in (root / ".dockerignore").read_text().splitlines():
            if line.startswith("!src/reconciliation/") and line.endswith(".py"):
                source = root / line[1:]
                target = runtime / "reconciliation" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        rules = runtime / "rules.json"
        shutil.copy2(root / "config" / "frozen.json", rules)
        url = database.url.update_query_dict({"options": f"-c search_path={schema} -c role={role}"})
        env = {**os.environ, "PYTHONPATH": str(runtime),
               "RECON_DATABASE_URL": url.render_as_string(hide_password=False)}
        out = runtime / "exports"
        args = [sys.executable, "-m", "reconciliation.matcher_entry", "restricted",
                manifest["business_dates"][0], manifest["final_cutoff"], "--rules", str(rules),
                "--out", str(out), "--sources-complete"]
        for file_id in ids:
            args.extend(("--file", str(file_id)))
        result = subprocess.run(args, cwd=runtime, env=env, capture_output=True, text=True, timeout=25)
        assert result.returncode == 0, result.stderr
        assert any(out.rglob("result.json"))
        assert not (runtime / "reconciliation" / "evaluation.py").exists()
    finally:
        with database.begin() as conn:
            query(conn, f'DROP OWNED BY "{role}"')
            query(conn, f'DROP ROLE "{role}"')
