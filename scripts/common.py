"""Shared helpers for the paper-tracking scripts.

Only depends on PyYAML plus the standard library so the GitHub Action stays
fast and cheap to install.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DAILY_DIR = ROOT / "daily"
CATEGORIES_FILE = DATA_DIR / "categories.yaml"
PAPERS_FILE = DATA_DIR / "papers.yaml"
CANDIDATES_FILE = DATA_DIR / "candidates.yaml"
CACHE_FILE = DATA_DIR / ".arxiv_cache.json"

ARXIV_API = "http://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
# Seconds to wait after arXiv signals throttling, and between successful calls.
THROTTLE_BACKOFF = 180
REQUEST_GAP = 15

# Field order used when writing papers.yaml back to disk.
FIELD_ORDER = [
    "arxiv",
    "title",
    "institution",
    "date",
    "url",
    "code",
    "project",
    "venue",
    "section",
    "subcategory",
    "star",
    "tags",
    "summary",
]

PAPERS_HEADER = """\
# The paper database. This file is the single source of truth for README.md,
# TIMELINE.md and BY_INSTITUTION.md -- never edit those by hand.
#
# Minimal entry (title / date / url are filled in by scripts/sync_metadata.py):
#
#   - arxiv: "2410.24164"
#     institution: "Physical Intelligence"
#     section: vla            # llm | vlm | vla
#     subcategory: robot-arch # must exist in data/categories.yaml
#     summary: "One line on why this paper matters."
#
# Optional: code, project, venue, tags, star (true = highlighted in README).
"""


# --------------------------------------------------------------------------
# config / io
# --------------------------------------------------------------------------
def load_categories() -> dict[str, Any]:
    with CATEGORIES_FILE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_papers() -> list[dict[str, Any]]:
    if not PAPERS_FILE.exists():
        return []
    with PAPERS_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return raw.get("papers") or []


def load_candidates() -> list[dict[str, Any]]:
    if not CANDIDATES_FILE.exists():
        return []
    with CANDIDATES_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return raw.get("candidates") or []


def _dump_entry(paper: dict[str, Any]) -> str:
    ordered = {k: paper[k] for k in FIELD_ORDER if k in paper}
    ordered.update({k: v for k, v in paper.items() if k not in FIELD_ORDER})
    body = yaml.dump(
        ordered,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=100000,
    )
    lines = body.rstrip("\n").split("\n")
    out = ["  - " + lines[0]]
    out.extend("    " + line for line in lines[1:])
    return "\n".join(out)


def save_papers(papers: list[dict[str, Any]], categories: dict[str, Any] | None = None) -> None:
    """Rewrite papers.yaml, grouped by section with banner comments."""
    categories = categories or load_categories()
    order = [s["id"] for s in categories["sections"]]
    titles = {s["id"]: f"{s['numeral']}. {s['title']}" for s in categories["sections"]}

    chunks = [PAPERS_HEADER, "\npapers:\n"]
    for section_id in order:
        group = [p for p in papers if p.get("section") == section_id]
        if not group:
            continue
        group.sort(key=lambda p: (p.get("subcategory", ""), _date_key(p)), reverse=False)
        chunks.append("  # " + "=" * 58 + "\n")
        chunks.append(f"  # {titles[section_id]}\n")
        chunks.append("  # " + "=" * 58 + "\n")
        for paper in group:
            chunks.append(_dump_entry(paper) + "\n\n")

    orphans = [p for p in papers if p.get("section") not in order]
    if orphans:
        chunks.append("  # UNCLASSIFIED -- fix the `section` field\n")
        for paper in orphans:
            chunks.append(_dump_entry(paper) + "\n\n")

    PAPERS_FILE.write_text("".join(chunks).rstrip("\n") + "\n", encoding="utf-8")


def save_candidates(candidates: list[dict[str, Any]]) -> None:
    header = (
        "# Auto-discovered papers waiting for review.\n"
        "# Promote one into data/papers.yaml with:\n"
        "#     python scripts/add_paper.py <arxiv_id>\n"
        "# Everything here is machine-generated; edits are safe to discard.\n\n"
    )
    body = yaml.dump(
        {"candidates": candidates},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=100000,
    )
    CANDIDATES_FILE.write_text(header + body, encoding="utf-8")


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------
MONTH_ONLY = re.compile(r"^\d{4}-\d{2}$")


def is_month_precision(value: Any) -> bool:
    """True for dates stored as YYYY-MM, i.e. inferred rather than confirmed."""
    return isinstance(value, str) and bool(MONTH_ONLY.match(value.strip()))


def date_from_arxiv_id(arxiv_id: Any) -> str | None:
    """Derive a YYYY-MM date from the arXiv id prefix.

    Used as an offline fallback: arXiv ids encode the submission month, which
    is enough to sort the list until the API confirms the exact day.
    """
    match = re.match(r"^(\d{2})(\d{2})\.", str(arxiv_id).strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"20{year:02d}-{month:02d}"


def parse_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                return dt.datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _date_key(paper: dict[str, Any]) -> dt.date:
    return parse_date(paper.get("date")) or dt.date(1970, 1, 1)


def format_date(value: Any) -> str:
    date = parse_date(value)
    if date is None:
        return "—"
    if is_month_precision(value):
        return date.strftime("%b %Y")
    return f"{date.strftime('%b')} {date.day}, {date.year}"


def date_badge(value: Any, today: dt.date | None = None) -> str:
    """A shields.io badge, coloured by how fresh the paper is."""
    date = parse_date(value)
    if date is None:
        return "—"
    today = today or dt.date.today()
    age = (today - date).days
    if age <= 90:
        color = "red"
    elif age <= 730:
        color = "blue"
    else:
        color = "lightgrey"
    text = format_date(value)
    label = text.replace("-", "--").replace(" ", "_")
    return f"![{text}](https://img.shields.io/badge/{urllib.parse.quote(label)}-{color}?style=flat-square)"


# --------------------------------------------------------------------------
# arXiv access
# --------------------------------------------------------------------------
def _http_get(url: str, retries: int = 5, timeout: int = 60) -> str:
    """GET with exponential backoff.

    arXiv throttles hard: a burst earns an HTTP 429 and then several minutes of
    silent timeouts from the same IP, so back off in minutes rather than
    seconds and treat a timeout as continued throttling.
    """
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "awesome-llm-vlm-vla-papers/1.0"}
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            last_error = exc
            wait = THROTTLE_BACKOFF if exc.code == 429 else 30
            print(f"    HTTP {exc.code} from arXiv, waiting {wait}s", flush=True)
            time.sleep(wait)
        except Exception as exc:  # noqa: BLE001 - network flakiness is expected
            last_error = exc
            wait = min(THROTTLE_BACKOFF, 30 * (2**attempt))
            print(f"    {type(exc).__name__} from arXiv, retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"arXiv request failed after {retries} attempts: {last_error}")


def _parse_entries(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    entries = []
    for node in root.findall(f"{ATOM}entry"):
        raw_id = (node.findtext(f"{ATOM}id") or "").strip()
        match = re.search(r"abs/([^v]+)(v\d+)?$", raw_id)
        if not match:
            continue
        published = (node.findtext(f"{ATOM}published") or "")[:10]
        updated = (node.findtext(f"{ATOM}updated") or "")[:10]
        categories = [c.get("term") for c in node.findall(f"{ATOM}category")]
        code = None
        for link in node.findall(f"{ATOM}link"):
            if link.get("title") == "doi":
                code = link.get("href")
        entries.append(
            {
                "arxiv": match.group(1),
                "title": normalize_ws(node.findtext(f"{ATOM}title") or ""),
                "abstract": normalize_ws(node.findtext(f"{ATOM}summary") or ""),
                "authors": [
                    normalize_ws(a.findtext(f"{ATOM}name") or "")
                    for a in node.findall(f"{ATOM}author")
                ],
                "published": published,
                "updated": updated,
                "categories": categories,
                "url": f"https://arxiv.org/abs/{match.group(1)}",
                "doi": code,
            }
        )
    return entries


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _load_cache() -> dict[str, Any]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict[str, Any]) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_by_ids(
    ids: Iterable[str], batch_size: int = 20, use_cache: bool = True
) -> dict[str, dict[str, Any]]:
    """Look up arXiv metadata for a list of ids, caching results on disk."""
    ids = [str(i).strip() for i in ids if str(i).strip()]
    cache = _load_cache() if use_cache else {}
    result = {i: cache[i] for i in ids if i in cache}
    todo = [i for i in ids if i not in result]
    if todo:
        print(f"  {len(result)} cached, fetching {len(todo)} from arXiv ...")
    for start in range(0, len(todo), batch_size):
        batch = todo[start : start + batch_size]
        url = f"{ARXIV_API}?id_list={','.join(batch)}&max_results={len(batch)}"
        for entry in _parse_entries(_http_get(url)):
            result[entry["arxiv"]] = entry
            cache[entry["arxiv"]] = entry
        _save_cache(cache)
        print(f"    {len(result)}/{len(ids)} resolved", flush=True)
        if start + batch_size < len(todo):
            time.sleep(REQUEST_GAP)
    return result


def search(query: str, max_results: int = 200, page_size: int = 100) -> list[dict[str, Any]]:
    """Run an arXiv search query, newest first, with paging."""
    collected: list[dict[str, Any]] = []
    for start in range(0, max_results, page_size):
        params = urllib.parse.urlencode(
            {
                "search_query": query,
                "start": start,
                "max_results": min(page_size, max_results - start),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        entries = _parse_entries(_http_get(f"{ARXIV_API}?{params}"))
        collected.extend(entries)
        if len(entries) < page_size:
            break
        time.sleep(REQUEST_GAP)
    return collected


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------
def build_classifier(categories: dict[str, Any]):
    """Return classify(title, abstract) -> (section_id, subcategory_id, score).

    Section and subcategory are None when nothing matched, so unrelated papers
    end up in an explicit "unsorted" bucket instead of silently landing in
    whichever category happens to be first.
    """
    rules = []
    for section in categories["sections"]:
        for sub in section["subcategories"]:
            weight = float(sub.get("weight", 1.0))
            keywords = [k.lower() for k in sub.get("keywords", [])]
            rules.append((section["id"], sub["id"], weight, keywords))

    def classify(title: str, abstract: str = "") -> tuple[str | None, str | None, float]:
        title_l = title.lower()
        abstract_l = abstract.lower()
        best: tuple[str | None, str | None, float] = (None, None, 0.0)
        for section_id, sub_id, weight, keywords in rules:
            score = 0.0
            for keyword in keywords:
                if keyword in title_l:
                    score += 3.0 * weight
                elif keyword in abstract_l:
                    score += 1.0 * weight
            if score > best[2]:
                best = (section_id, sub_id, score)
        return best

    return classify


def subcategory_index(categories: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    index = {}
    for section in categories["sections"]:
        for sub in section["subcategories"]:
            index[(section["id"], sub["id"])] = sub
    return index
