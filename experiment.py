#!/usr/bin/env python3
"""Batch runner for VibeAuthBench experiments.

Each experiment splits into an unattended phase and a manual one:

  launch       Start a container and run the autonomous steps. Records it in
               runs/pending_manual.txt.
  list         Show containers awaiting the manual phase.
  finish       Run the manual steps in one pending container.
  finish-list  Run the manual phase for the rows listed in a file.

Containers are kept alive with `sleep infinity`; removal is opt-in. The in-container logic is
entrypoint_auto.py and entrypoint_manual.py.
"""
import argparse
import fcntl
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from prompt_loader import build_task_prompt

APP_CONFIG = {
    "traggo": {
        "image": "vab-traggo",
        "server_start_cmd": "./build/traggo-server",
        "server_url": "http://localhost:3030",
    },
    "karaoke-eternal": {
        "image": "vab-karaoke-eternal",
        "server_start_cmd": "npm run serve",
        "server_url": "http://localhost:3000",
    },
    "babybuddy": {
        "image": "vab-babybuddy",
        "server_start_cmd": ".pyenv/bin/python manage.py runserver 0.0.0.0:8000",
        "server_url": "http://localhost:8000",
    },
}

MANIFEST = Path("runs/pending_manual.txt")
MANIFEST_LOCK = MANIFEST.with_suffix(".lock")


@contextmanager
def manifest_lock():
    MANIFEST_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_LOCK, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def container_name(app, model, run_ts):
    # Docker container names allow [a-zA-Z0-9][a-zA-Z0-9_.-]+ only.
    return f"vab-{app}-{model.replace('.', '-')}-{run_ts}"


def read_manifest():
    if not MANIFEST.exists():
        return []
    lines = [l for l in MANIFEST.read_text().splitlines() if l.strip()]
    return [tuple(l.split("\t")) for l in lines]


def write_manifest(rows):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text("".join("\t".join(r) + "\n" for r in rows))


def run_manual_phase(name):
    """Copy the current manual script into a container and run it interactively."""
    # A separate path, not the mount target: an active mount point can't be overwritten.
    subprocess.run(["sudo", "docker", "cp", "entrypoint_manual.py",
                    f"{name}:/entrypoint_manual_current.py"], check=True)
    return subprocess.run(
        ["sudo", "docker", "exec", "-it", name, "python3", "/entrypoint_manual_current.py"])


def cmd_launch(args):
    if args.app not in APP_CONFIG:
        sys.exit(f"No server config for app '{args.app}' - add an entry to APP_CONFIG in this script.")
    cfg = APP_CONFIG[args.app]

    task_prompt = build_task_prompt(args.app)

    run_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = f"/runs/{args.app}/{args.model}/{run_ts}"
    name = container_name(args.app, args.model, run_ts)

    Path("runs", args.app).mkdir(parents=True, exist_ok=True)
    cwd = Path.cwd()

    print(f"=== Launching {name} (kept alive - not --rm) ===")
    run_cmd = [
        "sudo", "docker", "run", "-d", "--name", name, "--network", "host",
        "-v", f"{cwd}/runs:/runs",
        "-v", f"{cwd}/entrypoint_auto.py:/entrypoint_auto.py:ro",
        "-v", f"{cwd}/entrypoint_manual.py:/entrypoint_manual.py:ro",
        "-e", f"ANTHROPIC_DEFAULT_OPUS_MODEL={args.model}",
        "-e", f"ANTHROPIC_DEFAULT_SONNET_MODEL={args.model}",
        "-e", f"ANTHROPIC_DEFAULT_HAIKU_MODEL={args.model}",
        "-e", f"RUN_DIR={run_dir}",
        "-e", f"TASK_PROMPT={task_prompt}",
        "-e", f"SERVER_START_CMD={cfg['server_start_cmd']}",
        "-e", f"SERVER_URL={cfg['server_url']}",
        "-w", f"/opt/{args.app}-base",
        cfg["image"], "sleep", "infinity",
    ]
    subprocess.run(run_cmd, check=True)

    print(f"=== Running auto phase (steps 1-3) in {name} ===")
    exec_cmd = ["sudo", "docker", "exec", name, "python3", "/entrypoint_auto.py"]
    result = subprocess.run(exec_cmd)

    with manifest_lock():
        rows = read_manifest()
        rows.append((name, args.app, args.model, run_dir))
        write_manifest(rows)

    print(f"=== {name}: auto phase exited {result.returncode}. "
          f"Container is still running - `experiment.py finish {name}` when ready. ===")


def cmd_list(args):
    rows = read_manifest()
    if not rows:
        print("No pending runs.")
        return
    for name, app, model, run_dir in rows:
        print(f"{name}\t{app}\t{model}\t{run_dir}")


