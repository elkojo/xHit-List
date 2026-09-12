# xHit-List — agent operating contract

This file is the contract. Any agent (Claude, Hermes, or another) that touches this
repo reads this file first and obeys it literally. `AGENTS.md` is a copy of this file
for agents that look for that name instead.

---

## 1. Charter

This repo maintains **one rolling, ranked list of at most 30 software projects worth
building**, kept in `HITLIST.md`.

Position 1 is the entry with the best ratio of **reward to effort**, weighted toward
ideas that **disrupt closed source, state-run service monopolies, or
(pseudo)monopolies**. Position 30 is the weakest entry still alive. Entry 31 does not
exist — when a better idea arrives, the weakest one is evicted to `GRAVEYARD.md`.

The list is a *hit list*, not a brainstorm. Every entry must be something a competent
developer working with AI agents could actually start on Monday.

**This repo holds the registry only.** When an idea gets built it becomes its own
repo, linked from its entry. No project code lives here.

---

## 2. Non-negotiables

These exist because each one, if broken, quietly destroys the list's value.

1. **Never hand-edit `HITLIST.md` or `GRAVEYARD.md`.** They are generated artifacts.
   Edit `ideas/*.yml`, then run `python3 harvest/render.py`. A PR that edits a
   generated file directly fails validation.
2. **One idea per file** in `ideas/`, named `<slug>.yml`. This is what makes
   concurrent agents possible — two agents adding ideas never touch the same file.
3. **No entry without evidence.** Every idea carries at least one `evidence` item
   with a URL and a date. An idea an agent merely thought of is not an idea; it is
   noise. Do not fabricate URLs, upvote counts, or dates — ever. If you cannot cite
   it, drop it.
4. **`disruption: 0` is out of charter.** A useful tool that threatens no closed,
   state, or monopoly incumbent does not belong here, however good it is.
5. **Never invent demand.** `demand` is scored from cited artifacts only, not from
   your sense that people would probably like this.
6. **Scores are sticky.** Do not re-score a live idea unless a stickiness trigger
   fires (§7). An agent that re-ranks everything on every run turns the list into
   noise and makes "position 1" meaningless.
7. **Respect `pinned: true`.** A pinned idea is never evicted by score. Only a human
   sets or clears `pinned`.
8. **Data files carry no prose.** `ideas/*.yml` holds structured fields that validate
   against `schema/idea.schema.json`. Argument and nuance go in the `rationale`
   field, capped at 60 words, and nowhere else.

---

## 3. Repo map

```
CLAUDE.md               this contract (AGENTS.md is a copy)
README.md               human-facing explanation
HITLIST.md              GENERATED — the ranked top 30
GRAVEYARD.md            GENERATED — evicted ideas, with reason and date
SHIPPED.md              GENERATED — ideas that became real repos
ideas/<slug>.yml        source of truth, one file per idea
schema/idea.schema.json validates every idea file
rubric/SCORING.md       the rubric, versioned — bumping it re-scores everything
harvest/sources.yml     where to look for candidates
harvest/harvest.py      deterministic fetch -> candidates/<date>.jsonl  (no LLM)
harvest/score.py        the one LLM pass: triage, score, dedupe, write ideas/
harvest/render.py       ideas/*.yml -> HITLIST.md, GRAVEYARD.md, SHIPPED.md
harvest/validate.py     schema check + generated-file drift check
candidates/<date>.jsonl raw harvest, pre-judgment, append-only
.github/workflows/      harvest.yml (cron), validate.yml (PR gate)
```

---

## 4. The data model

Every file in `ideas/` looks like this. Fields marked **required** must be present.

