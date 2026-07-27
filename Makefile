.PHONY: help fetch build sync check add reclassify

help:
	@echo "make fetch       crawl arXiv and write today's digest + review queue"
	@echo "make build       regenerate README.md / TIMELINE.md / BY_INSTITUTION.md"
	@echo "make sync        pull titles and dates from arXiv into data/papers.yaml"
	@echo "make check       verify ids, taxonomy and duplicates (no writes)"
	@echo "make reclassify  re-sort the review queue after editing categories.yaml"
	@echo "make add ID=2410.24164   add one paper by arXiv id"

fetch:
	python3 scripts/fetch_arxiv.py --days 2

build:
	python3 scripts/generate_readme.py

sync:
	python3 scripts/sync_metadata.py

check:
	python3 scripts/sync_metadata.py --check

reclassify:
	python3 scripts/reclassify.py --write

add:
	@test -n "$(ID)" || (echo "usage: make add ID=2410.24164"; exit 1)
	python3 scripts/add_paper.py $(ID)
