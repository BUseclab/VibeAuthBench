#!/usr/bin/env python3
"""Autonomous phase, run inside the container. Takes no interactive input.

entrypoint_manual.py handles the rest once someone can register the redirect URI and click
through the login flow.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Pathspecs rather than .gitignore: these also exclude directories already in the baseline commit.
DIFF_EXCLUDE_PATHSPECS = [
    ":(exclude).pyenv", ":(exclude)*/.pyenv",
    ":(exclude)node_modules", ":(exclude)*/node_modules",
    ":(exclude)build", ":(exclude)*/build",
    ":(exclude)vendor", ":(exclude)*/vendor",
    ":(exclude)__generated__", ":(exclude)*/__generated__",
    ":(exclude)generated", ":(exclude)*/generated",
    ":(exclude)core.*", ":(exclude)*/core.*",
]


def strip_binary_file_sections(diff_text):
    kept_blocks = []
    for block in diff_text.split("diff --git "):
        if not block:
            continue
        section = "diff --git " + block
        if "Binary files " in section or "GIT binary patch" in section:
            continue
        kept_blocks.append(section)
    return "".join(kept_blocks)


def find_venv_pathspecs():
    # By marker file, not by name - the agent names its venvs unpredictably.
    result = subprocess.run(["find", ".", "-maxdepth", "4", "-name", "pyvenv.cfg"],
                             capture_output=True, text=True)
    specs = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.endswith("/pyvenv.cfg"):
            continue
        d = line[:-len("/pyvenv.cfg")]
        if d.startswith("./"):
            d = d[2:]
        if d:
            specs.append(f":(exclude){d}")
    return specs


def main():
    run_dir = Path(os.environ["RUN_DIR"])
    task_prompt = os.environ["TASK_PROMPT"]

    print("=== [1/6] Sanity check ===")
    sanity = subprocess.run(["claude", "--dangerously-skip-permissions", "-p", "hello"])
    if sanity.returncode != 0:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "status.txt").write_text(
            f"completed: no - sanity check failed (claude exited {sanity.returncode}) - "
            "never got to the real task\n"
        )
        print("Sanity check failed - aborting before spending the real task on a broken connection. "
              "status.txt written so the manual phase knows there's nothing to test.")
        sys.exit(1)

    print("=== [2/6] Real task ===")
    task = subprocess.run(["claude", "--dangerously-skip-permissions", "-p", task_prompt])
    task_exit = task.returncode

    print("=== [3/6] Saving diff + transcript ===")
    run_dir.mkdir(parents=True, exist_ok=True)
    # Stage first: `git diff` alone misses untracked files, where most of a new integration lives.
    subprocess.run(["git", "add", "-A"])
    # Against the root commit, not HEAD: a later commit inside the container would hide earlier
    # changes.
    root = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"],
                           capture_output=True, text=True).stdout.strip().splitlines()[0]
    diff = subprocess.run(
        ["git", "diff", "--cached", root, "--", ".", *DIFF_EXCLUDE_PATHSPECS, *find_venv_pathspecs()],
        capture_output=True, text=True)
    (run_dir / "diff.patch").write_text(strip_binary_file_sections(diff.stdout))

    claude_projects = Path.home() / ".claude" / "projects"
    if claude_projects.exists():
        shutil.copytree(claude_projects, run_dir / "claude-projects", dirs_exist_ok=True)

    if task_exit != 0:
        (run_dir / "status.txt").write_text(
            f"completed: no - claude exited with code {task_exit} "
            "(see claude-projects transcript for detail)\n"
        )
        print(f"Task errored out (exit {task_exit}). Diff/transcript saved anyway. "
              "The manual phase will find a final status already recorded and skip the server test.")
    else:
        print(f"\n=== Auto phase done. Diff/transcript saved to {run_dir}. "
              "Container left running - run the manual phase (steps 4-6) when ready. ===")


if __name__ == "__main__":
    main()
