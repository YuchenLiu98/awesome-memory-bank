#!/usr/bin/env python3
"""Identify author affiliations from an arXiv paper's first page.

arXiv's API does not expose affiliations, so the only reliable source is the
PDF itself. The hard part is not reading the PDF -- it is not reading too much
of it. "We compare against LLaMA" in the body text must not make a paper come
from Meta, and a related-work paragraph must not hand it to every lab it cites.

The extractor therefore looks at two narrow zones of page one only:

  * the author block -- lines between the title and the abstract
  * the footnote zone -- the last few lines of the page, where affiliations
    and correspondence addresses live

Everything in between is ignored. Extracted text is cached under
`.pdf_cache/` so a re-run costs no download.

    python scripts/inst_utils.py 2508.19236        # try a single paper
    python scripts/inst_utils.py --check           # audit papers.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

import common

CACHE_DIR = common.ROOT / ".pdf_cache"
ABSTRACT_RE = re.compile(r"^\s*(abstract|a\s*b\s*s\s*t\s*r\s*a\s*c\s*t)\b", re.I)
STOP_RE = re.compile(r"^\s*(fig(ure)?\.?\s*\d|table\s*\d|\d\s+introduction|introduction\b)", re.I)
AFFIL_HINT = re.compile(
    r"university|universit|institute|laborator|\blab\b|\blabs\b|college|school of|"
    r"academy|research|inc\.|corp|ltd|llc|gmbh|@|\.edu|\.com|\.cn|\.org|department|dept\.",
    re.I,
)

# Canonical name -> regex alternatives. Ordered longest-first at match time so
# that "Microsoft Research Asia" wins over "Microsoft".
INSTITUTIONS: dict[str, list[str]] = {
    # Big tech and AI labs
    "Google DeepMind": [r"google\s+deepmind", r"\bdeepmind\b"],
    "Google": [r"google\s+research", r"google\s+brain", r"\bgoogle\b"],
    "OpenAI": [r"\bopenai\b"],
    "Anthropic": [r"\banthropic\b"],
    "Meta": [r"meta\s+ai", r"\bfair\b", r"facebook\s+ai", r"\bmeta\b(?!\s*-?\s*learning)"],
    "Microsoft": [r"microsoft\s+research\s+asia", r"\bmsra\b", r"microsoft\s+research", r"\bmicrosoft\b"],
    "NVIDIA": [r"\bnvidia\b"],
    "Apple": [r"apple\s+inc", r"\bapple\b"],
    "Amazon": [r"amazon\s+(science|research|web)", r"\baws\b"],
    "IBM Research": [r"ibm\s+research", r"\bibm\b"],
    "Adobe": [r"adobe\s+research", r"\badobe\b"],
    "Samsung": [r"samsung"],
    "Qualcomm": [r"qualcomm"],
    "Intel": [r"intel\s+labs", r"\bintel\b"],
    "Sony": [r"sony\s+(ai|research)"],
    "Salesforce": [r"salesforce"],
    "Snap": [r"snap\s+inc", r"snap\s+research"],
    "Mistral": [r"mistral\s+ai"],
    "Cohere": [r"\bcohere\b"],
    "xAI": [r"\bx\.?ai\b"],
    "Allen Institute for AI": [r"allen\s+institute", r"\bai2\b"],
    # Robotics and autonomous driving
    "Physical Intelligence": [r"physical\s+intelligence"],
    "Boston Dynamics": [r"boston\s+dynamics"],
    "Toyota Research Institute": [r"toyota\s+research", r"\btri\b"],
    "Figure AI": [r"figure\s+ai"],
    "Agility Robotics": [r"agility\s+robotics"],
    "Waymo": [r"\bwaymo\b"],
    "Wayve": [r"\bwayve\b"],
    "Mobileye": [r"mobileye"],
    "Bosch": [r"\bbosch\b"],
    "Unitree": [r"unitree"],
    "AgiBot": [r"agibot", r"zhiyuan\s+robotics"],
    "Galbot": [r"galbot"],
    "UBTech": [r"ubtech"],
    # Chinese tech
    "Alibaba": [r"alibaba", r"\bqwen\s+team", r"tongyi", r"damo\s+academy", r"ant\s+group"],
    "ByteDance": [r"bytedance", r"\bseed\s+team\b", r"tiktok"],
    "Tencent": [r"tencent", r"wechat\s+ai"],
    "Baidu": [r"baidu"],
    "Huawei": [r"huawei", r"noah'?s?\s+ark"],
    "Xiaomi": [r"xiaomi"],
    "SenseTime": [r"sensetime"],
    "Megvii": [r"megvii"],
    "Horizon Robotics": [r"horizon\s+robotics"],
    "Kuaishou": [r"kuaishou", r"kwai"],
    "Zhipu AI": [r"zhipu", r"\bz\.ai\b"],
    "Moonshot AI": [r"moonshot\s+ai"],
    "MiniMax": [r"minimax"],
    "StepFun": [r"stepfun", r"step\s+star"],
    "DeepSeek": [r"deepseek"],
    "01.AI": [r"01\.ai", r"zero\s+one"],
    "Meituan": [r"meituan"],
    "JD": [r"jd\.com", r"jd\s+explore"],
    "Li Auto": [r"li\s+auto"],
    "NIO": [r"\bnio\b"],
    "XPeng": [r"xpeng"],
    # US universities
    "Stanford": [r"stanford"],
    "MIT": [r"massachusetts\s+institute", r"\bmit\b", r"\bcsail\b"],
    "UC Berkeley": [r"uc\s+berkeley", r"university\s+of\s+california,?\s+berkeley", r"\bberkeley\b"],
    "CMU": [r"carnegie\s+mellon", r"\bcmu\b"],
    "Princeton": [r"princeton"],
    "Harvard": [r"harvard"],
    "Yale": [r"\byale\b"],
    "Cornell": [r"cornell"],
    "Columbia": [r"columbia\s+university"],
    "NYU": [r"new\s+york\s+university", r"\bnyu\b"],
    "UC San Diego": [r"uc\s+san\s+diego", r"university\s+of\s+california,?\s+san\s+diego", r"\bucsd\b"],
    "UCLA": [r"\bucla\b", r"university\s+of\s+california,?\s+los\s+angeles"],
    "Georgia Tech": [r"georgia\s+tech", r"georgia\s+institute"],
    "UT Austin": [r"ut\s+austin", r"university\s+of\s+texas\s+at\s+austin"],
    "University of Michigan": [r"university\s+of\s+michigan", r"\bumich\b"],
    "UIUC": [r"\buiuc\b", r"university\s+of\s+illinois"],
    "University of Washington": [r"university\s+of\s+washington"],
    "USC": [r"\busc\b", r"university\s+of\s+southern\s+california"],
    "University of Maryland": [r"university\s+of\s+maryland", r"\bumd\b"],
    "Johns Hopkins": [r"johns\s+hopkins", r"\bjhu\b"],
    "Northeastern": [r"northeastern\s+university"],
    "Ohio State University": [r"ohio\s+state"],
    "Rutgers": [r"rutgers"],
    "Purdue": [r"purdue"],
    "Duke": [r"duke\s+university"],
    "University of Wisconsin-Madison": [r"university\s+of\s+wisconsin"],
    "UNC Chapel Hill": [r"chapel\s+hill", r"\bunc\b"],
    "Arizona State University": [r"arizona\s+state"],
    "Penn": [r"university\s+of\s+pennsylvania", r"\bupenn\b"],
    "UC Santa Barbara": [r"santa\s+barbara", r"\bucsb\b"],
    "Rice University": [r"rice\s+university"],
    # Europe
    "Oxford": [r"university\s+of\s+oxford", r"\boxford\b"],
    "Cambridge": [r"university\s+of\s+cambridge"],
    "ETH Zurich": [r"eth\s+z"],
    "EPFL": [r"\bepfl\b"],
    "Imperial College London": [r"imperial\s+college"],
    "UCL": [r"university\s+college\s+london", r"\bucl\b"],
    "University of Edinburgh": [r"university\s+of\s+edinburgh"],
    "TU Munich": [r"technical\s+university\s+of\s+munich", r"\btum\b"],
    "University of Freiburg": [r"university\s+of\s+freiburg", r"freiburg"],
    "Max Planck Institute": [r"max\s+planck"],
    "Inria": [r"\binria\b"],
    "KAIST": [r"\bkaist\b"],
    "Seoul National University": [r"seoul\s+national"],
    "University of Tokyo": [r"university\s+of\s+tokyo"],
    "Tel Aviv University": [r"tel\s+aviv"],
    "Technion": [r"technion"],
    "Johannes Kepler University Linz": [r"johannes\s+kepler", r"jku\s+linz"],
    "Mila": [r"\bmila\b", r"university\s+of\s+montr"],
    "University of Toronto": [r"university\s+of\s+toronto"],
    "Vector Institute": [r"vector\s+institute"],
    "UBC": [r"university\s+of\s+british\s+columbia"],
    "McGill": [r"mcgill"],
    "ETS Montreal": [r"\b[eé]ts\s+montr", r"technologie\s+sup"],
    "ServiceNow": [r"servicenow"],
    # China
    "Tsinghua": [r"tsinghua"],
    "PKU": [r"peking\s+university", r"\bpku\b"],
    "SJTU": [r"shanghai\s+jiao\s*tong", r"\bsjtu\b"],
    "ZJU": [r"zhejiang\s+university", r"\bzju\b"],
    "Fudan": [r"fudan"],
    "USTC": [r"university\s+of\s+science\s+and\s+technology\s+of\s+china", r"\bustc\b"],
    "HUST": [r"huazhong\s+university", r"\bhust\b"],
    "NJU": [r"nanjing\s+university"],
    "Renmin University": [r"renmin\s+university"],
    "BUAA": [r"beihang", r"\bbuaa\b"],
    "BIT": [r"beijing\s+institute\s+of\s+technology"],
    "BUPT": [r"beijing\s+university\s+of\s+posts"],
    "HIT": [r"harbin\s+institute"],
    "XJTU": [r"xi'?an\s+jiaotong"],
    "SCUT": [r"south\s+china\s+university\s+of\s+technology"],
    "SYSU": [r"sun\s+yat", r"\bsysu\b"],
    "Tongji": [r"tongji\s+university"],
    "Westlake University": [r"westlake"],
    "ShanghaiTech": [r"shanghaitech"],
    "Shanghai AI Lab": [r"shanghai\s+ai\s+lab", r"shanghai\s+artificial\s+intelligence", r"opengvlab"],
    "BAAI": [r"beijing\s+academy\s+of\s+artificial", r"\bbaai\b"],
    "CASIA": [r"casia", r"institute\s+of\s+automation"],
    "CAS": [r"chinese\s+academy\s+of\s+sciences"],
    "Peng Cheng Laboratory": [r"peng\s+cheng"],
    "CUHK": [r"chinese\s+university\s+of\s+hong\s+kong", r"\bcuhk\b"],
    "HKU": [r"university\s+of\s+hong\s+kong", r"\bhku\b"],
    "HKUST": [r"hong\s+kong\s+university\s+of\s+science", r"\bhkust\b"],
    "PolyU": [r"hong\s+kong\s+polytechnic", r"\bpolyu\b"],
    "CityU": [r"city\s+university\s+of\s+hong\s+kong"],
    "NTU": [r"nanyang\s+technological", r"\bntu\b"],
    "NUS": [r"national\s+university\s+of\s+singapore", r"\bnus\b"],
    "A*STAR": [r"a\*star"],
    "MBZUAI": [r"mbzuai", r"mohamed\s+bin\s+zayed"],
    "KAUST": [r"kaust"],
    "IIT": [r"indian\s+institute\s+of\s+technology"],
    "University of Melbourne": [r"university\s+of\s+melbourne"],
    "University of Sydney": [r"university\s+of\s+sydney"],
    "University of Adelaide": [r"university\s+of\s+adelaide"],
}

# Model and product brands whose parent organisation is unambiguous. Applied
# only to the author block, never to the body -- citing Qwen is not the same as
# working at Alibaba, and only the author zone distinguishes the two.
MODEL_TO_ORG: dict[str, str] = {
    r"\bllama\b": "Meta",
    r"\bgemini\b|\bgemma\b|\bpalm\b": "Google DeepMind",
    r"\bgpt-[0-9]|\bdall-?e\b|\bsora\b|\bwhisper\b": "OpenAI",
    r"\bcosmos\b|\bnemotron\b|\bnemo\b": "NVIDIA",
    r"\bclaude\b": "Anthropic",
    r"\bmixtral\b": "Mistral",
    r"\bgrok\b": "xAI",
    r"\bqwen\b|\btongyi\b": "Alibaba",
    r"\bernie\b|\bpaddlepaddle\b": "Baidu",
    r"\bhunyuan\b": "Tencent",
    r"\bpangu\b": "Huawei",
    r"\bchatglm\b|\bglm-[0-9]": "Zhipu AI",
    r"\binternlm\b|\binternvl\b": "Shanghai AI Lab",
    r"\bkimi\b": "Moonshot AI",
    r"\bkling\b": "Kuaishou",
    r"\bsensenova\b": "SenseTime",
}

_COMPILED = {
    name: [re.compile(p, re.I) for p in patterns] for name, patterns in INSTITUTIONS.items()
}
_COMPILED_MODELS = {re.compile(p, re.I): org for p, org in MODEL_TO_ORG.items()}


# --------------------------------------------------------------------------
# pdf text
# --------------------------------------------------------------------------
def _pdf_to_text(data: bytes) -> str:
    """Extract page-one text, preferring pdfminer and falling back to pypdf."""
    import io

    try:
        from pdfminer.high_level import extract_text

        return extract_text(io.BytesIO(data), maxpages=1) or ""
    except ImportError:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return reader.pages[0].extract_text() or ""
    except ImportError as exc:
        raise RuntimeError(
            "no PDF backend available; pip install pdfminer.six (or pypdf)"
        ) from exc


def first_page_text(arxiv_id: str, verbose: bool = False) -> str:
    """Page-one text for an arXiv id, cached on disk."""
    CACHE_DIR.mkdir(exist_ok=True)
    cached = CACHE_DIR / f"{arxiv_id}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="replace")

    url = f"https://arxiv.org/pdf/{arxiv_id}"
    if verbose:
        print(f"    downloading {url}", flush=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "awesome-memory-bank/1.0 (contact via GitHub issues)"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    text = _pdf_to_text(data)
    cached.write_text(text, encoding="utf-8")
    return text


# --------------------------------------------------------------------------
# zone selection
# --------------------------------------------------------------------------
FUNCTION_WORDS = frozenset(
    "a an the of and or with that this we our is are was on in for to from by as "
    "which their its can be have has not but often when where while these those".split()
)


def _is_prose(line: str) -> bool:
    if len(line) <= 55:
        return False
    # "Institute of Automation, CAS / University of Chinese Academy of Sciences"
    # is three "of"s long and still an affiliation, so an affiliation keyword
    # overrides the word-count test.
    if AFFIL_HINT.search(line):
        return False
    words = re.findall(r"[a-z']+", line.lower())
    return sum(1 for w in words if w in FUNCTION_WORDS) >= 3


def author_zone(text: str, max_lines: int = 16) -> str:
    """The lines between the title and the abstract.

    Stops at the abstract, at a figure or section heading, at the first line of
    body prose, or after max_lines -- whichever comes first. This is the only
    zone where a bare organisation name can be trusted to mean "the authors
    work here".
    """
    lines = [ln.strip() for ln in text.splitlines()]
    # pdfminer renders arXiv's vertical margin stamp as dozens of one-character
    # lines. Left in place they consume the whole zone before the authors start.
    lines = [ln for ln in lines if len(ln) > 2]
    if not lines:
        return ""

    # The title is the first substantial line; anything above it is furniture.
    start = next((i for i, ln in enumerate(lines) if len(ln) >= 18), 0)

    zone: list[str] = []
    for line in lines[start + 1 : start + 1 + max_lines + 6]:
        if ABSTRACT_RE.match(line) or STOP_RE.match(line):
            break
        # Many papers start the abstract without the word "Abstract", so the
        # zone has to end on shape alone. Author and affiliation lines are
        # short lists of proper nouns; prose is long and full of function
        # words. Getting this boundary right is what stops "we evaluate on
        # Qwen" from being read as an affiliation.
        if _is_prose(line):
            break
        zone.append(line)
        if len(zone) >= max_lines:
            break
    return "\n".join(zone)


def footnote_zone(text: str, tail_lines: int = 20) -> str:
    """Bottom-of-page lines that actually look like affiliations.

    Correspondence and equal-contribution footnotes carry affiliations, but so
    does a lot of unrelated body text at the foot of a two-column page, hence
    the affiliation-keyword requirement and the length cap.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    keep = []
    for line in lines[-tail_lines:]:
        if len(line) > 200:
            continue
        if AFFIL_HINT.search(line):
            keep.append(line[:160])
    return "\n".join(keep)


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------
# Organisation-shaped phrases, for the long tail no pattern list will ever
# cover. A curated list of 200 names still misses ServiceNow AI Research and
# École de technologie supérieure; these shapes catch them.
GENERIC_ORG = [
    re.compile(r"\bUniversity of [A-Z][\w'-]+(?: [A-Z][\w'-]+)?"),
    re.compile(r"\b(?:[A-Z][\w'-]+ ){1,3}University\b"),
    re.compile(r"\b(?:[A-Z][\w'-]+ ){1,3}Institute(?: of [A-Z][\w'-]+(?: [A-Z][\w'-]+)?)?"),
    re.compile(r"\bInstitute of [A-Z][\w'-]+(?: [A-Z][\w'-]+)?"),
    re.compile(r"\b(?:[A-Z][\w'-]+ ){1,3}(?:AI Research|Research Lab(?:oratory)?|AI Lab)\b"),
    re.compile(r"\b[A-Z][\w'-]+(?: [A-Z][\w'-]+)? (?:Inc|Corp|Ltd|GmbH)\b"),
    re.compile(r"\bÉcole [\w'’ -]+supérieure", re.I),
]
_GENERIC_STOP = re.compile(
    r"^(the|this|we|our|these|abstract|figure|table|equal|corresponding|work|project)\b", re.I
)


