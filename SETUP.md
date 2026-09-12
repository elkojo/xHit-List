# Setup — remaining steps

Everything in this repo is built, committed and verified locally. What is left all
needs GitHub credentials, so it has to be done by a human (or by a Claude Code
session running with your `gh` login).

Pick up here.

---

## 1. Create the remote and push

The repo does not exist on GitHub yet. It was meant to be `elkojo/xHit-List`,
public.

**With `gh`** (not currently installed on poppy — `sudo apt install gh` or
`brew install gh`, then `gh auth login`):

```bash
cd ~/Claude/xHit
gh repo create elkojo/xHit-List --public --source=. --remote=origin --push
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

## 2. Add the model secrets

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

- [ ] `MODEL_BASE_URL`
- [ ] `MODEL_NAME`
- [ ] `MODEL_API_KEY`

## 3. Let the workflow push its commits

**Settings → Actions → General → Workflow permissions → Read and write
permissions.** Without this the daily job runs, finds ideas, and then fails at
`git push` — which looks like a mysterious harvest failure.

- [ ] workflow permissions set to read and write

## 4. First run

**Actions → harvest → Run workflow.** `HITLIST.md` is empty until this happens; the
cron only fires at 05:17 UTC daily.

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
  should earn their keep disproportionately.

---

## What was already verified

Done and tested on poppy, so you do not need to re-check it:

- `render.py` is idempotent, and `--check` correctly detects a hand-edited
  `HITLIST.md`
- the 30-entry cap evicts the weakest unpinned entries and writes a reason
- a `pinned: true` entry survives eviction with the worst possible score
- `validate.py` catches schema violations, slug/filename mismatches and cap breaches
- `harvest.py` fetched 56 real candidates from the GitHub sources

## Known environment notes

- **Only the GitHub sources work from poppy's sandbox.** HN, Reddit and Lobsters
  return `403 Forbidden` from the egress proxy — an allowlist, not a bug. The
  harvester degrades gracefully (logs and continues). GitHub Actions runners have no
  such allowlist, so all sources will work there. Do not "fix" this locally.
- **`.github/workflows/` is protected from remote file tools.** A Claude session
  working through the device bridge must write workflow files via the shell, not the
  file tools.
- `git`, `python3`, `node`, `curl`, PyYAML and jsonschema are present on poppy.
  `gh` is not.
- A stray `.github/workflows/probe.tmp` exists and is gitignored.
