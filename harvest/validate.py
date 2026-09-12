#!/usr/bin/env python3
"""Gate for every change to this repo. Exits non-zero on any failure.

Checks, in order of how much damage they prevent:
  1. every ideas/*.yml validates against schema/idea.schema.json
  2. slug == filename
  3. the 30-entry cap is respected
  4. generated files are not out of date (i.e. nobody hand-edited them)
  5. no two live ideas are near-duplicates (warning, not failure)

Usage:
    python3 harvest/validate.py
"""

from __future__ import annotations

import difflib
import json
import subprocess
import sys
from pathlib import Path

import yaml

try:
    from jsonschema import Draft7Validator
except ImportError:
    print("pip install -r harvest/requirements.txt", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parent.parent
IDEAS = ROOT / "ideas"
SCHEMA = ROOT / "schema" / "idea.schema.json"
MAX_LIVE = 30
DUP_RATIO = 0.82

errors: list[str] = []
warnings: list[str] = []


def main() -> int:
    validator = Draft7Validator(json.loads(SCHEMA.read_text()))
    ideas = []

    for path in sorted(IDEAS.glob("*.yml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            errors.append(f"{path.name}: invalid YAML — {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{path.name}: not a YAML mapping")
            continue

        for err in sorted(validator.iter_errors(data), key=lambda e: e.path):
            where = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"{path.name}: {where}: {err.message}")

        if data.get("slug") != path.stem:
            errors.append(
                f"{path.name}: slug {data.get('slug')!r} does not match filename"
            )

        for ev in data.get("evidence") or []:
            if not str(ev.get("url", "")).startswith(("http://", "https://")):
                errors.append(f"{path.name}: evidence url is not a url: {ev.get('url')}")

        if data.get("status") in ("building", "shipped") and not data.get("repo"):
            warnings.append(
                f"{path.name}: status {data['status']} but no repo link — "
                "the registry should point at where the work lives"
            )

        ideas.append(data)

    # --- cap
    live = [i for i in ideas if i.get("status") == "live"]
    unpinned = [i for i in live if not i.get("pinned")]
    if len(live) > MAX_LIVE and unpinned:
        errors.append(
            f"{len(live)} live ideas exceeds the cap of {MAX_LIVE} and "
            f"{len(unpinned)} are unpinned — run harvest/render.py to evict"
        )

    # --- near-duplicate live entries
    for i, a in enumerate(live):
        for b in live[i + 1 :]:
            ratio = difflib.SequenceMatcher(
                None, a["title"].lower(), b["title"].lower()
            ).ratio()
            same_target = (
                a.get("target", {}).get("name", "").lower()
                == b.get("target", {}).get("name", "").lower()
            )
            if ratio > DUP_RATIO or (same_target and ratio > 0.55):
                warnings.append(
                    f"possible duplicate: {a['slug']} / {b['slug']} "
                    f"(title similarity {ratio:.2f}"
                    f"{', same target' if same_target else ''})"
                )

    # --- generated files current
    if not errors:
        drift = subprocess.run(
            [sys.executable, str(ROOT / "harvest" / "render.py"), "--check"],
            capture_output=True,
            text=True,
        )
        if drift.returncode != 0:
            errors.append(
                "generated files are out of date or were hand-edited — "
                + drift.stderr.strip().replace("\n", " ")
            )

    for w in warnings:
        print(f"warn  {w}")
    for e in errors:
        print(f"FAIL  {e}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} error(s)", file=sys.stderr)
        return 1
    print(
        f"\nok — {len(ideas)} idea file(s), {len(live)}/{MAX_LIVE} live"
        f"{f', {len(warnings)} warning(s)' if warnings else ''}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
