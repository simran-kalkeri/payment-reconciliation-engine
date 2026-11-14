import json
import os
from datetime import date
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import SQLAlchemyError

from . import operations, workbench
from .contracts import timestamp
from .db import engine, event
from .ingestion import ingest
from .matching import Rules
from .normalization import verify_staged_replay, work
from .reconcile import reconcile, snapshot
from .reporting import export
from .storage import LocalStore

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False, add_completion=False)
issues = typer.Typer(no_args_is_help=True)
app.add_typer(issues, name="issues")


def print_json(value):
    typer.echo(json.dumps(value, indent=2, sort_keys=True, default=str))


@app.command()
def migrate(config: Path = Path("alembic.ini")):
    """Apply schema migrations."""
    command.upgrade(Config(str(config)), "head")


@app.command()
def generate(inputs: Path, truth_dir: Path, seed: int = 4242, count: int = 12400, per_category: int = 140,
             two_files: bool = typer.Option(False, help="Write one ledger CSV and one settlement CSV."),
             merchant_profiles: bool = typer.Option(False, help="Vary amounts, fees and arrival times by merchant.")):
    """Generate synthetic inputs and a separate answer key."""
    from .generator import generate as create_data
    print_json(create_data(inputs, truth_dir, seed, count, per_category, two_files=two_files,
                           merchant_profiles=merchant_profiles))


@app.command("ingest")
def ingest_command(path: Path, kind: str, source: str, date_format: str = "iso",
                   batch_size: int = typer.Option(500, min=1)):
    """Capture and stage a declared CSV."""
    db = engine()
    store = LocalStore(os.getenv("RECON_RAW_DIR", "artifacts/work/raw"))
    print_json({"file_id": ingest(db, store, path, kind, source, date_format, batch_size)})


@app.command("worker")
def worker_command(name: str = "local", batch_size: int = typer.Option(250, min=1),
                   file: list[int] = typer.Option(None), watch: bool = False):
    """Process staged rows. Use --watch for a persistent worker."""
    print_json(work(engine(), name, batch_size, file or None, watch))


@app.command("reconcile")
def reconcile_command(scope: str, day: str, cutoff: str, file: list[int] = typer.Option(...),
                      rules: Path = Path("config/frozen.json"), out: Path = Path("artifacts/work/exports"),
                      sources_complete: bool = False):
    """Run one business date and export a result or diagnostic."""
    report, evidence = reconcile(engine(), scope, date.fromisoformat(day), timestamp(cutoff), Rules.read(rules),
                                 file, sources_complete)
    print_json({"directory": str(export(out, report, evidence)), "report": report})
    if report["status"] != "complete":
        raise typer.Exit(2)


@app.command()
def report(result_id: int, out: Path = Path("artifacts/work/exports")):
    """Re-export an immutable result snapshot."""
    summary, evidence = snapshot(engine(), result_id)
    print_json({"directory": str(export(out, summary, evidence))})


@app.command()
def evaluate(truth: Path, result: list[Path] = typer.Option(...), out: Path = Path("artifacts/work/evaluation")):
    """Score result exports against truth without connecting to PostgreSQL."""
    from .evaluation import evaluate as score
    print_json(score(truth, result, out))


@app.command("verify-rerun")
def verify_command(scope: str, day: str, cutoff: str, file: list[int] = typer.Option(...),
                   rules: Path = Path("config/frozen.json")):
    """Replay staged evidence and compare publication hashes and state."""
    from .demo import verify
    print_json(verify(engine(), scope, date.fromisoformat(day), timestamp(cutoff), Rules.read(rules), file))


@app.command()
def demo(out: Path = Path("artifacts/work"), frozen: Path = Path("config/frozen.json"),
         retune: bool = False, isolated: bool = False):
    """Run generation, ingest, review, reconciliation, evaluation and replay."""
    from .demo import run_demo
    print_json(run_demo(out, frozen, retune=retune, isolated=isolated))


@app.command()
def health():
    """Inspect database readiness, backlog and operation counters."""
    print_json(operations.health(engine()))


@app.command()
def files():
    """Show file IDs and staging progress."""
    print_json(operations.file_status(engine()))


@app.command()
def dashboard(port: int = typer.Option(8765, min=1, max=65535), link_file: Path | None = None,
              open_browser: bool = typer.Option(False, help="Open the dashboard in your default browser."),
              local_demo: bool = typer.Option(False, "--local-demo",
                                              help="Skip sign-in for a trusted local demo with sample data.")):
    """Serve the report and review dashboard on this computer."""
    from .dashboard import serve
    serve(engine(), port, link_file, open_browser=open_browser, local_demo=local_demo)


@issues.command("list")
def issue_list(scope: str | None = None, day: str | None = None, category: str | None = None,
               status: str | None = None, merchant: str | None = None,
               min_amount: int | None = typer.Option(None, min=0), max_amount: int | None = typer.Option(None, min=0),
               include_inactive: bool = False, limit: int = typer.Option(100, min=1, max=500), after: int = 0):
    print_json(workbench.list_issues(engine(), scope=scope, day=date.fromisoformat(day) if day else None,
                                    category=category, status=status, merchant=merchant, min_amount=min_amount,
                                    max_amount=max_amount, include_inactive=include_inactive, limit=limit, after=after))


@issues.command()
def show(id: int):
    print_json(workbench.show(engine(), id))


@issues.command()
def history(id: int):
    print_json(workbench.history(engine(), id))


@issues.command()
def resolve(id: int, version: int = typer.Option(...), actor: str = typer.Option(...),
            reason: str = typer.Option(...)):
    print_json(workbench.review(engine(), id, version, actor, reason, "resolve"))


@issues.command()
def reopen(id: int, version: int = typer.Option(...), actor: str = typer.Option(...),
           reason: str = typer.Option(...)):
    print_json(workbench.review(engine(), id, version, actor, reason, "reopen"))


def main():
    try:
        app()
    except (SQLAlchemyError, OSError) as exc:
        event("cli", status="failed", error=type(exc).__name__)
        raise SystemExit(1) from None
    except ValueError as exc:
        event("cli", status="failed", error=type(exc).__name__, message=str(exc))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
