#!/usr/bin/env python3
"""The one judgment step: triage candidates into ideas, and re-score stale ideas.

Every act of judgment in this repo happens here and nowhere else. harvest.py only
fetches; render.py only computes and formats. That separation is what makes the
list auditable -- if a ranking looks wrong, there is exactly one place to look.

The model is pluggable by design. Any OpenAI-compatible /chat/completions endpoint
works, so swapping Claude for Hermes for a local model is three environment
variables and no code change:

    MODEL_BASE_URL   e.g. https://openrouter.ai/api/v1
    MODEL_NAME       e.g. nousresearch/hermes-4-405b
    MODEL_API_KEY    e.g. sk-...

Usage:
    python3 harvest/score.py [--limit N] [--no-rescore] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
IDEAS = ROOT / "ideas"
CANDIDATES = ROOT / "candidates"
CONTRACT = ROOT / "CLAUDE.md"
RUBRIC = ROOT / "rubric" / "SCORING.md"
SCHEMA = ROOT / "schema" / "idea.schema.json"

BATCH = 12          # candidates per model call
STALE_DAYS = 30     # stickiness trigger 2
CANDIDATE_DAYS = 8  # how far back to read candidate files


# ------------------------------------------------------------------ model client


def chat(messages: list[dict], *, max_tokens: int = 8000) -> str:
    base = os.environ.get("MODEL_BASE_URL", "").rstrip("/")
    name = os.environ.get("MODEL_NAME")
    key = os.environ.get("MODEL_API_KEY")
    if not (base and name):
        raise SystemExit(
            "MODEL_BASE_URL and MODEL_NAME must be set. See CLAUDE.md §8."
        )

    payload = {
        "model": name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,  # judgment, not creativity
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key or 'none'}",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read().decode())
    return body["choices"][0]["message"]["content"]


def parse_json(text: str):
    """Models fence JSON no matter how firmly you ask them not to."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = min((i for i in (text.find("["), text.find("{")) if i != -1), default=-1)
    if start > 0:
        text = text[start:]
    return json.loads(text)


# ------------------------------------------------------------------------ repo io


def rubric_version() -> int:
    for line in RUBRIC.read_text().splitlines():
        if line.strip().startswith("rubric_version:"):
            return int(line.split(":", 1)[1].strip())
    raise SystemExit("rubric/SCORING.md declares no rubric_version")


def load_ideas() -> list[dict]:
    out = []
    for path in sorted(IDEAS.glob("*.yml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text())
        data["_path"] = path
        out.append(data)
    return out


def write_idea(idea: dict) -> Path:
    idea.pop("_path", None)
    idea.pop("xhit", None)  # render.py owns xhit
    path = IDEAS / f"{idea['slug']}.yml"
    path.write_text(
        yaml.safe_dump(idea, sort_keys=False, allow_unicode=True, width=88),
        encoding="utf-8",
    )
    return path


def load_candidates() -> list[dict]:
    cutoff = date.today() - timedelta(days=CANDIDATE_DAYS)
    rows, seen = [], set()
    for path in sorted(CANDIDATES.glob("*.jsonl")):
        try:
            if datetime.strptime(path.stem, "%Y-%m-%d").date() < cutoff:
                continue
        except ValueError:
            continue
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row["url"] in seen:
                continue
            seen.add(row["url"])
            rows.append(row)
    return interleave(rows)


def interleave(rows: list[dict]) -> list[dict]:
    """Round-robin across sources, each source strongest-first.

    A flat sort by engagement is not comparable across sources: a GitHub repo
    carries 20,000 stars, a Discourse topic carries 31 likes, and an announced
    shutdown carries no number at all. Sorted flat, four GitHub queries own the
    entire head of the list and --limit throws away every forum signal and every
    regulator notice -- the two groups CLAUDE.md §10 rates highest.

    So: rank within each source, then take one from each in turn. Every source
    gets into the batch, and truncation costs each of them its weakest item
    rather than costing two sources everything.
    """
    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row["source_id"], []).append(row)
    for bucket in by_source.values():
        bucket.sort(key=lambda r: r["score"] + 2 * r["comments"], reverse=True)

    out: list[dict] = []
    buckets = list(by_source.values())
    for rank in range(max((len(b) for b in buckets), default=0)):
        for bucket in buckets:
            if rank < len(bucket):
                out.append(bucket[rank])
    return out


# -------------------------------------------------------------------- prompting


def system_prompt(existing: list[dict]) -> str:
    ledger = "\n".join(
        f"- {i['slug']} [{i['status']}] {i['title']} -> {i['target']['name']}"
        for i in existing
    ) or "(the list is empty)"

    return f"""You are the curator of the xHit-List. Follow the contract and rubric
below literally. They override any instinct you have about what makes a good idea.

=== CONTRACT (CLAUDE.md) ===
{CONTRACT.read_text()}

=== RUBRIC (rubric/SCORING.md) ===
{RUBRIC.read_text()}

=== SCHEMA (schema/idea.schema.json) ===
{SCHEMA.read_text()}

=== EXISTING IDEAS — DO NOT DUPLICATE ANY OF THESE ===
Graveyard entries count. An idea already buried must not be re-proposed unless the
new candidate is genuinely stronger evidence for it, in which case reuse its exact
existing slug so it is treated as a resurrection.
{ledger}

Rules for this task, in priority order:

1. Reject aggressively. Most candidates are not ideas. A typical batch of 12
   yields zero or one entry. Rejecting everything is a correct and common answer.
2. Never invent evidence. Every `evidence` url must be one of the candidate urls
   you were given in this batch. Every `date` must be that candidate's `posted`
   date. Fabricating a url or a date is the worst thing you can do here.
3. `disruption: 0` means reject. No closed-source, state-service or
   pseudo-monopoly target means the idea is out of charter, however good it is.
4. Score `demand` only from what the candidate artifacts actually show.
5. Be pessimistic about `effort`. Name the three hardest parts to yourself first;
   if you cannot, raise the estimate.
6. Do not propose an idea that restates an existing entry in new words.

Output STRICT JSON ONLY: an array of objects, `[]` if nothing qualifies. No prose,
no markdown fences, no explanation. Each object must validate against the schema,
with `status: "live"`, `pinned: false`, and no `xhit` field."""


def triage(batch: list[dict], existing: list[dict], rv: int, today: str) -> list[dict]:
    listing = json.dumps(
        [
            {
                "title": c["title"],
                "url": c["url"],
                "posted": c["posted"],
                "score": c["score"],
                "comments": c["comments"],
                "group": c["group"],
                "body": c["body"][:600],
            }
            for c in batch
        ],
        ensure_ascii=False,
        indent=1,
    )

    raw = chat(
        [
            {"role": "system", "content": system_prompt(existing)},
            {
                "role": "user",
                "content": (
                    f"Today is {today}. Candidate signals:\n\n{listing}\n\n"
                    "Return the JSON array."
                ),
            },
        ]
    )

    try:
        ideas = parse_json(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! unparseable model output ({exc}); batch skipped", file=sys.stderr)
        return []
    if not isinstance(ideas, list):
        return []

    urls = {c["url"] for c in batch}
    kept = []
    for idea in ideas:
        if not isinstance(idea, dict) or "slug" not in idea:
            continue
        # Enforce rule 2 in code, not on trust.
        idea["evidence"] = [
            e for e in (idea.get("evidence") or []) if e.get("url") in urls
        ]
        if not idea["evidence"]:
            print(f"  ! {idea['slug']}: no cited candidate url, dropped", file=sys.stderr)
            continue
        if idea.get("scores", {}).get("disruption", 0) < 1:
            continue
        idea["status"] = "live"
        idea["pinned"] = False
        idea.setdefault("first_seen", today)
        idea["last_scored"] = today
        idea["rubric_version"] = rv
        kept.append(idea)
    return kept


def rescore(idea: dict, rv: int, today: str) -> dict | None:
    raw = chat(
        [
            {
                "role": "system",
                "content": (
                    "Re-score one existing xHit-List idea against the rubric below. "
                    "Change a number only if the evidence justifies it. Return STRICT "
                    "JSON only: {\"reward\":n,\"disruption\":n,\"effort\":n,"
                    "\"demand\":n,\"moat_risk\":n}\n\n" + RUBRIC.read_text()
                ),
            },
            {
                "role": "user",
                "content": f"Today is {today}.\n\n"
                + yaml.safe_dump(
                    {k: v for k, v in idea.items() if k not in ("_path", "xhit")},
                    sort_keys=False,
                    allow_unicode=True,
                ),
            },
        ],
        max_tokens=400,
    )
    try:
        scores = parse_json(raw)
        idea["scores"] = {
            k: int(scores[k])
            for k in ("reward", "disruption", "effort", "demand", "moat_risk")
        }
    except Exception as exc:  # noqa: BLE001
        print(f"  ! {idea['slug']}: rescore failed ({exc}), keeping old", file=sys.stderr)
        return None
    idea["last_scored"] = today
    idea["rubric_version"] = rv
    return idea


def needs_rescore(idea: dict, rv: int, today: str) -> str | None:
    """Stickiness triggers — CLAUDE.md §7. Anything else keeps its score."""
    if idea["status"] != "live":
        return None
    if idea.get("rubric_version", 0) < rv:
        return "rubric bumped"
    last = idea.get("last_scored", "")
    newest = max((e.get("date", "") for e in idea.get("evidence") or []), default="")
    if newest > last:
        return "new evidence"
    try:
        age = (date.fromisoformat(today) - date.fromisoformat(last)).days
    except ValueError:
        return "unparseable last_scored"
    if age > STALE_DAYS:
        return f"{age} days stale"
    return None


# -------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60, help="max candidates to triage")
    ap.add_argument("--no-rescore", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args()

    today = date.today().isoformat()
    rv = rubric_version()
    existing = load_ideas()
    IDEAS.mkdir(exist_ok=True)

    # --- 1. stale re-scores, before triage, so dedupe sees current scores
    if not args.no_rescore:
        for idea in existing:
            why = needs_rescore(idea, rv, today)
            if not why:
                continue
            print(f"rescore {idea['slug']} ({why})")
            before = dict(idea["scores"])
            if rescore(idea, rv, today) and not args.dry_run:
                write_idea(idea)
            if before != idea["scores"]:
                print(f"    {before} -> {idea['scores']}")

    # --- 2. triage new candidates
    candidates = load_candidates()[: args.limit]
    if not candidates:
        print("no recent candidates; run harvest.py first")
        return 0

    print(f"\ntriaging {len(candidates)} candidates in batches of {BATCH}")
    known = {i["slug"] for i in existing}
    added = 0

    for start in range(0, len(candidates), BATCH):
        batch = candidates[start : start + BATCH]
        print(f"- batch {start // BATCH + 1}")
        for idea in triage(batch, existing, rv, today):
            resurrection = idea["slug"] in known
            if resurrection:
                prior = next(i for i in existing if i["slug"] == idea["slug"])
                idea["first_seen"] = prior.get("first_seen", today)
                idea["pinned"] = prior.get("pinned", False)
                seen = {e["url"] for e in idea["evidence"]}
                idea["evidence"] += [
                    e for e in (prior.get("evidence") or []) if e["url"] not in seen
                ]
                idea["evidence"] = idea["evidence"][:12]
            print(
                f"    {'resurrect' if resurrection else '+'} {idea['slug']}"
                f"  {idea['target']['name']}"
            )
            if not args.dry_run:
                write_idea(idea)
            known.add(idea["slug"])
            existing = [i for i in existing if i["slug"] != idea["slug"]] + [idea]
            added += 1

    print(f"\n{added} idea file(s) written")
    if args.dry_run:
        print("(dry run)")
    else:
        print("now run: python3 harvest/render.py && python3 harvest/validate.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
