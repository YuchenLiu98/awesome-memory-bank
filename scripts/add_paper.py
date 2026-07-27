#!/usr/bin/env python3
"""Add a paper to data/papers.yaml by arXiv id.

    python scripts/add_paper.py 2410.24164
    python scripts/add_paper.py 2410.24164 --institution "Physical Intelligence" \\
        --section vla --subcategory robot-arch --star \\
        --summary "Flow-matching action expert on top of a VLM."

Title, date and url come from the arXiv API. If the paper is sitting in
data/candidates.yaml it is removed from that queue. When --section is omitted
the keyword classifier picks one, so always check the printed result.
"""

from __future__ import annotations

import argparse
import re
import sys

import common


def _queued_value(queued: dict | None, field: str) -> str | None:
    """Read a field from the review queue, ignoring the 'unsorted' placeholder."""
    value = (queued or {}).get(field)
    return None if value in (None, "unsorted") else value


def normalize_id(value: str) -> str:
    value = value.strip()
    match = re.search(r"(\d{4}\.\d{4,5})", value)
    return match.group(1) if match else value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("arxiv_id", help="arXiv id or abs/pdf url")
    parser.add_argument("--institution", default=None)
    parser.add_argument("--section", default=None, help="llm | vlm | vla")
    parser.add_argument("--subcategory", default=None)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--code", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--star", action="store_true", help="highlight in the README")
    parser.add_argument("--no-generate", action="store_true", help="skip regenerating the views")
    args = parser.parse_args()

    arxiv_id = normalize_id(args.arxiv_id)
    categories = common.load_categories()
    papers = common.load_papers()

    if any(str(p.get("arxiv")).strip() == arxiv_id for p in papers):
        print(f"{arxiv_id} is already in papers.yaml")
        return 1

    meta = common.fetch_by_ids([arxiv_id])
    entry = meta.get(arxiv_id)
    if entry is None:
        print(f"Could not find {arxiv_id} on arXiv")
        return 1

    candidates = common.load_candidates()
    queued = next((c for c in candidates if str(c.get("arxiv")).strip() == arxiv_id), None)

    section = args.section or _queued_value(queued, "section")
    subcategory = args.subcategory or _queued_value(queued, "subcategory")
    if not section or not subcategory:
        classify = common.build_classifier(categories)
        section, subcategory, score = classify(entry["title"], entry["abstract"])
        if not section:
            print("Could not classify this paper automatically.")
            print("Re-run with --section and --subcategory, for example:")
            print(f"  python scripts/add_paper.py {arxiv_id} --section vla --subcategory robot-arch")
            return 1
        print(f"Auto-classified as {section}/{subcategory} (confidence {score:.1f})")

    valid = common.subcategory_index(categories)
    if (section, subcategory) not in valid:
        print(f"Unknown section/subcategory: {section}/{subcategory}")
        print("Valid combinations:")
        for sec, sub in valid:
            print(f"  {sec}/{sub}")
        return 1

    institution = args.institution
    if not institution:
        # arXiv does not expose affiliations, so read them off the PDF.
        import inst_utils

        institution = inst_utils.as_field(arxiv_id, verbose=True)

    paper = {
        "arxiv": arxiv_id,
        "title": entry["title"],
        "institution": institution or "—",
        "date": entry["published"],
        "url": entry["url"],
        "venue": f"arXiv {entry['published'][:4]}",
        "section": section,
        "subcategory": subcategory,
        "summary": args.summary or "",
    }
    if args.code:
        paper["code"] = args.code
    if args.project:
        paper["project"] = args.project
    if args.star:
        paper["star"] = True

    papers.append(paper)
    common.save_papers(papers, categories)

    if queued is not None:
        common.save_candidates([c for c in candidates if c is not queued])

    print(f"Added {arxiv_id} -> {section}/{subcategory}")
    print(f"  {entry['title']}")
    if not args.institution:
        if institution:
            print(f"  institution from PDF: {institution} — check it")
        else:
            print("  note: institution left as '—', nothing matched on the PDF first page")
    if not args.summary:
        print("  note: no summary yet, add one in data/papers.yaml")

    if not args.no_generate:
        import generate_readme

        generate_readme.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
