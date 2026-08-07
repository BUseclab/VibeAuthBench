#!/usr/bin/env python3
"""Builds the task prompt from prompts.json and per-app credentials in .env.

.env is read on the host and never enters the container; only the rendered prompt does.
"""
import json
import sys
from pathlib import Path


def load_env(path=Path(".env")):
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def build_task_prompt(app):
    prompts_file = Path("prompts.json")
    if not prompts_file.exists():
        sys.exit("Missing prompts.json in the current directory.")
    templates = json.loads(prompts_file.read_text())
    if app not in templates:
        sys.exit(f"No prompt template for app '{app}' in prompts.json.")

    env = load_env()
    client_id_key = f"{app.upper()}_GOOGLE_CLIENT_ID"
    client_secret_key = f"{app.upper()}_GOOGLE_CLIENT_SECRET"
    client_id = env.get(client_id_key)
    client_secret = env.get(client_secret_key)
    if not client_id or not client_secret:
        sys.exit(f"Missing {client_id_key} and/or {client_secret_key} in .env "
                 "(see .env.example for the expected format).")

    return templates[app].format(client_id=client_id, client_secret=client_secret)
