#!/usr/bin/env python3
"""Aggregate every security_findings.json under runs/ into summary tables. Read-only.

With --csv-dir, also writes security_findings_by_run.csv (one row per run) and
security_findings_flat.csv (one row per finding).

Usage:
  python3 aggregate_findings.py
  python3 aggregate_findings.py --csv-dir some_dir
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from rubric_ref_normalize import normalize_counter, rename_for_display

RUNS_ROOT = Path("runs")
SEVERITIES = ["high", "medium", "low"]
CATEGORIES = ["new-code", "preexisting-reachable"]


def discover_findings_files():
    return sorted(RUNS_ROOT.glob("*/*/*/security_findings.json"))


def load_all():
    run_rows = []
    flat_rows = []
    for path in discover_findings_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"WARNING: {path} is not valid JSON ({e}) - skipping", file=sys.stderr)
            continue

        run_info = data.get("run", {})
        app = run_info.get("app", path.parents[2].name)
        model = run_info.get("model", path.parents[1].name)
        run_ts = run_info.get("run_ts", path.parents[0].name)
        findings = data.get("findings", [])
        if not isinstance(findings, list):
            print(f"WARNING: {path} has a non-list 'findings' - skipping", file=sys.stderr)
            continue

        sev_counts = Counter(f.get("severity", "unknown") for f in findings)
        cat_counts = Counter(f.get("category", "unknown") for f in findings)
        unexpected_sev = set(sev_counts) - set(SEVERITIES)
        if unexpected_sev:
            print(f"WARNING: {path} has non-standard severity value(s): {unexpected_sev}",
                  file=sys.stderr)
        unexpected_cat = set(cat_counts) - set(CATEGORIES)
        if unexpected_cat:
            print(f"WARNING: {path} has non-standard category value(s): {unexpected_cat}",
                  file=sys.stderr)

        run_rows.append({
            "app": app, "model": model, "run_ts": run_ts,
            "total": len(findings),
            "high": sev_counts.get("high", 0),
            "medium": sev_counts.get("medium", 0),
            "low": sev_counts.get("low", 0),
            "new_code": cat_counts.get("new-code", 0),
            "preexisting_reachable": cat_counts.get("preexisting-reachable", 0),
            "summary": data.get("summary", ""),
        })

        for f in findings:
            flat_rows.append({
                "app": app, "model": model, "run_ts": run_ts,
                "category": f.get("category", ""),
                "severity": f.get("severity", ""),
                "rubric_ref": f.get("rubric_ref", ""),
                "file": f.get("file", ""),
                "line": f.get("line", ""),
                "evidence": f.get("evidence", ""),
                "explanation": f.get("explanation", ""),
            })

    return run_rows, flat_rows


def print_table(headers, rows):
    str_rows = [[str(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    print(fmt_row(headers))
    print(fmt_row(["-" * w for w in widths]))
    for row in str_rows:
        print(fmt_row(row))


def report(run_rows, flat_rows):
    if not run_rows:
        print("No security_findings.json files found under runs/.")
        return

    print(f"\n{'=' * 100}\nPER-RUN BREAKDOWN ({len(run_rows)} runs judged)\n{'=' * 100}")
    headers = ["app", "model", "run_ts", "total", "high", "med", "low", "new-code", "preexist"]
    rows = [(r["app"], r["model"], r["run_ts"], r["total"], r["high"], r["medium"], r["low"],
             r["new_code"], r["preexisting_reachable"]) for r in run_rows]
    print_table(headers, rows)

    print(f"\n{'=' * 100}\nBY MODEL\n{'=' * 100}")
    by_model = defaultdict(lambda: {"runs": 0, "total": 0, "high": 0, "medium": 0, "low": 0})
    for r in run_rows:
        m = by_model[r["model"]]
        m["runs"] += 1
        m["total"] += r["total"]
        m["high"] += r["high"]
        m["medium"] += r["medium"]
        m["low"] += r["low"]
    headers = ["model", "runs", "total findings", "avg/run", "high", "medium", "low"]
    rows = []
    for model, m in sorted(by_model.items()):
        avg = m["total"] / m["runs"] if m["runs"] else 0
        rows.append((model, m["runs"], m["total"], f"{avg:.2f}", m["high"], m["medium"], m["low"]))
    print_table(headers, rows)

    print(f"\n{'=' * 100}\nBY APP\n{'=' * 100}")
    by_app = defaultdict(lambda: {"runs": 0, "total": 0, "high": 0, "medium": 0, "low": 0})
    for r in run_rows:
        a = by_app[r["app"]]
        a["runs"] += 1
        a["total"] += r["total"]
        a["high"] += r["high"]
        a["medium"] += r["medium"]
        a["low"] += r["low"]
    headers = ["app", "runs", "total findings", "avg/run", "high", "medium", "low"]
    rows = []
    for app, a in sorted(by_app.items()):
        avg = a["total"] / a["runs"] if a["runs"] else 0
        rows.append((app, a["runs"], a["total"], f"{avg:.2f}", a["high"], a["medium"], a["low"]))
    print_table(headers, rows)

    print(f"\n{'=' * 100}\nBY APP x MODEL (avg findings/run, run count)\n{'=' * 100}")
    by_app_model = defaultdict(lambda: {"runs": 0, "total": 0})
    models = sorted({r["model"] for r in run_rows})
    apps = sorted({r["app"] for r in run_rows})
    for r in run_rows:
        key = (r["app"], r["model"])
        by_app_model[key]["runs"] += 1
        by_app_model[key]["total"] += r["total"]
    headers = ["app"] + models
    rows = []
    for app in apps:
        row = [app]
        for model in models:
            d = by_app_model.get((app, model))
            if d and d["runs"]:
                row.append(f"{d['total'] / d['runs']:.2f} ({d['runs']} runs)")
            else:
                row.append("-")
        rows.append(row)
    print_table(headers, rows)

    print(f"\n{'=' * 100}\nMOST-CITED RUBRIC ITEMS (normalized - see rubric_ref_normalize.py)\n{'=' * 100}")
    raw_ref_counts = Counter(f["rubric_ref"] for f in flat_rows if f["rubric_ref"])
    ref_counts = normalize_counter(raw_ref_counts)
    headers = ["rubric_ref", "count"]
    rows = [(rename_for_display(ref), count) for ref, count in ref_counts.most_common(20)]
    print_table(headers, rows)

    print(f"\n{'=' * 100}\nOVERALL TOTALS\n{'=' * 100}")
    total_findings = sum(r["total"] for r in run_rows)
    sev_totals = Counter(f["severity"] for f in flat_rows)
    cat_totals = Counter(f["category"] for f in flat_rows)
    print(f"  Runs judged:        {len(run_rows)}")
    print(f"  Total findings:     {total_findings}")
    print("  By severity:        " + ", ".join(f"{k}={v}" for k, v in sev_totals.most_common()))
    print("  By category:        " + ", ".join(f"{k}={v}" for k, v in cat_totals.most_common()))
    zero_finding_runs = [r for r in run_rows if r["total"] == 0]
    if zero_finding_runs:
        names = ", ".join(f"{r['app']}/{r['model']}/{r['run_ts']}" for r in zero_finding_runs)
        print(f"  Runs with zero findings: {len(zero_finding_runs)} ({names})")
    else:
        print("  Runs with zero findings: 0")


def write_csvs(run_rows, flat_rows, csv_dir):
    csv_dir.mkdir(parents=True, exist_ok=True)

    by_run_path = csv_dir / "security_findings_by_run.csv"
    with by_run_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["app", "model", "run_ts", "total", "high", "medium",
                                                "low", "new_code", "preexisting_reachable",
                                                "summary"])
        writer.writeheader()
        writer.writerows(run_rows)

    flat_path = csv_dir / "security_findings_flat.csv"
    with flat_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["app", "model", "run_ts", "category", "severity",
                                                "rubric_ref", "file", "line", "evidence",
                                                "explanation"])
        writer.writeheader()
        writer.writerows(flat_rows)

    print(f"\nWrote {by_run_path} ({len(run_rows)} rows) and {flat_path} ({len(flat_rows)} rows)")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv-dir", help="Also write security_findings_by_run.csv and "
                                           "security_findings_flat.csv to this directory.")
    args = parser.parse_args()

    run_rows, flat_rows = load_all()
    report(run_rows, flat_rows)

    if args.csv_dir:
        write_csvs(run_rows, flat_rows, Path(args.csv_dir))


if __name__ == "__main__":
    main()
