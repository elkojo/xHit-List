# Setup — remaining steps

Everything in this repo is built, committed and verified locally. What is left all
needs GitHub credentials, so it has to be done by a human (or by a Claude Code
session running with your `gh` login).

Pick up here.

---

## 0. Where this stands (2026-09-13)

The repo is live at **<https://github.com/elkojo/xHit-List>** (public). `main`
holds the scaffold plus one harvest-audit commit; the work from the 2026-09-12 and
2026-09-13 sessions is on branch **`harvest/live-sources`**, pushed and under
review in **[PR #1](https://github.com/elkojo/xHit-List/pull/1)**:

```
a74b57e  harvest: 1571 candidates from 100 sources         (branch)
7c6ad0a  sources: 100-source registry + SOURCES.md         (branch)
c688900  docs(setup): record session state                 (branch)
212d7c6  harvest: +4 ideas, 0 evicted, 0 rescored          (branch)
ea6e46b  harvest: normalise YAML-native dates on load      (branch)
e49384f  harvest: replace dead sources, add five collectors, fix ordering  (branch)
a7318fb  harvest: 70 candidates, 0 ideas, 0 rescored       (main)
```

It is a PR and not a merge to `main` because it changes `harvest.py`, `score.py`,
`render.py` and `validate.py`, which CLAUDE.md §9 puts behind review. The
`validate` workflow passes on it.

`HITLIST.md` is seeded with 4 live entries. The pipeline is green end to end
(`validate.py` exits 0).

**Settled 2026-09-13.** The scoring pass is the connected agent's, not `score.py`
calling an endpoint. CLAUDE.md §8 now says so and names the endpoint as optional
automation; the workflow skips the score step unless `MODEL_BASE_URL` is set. A
harvest-only night commits candidates, `SOURCES.md` and health, and says so in the
commit subject instead of reporting "+0 ideas".

---

## 1. Create the remote and push — DONE 2026-09-13

<https://github.com/elkojo/xHit-List>, public, `origin` over https. `gh` is
authenticated as `elkojo`.

- [x] remote created
- [x] `main` pushed
- [x] `harvest/live-sources` pushed and [PR #1](https://github.com/elkojo/xHit-List/pull/1) opened
- [ ] PR #1 reviewed and merged

## 2. Add the model secrets — OPTIONAL

Not needed. The scoring pass is the connected agent's (CLAUDE.md §8, route 1) and
the nightly workflow skips `score.py` entirely when `MODEL_BASE_URL` is unset.

Set these only if you want the cron to triage unattended as well:

**Settings → Secrets and variables → Actions → New repository secret.** Three of
them, matching `CLAUDE.md` §8:

| secret | example |
|---|---|
| `MODEL_BASE_URL` | `https://openrouter.ai/api/v1` |
| `MODEL_NAME` | `nousresearch/hermes-4-405b` or `anthropic/claude-...` |
| `MODEL_API_KEY` | the key for that endpoint |

OpenRouter is the pragmatic choice if you want both Hermes and Claude reachable
through one key. A local llama.cpp also works, but not from a GitHub runner — for
that, run `score.py` on poppy against `http://localhost:8080/v1` and push the result.

- [x] decided: optional second route, agent is primary (2026-09-13)
- [ ] `MODEL_BASE_URL`
- [ ] `MODEL_NAME`
- [ ] `MODEL_API_KEY`

## 3. Let the workflow push its commits

**Settings → Actions → General → Workflow permissions → Read and write
permissions.** Without this the daily job runs, finds ideas, and then fails at
`git push` — which looks like a mysterious harvest failure.

- [x] workflow permissions set to read and write (2026-09-13, via the API)

## 4. First run

**Actions → harvest → Run workflow.** The cron fires at 05:17 UTC daily.

Start conservative: `limit: 30` on the first run so you can read every entry the
curator produced and check its judgment against the rubric before trusting it with
60 candidates a night.

- [ ] first manual run green
- [ ] entries in `HITLIST.md` reviewed against `rubric/SCORING.md`

## 5. Tune after you have seen real output

Judgment quality is the one thing that cannot be verified before a real run. Things
to look at, in the order they usually go wrong:

- **Effort estimates too optimistic.** The most likely failure. If entries at
  `effort: 1` clearly are not weekend projects, tighten the wording in
  `rubric/SCORING.md` rather than arguing with individual scores.
- **Too many entries accepted.** A typical batch of 12 candidates should yield zero
  or one. If it yields four, the model is not rejecting hard enough — strengthen
  rule 1 in `score.py`'s system prompt.
- **Duplicate warnings from `validate.py`.** The `same_target and ratio > 0.55`
  heuristic is deliberately noisy. Loosen `DUP_RATIO` once you see what real
  titles look like.
- **Source yield.** After a week, check which `sources.yml` entries ever produced an
  accepted idea. `SOURCES.md` now shows each one's failing and dry streaks, so this
  is a matter of reading the health column — but a source that answers every day and
  has never produced an entry is the one to cut, and only the ideas tell you that.
  Retire it into `retired:` with a reason; never just delete the entry.

---

## What was already verified

Done and tested on poppy, so you do not need to re-check it:

- `render.py` is idempotent, and `--check` correctly detects a hand-edited
  `HITLIST.md`
- the 30-entry cap evicts the weakest unpinned entries and writes a reason
- a `pinned: true` entry survives eviction with the worst possible score
- `validate.py` catches schema violations, slug/filename mismatches and cap breaches
- every source in `sources.yml` was probed live before being added, and the full
  100-source list was run end to end on 2026-09-13: **1571 candidates, 98/100 sources
  healthy**, all four groups populated
- `render.py` generates `SOURCES.md` from `sources.yml` + `source_health.json`, and
  `validate.py` fails on a duplicate source id, an unknown collector, a collector
  missing a required param, a retirement with no reason, or a 101st source

## Source notes from the 2026-09-12 rebuild

- **Reddit is gone.** All five subreddits return `403` to unauthenticated clients;
  this is Reddit's policy, not a local egress rule, and no user agent fixes it.
  Replaced by Lemmy (`lemmy.world/selfhosted`, `lemmy.ml/opensource,degoogle,
  privacy,linux`) and Discourse (Privacy Guides, Home Assistant, F-Droid, OpenWrt,
  Framework). Note which Lemmy instance hosts which community — they differ.
- **HN Algolia ANDs every word in a query.** Multi-word queries like
  `"API shutting down deprecated"` matched almost nothing. Queries are now one
  concept each; the mandate ones carry `window_days: 90` because regulation does
  not move in a fortnight.
- **Never star-sort a static GitHub corpus.** `archived:true stars:>1500` sorted by
  stars returns the same forty famous corpses on every run forever. Sort by
  `updated` and window the push date.
- **Dropped after testing:** the OpenStreetMap forum (49 tagging-minutiae topics
  for 2 usable signals) and `se-opendata` (dataset requests, not idea signal).
- **`softwarerecs` unanswered questions are the densest signal in the file** — a
  stated need with no product behind it — but the site is quiet, so recent entries
  score 0–1. That is expected; do not raise `min_score` on it.

## Source notes from the 2026-09-13 import

- **The list is capped at 100 and `SOURCES.md` is generated** — see CLAUDE.md §13.
  Removing a source means moving it to `retired:` in `sources.yml`, never deleting
  the entry. The 2026-09-12 session dropped the OpenStreetMap forum and `se-opendata`
  with good reasons, but had nowhere to write them down, so this session re-proposed
  both. They are now in `retired:` and cannot come back by accident.
- **The RSS import.** `harvest/rssguard_feeds_2026-06-30.opml` holds 41 feeds. Nine
  were in charter and kept; nine are consumer-tech and pop-science; 22 are sport,
  travel, humour and general news. All 32 rejects are in `retired:` as two bucket
  entries so the same OPML never has to be triaged twice.
- **A feed that answers a probe can still be gated.** `theregister.com` served 50
  items to the probe and a proof-of-work "are we human" interstitial to the harvest
  an hour later. Replaced with `netzpolitik.org`. When a source starts failing,
  fetch it by hand before assuming the harvester broke.
- **`score.py --limit` had to rise to 120.** The round-robin takes one item per
  source before a second from any, so a 60-item batch across 100 sources could never
  reach the tail of the file. The bucket order now also rotates with the date, so no
  source can sit permanently below the cut.
- **Feeds carry no engagement number at all.** 38 of the 100 sources (37 RSS plus
  Killed by Google) now score 0 on every item, which makes `score.py`'s round-robin
  load-bearing rather than a nicety — a flat sort would bury every one of them.

## Known environment notes

- **Python packages need a venv.** poppy is PEP 668 managed, so `pip install` into
  the system interpreter is refused. `jsonschema` is *not* present system-wide:

  ```bash
  python3 -m venv .venv && .venv/bin/pip install -r harvest/requirements.txt
  .venv/bin/python harvest/render.py
  ```

  `.venv/` is gitignored. PyYAML alone is present system-wide.
- **The egress note in earlier versions of this file was wrong.** HN, Lobsters,
  Lemmy, Discourse, Stack Exchange, GitHub and the EU RSS feed all answer fine from
  poppy. Only Reddit 403s, and it does that everywhere.
- **`.github/workflows/` is protected from remote file tools.** A Claude session
  working through the device bridge must write workflow files via the shell, not the
  file tools.
- `git`, `python3`, `node`, `curl`, `gh` (authenticated as `elkojo`) and PyYAML are
  present on poppy.
- A stray `.github/workflows/probe.tmp` exists and is gitignored.
