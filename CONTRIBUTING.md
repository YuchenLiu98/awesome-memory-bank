# Contributing

Thanks for adding a paper. The whole process is one YAML entry.

## Is it in scope?

One question decides it: **is memory the contribution?** The paper must store
something and retrieve it later — across turns, across hours of video, across
visits to the same room. A stronger backbone that happens to have a KV cache is
out of scope no matter how good it is, and so is a systems paper about cutting
GPU memory. When in doubt, ask whether the title would still make sense with
the word "memory" removed; if it would, the paper probably belongs elsewhere.

## Quick path

```bash
python scripts/add_paper.py 2508.19236 \
    --institution "Shanghai AI Lab, Tsinghua" \
    --section vla --subcategory vla-mem \
    --summary "Perceptual-cognitive memory bank that gives VLA policies temporal context."
```

That fetches the title and date from arXiv, writes the entry to
`data/papers.yaml`, and regenerates `README.md`, `TIMELINE.md` and
`BY_INSTITUTION.md`. Commit all of them together.

## Manual path

Append to the `papers:` list in `data/papers.yaml`:

```yaml
  - arxiv: "2508.19236"
    institution: "Shanghai AI Lab, Tsinghua"
    section: vla            # llm | vlm | vla
    subcategory: vla-mem    # see data/categories.yaml
    summary: "One line on why this paper matters."
    star: true              # optional, highlights the entry
    code: "https://github.com/..."     # optional
    project: "https://..."             # optional
```

Then:

```bash
python scripts/sync_metadata.py     # fills title / date / url from arXiv
python scripts/generate_readme.py   # regenerates the three views
```

## Rules that keep the list readable

1. **Never edit `README.md`, `TIMELINE.md` or `BY_INSTITUTION.md`.** They are
   build artifacts and your change will be overwritten. Edit `data/papers.yaml`.
2. **Summaries are one line and say why the paper matters**, not what it
   contains. "Ebbinghaus-curve forgetting applied to stored dialogues" beats "a
   long-term memory method for language models".
3. **Pick the most specific subcategory.** If a paper genuinely spans two, pick
   the one a reader would look under first.
4. **`star: true` is for entry points**, not for papers you like. Roughly one in
   five is already generous.
5. **Institutions**: comma-separated, industry lab or lead affiliation first,
   short forms (`Tsinghua`, `PKU`, `Google DeepMind`) for consistency with
   existing entries.

## Adding a subcategory

Edit `data/categories.yaml`. A new subcategory needs an `id`, a `title` and a
`keywords` list used by the daily crawler for auto-classification. Optionally
set `weight` above 1.0 to make it win ties against broader buckets. Run
`python scripts/generate_readme.py` afterwards.

## Before opening a PR

```bash
python scripts/sync_metadata.py --check   # verifies ids against arXiv
python scripts/generate_readme.py
```

CI runs the same checks plus a staleness check on the generated views.
