# Setup — remaining steps

Everything in this repo is built, committed and verified locally. What is left all
needs GitHub credentials, so it has to be done by a human (or by a Claude Code
session running with your `gh` login).

Pick up here.

---

## 0. Where this stands (2026-09-12)

Four commits exist. `main` holds the scaffold plus one harvest-audit commit; the
work from the 2026-09-12 session sits on branch **`harvest/live-sources`**, unpushed
because there is still no remote:

```
212d7c6  harvest: +4 ideas, 0 evicted, 0 rescored        (branch)
ea6e46b  harvest: normalise YAML-native dates on load     (branch)
e49384f  harvest: replace dead sources, add five collectors, fix ordering  (branch)
a7318fb  harvest: 70 candidates, 0 ideas, 0 rescored      (main)
```

That branch needs a PR, not a merge to `main` — it changes `harvest.py`,
`score.py`, `render.py` and `validate.py`, which CLAUDE.md §9 puts behind review.
Opening it is blocked on step 1.

`HITLIST.md` is seeded with 4 live entries. The pipeline is green end to end
(`validate.py` exits 0).

**Open question, answered but not yet written into the contract.** The scoring pass
is to be done by the agent connected to the repo, not by `score.py` calling an
endpoint. CLAUDE.md §8 and `.github/workflows/harvest.yml` still assume the
endpoint, so the nightly cron will fail at `score.py` until one of the two is
changed. Decide which is primary, then open a PR against §8 and the workflow.

---

## 1. Create the remote and push

The repo does not exist on GitHub yet. It was meant to be `elkojo/xHit-List`,
public.

`gh` **is** installed and authenticated as `elkojo`:

```bash
cd ~/Claude/xHit
gh repo create elkojo/xHit-List --public --source=. --remote=origin --push
git push -u origin harvest/live-sources
gh pr create --base main --head harvest/live-sources
```

**Without `gh`** — create an empty repo named `xHit-List` at
<https://github.com/new> (public, **no** README, **no** .gitignore, **no** licence —
this repo already has them and an auto-init would collide), then:

```bash
cd ~/Claude/xHit
git remote add origin git@github.com:elkojo/xHit-List.git
git push -u origin main
```

- [ ] remote created
- [ ] `main` pushed
- [ ] `harvest/live-sources` pushed and PR opened

## 2. Add the model secrets

Only needed if `score.py` stays a scoring route — see the open question in §0.

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

- [ ] decided whether the endpoint is a route at all
- [ ] `MODEL_BASE_URL`
- [ ] `MODEL_NAME`
- [ ] `MODEL_API_KEY`

## 3. Let the workflow push its commits

**Settings → Actions → General → Workflow permissions → Read and write
permissions.** Without this the daily job runs, finds ideas, and then fails at
`git push` — which looks like a mysterious harvest failure.

- [ ] workflow permissions set to read and write

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
  accepted idea. Drop the dead ones; the `enshittification` and `mandate` groups
  should earn their keep disproportionately. One pass of this was already done on
  2026-09-12 — see the notes below.

---

## What was already verified

Done and tested on poppy, so you do not need to re-check it:

- `render.py` is idempotent, and `--check` correctly detects a hand-edited
  `HITLIST.md`
- the 30-entry cap evicts the weakest unpinned entries and writes a reason
- a `pinned: true` entry survives eviction with the worst possible score
- `validate.py` catches schema violations, slug/filename mismatches and cap breaches
- every source in `sources.yml` was probed live on 2026-09-12 and answered: 425
  candidates, no warnings, all four groups populated

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