```yaml
slug: open-eidas-wallet            # required, kebab-case, == filename
title: Open-source eIDAS 2.0 wallet client   # required, <= 70 chars
status: live                       # required: live | graveyard | building | shipped
pinned: false                      # human-only flag

target:                            # required — what this disrupts
  kind: state_service              # closed_source | state_service | pseudo_monopoly
  name: National e-ID portals
  why_vulnerable: >                # <= 30 words
    Regulation mandates the interface; no usable open client exists.

what: >                            # required, <= 40 words. The build, concretely.
  A cross-platform wallet that speaks the mandated protocol, stores credentials
  locally, and never phones a vendor server.

rationale: >                       # required, <= 60 words. Why now, why this wins.
  The interoperability obligation is live but every shipped client is a national
  contractor build. An open client becomes the reference implementation.

scores:                            # required — see rubric/SCORING.md
  reward: 5
  disruption: 5
  effort: 3
  demand: 3
  moat_risk: 1
xhit: 7.27                         # computed by render.py — never set by hand

evidence:                          # required, >= 1 item
  - url: https://example.org/thread
    date: 2026-09-04
    note: 200-comment thread asking for exactly this   # <= 15 words

first_seen: 2026-09-12             # required, set once, never changed
last_scored: 2026-09-12            # required, set by score.py
rubric_version: 1                  # required, from rubric/SCORING.md

repo:                              # only when status is building or shipped
legal_note:                        # optional, informational, not scored
```

`legal_note` matters here. Disrupting state services and monopolies can carry real
regulatory exposure. Record it plainly so a human can judge it; it never changes the
score.

---

## 5. The rubric

Each axis is an integer. The full scale definitions live in `rubric/SCORING.md` —
read that file before scoring anything. Summary:

| axis | 1 | 5 |
|---|---|---|
| `reward` | niche convenience | frees thousands from a hard dependency, or opens a category |
| `disruption` | marginally reduces dependence | replaces a core function of a state monopoly or dominant platform with no open substitute today |
| `effort` | a weekend | many months, or needs a team, capital, or hardware |
| `demand` | inferred from one artifact | loud, repeated, recent, evidenced |
| `moat_risk` | *(0)* nobody can switch it off | legally exposed, or needs the incumbent's cooperation |

`effort` is calibrated to **one competent developer working with AI agents,
part-time**. Every estimate uses that same yardstick or the list stops being
comparable.

**The score:**

```
xhit = (2·reward + 2·disruption + demand) / (effort + moat_risk/2)
```

Effort sits in the denominator on purpose: that is what makes the top of the list
"most rewarding *and* reasonably easy to code" rather than just most ambitious.
Ties break toward lower `effort`, then toward more recent `evidence`.

Hard gate: `disruption == 0` → reject, do not write a file.

---

## 6. Lifecycle

```
candidates/*.jsonl ──triage──> ideas/<slug>.yml (live) ──> top 30 in HITLIST.md
                                      │
                          score falls out of top 30
                                      ▼
                            status: graveyard ──new evidence──> back to live
                                      │
                        human starts building it
                                      ▼
                        status: building (repo: url) ──> status: shipped
```

- **The cap is 30 live entries.** After every scoring run, `render.py` sorts live
  ideas by `xhit` descending. Ranks 31+ get `status: graveyard`, an `evicted_on`
  date, and a one-line reason. Pinned ideas are exempt and do not consume a slot's
  eviction pressure — if pinning pushes the list over 30, the cap applies to the
  unpinned remainder.
- **Graveyard entries keep their file.** This is deliberate: it is the dedupe ledger.
  Without it the harvester re-proposes the same dead idea every week.
- **Resurrection is allowed.** If new evidence raises a graveyard idea's score above
  the current rank-30 entry, flip it back to `live`. Note the resurrection in
  `evidence`.
- **`building` and `shipped` leave the 30**, freeing a slot. They move to
  `SHIPPED.md` with a link to their own repo. The list is for work not yet started.

---

## 7. Score stickiness

Re-score a live idea **only** when one of these fires:

1. New `evidence` was attached since `last_scored`.
2. `last_scored` is more than 30 days ago.
3. `rubric_version` in the file is behind `rubric/SCORING.md` (a rubric change
   re-scores the whole list, once).
4. A human asked for it.

