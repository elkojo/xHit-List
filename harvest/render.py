#!/usr/bin/env python3
"""Render ideas/*.yml into HITLIST.md, GRAVEYARD.md and SHIPPED.md.

This script owns three things and nothing else:
  1. computing `xhit` from `scores` (the formula lives here, once)
  2. enforcing the 30-entry cap and writing evictions back to the idea files
  3. generating the markdown

No model calls, no network, no judgment. Deterministic: running it twice in a row
produces identical output. `--check` makes it read-only, which is how validate.py
detects that someone hand-edited a generated file.

Usage:
    python3 harvest/render.py [--check]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
IDEAS = ROOT / "ideas"
RUBRIC = ROOT / "rubric" / "SCORING.md"

MAX_LIVE = 30

KIND_LABEL = {
    "closed_source": "closed source",
    "state_service": "state service",
    "pseudo_monopoly": "pseudo-monopoly",
}


# ------------------------------------------------------------------- the formula


def xhit(scores: dict) -> float:
    """xhit = (2*reward + 2*disruption + demand) / (effort + moat_risk/2)

    Effort divides, which is what keeps the top of the list buildable rather than
    merely grand. See rubric/SCORING.md.
    """
    numerator = 2 * scores["reward"] + 2 * scores["disruption"] + scores["demand"]
    denominator = scores["effort"] + scores["moat_risk"] / 2
    return round(numerator / denominator, 2)


def sort_key(idea: dict) -> tuple:
    """Rank order. Ties break toward lower effort, then more recent evidence."""
    newest_evidence = max(
        (e.get("date", "") for e in idea.get("evidence") or []), default=""
    )
    return (
        -idea["xhit"],
        idea["scores"]["effort"],
        # negate via reversed string comparison: later date should sort first
        [-ord(c) for c in newest_evidence],
        idea["slug"],
    )


# ------------------------------------------------------------------------- io


def rubric_version() -> int:
    for line in RUBRIC.read_text().splitlines():
        if line.strip().startswith("rubric_version:"):
            return int(line.split(":", 1)[1].strip())
    raise SystemExit("rubric/SCORING.md declares no rubric_version")


def iso_dates(node):
    """YAML parses an unquoted 2026-09-07 into a date object, not a string.

    Every date field in the schema is a string, and score.py quotes them on the
    way out -- but a hand-written idea file will not, and the failure was an
    opaque TypeError three functions later. Normalise on the way in instead.
    """
    if isinstance(node, dict):
        return {k: iso_dates(v) for k, v in node.items()}
    if isinstance(node, list):
        return [iso_dates(v) for v in node]
    if isinstance(node, (date, datetime)):
        return node.isoformat()[:10]
    return node


def load_ideas() -> list[dict]:
    ideas = []
    for path in sorted(IDEAS.glob("*.yml")):
        if path.name.startswith("_"):
            continue  # _EXAMPLE.yml and friends are documentation, not data
        data = iso_dates(yaml.safe_load(path.read_text()))
        if not isinstance(data, dict):
            raise SystemExit(f"{path.name}: not a YAML mapping")
        if data.get("slug") != path.stem:
            raise SystemExit(f"{path.name}: slug {data.get('slug')!r} != filename")
        data["_path"] = path
        ideas.append(data)
    return ideas


def save(idea: dict) -> None:
    path = idea.pop("_path")
    path.write_text(
        yaml.safe_dump(idea, sort_keys=False, allow_unicode=True, width=88),
        encoding="utf-8",
    )
    idea["_path"] = path


# ---------------------------------------------------------------------- the cap


def apply_cap(ideas: list[dict], today: str, write: bool) -> None:
    """Trim live entries to MAX_LIVE, evicting the weakest unpinned ones.

    Pinned ideas are never evicted; if pinning alone exceeds the cap the list is
    allowed to run long rather than silently dropping something a human chose.
    """
    live = [i for i in ideas if i["status"] == "live"]
    if len(live) <= MAX_LIVE:
        return

    live.sort(key=sort_key)
    surplus = len(live) - MAX_LIVE
    cutoff = live[MAX_LIVE - 1]["xhit"] if MAX_LIVE <= len(live) else 0

    for idea in reversed(live):
        if surplus <= 0:
            break
        if idea.get("pinned"):
            continue
        idea["status"] = "graveyard"
        idea["evicted_on"] = today
        idea["evicted_reason"] = (
            f"xhit {idea['xhit']} ranked below the rank-{MAX_LIVE} "
            f"cutoff of {cutoff} (ties broken by effort, then evidence date)"
        )
        surplus -= 1
        if write:
            save(idea)


# ------------------------------------------------------------------- rendering


def fmt_evidence(idea: dict, limit: int = 3) -> str:
    items = sorted(
        idea.get("evidence") or [], key=lambda e: e.get("date", ""), reverse=True
    )[:limit]
    return " · ".join(f"[{e['date']}]({e['url']})" for e in items)


def render_hitlist(live: list[dict], today: str, rv: int) -> str:
    lines = [
        "# The xHit List",
        "",
        "<!-- GENERATED by harvest/render.py — do not edit. Edit ideas/*.yml. -->",
        "",
        f"Top {MAX_LIVE} projects worth building, ranked by reward against effort and",
        "weighted toward breaking closed source, state service monopolies and",
        "pseudo-monopolies.",
        "",
        f"`{len(live)}/{MAX_LIVE} live` · `rubric v{rv}` · updated {today}",
        "",
        "| # | idea | xhit | target | R | D | E | Dm | M | evidence |",
        "|---:|---|---:|---|:-:|:-:|:-:|:-:|:-:|---|",
    ]

    for rank, idea in enumerate(live, 1):
        s = idea["scores"]
        pin = " 📌" if idea.get("pinned") else ""
        lines.append(
            f"| {rank} | **[{idea['title']}](#{idea['slug']})**{pin} "
            f"| {idea['xhit']:.2f} "
            f"| {idea['target']['name']} <sup>{KIND_LABEL[idea['target']['kind']]}</sup> "
            f"| {s['reward']} | {s['disruption']} | {s['effort']} "
            f"| {s['demand']} | {s['moat_risk']} "
            f"| {fmt_evidence(idea, 1)} |"
        )

    lines += [
        "",
        "<sub>R reward · D disruption · E effort (lower is easier) · "
        "Dm demand · M moat risk. See [rubric/SCORING.md](rubric/SCORING.md).</sub>",
        "",
        "---",
        "",
        "## Entries",
        "",
    ]

    for rank, idea in enumerate(live, 1):
        s = idea["scores"]
        lines += [
            f"### {idea['slug']}",
            "",
            f"**{rank}. {idea['title']}** — xhit **{idea['xhit']:.2f}**"
            + ("  📌 pinned" if idea.get("pinned") else ""),
            "",
            f"*What:* {idea['what'].strip()}",
            "",
            f"*Target:* {idea['target']['name']} "
            f"({KIND_LABEL[idea['target']['kind']]}) — "
            f"{idea['target']['why_vulnerable'].strip()}",
            "",
            f"*Why now:* {idea['rationale'].strip()}",
            "",
            f"*Scores:* reward {s['reward']} · disruption {s['disruption']} · "
            f"effort {s['effort']} · demand {s['demand']} · moat risk {s['moat_risk']}",
            "",
        ]
        if idea.get("legal_note"):
            lines += [f"*Legal note:* {idea['legal_note'].strip()}", ""]
        lines += [
            f"*Evidence:* {fmt_evidence(idea, 6)}",
            "",
            f"<sub>first seen {idea['first_seen']} · "
            f"last scored {idea['last_scored']} · rubric v{idea['rubric_version']}</sub>",
            "",
        ]

    return "\n".join(lines).rstrip() + "\n"


def render_graveyard(dead: list[dict], today: str) -> str:
    lines = [
        "# Graveyard",
        "",
        "<!-- GENERATED by harvest/render.py — do not edit. Edit ideas/*.yml. -->",
        "",
        "Evicted ideas. They keep their files on purpose: this is the dedupe ledger",
        "that stops the harvester re-proposing the same dead idea every week.",
        "",
        "An entry comes back to life if new evidence lifts its score above the",
        f"current rank-{MAX_LIVE} cutoff.",
        "",
        f"`{len(dead)} buried` · updated {today}",
        "",
        "| idea | xhit | target | evicted | why |",
        "|---|---:|---|---|---|",
    ]
    for idea in sorted(dead, key=sort_key):
        lines.append(
            f"| {idea['title']} | {idea['xhit']:.2f} "
            f"| {idea['target']['name']} "
            f"| {idea.get('evicted_on') or '—'} "
            f"| {idea.get('evicted_reason') or '—'} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_shipped(building: list[dict], shipped: list[dict], today: str) -> str:
    lines = [
        "# Building & shipped",
        "",
        "<!-- GENERATED by harvest/render.py — do not edit. Edit ideas/*.yml. -->",
        "",
        "Ideas that left the list because someone started on them. They free a slot",
        "the moment they move here — the hit list is for work not yet begun.",
        "",
        f"updated {today}",
        "",
    ]
    for heading, group in (("In progress", building), ("Shipped", shipped)):
        lines += [f"## {heading}", ""]
        if not group:
            lines += ["_nothing yet._", ""]
            continue
        lines += ["| idea | repo | target | xhit at handoff |", "|---|---|---|---:|"]
        for idea in sorted(group, key=sort_key):
            repo = idea.get("repo")
            lines.append(
                f"| {idea['title']} "
                f"| {f'[{repo}]({repo})' if repo else '—'} "
                f"| {idea['target']['name']} | {idea['xhit']:.2f} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# -------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if any generated file is out of date",
    )
    args = ap.parse_args()

    today = date.today().isoformat()
    rv = rubric_version()
    ideas = load_ideas()

    for idea in ideas:
        idea["xhit"] = xhit(idea["scores"])

    apply_cap(ideas, today, write=not args.check)

    if not args.check:
        for idea in ideas:
            save(idea)

    live = sorted((i for i in ideas if i["status"] == "live"), key=sort_key)
    dead = [i for i in ideas if i["status"] == "graveyard"]
    building = [i for i in ideas if i["status"] == "building"]
    shipped = [i for i in ideas if i["status"] == "shipped"]

    targets = {
        ROOT / "HITLIST.md": render_hitlist(live, today, rv),
        ROOT / "GRAVEYARD.md": render_graveyard(dead, today),
        ROOT / "SHIPPED.md": render_shipped(building, shipped, today),
    }

    if args.check:
        # The "updated" date line changes daily, so compare everything except it.
        def strip_dates(text: str) -> str:
            return "\n".join(
                ln for ln in text.splitlines() if "updated " not in ln
            )

        stale = [
            p.name
            for p, want in targets.items()
            if not p.exists() or strip_dates(p.read_text()) != strip_dates(want)
        ]
        if stale:
            print("out of date: " + ", ".join(stale), file=sys.stderr)
            print("run: python3 harvest/render.py", file=sys.stderr)
            return 1
        print("generated files are current")
        return 0

    for path, text in targets.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.name}")

    print(
        f"{len(live)} live · {len(dead)} buried · "
        f"{len(building)} building · {len(shipped)} shipped"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
