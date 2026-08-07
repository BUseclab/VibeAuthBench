#!/usr/bin/env python3
"""Print each run's final completion message, to check whether the agent named a redirect URI.

The auto phase runs two `claude -p` invocations - a short sanity check and the real task - each
writing its own session file, so the larger file is the task.

Usage:
  python3 show_completion.py            # every run under runs/, oldest first
  python3 show_completion.py traggo     # only one app
  python3 show_completion.py --pending  # only runs still in runs/pending_manual.txt
"""
import argparse
import json
import re
from pathlib import Path

# Bare paths must contain an OAuth keyword, so ordinary paths like /opt/traggo-base don't match.
URI_RE = re.compile(
    r"https?://[^\s`\"'()<>]+"
    r"|/[\w./-]*(?:callback|redirect|openid|oauth)[\w./-]*",
    re.IGNORECASE,
)
MENTIONS_RE = re.compile(r"\b(?:redirect|callback)\b", re.IGNORECASE)


def find_uri_candidates(text):
    seen = []
    for m in URI_RE.finditer(text):
        token = m.group(0).rstrip(".,;:")
        if token not in seen:
            seen.append(token)
    return seen

RUNS_DIR = Path("runs")
MANIFEST = RUNS_DIR / "pending_manual.txt"


def pending_run_dirs():
    if not MANIFEST.exists():
        return set()
    dirs = set()
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        _name, _app, _model, run_dir = line.split("\t")
        dirs.add(RUNS_DIR / Path(run_dir).relative_to("/runs"))
    return dirs


def real_task_session(run_dir):
    proj_root = run_dir / "claude-projects"
    if not proj_root.exists():
        return None
    candidates = [p for p in proj_root.glob("*/*.jsonl") if p.parent.parent == proj_root]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def last_assistant_text(session_path):
    text_parts = None
    with open(session_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("type") != "assistant":
                continue
            content = rec.get("message", {}).get("content", [])
            texts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
            if texts:
                text_parts = texts
    return "\n".join(text_parts) if text_parts else None


def iter_run_dirs(app_filter):
    for app_dir in sorted(RUNS_DIR.iterdir()):
        if not app_dir.is_dir():
            continue
        if app_filter and app_dir.name != app_filter:
            continue
        for model_dir in sorted(app_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            for run_dir in sorted(model_dir.iterdir()):
                if run_dir.is_dir():
                    yield run_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("app", nargs="?", help="only show this app (traggo/karaoke-eternal/babybuddy)")
    parser.add_argument("--pending", action="store_true", help="only runs still in pending_manual.txt")
    parser.add_argument("--summary", action="store_true",
                         help="one line per run: did the completion message mention a redirect/callback URI, "
                              "instead of dumping the full message")
    args = parser.parse_args()

    only_dirs = pending_run_dirs() if args.pending else None

    shown = 0
    for run_dir in iter_run_dirs(args.app):
        if only_dirs is not None and run_dir not in only_dirs:
            continue

        status_path = run_dir / "status.txt"
        status = status_path.read_text().strip() if status_path.exists() else None

        session = real_task_session(run_dir)
        completion = last_assistant_text(session) if session else None
        shown += 1

        if args.summary:
            label = str(run_dir)
            if not completion:
                print(f"{label}\tNO COMPLETION MESSAGE FOUND")
                continue
            uris = find_uri_candidates(completion)
            if uris:
                print(f"{label}\tURI FOUND -> {' | '.join(uris)}")
            elif MENTIONS_RE.search(completion):
                print(f"{label}\tmentions redirect/callback but no concrete URI - read the full message")
            else:
                print(f"{label}\tno mention of redirect/callback at all")
            continue

        print("=" * 100)
        print(run_dir)
        if status:
            print(f"[status.txt: {status}]")
        print("-" * 100)
        if completion:
            print(completion)
        else:
            print("(no completion message found - task may have errored before finishing, or claude-projects/ is missing)")
        print()

    if shown == 0:
        print("No matching runs found.")


if __name__ == "__main__":
    main()
