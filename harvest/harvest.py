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
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree

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
    window = src.get("window_days", cfg["window_days"])
    since = int((datetime.now(timezone.utc) - timedelta(days=window)).timestamp())
    params = urllib.parse.urlencode(
        {
            "query": src.get("query", ""),
            "tags": src.get("tags", "story"),
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


def collect_lemmy(src: dict, cfg: dict) -> list[dict]:
    """Lemmy communities. Reddit's JSON endpoint now 403s for unauthenticated
    clients; the self-hosting and privacy crowd it used to carry is here, behind a
    documented API that needs no key."""
    params = urllib.parse.urlencode(
        {
            "community_name": src["community"],
            "sort": src.get("sort", "TopWeek"),
            "limit": 50,
        }
    )
    data = fetch_json(
        f"https://{src['instance']}/api/v3/post/list?{params}", cfg["user_agent"]
    )
    if not data:
        return []
    out = []
    for row in data.get("posts", []):
        post = row.get("post", {})
        counts = row.get("counts", {})
        if counts.get("score", 0) < src.get("min_score", 0):
            continue
        out.append(
            item(
                source_id=src["id"],
                group=src["group"],
                title=post.get("name", ""),
                url=post.get("ap_id") or "",
                posted=(post.get("published") or "")[:10],
                score=counts.get("score", 0),
                comments=counts.get("comments", 0),
                body=post.get("body") or post.get("url") or "",
            )
        )
    return out


def collect_discourse(src: dict, cfg: dict) -> list[dict]:
    """Any Discourse instance, via the /top.json every install exposes. One
    collector, many forums -- adding a community is one entry in sources.yml."""
    host = src["host"]
    period = src.get("period", "weekly")
    data = fetch_json(f"https://{host}/top.json?period={period}", cfg["user_agent"])
    if not data:
        return []
    out = []
    for topic in (data.get("topic_list") or {}).get("topics", []):
        if topic.get("like_count", 0) < src.get("min_likes", 0):
            continue
        if topic.get("pinned") or topic.get("archetype") != "regular":
            continue
        slug = topic.get("slug") or "topic"
        out.append(
            item(
                source_id=src["id"],
                group=src["group"],
                title=topic.get("title", ""),
                url=f"https://{host}/t/{slug}/{topic.get('id')}",
                posted=(topic.get("created_at") or "")[:10],
                score=topic.get("like_count", 0),
                comments=max(topic.get("posts_count", 1) - 1, 0),
                body=topic.get("excerpt") or "",
            )
        )
    return out


def collect_stackexchange(src: dict, cfg: dict) -> list[dict]:
    """Stack Exchange. softwarerecs is the highest-density source in the whole
    file: every unanswered question is a tool someone wants that does not exist.
    Keyless quota is 300 requests/day, far more than a daily harvest needs."""
    path = "questions/unanswered" if src.get("unanswered") else "questions"
    params = urllib.parse.urlencode(
        {
            "site": src["site"],
            "order": "desc",
            "sort": src.get("sort", "votes"),
            "pagesize": 50,
            "filter": "withbody",  # documented built-in: default shape + body
        }
    )
    data = fetch_json(
        f"https://api.stackexchange.com/2.3/{path}?{params}", cfg["user_agent"]
    )
    if not data:
        return []
    out = []
    for q in data.get("items", []):
        if q.get("score", 0) < src.get("min_score", 0):
            continue
        created = q.get("creation_date")
        out.append(
            item(
                source_id=src["id"],
                group=src["group"],
                title=q.get("title", ""),
                url=q.get("link", ""),
                posted=(
                    datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%d")
                    if created
                    else ""
                ),
                score=q.get("score", 0),
                comments=q.get("answer_count", 0),
                body=re.sub(r"<[^>]+>", " ", q.get("body") or ""),
            )
        )
    return out


def collect_killedbygoogle(src: dict, cfg: dict) -> list[dict]:
    """Announced shutdowns, straight from the horse's mouth. CLAUDE.md §10 calls
    this class of signal the highest-yield in the system: when a monopolist closes
    a door, the window opens that same week."""
    data = fetch_json("https://killedbygoogle.com/api/graveyard", cfg["user_agent"])
    if not isinstance(data, list):
        return []
    horizon = (
        date.today() - timedelta(days=src.get("closed_within_days", 365))
    ).isoformat()
    out = []
    for entry in data:
        closed = entry.get("dateClose") or ""
        if closed < horizon:  # already cold; the window shut long ago
            continue
        out.append(
            item(
                source_id=src["id"],
                group=src["group"],
                title=f"Google is shutting down {entry.get('name')} ({closed})",
                url=entry.get("link") or "",
                posted=closed,
                score=0,  # no engagement metric exists; ordering is score.py's job
                comments=0,
                body=(
                    f"type={entry.get('type')} opened={entry.get('dateOpen')} "
                    f"closes={closed}. {entry.get('description') or ''}"
                ),
            )
        )
    return out


def collect_rss(src: dict, cfg: dict) -> list[dict]:
    """Plain RSS/Atom. Carries the mandate group, which has no upvote anywhere:
    regulators do not post to forums."""
    text = fetch_text(src["url"], cfg["user_agent"])
    if not text:
        return []
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        warn(f"{src['id']}: unparseable feed ({exc})")
        return []

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=src.get("window_days", 30))
    ).date()
    out = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        fields = {c.tag.rsplit("}", 1)[-1]: c for c in node}
        title = (fields.get("title").text or "") if "title" in fields else ""
        link = ""
        if "link" in fields:
            link = fields["link"].get("href") or (fields["link"].text or "")
        raw_date = ""
        for key in ("pubDate", "published", "updated", "date"):
            if key in fields and fields[key].text:
                raw_date = fields[key].text.strip()
                break
        posted = parse_feed_date(raw_date)
        if posted and date.fromisoformat(posted) < cutoff:
            continue
        summary = ""
        for key in ("description", "summary", "content"):
            if key in fields and fields[key].text:
                summary = fields[key].text
                break
        out.append(
            item(
                source_id=src["id"],
                group=src["group"],
                title=title,
                url=link,
                posted=posted,
                score=0,  # feeds carry no engagement signal
                comments=0,
                body=re.sub(r"<[^>]+>", " ", summary),
            )
        )
    return out


def parse_feed_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


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
    "lemmy": collect_lemmy,
    "discourse": collect_discourse,
    "stackexchange": collect_stackexchange,
    "killedbygoogle": collect_killedbygoogle,
    "rss": collect_rss,
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
