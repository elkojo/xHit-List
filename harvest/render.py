#!/usr/bin/env python3
"""Render ideas/*.yml into HITLIST.md, GRAVEYARD.md, SHIPPED.md and SOURCES.md.

This script owns four things and nothing else:
  1. computing `xhit` from `scores` (the formula lives here, once)
  2. enforcing the 30-entry cap and writing evictions back to the idea files
  3. enforcing the source cap and reporting each source's health
  4. generating the markdown

No model calls, no network, no judgment. Deterministic: running it twice in a row
produces identical output. `--check` makes it read-only, which is how validate.py
detects that someone hand-edited a generated file.

Usage:
    python3 harvest/render.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
IDEAS = ROOT / "ideas"
RUBRIC = ROOT / "rubric" / "SCORING.md"
SOURCES = ROOT / "harvest" / "sources.yml"
HEALTH = ROOT / "harvest" / "source_health.json"

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


# --------------------------------------------------------------------- sources

# How many consecutive bad runs before a source is called out. Crossing a line
# does not retire anything: it puts the source in front of a human who decides.
FAILING_AFTER = 3
DRY_AFTER = 6
RETIRE_AFTER = 8


def source_link(src: dict) -> str:
    """Where a human goes to look at this source with their own eyes.

    Derived, never stored: a URL written next to the params it is built from is a
    URL that goes stale the first time somebody edits one and not the other.
    """
    c = src["collector"]
    if c == "rss":
        return src["url"]
    if c == "discourse":
        return f"https://{src['host']}"
    if c == "lemmy":
        return f"https://{src['instance']}/c/{src['community']}"
    if c == "hn_algolia":
        q = urllib.parse.quote(src.get("query") or "")
        tags = src.get("tags") or "story"
        return f"https://hn.algolia.com/?query={q}&tags={tags}&sort=byDate"
    if c == "stackexchange":
        return f"https://{src['site']}.stackexchange.com"
    if c == "github_search":
        q = urllib.parse.quote(src["query"])
        return f"https://github.com/search?q={q}&type=repositories"
    if c == "lobsters":
        return "https://lobste.rs"
    if c == "killedbygoogle":
        return "https://killedbygoogle.com"
    return ""


def source_filter(src: dict, default_window: int) -> str:
    """The one-line answer to "what does this actually pull?"."""
    c = src["collector"]
    window = src.get("window_days", default_window)
    if c == "hn_algolia":
        what = f'"{src["query"]}"' if src.get("query") else src.get("tags", "story")
        return f"{what} · ≥{src.get('min_points', 0)} pts · {window}d"
    if c == "lemmy":
        return f"{src.get('sort', 'TopWeek')} · ≥{src.get('min_score', 0)}"
    if c == "discourse":
        return f"top/{src.get('period', 'weekly')} · ≥{src.get('min_likes', 0)} likes"
    if c == "stackexchange":
        kind = "unanswered" if src.get("unanswered") else "questions"
        return f"{kind} by {src.get('sort', 'votes')} · ≥{src.get('min_score', 0)}"
    if c == "github_search":
        return f"`{src['query']}` by {src.get('sort', 'stars')}"
    if c == "killedbygoogle":
        return f"closed within {src.get('closed_within_days', 365)}d"
    if c == "lobsters":
        return f"hottest · ≥{src.get('min_score', 0)}"
    return f"{window}d window"


def source_health(rec: dict | None) -> tuple[str, str]:
    """(status, detail). Deterministic: thresholds only, no judgment."""
    if not rec:
        return "new", "not harvested yet"
    fails = rec.get("consecutive_failures", 0)
    dry = rec.get("consecutive_dry", 0)
    items = rec.get("last_items", 0)
    if fails >= RETIRE_AFTER or dry >= RETIRE_AFTER + DRY_AFTER:
        return "retire?", f"{fails} failed / {dry} dry runs in a row"
    if fails >= FAILING_AFTER:
        return "failing", (rec.get("last_error") or "")[:60] or f"{fails} in a row"
    if fails:
        return "warn", (rec.get("last_error") or "")[:60] or "1 failed run"
    if dry >= DRY_AFTER:
        return "dry", f"{dry} runs with nothing"
    return "ok", f"{items} items"


def load_sources() -> tuple[dict, list[dict], list[dict]]:
    spec = iso_dates(yaml.safe_load(SOURCES.read_text()))
    return spec.get("defaults", {}), spec.get("sources") or [], spec.get("retired") or []


def load_health() -> dict:
    if not HEALTH.exists():
        return {}
    return json.loads(HEALTH.read_text()).get("sources", {})


def render_sources(
    defaults: dict, sources: list[dict], retired: list[dict], health: dict, today: str
) -> str:
    cap = defaults.get("max_sources", 100)
    window = defaults.get("window_days", 14)
    groups: dict[str, list[dict]] = {}
    for src in sources:
        groups.setdefault(src.get("group", "—"), []).append(src)

    over = len(sources) - cap
    lines = [
        "# Sources",
        "",
        "<!-- GENERATED by harvest/render.py — do not edit. "
        "Edit harvest/sources.yml. -->",
        "",
        f"Every place `harvest.py` looks for candidates, capped at {cap}. Past the",
        "cap a new source has to displace a worse one: move the loser to the",
        "[retired](#retired) table with a reason, so nobody re-adds it next month.",
        "",
        f"`{len(sources)}/{cap} active` · `{len(retired)} retired` · updated {today}",
        "",
    ]
    if over > 0:
        lines += [
            f"> ⚠️ **{over} over the cap.** Retire {over} before adding another.",
            "",
        ]

    lines += [
        "| group | what it means | sources |",
        "|---|---|---:|",
        "| `enshittification` | an incumbent closing a door — the highest-yield "
        "signal there is | %d |" % len(groups.get("enshittification", [])),
        "| `mandate` | a rule that forces an interface open | %d |"
        % len(groups.get("mandate", [])),
        "| `pain` | someone saying a dependency hurts | %d |"
        % len(groups.get("pain", [])),
        "| `vacancy` | a solved problem whose solution died | %d |"
        % len(groups.get("vacancy", [])),
        "",
        "Health is counted by `harvest.py` and written to `source_health.json`: "
        f"`warn` is one failed run, `failing` is {FAILING_AFTER} in a row, `dry` is "
        f"{DRY_AFTER} runs that returned nothing, `retire?` means stop carrying it.",
        "",
        "---",
        "",
    ]

    for group in ("enshittification", "mandate", "pain", "vacancy"):
        rows = sorted(groups.get(group, []), key=lambda s: s["id"])
        if not rows:
            continue
        lines += [
            f"## {group} <sub>{len(rows)}</sub>",
            "",
            "| source | via | fetches | added | health |",
            "|---|---|---|---|---|",
        ]
        for src in rows:
            status, detail = source_health(health.get(src["id"]))
            link = source_link(src)
            name = f"[{src['id']}]({link})" if link else src["id"]
            note = f"<br><sub>{src['note']}</sub>" if src.get("note") else ""
            lines.append(
                f"| {name}{note} | `{src['collector']}` "
                f"| {source_filter(src, window)} "
                f"| {src.get('added', '—')} "
                f"| `{status}` <sub>{detail}</sub> |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## Retired",
        "",
        "Tried, found wanting, and kept here on purpose — this is the dedupe ledger",
        "for sources, the same way GRAVEYARD.md is the one for ideas.",
        "",
        "| source | where | retired | why |",
        "|---|---|---|---|",
    ]
    for src in sorted(retired, key=lambda s: (str(s.get("retired_on", "")), s["id"])):
        where = src.get("where", "")
        where_md = f"<{where}>" if str(where).startswith("http") else where
        lines.append(
            f"| {src['id']} | {where_md} "
            f"| {src.get('retired_on', '—')} | {src.get('why', '—')} |"
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

    defaults, sources, retired = load_sources()
    health = load_health()

    targets = {
        ROOT / "HITLIST.md": render_hitlist(live, today, rv),
        ROOT / "GRAVEYARD.md": render_graveyard(dead, today),
        ROOT / "SHIPPED.md": render_shipped(building, shipped, today),
        ROOT / "SOURCES.md": render_sources(defaults, sources, retired, health, today),
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

    cap = defaults.get("max_sources", 100)
    print(
        f"{len(live)} live · {len(dead)} buried · "
        f"{len(building)} building · {len(shipped)} shipped · "
        f"{len(sources)}/{cap} sources"
    )
    if len(sources) > cap:
        print(
            f"note: {len(sources) - cap} source(s) over the cap — "
            "retire one in harvest/sources.yml",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
