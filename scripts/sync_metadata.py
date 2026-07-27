#!/usr/bin/env python3
"""Fill in and verify paper metadata from the arXiv API.

    python scripts/sync_metadata.py            # fill missing title/date/url
    python scripts/sync_metadata.py --force    # also overwrite existing values
    python scripts/sync_metadata.py --check    # report only, non-zero on problems

A low title similarity almost always means the arXiv id in papers.yaml is
wrong, so that check is the main guard against silently citing the wrong paper.
"""

from __future__ import annotations

import argparse
import difflib
import sys

import common

SIMILARITY_FLOOR = 0.62


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def report(problems: list[str], warnings: list[str]) -> None:
    if warnings:
        print(f"\n--- {len(warnings)} warning(s) ---")
        for warning in warnings:
            print("  " + warning)
    if problems:
        print(f"\n--- {len(problems)} problem(s) ---")
        for problem in problems:
            print("  " + problem)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing title/date")
    parser.add_argument("--check", action="store_true", help="do not write, only report")
    parser.add_argument(
        "--offline", action="store_true", help="skip arXiv, check taxonomy and duplicates only"
    )
    args = parser.parse_args()

    categories = common.load_categories()
    papers = common.load_papers()
    valid_subs = common.subcategory_index(categories)

    problems: list[str] = []
    warnings: list[str] = []
    seen: dict[str, int] = {}
    for i, paper in enumerate(papers):
        key = (paper.get("section"), paper.get("subcategory"))
        if key not in valid_subs:
            problems.append(f"[taxonomy] {paper.get('arxiv')}: unknown section/subcategory {key}")
        arxiv_id = str(paper.get("arxiv") or "").strip()
        if not arxiv_id:
            problems.append(f"[missing id] entry #{i}: {paper.get('title')!r}")
            continue
        if arxiv_id in seen:
            problems.append(f"[duplicate] {arxiv_id} appears twice")
        seen[arxiv_id] = i

        if not (paper.get("summary") or "").strip():
            warnings.append(f"[no summary] {arxiv_id} ({paper.get('title')!r})")
        if not (paper.get("institution") or "").strip("— "):
            warnings.append(f"[no institution] {arxiv_id}")

    if args.offline:
        filled = 0
        for paper in papers:
            if not paper.get("date"):
                fallback = common.date_from_arxiv_id(paper.get("arxiv"))
                if fallback:
                    paper["date"] = fallback
                    filled += 1
            if not paper.get("url") and paper.get("arxiv"):
                paper["url"] = f"https://arxiv.org/abs/{paper['arxiv']}"
        report(problems, warnings)
        print(f"Checked {len(papers)} papers offline.")
        if filled and not args.check:
            common.save_papers(papers, categories)
            print(f"Filled {filled} month-precision date(s) from arXiv ids; "
                  "run without --offline to get exact dates.")
        return 1 if problems else 0

    ids = [str(p["arxiv"]).strip() for p in papers if p.get("arxiv")]
    print(f"Querying arXiv for {len(ids)} papers ...")
    meta = common.fetch_by_ids(ids)
    print(f"Got metadata for {len(meta)} of them.")

    updated = 0
    for paper in papers:
        arxiv_id = str(paper.get("arxiv") or "").strip()
        entry = meta.get(arxiv_id)
        if entry is None:
            problems.append(f"[not found] {arxiv_id} ({paper.get('title')!r})")
            continue

        local_title = (paper.get("title") or "").strip()
        if local_title:
            ratio = similarity(local_title, entry["title"])
            if ratio < SIMILARITY_FLOOR:
                problems.append(
                    f"[title mismatch {ratio:.2f}] {arxiv_id}\n"
                    f"    local  : {local_title}\n"
                    f"    arXiv  : {entry['title']}"
                )
        if not local_title or args.force:
            if paper.get("title") != entry["title"]:
                paper["title"] = entry["title"]
                updated += 1

        # Month-precision dates come from the offline fallback: always replace.
        if not paper.get("date") or common.is_month_precision(paper.get("date")) or args.force:
            if paper.get("date") != entry["published"]:
                paper["date"] = entry["published"]
                updated += 1
        if not paper.get("url") or args.force:
            if paper.get("url") != entry["url"]:
                paper["url"] = entry["url"]
                updated += 1
        if not paper.get("venue"):
            year = entry["published"][:4]
            paper["venue"] = f"arXiv {year}"

    report(problems, warnings)

    if args.check:
        return 1 if problems else 0

    common.save_papers(papers, categories)
    print(f"\nWrote {len(papers)} papers to {common.PAPERS_FILE.relative_to(common.ROOT)} "
          f"({updated} field(s) updated).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
