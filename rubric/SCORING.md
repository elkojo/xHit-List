# Scoring rubric

```
rubric_version: 1
```

Bumping `rubric_version` re-scores every live idea on the next run. Do not bump it
casually — a bump invalidates every comparison in the list. Changes to this file go
through a PR.

All axes are integers. When an idea sits between two levels, take the **lower**
reward-side score and the **higher** cost-side score. Optimism is the main failure
mode of this rubric.

---

## `reward` — value if it exists and works (1–5)

| | |
|---|---|
| 5 | Frees thousands of people from a hard dependency, or opens a whole category that has no open option at all |
| 4 | A serious, daily-use replacement for something many people currently pay for or tolerate |
| 3 | Solves a real recurring pain for a defined group of people |
| 2 | Useful; a better version of something that already exists |
| 1 | Niche convenience |

## `disruption` — how hard it hits the incumbent (0–5)

| | |
|---|---|
| 5 | Replaces a core function of a state monopoly or a dominant platform that has **no viable open substitute today** |
| 4 | Credible open replacement for a paid closed-source product with strong lock-in |
| 3 | Removes a specific lock-in point: an exporter, a protocol bridge, a format liberator, an open client for a closed API |
| 2 | Open alternative in a market that already has some open options |
| 1 | Marginally reduces dependence on an incumbent |
| 0 | **Out of charter — reject.** Threatens no closed, state, or monopoly incumbent |

Three target kinds count, recorded in `target.kind`:

- **`closed_source`** — a proprietary product or platform with lock-in.
- **`state_service`** — a government-run service that is a monopoly by law or by
  default: registries, identity, filing, permits, transparency portals, public data
  locked behind unusable interfaces.
- **`pseudo_monopoly`** — not a legal monopoly, but effectively unavoidable: the one
  payment rail, the one app store, the one cloud API your whole stack assumes, a
  standards body captured by one vendor.

## `effort` — build cost (1–5)

Calibrated to **one competent developer working with AI agents, part-time.** Same
yardstick every time, or the list is not comparable.

| | |
|---|---|
| 1 | A weekend. One clear interface, no unknowns |
| 2 | About two weeks. Known techniques, some integration work |
| 3 | About two months. Real design decisions, one genuinely hard part |
| 4 | About six months. Several hard parts, or reverse-engineering required |
| 5 | Longer, or needs a team, capital, hardware, or a licence |

Test before you score: **name the three hardest parts.** If you cannot, the estimate
is too low. Add 1 if the project requires reverse-engineering an undocumented
protocol, and 1 if it requires ongoing maintenance against a hostile moving target.

## `demand` — evidenced, not assumed (1–5)

| | |
|---|---|
| 5 | Loud, repeated, recent: multiple high-engagement threads or issues, or a popular abandoned project with many forks |
| 4 | Several independent, dated artifacts asking for it |
| 3 | Clear but scattered |
| 2 | Thin: one substantial artifact |
| 1 | Inferred from a single weak artifact |

Every point here must trace to an `evidence` entry. No artifact, no score above 1.

## `moat_risk` — can the incumbent switch it off (0–5)

| | |
|---|---|
| 0 | Nobody can stop it. Runs locally, standards-based, or on data that is already public |
| 1–2 | Mild exposure: depends on a stable public interface, or on a format that rarely changes |
| 3 | Depends on an API the incumbent controls and could close or price out |
| 4 | Requires scraping or reverse-engineering something actively defended |
| 5 | Legally exposed, or needs the incumbent's cooperation to work at all |

This is a cost, not a veto. A high-reward idea with `moat_risk: 4` can still rank
well; it just has to be worth the fight. Record the specifics in `legal_note`.

---

## The formula

```
xhit = (2·reward + 2·disruption + demand) / (effort + moat_risk/2)
```

Rounded to two decimals by `render.py`. Never write `xhit` by hand.

Reward and disruption are weighted equally and doubled — this is a list about
breaking dependencies, so an idea that is merely useful cannot outrank one that is
useful *and* lands a hit. Effort divides, which is what keeps the top of the list
buildable rather than merely grand.

Ties break toward lower `effort`, then toward the most recent `evidence` date.

### Worked example

An open client for a government interface that regulation already mandates:
`reward 5`, `disruption 5`, `effort 3`, `demand 3`, `moat_risk 1`

```
(2·5 + 2·5 + 3) / (3 + 0.5) = 23 / 3.5 = 6.57
```

A weekend tool that exports your data out of one paid app:
`reward 2`, `disruption 3`, `effort 1`, `demand 4`, `moat_risk 3`

```
(2·2 + 2·3 + 4) / (1 + 1.5) = 14 / 2.5 = 5.60
```

Both rank well, for opposite reasons. That is the rubric working.
