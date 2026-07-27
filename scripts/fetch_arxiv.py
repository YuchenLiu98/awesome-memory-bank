#!/usr/bin/env python3
"""Crawl new arXiv papers, classify them, and write a daily digest.

    python scripts/fetch_arxiv.py                # last 2 days
    python scripts/fetch_arxiv.py --days 7       # catch up after a break
    python scripts/fetch_arxiv.py --dry-run      # print, write nothing

Results land in two places:
  * daily/YYYY-MM-DD.md   — a human-readable digest, committed by the Action
  * data/candidates.yaml  — the review queue for scripts/add_paper.py

Nothing is added to data/papers.yaml automatically: the curated list stays
curated, the crawler only proposes.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections import defaultdict
from typing import Any

import common

SNIPPET_CHARS = 200
UNSORTED = "unsorted"


def is_memory_paper(title: str, abstract: str, cfg: dict[str, Any]) -> bool:
    """The topic gate: does this paper study memory, or just use RAM?

    Requires an explicit memory phrase such as "episodic memory" -- the bare
    word "memory" is not enough, because in ML writing it far more often means
    VRAM ("memory-efficient fine-tuning") than anything cognitive. Hardware
    phrasing is masked out before matching so that a paper about reducing the
    memory footprint cannot sneak in on the word alone.
    """
    haystack = f"{title} {abstract}".lower()
    for phrase in cfg.get("hardware_memory_keywords", []):
        haystack = haystack.replace(phrase.lower(), " ")
    return any(phrase.lower() in haystack for phrase in cfg.get("memory_keywords", []))


def matches_gate(entry: dict[str, Any], cfg: dict[str, Any]) -> bool:
    gate = [k.lower() for k in cfg.get("gate_keywords", [])]
    block = [k.lower() for k in cfg.get("block_keywords", [])]
    primary = cfg.get("primary_categories")
    title_l = entry["title"].lower()
    haystack = (entry["title"] + " " + entry["abstract"]).lower()
    if primary and entry.get("categories") and entry["categories"][0] not in primary:
        return False
    if any(word in title_l for word in block):
        return False
    if not is_memory_paper(entry["title"], entry["abstract"], cfg):
        return False
    return any(word in haystack for word in gate)


def snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    text = common.normalize_ws(text)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " …"


def collect(categories: dict[str, Any], days: int, per_query: int) -> list[dict[str, Any]]:
    cfg = categories["arxiv"]
    classify = common.build_classifier(categories)
    cutoff = dt.date.today() - dt.timedelta(days=days)

    known = {str(p.get("arxiv")).strip() for p in common.load_papers()}
    queued = {str(c.get("arxiv")).strip() for c in common.load_candidates()}

    found: dict[str, dict[str, Any]] = {}
    for spec in cfg["queries"]:
        print(f"  querying track '{spec['id']}' ...")
        try:
            entries = common.search(common.normalize_ws(spec["query"]), max_results=per_query)
        except RuntimeError as exc:
            print(f"    skipped: {exc}")
            continue
        kept = 0
        for entry in entries:
            arxiv_id = entry["arxiv"]
            published = common.parse_date(entry["published"])
            if published is None or published < cutoff:
                continue
            if arxiv_id in known or arxiv_id in queued or arxiv_id in found:
                continue
            if not matches_gate(entry, cfg):
                continue
            section, subcategory, score = classify(entry["title"], entry["abstract"])
            found[arxiv_id] = {
                "arxiv": arxiv_id,
                "title": entry["title"],
                "date": entry["published"],
                "url": entry["url"],
                "section": section or UNSORTED,
                "subcategory": subcategory or UNSORTED,
                "score": round(score, 1),
                "arxiv_categories": entry["categories"][:3],
                "abstract": snippet(entry["abstract"], 400),
            }
            kept += 1
        print(f"    {len(entries)} results, {kept} new")
    return sorted(found.values(), key=lambda p: (-p["score"], p["date"]), reverse=False)


def build_digest(
    categories: dict[str, Any], items: list[dict[str, Any]], today: dt.date, days: int
) -> str:
    section_titles = {s["id"]: f"{s['numeral']}. {s['title']}" for s in categories["sections"]}
    sub_titles = {
        (s["id"], sub["id"]): sub["title"]
        for s in categories["sections"]
        for sub in s["subcategories"]
    }
    by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_section[item["section"]].append(item)

    out = [
        f"# arXiv digest · {today.isoformat()}",
        "",
        f"{len(items)} new papers from the last {days} day(s), auto-classified against "
        "[the taxonomy](../data/categories.yaml). "
        "Ranked by keyword confidence, so treat the ordering as a hint, not a verdict.",
        "",
        "Back to the [README](../README.md) · [all digests](README.md)",
        "",
    ]
    if not items:
        out += ["_Nothing matched today._", ""]
        return "\n".join(out)

    ordered = [(s["id"], section_titles[s["id"]]) for s in categories["sections"]]
    ordered.append((UNSORTED, "Unsorted"))

    for section_id, heading in ordered:
        rows = sorted(by_section.get(section_id, []), key=lambda p: -p["score"])
        if not rows:
            continue
        out += [f"## {heading} ({len(rows)})", ""]
        if section_id == UNSORTED:
            out += [
                "_Matched the search queries but no subcategory keywords. "
                "Usually noise; occasionally a genuinely new topic worth a category._",
                "",
            ]
        for item in rows:
            sub = sub_titles.get((item["section"], item["subcategory"]), item["subcategory"])
            out += [
                f"### [{item['title']}]({item['url']})",
                "",
                f"`{sub}` · {item['date']} · `arXiv:{item['arxiv']}` · "
                f"confidence {item['score']}",
                "",
                f"> {item['abstract']}",
                "",
            ]
    return "\n".join(out)


def update_digest_index() -> None:
    files = sorted(
        (p for p in common.DAILY_DIR.glob("*.md") if p.name != "README.md"),
        reverse=True,
    )
    out = [
        "# Daily arXiv Digests",
        "",
        "Auto-generated every morning by "
        "[`scripts/fetch_arxiv.py`](../scripts/fetch_arxiv.py). "
        "Back to the [README](../README.md).",
        "",
        "Each digest lists the previous day's arXiv papers that clear the memory "
        "gate described in [WORKFLOW.md](../WORKFLOW.md) -- papers where memory is "
        "the contribution, not papers that merely mention the word.",
        "",
    ]
    by_month: dict[str, list[str]] = defaultdict(list)
    for path in files:
        by_month[path.stem[:7]].append(path.stem)
    for month in sorted(by_month, reverse=True):
        out += [f"## {month}", ""]
        out += [f"- [{stem}]({stem}.md)" for stem in sorted(by_month[month], reverse=True)]
        out.append("")
    (common.DAILY_DIR / "README.md").write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=2, help="look-back window in days")
    parser.add_argument("--per-query", type=int, default=200, help="max results per track query")
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = parser.parse_args()

    categories = common.load_categories()
    today = dt.date.today()

    print(f"Crawling arXiv for the last {args.days} day(s) ...")
    items = collect(categories, args.days, args.per_query)
    print(f"{len(items)} new candidate(s).")

    if args.dry_run:
        for item in items[:30]:
            print(f"  [{item['score']:5.1f}] {item['section']}/{item['subcategory']}  {item['title']}")
        return 0

    common.DAILY_DIR.mkdir(exist_ok=True)
    digest_path = common.DAILY_DIR / f"{today.isoformat()}.md"
    digest_path.write_text(build_digest(categories, items, today, args.days), encoding="utf-8")
    update_digest_index()

    candidates = common.load_candidates()
    for item in items:
        candidates.append({**item, "found_on": today.isoformat()})
    # Keep the queue bounded: newest 400 entries.
    candidates = sorted(candidates, key=lambda c: c.get("date", ""), reverse=True)[:400]
    common.save_candidates(candidates)

    print(f"Wrote {digest_path.relative_to(common.ROOT)} and "
          f"{len(candidates)} queued candidate(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
