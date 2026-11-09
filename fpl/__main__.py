"""Run with python -m fpl fetch ... or python -m fpl report ..."""

import argparse
import json
from pathlib import Path
import sys
import urllib.error

from .fetch import fetch_snapshot
from .report import markdown, reconcile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="Fetch nine official responses into a NEW snapshot")
    fetch.add_argument("--output", required=True, type=Path)
    fetch.add_argument("--players", nargs=4, type=int, default=[1, 4, 12, 411])
    fetch.add_argument("--gameweeks", nargs=2, type=int, default=[1, 2])
    report = commands.add_parser("report", help="Calculate offline from one saved observation")
    report.add_argument("snapshot", type=Path)
    report.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "fetch":
            snapshot = fetch_snapshot(args.output, args.players, args.gameweeks)
            print(f"Saved {len(snapshot['observations'])} responses to {args.output}")
            return 0
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        result = reconcile(snapshot)
        results_path = args.output_dir / "results.json"
        report_path = args.output_dir / "report.md"
        if any(path.exists() and path.samefile(args.snapshot) for path in (results_path, report_path)):
            raise ValueError("Report output would overwrite the input snapshot")
        report_text = markdown(snapshot, result)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        results_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_path.write_text(report_text, encoding="utf-8")
        print(f"{len(result['fixtures'])} fixtures; {len(result['gameweeks'])} player/GWs; {len(result['issues'])} diagnostics. Report: {report_path}")
        return 1 if result["issues"] else 0
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
