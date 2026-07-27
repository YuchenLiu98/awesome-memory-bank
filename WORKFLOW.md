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
                            |  \
                            |   `-- inst_utils.py  (affiliations from the PDF)
                            v
                    data/papers.yaml     (curated source of truth)
                            |
                  generate_readme.py
                            |
        +-------------------+-------------------+
        v                   v                   v
    README.md          TIMELINE.md      BY_INSTITUTION.md
```

## What counts as a memory paper

The list has exactly one admission criterion: **memory is the contribution**,
not a component the method happens to contain. A model that stores and later
retrieves its own past belongs here; a stronger backbone that merely has a KV
cache does not. Concretely, *MemoryVLA: Perceptual-Cognitive Memory in
Vision-Language-Action Models* is in scope and *Qwen2-VL* is not, even though
the second is the more influential paper.

The word "memory" alone cannot decide this, because in machine-learning writing
it usually means VRAM. `arxiv.memory_keywords` in `data/categories.yaml`
therefore lists only explicit phrases — `episodic memory`, `memory bank`,
`knowledge editing`, `kv cache` — and `hardware_memory_keywords` masks out
`memory-efficient`, `memory footprint` and friends before matching, so a
systems paper about reducing GPU memory cannot enter on the word alone.

## The three tracks

| Track | Scope | The memory question it asks |
| --- | --- | --- |
| **LLM & Agent** | Language-only models and text agents | What should the model carry forward across turns and sessions? |
| **VLM** | Vision-language and video models | What should it retain from hours of visual input? |
| **VLA** | Policies grounded in physical action | What must it remember about a place it has been? |

The boundary cases are deliberate: a GUI agent's workflow memory is **VLM**
(its action space is the interface, not the physical world), while a robot or
navigation policy is **VLA**. Classic pre-LLM work such as Neural Turing
Machines sits under **LLM** as the architectural ancestor of the rest.

Subcategories live in `data/categories.yaml`. Adding one there is enough — both
the generator and the crawler pick it up on the next run.

## Daily automation

`.github/workflows/daily-update.yml` runs at 01:00 UTC (09:00 Beijing), just
after arXiv's overnight announcement:

1. `fetch_arxiv.py --days 2` runs one broad query per arXiv category —
   `cat:cs.CL AND abs:"memory"` and its four siblings — and does the real
   filtering locally: primary-category allowlist, then the memory gate above,
   then the track gate. Survivors are scored against every subcategory's
   keyword list, where title hits count triple, abstract hits count once, and
   each subcategory has an optional `weight` to break ties in favour of the
   more specific bucket.

   Casting a wide net and filtering locally beats enumerating phrases at the
   API, which always misses papers whose wording nobody anticipated. On a 2026
   backfill the category queries surfaced 839 memory papers where a hand-tuned
   phrase list had found a few dozen.
2. The results are written to `daily/YYYY-MM-DD.md` and appended to
   `data/candidates.yaml`, capped at the newest 400 entries. Papers that match
   the queries but no subcategory keywords land in an **Unsorted** bucket
   rather than being forced into the nearest category — that bucket is where
   genuinely new topics show up first.
3. `generate_readme.py` re-renders the three views.
4. The Action commits only if something actually changed.

The two-day window is intentional overlap: a missed run does not create a hole,
and duplicates are filtered against both `papers.yaml` and the queue.

## Promoting a candidate

Read the digest, pick what is worth keeping, then:

```bash
python scripts/add_paper.py 2604.01234 \
    --institution "Tsinghua, Shanghai AI Lab" \
    --section vla --subcategory vla-mem \
    --summary "One line on why this matters." --star
```

The script pulls the title and date from arXiv, removes the entry from the
review queue, and regenerates the views. Omit `--section` and the keyword
classifier guesses — always check what it printed.

## Tuning the classifier

Keyword lists drift out of date faster than the papers do. After editing
`data/categories.yaml`:

```bash
python scripts/reclassify.py           # preview the moves
python scripts/reclassify.py --write   # apply and rebuild today's digest
```

Two rules keep the buckets clean. Keep keywords **specific to their track** — a
bare `memory module` under VLA swallows every LLM agent paper, whereas
`embodied memory` does not. And raise `weight` only on the narrow subcategories
that keep losing to broader ones, since a title hit is already worth three
abstract hits.

## Where institutions come from

The arXiv API does not expose affiliations, so `scripts/inst_utils.py` reads
them off page one of the PDF and matches against roughly 200 institution
patterns. It also maps well-known model and product names to their parent
organisation, so a `Qwen`-branded paper is credited to Alibaba.

The difficulty is not reading the PDF but reading little enough of it. Only two
zones are searched:

- the **author block**, from below the title to the abstract, capped at 14
  lines and cut short by a figure or section heading
- the **footnote zone**, the last 20 lines, filtered down to lines that
  actually contain an affiliation keyword and truncated at 160 characters

Body text, figure captions and related work are never searched. That exclusion
is the whole point: "we compare against LLaMA" must not make a paper come from
Meta, and a related-work paragraph must not credit every lab it cites.

```bash
python scripts/inst_utils.py 2508.19236   # what does the PDF say?
make inst                                 # audit papers.yaml against the PDFs
```

`add_paper.py` calls this automatically when you omit `--institution`. Treat
the result as a first draft: two-column layouts and image-only PDFs defeat it,
and it prints what it found so you can correct it. Extracted text is cached in
`.pdf_cache/` (git-ignored), so an audit re-run costs no downloads.

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
