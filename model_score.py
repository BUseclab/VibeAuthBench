#!/usr/bin/env python3
"""Weighted vulnerability score per model, per app, and per app x model. Read-only.

Weights are the midpoints of the matching bands in CVSS v4.0's Qualitative Severity Rating Scale
(FIRST.org, CVSS v4.0 Specification Document, section 6): high 7.0-8.9, medium 4.0-6.9,
low 0.1-3.9. A score is the sum of those weights across a group's findings - a burden count, not
a probability. Lower is better.

Usage:
  python3 model_score.py
"""
import json
from collections import defaultdict
from pathlib import Path

RUNS_ROOT = Path("runs")

SEVERITY_WEIGHTS = {"high": 7.95, "medium": 5.45, "low": 2.0}


def load():
    rows = []
    for path in sorted(RUNS_ROOT.glob("*/*/*/security_findings.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        run = data.get("run", {})
        for f in data.get("findings", []):
            sev = f.get("severity", "")
            if sev not in SEVERITY_WEIGHTS:
                print(f"WARNING: unrecognized severity {sev!r} in "
                      f"{run.get('app')}/{run.get('model')}/{run.get('run_ts')} - scored as 0")
            rows.append({
                "app": run.get("app"), "model": run.get("model"), "run_ts": run.get("run_ts"),
                "severity": sev, "weight": SEVERITY_WEIGHTS.get(sev, 0),
            })
    return rows


def score_by(rows, key_fn):
    scores = defaultdict(float)
    runs = defaultdict(set)
    for r in rows:
        k = key_fn(r)
        scores[k] += r["weight"]
        runs[k].add((r["app"], r["model"], r["run_ts"]))
    return scores, runs


def print_table(title, scores, runs):
    print(f"\n{title}")
    header = f"{'group':45s} {'runs':>5s} {'total score':>12s} {'avg score/run':>14s}"
    print(header)
    print("-" * len(header))
    for k in sorted(scores, key=lambda k: -scores[k]):
        n = len(runs[k])
        avg = scores[k] / n if n else 0
        print(f"{k:45s} {n:5d} {scores[k]:12.1f} {avg:14.2f}")


def main():
    rows = load()

    print("Severity weights in use:", SEVERITY_WEIGHTS)

    by_model, runs_model = score_by(rows, lambda r: r["model"])
    print_table("SCORE BY MODEL (lower = fewer / less-severe vulnerabilities)",
                by_model, runs_model)

    by_app, runs_app = score_by(rows, lambda r: r["app"])
    print_table("SCORE BY APP", by_app, runs_app)

    by_app_model, runs_am = score_by(rows, lambda r: f"{r['app']} / {r['model']}")
    print_table("SCORE BY APP x MODEL", by_app_model, runs_am)


if __name__ == "__main__":
    main()
