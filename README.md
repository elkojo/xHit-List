# xHit-List

A rolling, agent-maintained list of the **30 software projects most worth building
right now** — ranked by reward against effort, and weighted toward ideas that
disrupt **closed source**, **state service monopolies**, and **(pseudo)monopolies**.

**→ [`HITLIST.md`](HITLIST.md)** is the list. Position 1 is the best
reward-to-effort bet on the board today.

Everything else in this repo exists to keep that one file honest.

---

## How it works

```
sources.yml ──harvest.py──> candidates/*.jsonl ──score.py──> ideas/*.yml
                (fetch only,                      (the one          (source
                 no judgment)                    judgment step)    of truth)
                                                                        │
                                                                   render.py
                                                                        ▼
                                                    HITLIST.md · GRAVEYARD.md · SHIPPED.md
```

A daily GitHub Action fetches signals from ~20 sources, an LLM triages them against
a fixed rubric, and a deterministic script re-ranks and regenerates the markdown.
Judgment lives in exactly one script, so when a ranking looks wrong there is exactly
one place to look.

**The list is capped at 30.** A new idea earns its place by pushing a weaker one out
to [`GRAVEYARD.md`](GRAVEYARD.md) — with its score, the date, and the reason.
Buried ideas keep their files, which is what stops the harvester re-proposing the
same dead idea every week. If new evidence lifts a buried idea back above the
rank-30 cutoff, it comes back.

## The ranking

```
xhit = (2·reward + 2·disruption + demand) / (effort + moat_risk/2)
```

Effort sits in the denominator on purpose. That is what makes the top of the list
*most rewarding **and** reasonably easy to code*, rather than just most ambitious.
Full scale definitions: [`rubric/SCORING.md`](rubric/SCORING.md).

Three things count as a target:

- **closed source** — a proprietary product or platform with real lock-in
- **state service** — a government service that is a monopoly by law or by default:
  registries, identity, filing, permits, public data locked behind unusable portals
- **pseudo-monopoly** — not a legal monopoly but effectively unavoidable: the one
  payment rail, the one app store, the one cloud API your whole stack assumes

An idea that threatens none of these is out of charter, however good it is.

## What gets an idea in

Evidence that **someone else already feels the pain** — and the highest-yield signal
of all is an incumbent closing a door. A price rise, an API shutdown, a licence
change, a free tier withdrawn: when a monopolist locks something down, the window
opens that same week. The harvester watches for exactly that.

The second-best signal is a **mandate**: a regulation that requires an interface
nobody has built an open client for. The incumbent cannot legally close the door it
was ordered to open.

## Status

Not yet live. `SETUP.md` has the remaining steps: create the remote, add the three
model secrets, allow the workflow to push, and trigger the first run.

## Contributing

Humans and agents follow the same contract: **[`CLAUDE.md`](CLAUDE.md)**
(also served as `AGENTS.md`). The short version:

- Never hand-edit `HITLIST.md`, `GRAVEYARD.md` or `SHIPPED.md`. Edit `ideas/*.yml`
  and run `python3 harvest/render.py`.
- One idea per file. No entry without a dated evidence URL. Never fabricate one.
- Run `python3 harvest/validate.py` before you push. CI runs it anyway.

New ideas are also welcome as issues — an agent will triage them into the list.

## Running it yourself

```bash
pip install -r harvest/requirements.txt

python3 harvest/harvest.py --dry-run          # see what the sources return
python3 harvest/score.py --dry-run            # see what would be added
python3 harvest/render.py                     # regenerate the markdown
python3 harvest/validate.py                   # schema + cap + drift
```

The curator model is pluggable — any OpenAI-compatible endpoint:

```bash
export MODEL_BASE_URL=https://openrouter.ai/api/v1
export MODEL_NAME=nousresearch/hermes-4-405b
export MODEL_API_KEY=sk-...
```

Claude, Hermes, or a local llama.cpp are three environment variables apart, with no
code change. In CI these come from repo secrets of the same names.

## Scope

This repo is a **registry, not a workspace**. When an idea gets built it becomes its
own repo, linked from its entry, and moves to [`SHIPPED.md`](SHIPPED.md) — freeing a
slot. The hit list is for work not yet begun.

## Licence

Ideas are not property. Everything here is [CC0](LICENSE) — take one and build it.
