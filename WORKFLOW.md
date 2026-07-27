# Workflow & Methodology

How this list is produced and kept current. Back to the [README](README.md).

## Design in one paragraph

`data/papers.yaml` is the only file a human edits. Everything visible —
`README.md`, `TIMELINE.md`, `BY_INSTITUTION.md` — is regenerated from it, so
there is no way for the views to drift apart. A GitHub Action crawls arXiv every
morning, classifies what it finds against the taxonomy in
`data/categories.yaml`, and drops the results into a digest plus a review queue.
Nothing enters the curated list without a human promoting it.

```
                  data/categories.yaml   (taxonomy + search queries)
                            |
   arXiv  --fetch_arxiv.py--+--> daily/YYYY-MM-DD.md      (digest, auto)
                            |    data/candidates.yaml     (review queue, auto)
                            |
                    add_paper.py  (human promotes)
                            |
                            v
                    data/papers.yaml     (curated source of truth)
                            |
                  generate_readme.py
                            |
        +-------------------+-------------------+
        v                   v                   v
    README.md          TIMELINE.md      BY_INSTITUTION.md
```

## The three tracks

| Track | Scope | Typical question it answers |
| --- | --- | --- |
| **LLM & Agent** | Language-only models, post-training, agents, tool use | How does the model think and act through text? |
| **VLM** | Vision-language understanding, video, spatial, GUI agents | How does the model see? |
| **VLA** | Perception and language grounded into physical action | How does the model act in the world? |

The boundary cases are deliberate: a GUI agent driving a screen is **VLM**
(its action space is the interface, not the physical world), while a robot or
vehicle policy is **VLA**. A reasoning paper with no visual input is **LLM**
even when the method later transfers to VLA post-training.

Subcategories live in `data/categories.yaml`. Adding one there is enough — both
the generator and the crawler pick it up on the next run.

## Daily automation

`.github/workflows/daily-update.yml` runs at 01:00 UTC (09:00 Beijing), just
after arXiv's overnight announcement:

1. `fetch_arxiv.py --days 2` runs one search per track, keeps papers newer than
   the cutoff that pass the gate keywords, and scores each one against every
   subcategory's keyword list. Title hits count triple, abstract hits count
   once, and each subcategory has an optional `weight` to break ties in favour
   of the more specific bucket.
2. The results are written to `daily/YYYY-MM-DD.md` and appended to
   `data/candidates.yaml`, capped at the newest 400 entries.
3. `generate_readme.py` re-renders the three views.
4. The Action commits only if something actually changed.

The two-day window is intentional overlap: a missed run does not create a hole,
and duplicates are filtered against both `papers.yaml` and the queue.

## Promoting a candidate

Read the digest, pick what is worth keeping, then:

```bash
python scripts/add_paper.py 2604.01234 \
    --institution "Tsinghua, Xiaomi" \
    --section vla --subcategory driving \
    --summary "One line on why this matters." --star
```

The script pulls the title and date from arXiv, removes the entry from the
review queue, and regenerates the views. Omit `--section` and the keyword
classifier guesses — always check what it printed.

## Verifying the data

```bash
python scripts/sync_metadata.py --check     # compare local titles against arXiv
python scripts/sync_metadata.py --offline   # taxonomy and duplicates only, no network
```

The title-similarity check is the important one: it is the only thing standing
between a mistyped arXiv id and a confidently wrong citation. Anything below
0.62 similarity is reported with both titles side by side.

## Rate limits

arXiv throttles hard and answers a burst with HTTP 429 followed by several
minutes of timeouts from the same IP. The client therefore waits 15 seconds
between calls, backs off for three minutes on a 429, and caches every response
in `data/.arxiv_cache.json` (git-ignored) so a re-run costs nothing. If you are
on a shared or corporate IP, expect the first full sync to take a while; the
GitHub Action rarely hits the limit.

## Conventions

- **One line per summary.** If it needs two, it belongs in `reports/`.
- **`star: true` sparingly** — reserved for papers a newcomer should read first.
- **Institutions** are written as a comma-separated list, industry lab first;
  `BY_INSTITUTION.md` splits and counts each one.
- **Dates** are the arXiv v1 submission date, never the conference date, so the
  timeline reflects when the idea became public.
