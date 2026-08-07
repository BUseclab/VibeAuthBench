#!/usr/bin/env python3
"""Normalize security_findings.json's `rubric_ref` strings into canonical rubric items.

The judge cites items inconsistently - tersely, with a gloss appended, or two at once as
"X (and Y)" or "X / Y" - so each variant would otherwise become its own near-duplicate bucket.
The canonical vocabulary is parsed from the source documents themselves: the cheatsheet's `N. `
numbering and the Google doc's `## ` headings.

Used by aggregate_findings.py so its counts match this script's.

Usage:
  python3 rubric_ref_normalize.py    # print the audit trace and final counts
"""
import re
from collections import Counter
from pathlib import Path

CHEATSHEET_PATH = Path(__file__).parent / "OWASP_OAuth2_Cheat_Sheet.md"
GOOGLE_DOC_PATH = Path(__file__).parent / "Google_OAuth2_BestPractices.md"


def parse_owasp_item_numbers():
    text = CHEATSHEET_PATH.read_text(encoding="utf-8")
    return {int(m.group(1)) for m in re.finditer(r"(?m)^(\d+)\.\s", text)}


def parse_google_doc_headings():
    text = GOOGLE_DOC_PATH.read_text(encoding="utf-8")
    return {line[3:].strip() for line in text.splitlines() if line.startswith("## ")}


OWASP_ITEM_NUMBERS = parse_owasp_item_numbers()
GOOGLE_DOC_HEADINGS = parse_google_doc_headings()


def is_canonical(item):
    m = re.match(r"^cheatsheet #(\d+)$", item)
    if m:
        return int(m.group(1)) in OWASP_ITEM_NUMBERS
    m = re.match(r"^google-doc:\s*(.+)$", item)
    if m:
        return m.group(1).strip() in GOOGLE_DOC_HEADINGS
    return False


def _prefix_and_body(ref):
    if ref.startswith("cheatsheet "):
        return "cheatsheet ", ref[len("cheatsheet "):]
    if ref.startswith("google-doc:"):
        return "google-doc: ", ref[len("google-doc:"):].strip()
    return None, ref


def normalize_rubric_ref(raw_ref, trace=None):
    """Return the canonical items a raw rubric_ref counts toward - one ref can yield several."""
    ref = raw_ref.strip()

    def log(msg):
        if trace is not None:
            trace.append(msg)

    if is_canonical(ref):
        log(f"{ref!r} -> already canonical, unchanged")
        return [ref]

    if ref.endswith(")") and " (and " in ref:
        first, rest = ref.split(" (and ", 1)
        first, rest = first.strip(), rest[:-1].strip()
        if is_canonical(first) and is_canonical(rest):
            log(f"{ref!r} -> split (joint '(and' citation) into {first!r} + {rest!r}")
            return [first, rest]

    # Split only if every part verifies on its own; a "/" inside one item's body text is not a
    # second citation.
    if " / " in ref:
        prefix, body = _prefix_and_body(ref)
        if prefix:
            parts = [p.strip() for p in body.split(" / ")]
            if len(parts) >= 2:
                candidates = [f"{prefix}{p}" for p in parts]
                if all(is_canonical(c) for c in candidates):
                    log(f"{ref!r} -> split ('/' citation, all {len(candidates)} parts "
                        f"independently verified canonical) into {candidates}")
                    return candidates

    prefix, body = _prefix_and_body(ref)
    if prefix == "cheatsheet ":
        m = re.match(r"#\d+", body)
        if m:
            candidate = f"cheatsheet {m.group(0)}"
            if is_canonical(candidate) and candidate != ref:
                log(f"{ref!r} -> merged (trailing text after a real item number) into {candidate!r}")
                return [candidate]
    elif prefix == "google-doc: ":
        for heading in GOOGLE_DOC_HEADINGS:
            if body.startswith(heading):
                candidate = f"google-doc: {heading}"
                log(f"{ref!r} -> merged (trailing text after a real heading) into {candidate!r}")
                return [candidate]

    log(f"{ref!r} -> UNRESOLVED - could not verify against either source doc, left as its own bucket")
    return [ref]


def normalize_counter(raw_counter, trace=None):
    out = Counter()
    for ref, n in raw_counter.items():
        for item in normalize_rubric_ref(ref, trace=trace):
            out[item] += n
    return out


def rename_for_display(item):
    if item.startswith("cheatsheet #"):
        return "OWASP " + item[len("cheatsheet "):]
    if item.startswith("google-doc:"):
        return "Google:" + item[len("google-doc:"):]
    return item


def _load_raw_counter():
    import json
    import glob
    raw_counter = Counter()
    for path in sorted(glob.glob("runs/*/*/*/security_findings.json")):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for f in data.get("findings", []):
            r = f.get("rubric_ref", "")
            if r:
                raw_counter[r] += 1
    return raw_counter


def audit_report():
    raw_counter = _load_raw_counter()
    trace = []
    normalized = normalize_counter(raw_counter, trace=trace)
    unresolved = [line for line in trace if "UNRESOLVED" in line]

    lines = [
        f"OWASP cheatsheet item numbers found in {CHEATSHEET_PATH.name}: {sorted(OWASP_ITEM_NUMBERS)}",
        f"Google-doc headings found in {GOOGLE_DOC_PATH.name}:",
    ]
    lines += [f"  - {h}" for h in sorted(GOOGLE_DOC_HEADINGS)]
    lines += ["", f"{len(raw_counter)} distinct raw rubric_ref strings observed. Decisions:", ""]
    lines += sorted(trace)
    lines += [
        "",
        f"-> {len(normalized)} canonical items after normalization "
        f"({len(unresolved)} unresolved, left as their own bucket)",
        "",
        "Final canonical counts:",
    ]
    for item, count in normalized.most_common():
        lines.append(f"  {count:3d}  {rename_for_display(item)}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(audit_report())
