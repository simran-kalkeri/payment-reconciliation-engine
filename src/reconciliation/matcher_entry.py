"""Restricted runtime entry point. Accepts rule and output paths, never truth."""

import argparse
import json
from datetime import date
from pathlib import Path

from .contracts import timestamp
from .db import engine
from .matching import Rules
from .reconcile import reconcile
from .reporting import export


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope")
    parser.add_argument("day", type=date.fromisoformat)
    parser.add_argument("cutoff", type=timestamp)
    parser.add_argument("--file", action="append", type=int, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sources-complete", action="store_true")
    args = parser.parse_args()
    db = engine()
    report, evidence = reconcile(db, args.scope, args.day, args.cutoff, Rules.read(args.rules), args.file,
                                 args.sources_complete)
    directory = export(args.out, report, evidence)
    print(json.dumps({"directory": str(directory), "report": report}))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
