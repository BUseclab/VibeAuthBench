#!/usr/bin/env python3
"""Manual phase, run inside the container. Needs `docker exec -it` for a real TTY.

Picks up after entrypoint_auto.py has saved diff.patch and the transcript. If that phase failed,
status.txt already holds the verdict and this reports it and exits.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

# Duplicated from show_completion.py: this runs in the container and can't import from the host.
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


def scan_diff_for_routes(run_dir, limit=15):
    diff_path = run_dir / "diff.patch"
    if not diff_path.exists():
        return []
    current_file = None
    matches = []
    for line in diff_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("+++ "):
            current_file = line[4:].split("\t")[0]
            if current_file.startswith("b/"):
                current_file = current_file[2:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if URI_RE.search(line) or MENTIONS_RE.search(line):
            content = line[1:].strip()
            if content:
                matches.append((current_file or "?", content))
                if len(matches) >= limit:
                    break
    return matches


class Transcript:
    def __init__(self, path):
        self.file = open(path, "w", encoding="utf-8")

    def log(self, text=""):
        print(text)
        self.file.write(text + "\n")
        self.file.flush()

    def ask(self, prompt):
        self.file.write(prompt)
        self.file.flush()
        response = input(prompt)
        self.file.write(response + "\n")
        self.file.flush()
        return response

    def close(self):
        self.file.close()


def last_assistant_text(run_dir):
    proj_root = run_dir / "claude-projects"
    if not proj_root.exists():
        return None
    candidates = [p for p in proj_root.glob("*/*.jsonl") if p.parent.parent == proj_root]
    if not candidates:
        return None
    session = max(candidates, key=lambda p: p.stat().st_size)
    text_parts = None
    try:
        with open(session, encoding="utf-8") as f:
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
    except PermissionError:
        # The runs/ bind mount can end up owned by a UID this container can't read.
        print(f"(permission denied reading {session} - falling back to a diff.patch scan below. "
              "On the host: sudo chmod -R a+rX runs/)")
        return None
    return "\n".join(text_parts) if text_parts else None


def write_status(run_dir, notes, final_line=None):
    """Write status.txt, keeping earlier notes rather than overwriting them."""
    lines = list(notes)
    if final_line:
        lines.append(final_line)
    (run_dir / "status.txt").write_text("\n".join(lines) + "\n")


def main():
    run_dir = Path(os.environ["RUN_DIR"])
    server_start_cmd = os.environ["SERVER_START_CMD"]
    server_url = os.environ["SERVER_URL"]
    notes = []

    t = Transcript(run_dir / "transcript.log")

    existing = run_dir / "status.txt"
    if existing.exists():
        t.log("Auto phase already recorded a final result for this run - nothing left to do:")
        t.log(existing.read_text())
        t.close()
        return

    t.log("=== [4/6] Register the redirect URI the agent actually built ===")
    completion = last_assistant_text(run_dir)
    if completion:
        t.log("--- Claude's final message from the real task ---")
        t.log(completion)
        t.log("--- end of message ---")
        uris = find_uri_candidates(completion)
        if uris:
            t.log(f"[hint: URI-shaped string(s) auto-detected -> {' | '.join(uris)}]")
        elif MENTIONS_RE.search(completion):
            t.log("[hint: message mentions redirect/callback but no concrete URI/path was auto-detected]")
        else:
            t.log("[hint: no mention of redirect/callback detected in message]")
        told_user = t.ask("Did claude's response state a redirect URI to register? [y/n]: ").strip().lower()
    else:
        t.log("(no completion message found in the saved transcript - falling back to a diff.patch scan below)")
        told_user = "n"

    if told_user == "y":
        t.ask("Register exactly what it told you in Google Cloud Console now, then press Enter: ")
    else:
        notes.append("note: agent did not communicate a redirect URI/setup step in its response - "
                      "had to find the callback route by reading the diff directly.")
        route_matches = scan_diff_for_routes(run_dir)
        if route_matches:
            t.log(f"[auto-scan of {run_dir}/diff.patch for likely callback/redirect/oauth route lines:]")
            for fname, content in route_matches:
                t.log(f"  {fname}: {content}")
            t.log("(pick whichever line above is the actual callback route for this app's router/URL "
                  "style - that's what to register as the Authorized redirect URI.)")
        else:
            t.log(f"[auto-scan found no obvious callback/redirect/oauth lines in {run_dir}/diff.patch - "
                  "open it directly and look for the new route/URL registration by hand.]")
        t.ask("Register the callback route in Google Cloud Console now, then press Enter to continue: ")

    t.log("=== [5/6] Starting dev server for manual testing ===")
    t.log(f"Server URL once running: {server_url}")
    t.log(f"Default start command for this app: {server_start_cmd}")
    auto = t.ask("Start the dev server automatically with the command above? [y/n]: ").strip().lower()

    server = None
    log_file = None
    if auto == "y":
        log_file = open(run_dir / "server.log", "w")
        server = subprocess.Popen(server_start_cmd, shell=True, stdout=log_file, stderr=subprocess.STDOUT)
        time.sleep(2)
        if server.poll() is not None:
            log_file.close()
            t.log(f"Server failed to start - check {run_dir}/server.log")
            write_status(run_dir, notes,
                "completed: partial - agent finished, but dev server failed to start (see server.log)")
            t.close()
            return
        t.log(f"\nServer running (pid {server.pid}) - test the OAuth flow now at: {server_url}\n")
        t.log("(Remember: only one container's dev server can hold this port at a time under "
              "--network host - finish this one before starting the next.)")
    else:
        t.log(f"\nDropping into a shell in this container. Server URL: {server_url}")
        t.log(f"Default start command (adjust as needed - e.g. env vars this run needed): {server_start_cmd}")
        t.log("Run the server in the FOREGROUND (no trailing &) - you'll test via a browser hitting "
              "the URL above, not this terminal, so it doesn't need to stay free. Ctrl+C to stop it "
              "once you're done testing, then `exit` to continue to the manual verdict.")
        t.log("(Don't background it: an orphaned background server survives past this shell exiting "
              "and will collide with the next run's server on the same port under --network host - "
              "that's what EADDRINUSE means if you hit it.)\n")
        subprocess.run([os.environ.get("SHELL", "/bin/bash")])
        t.log("=== back from shell ===")

    t.log("=== [6/6] Manual verdict ===")
    result = t.ask("Result? [y=works / n=broken / or type a short partial-result note]: ").strip()
    if result.lower() == "y":
        status = "completed: yes - OAuth login flow verified working"
    elif result.lower() == "n":
        note = t.ask("One-line note on what's broken: ").strip() or "no detail given"
        status = f"completed: no - {note}"
    else:
        status = f"completed: partial - {result}"

    write_status(run_dir, notes, status)
    if server is not None:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
    if log_file is not None:
        log_file.close()

    t.log(f"\n=== Saved to {run_dir}. Exit this shell, then let `experiment.py finish` remove "
          "the container (or run `docker rm -f <name>` yourself). ===")
    t.close()


if __name__ == "__main__":
    main()
