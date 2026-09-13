#!/usr/bin/env python3
"""Gate for every change to this repo. Exits non-zero on any failure.

Checks, in order of how much damage they prevent:
  1. every ideas/*.yml validates against schema/idea.schema.json
  2. slug == filename
  3. the 30-entry cap is respected
  4. harvest/sources.yml is coherent and inside the source cap
  5. generated files are not out of date (i.e. nobody hand-edited them)
  6. no two live ideas are near-duplicates (warning, not failure)

Usage:
    python3 harvest/validate.py
"""

from __future__ import annotations

import difflib
import json
import subprocess
import sys
from datetime import date, datetime
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
SOURCES = ROOT / "harvest" / "sources.yml"
MAX_LIVE = 30
DUP_RATIO = 0.82

sys.path.insert(0, str(ROOT / "harvest"))
import harvest  # noqa: E402  -- for COLLECTORS, the one list of what exists

# What each collector cannot work without. A source missing one of these fails at
# 3am inside a try/except and reads as "the world went quiet" for weeks.
REQUIRED_PARAMS = {
    "rss": ["url"],
    "discourse": ["host"],
    "lemmy": ["instance", "community"],
    "stackexchange": ["site"],
    "github_search": ["query"],
    "hn_algolia": [],
    "lobsters": [],
    "killedbygoogle": [],
}
GROUPS = {"pain", "enshittification", "mandate", "vacancy"}

errors: list[str] = []
warnings: list[str] = []


def iso_dates(node):
    """Match render.py: an unquoted YAML date is a date object, not a string."""
    if isinstance(node, dict):
        return {k: iso_dates(v) for k, v in node.items()}
    if isinstance(node, list):
        return [iso_dates(v) for v in node]
    if isinstance(node, (date, datetime)):
        return node.isoformat()[:10]
    return node


def check_sources() -> None:
    """sources.yml is not schema-validated -- its shape is per-collector -- so the
    checks that matter are done here: nothing unfetchable, nothing duplicated,
    nothing over the cap."""
    try:
        spec = iso_dates(yaml.safe_load(SOURCES.read_text()))
    except yaml.YAMLError as exc:
        errors.append(f"sources.yml: invalid YAML — {exc}")
        return

    sources = spec.get("sources") or []
    retired = spec.get("retired") or []
    cap = (spec.get("defaults") or {}).get("max_sources", 100)

    seen: set[str] = set()
    for src in sources:
        sid = src.get("id")
        if not sid:
            errors.append("sources.yml: a source has no id")
            continue
        if sid in seen:
            errors.append(f"sources.yml: duplicate source id {sid!r}")
        seen.add(sid)

        collector = src.get("collector")
        if collector not in harvest.COLLECTORS:
            errors.append(f"sources.yml: {sid}: unknown collector {collector!r}")
            continue
        for key in REQUIRED_PARAMS.get(collector, []):
            if not src.get(key):
                errors.append(f"sources.yml: {sid}: {collector} needs `{key}`")
        if src.get("group") not in GROUPS:
            errors.append(
                f"sources.yml: {sid}: group {src.get('group')!r} is not one of "
                + ", ".join(sorted(GROUPS))
            )
        if not src.get("added"):
            warnings.append(f"sources.yml: {sid}: no `added` date")

    for src in retired:
        sid = src.get("id", "?")
        if sid in seen:
            errors.append(f"sources.yml: {sid!r} is both active and retired")
        if not src.get("why") or not src.get("retired_on"):
            errors.append(
                f"sources.yml: retired {sid!r} needs both `why` and `retired_on` — "
                "a retirement without a reason gets re-added next month"
            )

    if len(sources) > cap:
        errors.append(
            f"sources.yml: {len(sources)} sources exceeds the cap of {cap} — "
            "retire one before adding another"
        )


def main() -> int:
    validator = Draft7Validator(json.loads(SCHEMA.read_text()))
    ideas = []

    for path in sorted(IDEAS.glob("*.yml")):
        if path.name.startswith("_"):
            continue
        try:
            data = iso_dates(yaml.safe_load(path.read_text()))
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

    # --- sources
    check_sources()

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
    spec = yaml.safe_load(SOURCES.read_text())
    n_src = len(spec.get("sources") or [])
    cap = (spec.get("defaults") or {}).get("max_sources", 100)
    print(
        f"\nok — {len(ideas)} idea file(s), {len(live)}/{MAX_LIVE} live, "
        f"{n_src}/{cap} sources"
        f"{f', {len(warnings)} warning(s)' if warnings else ''}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