def cmd_finish(args):
    rows = read_manifest()
    if not rows:
        sys.exit("No pending runs recorded.")

    if args.name:
        matches = [r for r in rows if r[0] == args.name]
        if not matches:
            sys.exit(f"No pending run named '{args.name}' found. Run `experiment.py list` to see options.")
        target = matches[0]
    else:
        target = rows[0]

    name, app, model, run_dir = target
    print(f"=== Finishing {name} ({app}/{model}, {run_dir}) ===")
    result = run_manual_phase(name)

    if not args.remove:
        print(f"=== {name}: --remove not passed (default) - leaving container running, still in "
              "pending_manual.txt. Pass --remove once you're actually done with it. ===")
        write_manifest(rows)
        return

    # An interrupted phase leaves the container's filesystem as the only record of the run.
    if result.returncode != 0:
        print(f"=== {name}: manual phase exited {result.returncode} (interrupted or errored) - "
              f"NOT removing despite --remove, so nothing is lost. Re-run `finish {name}` (or "
              f"put it in a finish-list file) once it actually completes, or `docker rm -f {name}` "
              "yourself if you're sure the container's state is worthless. ===")
        write_manifest(rows)
        return

    subprocess.run(["sudo", "docker", "rm", "-f", name])
    print(f"Removed container {name}.")
    write_manifest([r for r in rows if r[0] != name])


def cmd_finish_list(args):
    """Run the manual phase for the (app, model, run_ts) rows in a file, in order.

    Never removes containers; only drops finished rows from pending_manual.txt.
    """
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"No such file: {path}")

    approved = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Any whitespace, not just tabs - these files are hand-edited.
        parts = line.split()
        if len(parts) != 3:
            sys.exit(f"Bad line in {path} (expected app<whitespace>model<whitespace>run_ts): {line!r}")
        approved.append(tuple(parts))

    if not approved:
        sys.exit(f"No approved rows found in {path}.")

    for app, model, run_ts in approved:
        name = container_name(app, model, run_ts)
        rows = read_manifest()
        row_by_name = {r[0]: r for r in rows}

        if name not in row_by_name:
            print(f"=== Skipping {name}: not in pending_manual.txt "
                  "(already finished, removed, or never launched under this name) ===")
            continue

        _, _, _, run_dir = row_by_name[name]
        print(f"\n{'=' * 100}\n=== {name} ({app}/{model}, {run_dir}) ===\n{'=' * 100}")
        result = run_manual_phase(name)

        # Drop the row only on a clean exit, so an interrupt doesn't lose track of the run.
        if result.returncode != 0:
            print(f"=== {name}: manual phase exited {result.returncode} (interrupted or errored) - "
                  f"leaving it in pending_manual.txt. Container also left running, as always with "
                  f"finish-list - re-run finish-list (or `finish {name}`) once it actually completes. ===")
            continue

        remaining = [r for r in read_manifest() if r[0] != name]
        write_manifest(remaining)
        print(f"=== {name}: manual phase recorded, removed from pending_manual.txt. "
              f"Container left running (not removed) - `docker rm -f {name}` yourself when done with it. ===")

    print("\n=== finish-list: done with all rows in the file. ===")


def main():
    parser = argparse.ArgumentParser(description="Run VibeAuthBench experiments in batch (see module docstring).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_launch = sub.add_parser("launch", help="Start a container and run the autonomous phase (steps 1-3).")
    p_launch.add_argument("app", help="base application to run against (a key of APP_CONFIG)")
    p_launch.add_argument("model", help="exact --served-model-name used in vllm serve")
    p_launch.set_defaults(func=cmd_launch)

    p_list = sub.add_parser("list", help="List containers awaiting the manual phase.")
    p_list.set_defaults(func=cmd_list)

    p_finish = sub.add_parser("finish", help="Run the manual phase (steps 4-6) for one pending container.")
    p_finish.add_argument("name", nargs="?", help="container name (see `list`); omit to take the oldest pending one")
    p_finish.add_argument("--remove", action="store_true",
                           help="remove the container after a successful manual phase (default: keep it "
                                "running). Ignored - container is kept regardless - if the manual phase "
                                "didn't exit cleanly (e.g. Ctrl+C mid-prompt).")
    p_finish.set_defaults(func=cmd_finish)

    p_finish_list = sub.add_parser(
        "finish-list",
        help="Run the manual phase for exactly the approved (app, model, run_ts) rows in a file, "
             "in order. Never removes containers - only drops finished rows from pending_manual.txt."
    )
    p_finish_list.add_argument("file", help="tab-separated file: app<TAB>model<TAB>run_ts per line, '#' comments allowed")
    p_finish_list.set_defaults(func=cmd_finish_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