New candidates are always scored on arrival. Everything else keeps the score it has.

---

## 8. Running the jobs

```bash
python3 harvest/harvest.py                 # fetch candidates -> candidates/<date>.jsonl
python3 harvest/score.py                   # LLM pass: triage, score, write ideas/
python3 harvest/render.py                  # regenerate HITLIST.md, GRAVEYARD.md, SHIPPED.md
python3 harvest/validate.py                # schema + drift check; exits non-zero on failure
```

`harvest.py` and `render.py` use no model and must stay that way — keeping judgment
in exactly one place is what makes the list auditable.

**The model is pluggable.** `score.py` talks to any OpenAI-compatible
`/chat/completions` endpoint:

```bash
MODEL_BASE_URL=https://api.openai.com/v1        MODEL_NAME=...        MODEL_API_KEY=...
MODEL_BASE_URL=https://openrouter.ai/api/v1     MODEL_NAME=nousresearch/hermes-...
MODEL_BASE_URL=http://localhost:8080/v1         MODEL_NAME=local      MODEL_API_KEY=none
```

Swapping Claude for Hermes for a local model is three environment variables and no
code change. In CI these come from repo secrets. Do not hardcode a provider, and do
not add a second code path for a specific vendor.

---

## 9. Commit conventions

- Daily harvest commits straight to `main`. It is a list, not production code; git
  history is the audit trail and reverting is one command.
- Open a **PR instead of committing** when: evicting a `pinned` idea, changing
  `rubric/SCORING.md`, changing `schema/`, or changing any script.
- One logical change per commit. Message form:
  `harvest: +3 ideas, -1 evicted, 2 rescored` / `idea(open-eidas-wallet): new evidence`
- Bot commits are authored `xhit-bot <bot@xhit.list>` so human and agent history stay
  separable.
- Always run `render.py` then `validate.py` before committing. Never commit with
  generated files out of date.

---

## 10. Evidence standards

Good evidence shows **someone else already feels the pain**:

- a thread, issue, or comment asking for exactly this thing, with a date
- a popular repo that is archived or unmaintained (an abandoned solution is a proven
  demand with a vacant seat)
- an incumbent's own announcement of a price rise, API shutdown, rate limit, or
  licence change — this is the single highest-yield signal in the whole system. When
  a monopolist closes a door, the window opens that same week
- a regulation that mandates an interface nobody has built an open client for
- an open-data or transparency dataset that is public but effectively unusable

Bad evidence: a blog post arguing the idea is nice; a landing page for a product that
already does it well; anything undated; your own reasoning.

---

## 11. Anti-patterns — do not add these

- **"An open-source X"** with no wedge. "Open-source Figma" is not an idea, it is a
  wish. The idea is the specific lever that makes it possible now.
- **Ideas that need a network before they are useful.** A federated anything with
  zero users beats nothing. Prefer tools that are valuable to their first single
  user.
- **Effort scored by enthusiasm.** If you cannot name the three hardest parts, the
  effort estimate is wrong — and it is almost always too low.
- **Chasing a hype cycle.** The list rewards durable dependencies broken, not the
  newest framework.
- **Restating an existing entry in new words.** Check `ideas/` — *including
  graveyard entries* — before writing a file. Match on slug, on target name, and on
  fuzzy title.
- **Thirty variations on one theme.** Diversity of target is a feature. If five live
  entries attack the same incumbent, keep the strongest and graveyard the rest.

---

## 12. Working on this repo as an agent

- Read this file, then `rubric/SCORING.md`, then `schema/idea.schema.json`. Do not
  infer the format from `HITLIST.md`; it is generated output.
- Prefer a small, correct change over a large one. Adding two well-evidenced ideas
  is worth more than twenty thin ones, and the cap means thin ones only push good
  ideas out.
- Emit strict JSON matching the schema. No markdown fences, no commentary.
- If you find this contract ambiguous or wrong, do not improvise around it. Open a
  PR that changes this file and say why.
