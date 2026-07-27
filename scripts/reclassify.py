#!/usr/bin/env python3
"""Re-run the keyword classifier over the review queue.

    python scripts/reclassify.py            # show what would change
    python scripts/reclassify.py --write    # apply, and rebuild today's digest

Run this after editing the keyword lists in data/categories.yaml: it re-sorts
the pending candidates without touching arXiv or the curated papers.yaml.
"""

from __future__ import annotations

import argparse
import datetime as dt

import common
import fetch_arxiv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="save the new classification")
    args = parser.parse_args()

    categories = common.load_categories()
    classify = common.build_classifier(categories)
    candidates = common.load_candidates()

    changed = 0
    for item in candidates:
        section, subcategory, score = classify(item.get("title", ""), item.get("abstract", ""))
        section = section or fetch_arxiv.UNSORTED
        subcategory = subcategory or fetch_arxiv.UNSORTED
        if (section, subcategory) != (item.get("section"), item.get("subcategory")):
            print(
                f"  {item.get('section')}/{item.get('subcategory')} -> {section}/{subcategory}"
                f"  :: {item.get('title', '')[:70]}"
            )
            changed += 1
        item["section"], item["subcategory"], item["score"] = section, subcategory, round(score, 1)

    print(f"{changed} of {len(candidates)} candidate(s) reclassified.")
    if not args.write:
        print("Dry run; pass --write to apply.")
        return 0

    common.save_candidates(candidates)

    today = dt.date.today()
    digest_path = common.DAILY_DIR / f"{today.isoformat()}.md"
    if digest_path.exists():
        todays = [c for c in candidates if c.get("found_on") == today.isoformat()]
        digest_path.write_text(
            fetch_arxiv.build_digest(categories, todays, today, 1), encoding="utf-8"
        )
        print(f"Rebuilt {digest_path.relative_to(common.ROOT)} with {len(todays)} entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
