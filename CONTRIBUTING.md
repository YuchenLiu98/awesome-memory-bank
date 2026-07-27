# Contributing

Thanks for adding a paper. The whole process is one YAML entry.

## Quick path

```bash
python scripts/add_paper.py 2410.24164 \
    --institution "Physical Intelligence" \
    --section vla --subcategory robot-arch \
    --summary "Flow-matching action expert on top of a VLM backbone."
```

That fetches the title and date from arXiv, writes the entry to
`data/papers.yaml`, and regenerates `README.md`, `TIMELINE.md` and
`BY_INSTITUTION.md`. Commit all of them together.

## Manual path

Append to the `papers:` list in `data/papers.yaml`:

```yaml
  - arxiv: "2410.24164"
    institution: "Physical Intelligence"
    section: vla            # llm | vlm | vla
    subcategory: robot-arch # see data/categories.yaml
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
   contains. "GRPO, the critic-free optimizer now used everywhere" beats "a
   reinforcement learning method for language models".
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