def _generic_orgs(zone_text: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for pattern in GENERIC_ORG:
        for hit in pattern.finditer(zone_text):
            name = " ".join(hit.group(0).split())
            if _GENERIC_STOP.match(name) or len(name) < 6:
                continue
            found.setdefault(name, hit.start())
    return found


def _split_markers(text: str) -> str:
    """Detach superscript affiliation markers from the name they precede.

    pdfminer renders them inline, so "1Xiamen University" arrives as one token
    and every pattern anchored on a word boundary silently fails to match it.
    Numbered affiliation lists are the norm, so without this the extractor
    misses roughly a third of all papers.
    """
    return re.sub(r"(?<=\d)(?=[A-Z])", " ", text)


def match_institutions(zone_text: str, generic: bool = True) -> list[str]:
    """Canonical institution names appearing in the given zone, in page order."""
    zone_text = _split_markers(zone_text)
    found: dict[str, int] = {}
    for name, patterns in _COMPILED.items():
        for pattern in patterns:
            hit = pattern.search(zone_text)
            if hit:
                found.setdefault(name, hit.start())
                break
    # Brand names are only evidence of employment on a line that is itself an
    # affiliation. "Qwen" in a sentence means the authors used the model.
    affil_lines = "\n".join(
        ln for ln in zone_text.splitlines() if AFFIL_HINT.search(ln) or re.search(r"\d", ln)
    )
    for pattern, org in _COMPILED_MODELS.items():
        hit = pattern.search(affil_lines)
        if hit:
            found.setdefault(org, hit.start())
    if generic and not found:
        found = _generic_orgs(zone_text)
    return [name for name, _ in sorted(found.items(), key=lambda kv: kv[1])]


def extract(arxiv_id: str, verbose: bool = False) -> list[str]:
    """Best-effort affiliation list for one arXiv id."""
    try:
        text = first_page_text(arxiv_id, verbose=verbose)
    except Exception as exc:  # network, parsing, missing backend
        if verbose:
            print(f"    {arxiv_id}: {exc}", flush=True)
        return []
    names = match_institutions(author_zone(text))
    if not names:
        names = match_institutions(footnote_zone(text))
    return names


def as_field(arxiv_id: str, limit: int = 3, verbose: bool = False) -> str:
    """The `institution` string for papers.yaml, or "" when nothing matched."""
    return ", ".join(extract(arxiv_id, verbose=verbose)[:limit])


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arxiv_id", nargs="?", help="try a single paper")
    parser.add_argument("--check", action="store_true", help="audit papers.yaml")
    parser.add_argument("--limit", type=int, default=0, help="stop after N papers")
    args = parser.parse_args()

    if args.arxiv_id:
        print(args.arxiv_id, "->", as_field(args.arxiv_id, verbose=True) or "(no match)")
        return 0

    if not args.check:
        parser.print_help()
        return 1

    papers = common.load_papers()
    if args.limit:
        papers = papers[: args.limit]
    disagree = 0
    for paper in papers:
        found = extract(paper["arxiv"], verbose=True)
        local = paper.get("institution", "")
        if not found:
            print(f"  [no match] {paper['arxiv']}  local: {local}")
            continue
        overlap = {f.lower() for f in found} & {p.strip().lower() for p in local.split(",")}
        if not overlap:
            disagree += 1
            print(f"  [differs]  {paper['arxiv']}\n    local: {local}\n    pdf  : {', '.join(found)}")
    print(f"\n{disagree} disagreement(s) over {len(papers)} paper(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
