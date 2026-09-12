#!/usr/bin/env python3
"""Deterministic candidate harvester for xHit-List.

Fetches raw signals from the sources in sources.yml and appends them to
candidates/<date>.jsonl. Contains NO judgment and NO model calls -- by design.
All triage, scoring and dedupe happens in score.py, so that every act of judgment
in this repo lives in exactly one auditable place.

Usage:
    python3 harvest/harvest.py [--dry-run] [--group pain,mandate]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "harvest" / "sources.yml"
CANDIDATES = ROOT / "candidates"

TIMEOUT = 30
RETRIES = 3


# --------------------------------------------------------------------------- http


def fetch_json(url: str, user_agent: str) -> dict | list | None:
    """GET a URL and parse JSON. Returns None on persistent failure.

    A dead source must never kill the run -- a harvest that fails closed on one
    404 is a harvest that silently stops working.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"

    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < RETRIES - 1:
                time.sleep(2 ** attempt * 2)
                continue
            warn(f"HTTP {exc.code} for {url}")
            return None
        except Exception as exc:  # noqa: BLE001 - network is allowed to be messy
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            warn(f"{type(exc).__name__} for {url}: {exc}")
            return None
    return None


def fetch_text(url: str, user_agent: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        warn(f"{type(exc).__name__} for {url}: {exc}")
        return None


def warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr)


# ---------------------------------------------------------------- normalised item


def item(
    *,
    source_id: str,
    group: str,
    title: str,
    url: str,
    posted: str,
    score: int,
    comments: int = 0,
    body: str = "",
) -> dict:
    """One candidate signal, in the only shape score.py accepts."""
    return {
        "source_id": source_id,
        "group": group,
        "title": (title or "").strip()[:300],
        "url": url,
        "posted": posted,
        "score": int(score or 0),
        "comments": int(comments or 0),
        "body": (body or "").strip()[:1200],
        "harvested_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


# ------------------------------------------------------------------- collectors


def collect_hn_algolia(src: dict, cfg: dict) -> list[dict]:
    since = int(
        (datetime.now(timezone.utc) - timedelta(days=cfg["window_days"])).timestamp()
    )
    params = urllib.parse.urlencode(
        {
            "query": src["query"],
            "tags": "story",
            "numericFilters": f"created_at_i>{since},points>{src.get('min_points', 10)}",
            "hitsPerPage": 50,
        }
    )
    data = fetch_json(
        f"https://hn.algolia.com/api/v1/search_by_date?{params}", cfg["user_agent"]
    )
    if not data:
        return []
    out = []
    for hit in data.get("hits", []):
        out.append(
            item(
                source_id=src["id"],
                group=src["group"],
                title=hit.get("title") or hit.get("story_title") or "",
                url=f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                posted=(hit.get("created_at") or "")[:10],
                score=hit.get("points", 0),
                comments=hit.get("num_comments", 0),
                body=hit.get("story_text") or hit.get("url") or "",
            )
        )
    return out


def collect_reddit(src: dict, cfg: dict) -> list[dict]:
    params = urllib.parse.urlencode({"t": src.get("period", "week"), "limit": 60})
    url = (
        f"https://www.reddit.com/r/{src['subreddit']}/"
        f"{src.get('listing', 'top')}.json?{params}"
    )
    data = fetch_json(url, cfg["user_agent"])
    if not data:
        return []
    out = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        if post.get("score", 0) < src.get("min_score", 0):
            continue
        created = post.get("created_utc")
        posted = (
            datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%d")
            if created
            else ""
        )
        out.append(
            item(
                source_id=src["id"],
                group=src["group"],
                title=post.get("title", ""),
                url="https://www.reddit.com" + post.get("permalink", ""),
                posted=posted,
                score=post.get("score", 0),
                comments=post.get("num_comments", 0),
                body=post.get("selftext", ""),
            )
        )
    return out


def collect_lobsters(src: dict, cfg: dict) -> list[dict]:
    data = fetch_json("https://lobste.rs/hottest.json", cfg["user_agent"])
    if not data:
        return []
    out = []
    for post in data if isinstance(data, list) else []:
        if post.get("score", 0) < src.get("min_score", 0):
            continue
        out.append(
            item(
                source_id=src["id"],
                group=src["group"],
                title=post.get("title", ""),
                url=post.get("short_id_url") or post.get("url", ""),
                posted=(post.get("created_at") or "")[:10],
                score=post.get("score", 0),
                comments=post.get("comment_count", 0),
                body=post.get("description_plain") or "",
            )
        )
    return out


def collect_github_search(src: dict, cfg: dict) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "q": src["query"],
            "sort": src.get("sort", "stars"),
            "order": "desc",
            "per_page": 40,
        }
    )
    data = fetch_json(
        f"https://api.github.com/search/repositories?{params}", cfg["user_agent"]
    )
    if not data:
        return []
    out = []
    for repo in data.get("items", []):
        out.append(
            item(
                source_id=src["id"],
                group=src["group"],
                title=f"{repo.get('full_name')} — {repo.get('description') or ''}",
                url=repo.get("html_url", ""),
                posted=(repo.get("pushed_at") or "")[:10],
                score=repo.get("stargazers_count", 0),
                comments=repo.get("open_issues_count", 0),
                body=(
                    f"archived={repo.get('archived')} "
                    f"forks={repo.get('forks_count')} "
                    f"lang={repo.get('language')} "
                    f"topics={','.join(repo.get('topics') or [])}"
                ),
            )
        )
    return out


COLLECTORS = {
    "hn_algolia": collect_hn_algolia,
    "reddit": collect_reddit,
    "lobsters": collect_lobsters,
    "github_search": collect_github_search,
}


# -------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fetch but do not write")
    ap.add_argument("--group", help="comma-separated groups to restrict to")
    args = ap.parse_args()

    spec = yaml.safe_load(SOURCES.read_text())
    cfg = spec.get("defaults", {})
    cfg.setdefault("window_days", 7)
    cfg.setdefault("user_agent", "xhit-list-harvester/1")

    wanted = set(args.group.split(",")) if args.group else None

    seen_urls: set[str] = set()
    rows: list[dict] = []

    for src in spec["sources"]:
        if wanted and src.get("group") not in wanted:
            continue
        collector = COLLECTORS.get(src["collector"])
        if not collector:
            warn(f"unknown collector {src['collector']!r} in {src['id']}")
            continue

        print(f"- {src['id']} ({src['group']})")
        try:
            found = collector(src, cfg)
        except Exception as exc:  # noqa: BLE001
            warn(f"{src['id']} raised {type(exc).__name__}: {exc}")
            continue

        fresh = [r for r in found if r["url"] and r["url"] not in seen_urls]
        seen_urls.update(r["url"] for r in fresh)
        rows.extend(fresh)
        print(f"    {len(fresh)} new ({len(found)} fetched)")
        time.sleep(1)  # be a good citizen

    print(f"\n{len(rows)} candidates from {len(seen_urls)} unique urls")

    if args.dry_run:
        print("(dry run, nothing written)")
        return 0

    CANDIDATES.mkdir(exist_ok=True)
    out = CANDIDATES / f"{date.today().isoformat()}.jsonl"
    with out.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"appended -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
