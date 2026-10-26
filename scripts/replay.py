"""T2 (N23): replay the chain on stored single-provider results of the web benchmark (no network, no Hermes).

Maintainer only: the stored results contain page texts and are not published.

    uv run python scripts/replay.py RAWDATA GRADES [--order jina,brightdata,firecrawl,keenable] [--run vorlauf]

RAWDATA  folder with laeufe/<run>/<provider>.jsonl (one JSON line per case: "id", "content", "error", "code", ...);
         Firecrawl from laeufe/d1/firecrawl.jsonl when the run is "vorlauf" (as in the benchmark).
GRADES   CSV with one row per case: "id" and per provider the grade of its single result against the ground truth
         (voll = complete, teil = partial, klar = failure the chain can see, unklar = silent failure).

The stored results are turned into what the plugin's fetchers return (target status, no final URL where the
provider gives none), sent through run_chain, and the returned result is graded with the grade of the provider it
came from. Prints counts (complete, partial, wrong, nothing), the sources, and the fallback and paywall notes per
source stage. Prints no page text.
"""

import argparse
import asyncio
import collections
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract_chain import chain  # noqa: E402
from extract_chain.chain import Stage, run_chain  # noqa: E402
from extract_chain.fetchers import is_pdf, jina_doc  # noqa: E402

NAMES = {
    "brightdata": "Bright Data",
    "jina": "Jina",
    "firecrawl": "Firecrawl",
    "tavily": "Tavily",
    "keenable": "Keenable",
}
NO_FINAL_URL = {"brightdata", "jina", "tavily"}  # N11-N13: these providers report no final URL
_JINA_WARNING = re.compile(r"^Warning: Target URL returned error (\d{3})", re.MULTILINE)
_TARGET = re.compile(r"target_(\d{3})")
NOTES = ("NOTE_LONGEST", "NOTE_LONGEST_COPY", "NOTE_CHECK", "NOTE_WALL", "NOTE_PAYWALL")


def load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    # split at "\n" only: page texts may hold other line separators (U+2028) that splitlines() would cut at
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip())
    return {row["id"]: row for row in rows}


def jina_text_at(text: str) -> int | None:
    """Stored text replies of Jina up to 0.3.2 (sets 1 and 2): where the page text starts after the header block."""
    end = text.find("Markdown Content:", 0, 4000)
    return end + len("Markdown Content:") if end >= 0 else None


def jina_head(text: str) -> str:
    end = text.find("Markdown Content:", 0, 4000)
    return text[:end] if end >= 0 else ""


def as_fetched(provider: str, row: dict | None) -> dict:
    """What the plugin's fetcher would have returned for this stored result."""
    if row is None:
        return {"error": f"{NAMES[provider]}: no stored result", "code": "no_result"}
    if row.get("error"):
        failed = {"error": " ".join(str(row["error"]).split())[:220], "code": row.get("code") or "error"}
        if m := _TARGET.fullmatch(str(row.get("code") or "")):
            failed["target_status"] = int(m.group(1))
        return failed
    if provider == "jina" and "links" in row:  # A7: a stored JSON reply (set 3), read by the fetcher's own code
        data = {k: row.get(k) for k in ("title", "links", "httpStatus")}
        return jina_doc({"data": {**data, "text": row.get("content")}})
    doc = {"title": row.get("title") or "", "content": row.get("content") or ""}
    doc["final_url"] = None if provider in NO_FINAL_URL else row.get("final_url")
    if provider == "brightdata" and is_pdf(doc["content"]):  # A1, D39: as the fetcher
        return {"error": "Bright Data: PDF file, not text", "code": "pdf"}
    if provider == "jina":  # stored text reply up to 0.3.2: a warning in the header block is an error
        warning = _JINA_WARNING.search(jina_head(doc["content"]))
        if warning and int(warning.group(1)) >= 400:
            status = int(warning.group(1))
            return {"error": f"Jina: target HTTP {status}", "code": f"target_{status}", "target_status": status}
        if (text_at := jina_text_at(doc["content"])) is not None:  # E2: lengths without the header lines (D37)
            doc["text_at"] = text_at
    return doc


def replay(order: list[str], data: dict[str, dict[str, dict]], case: str) -> tuple[str, dict]:
    """(source provider or "", result entry) for one case."""
    docs = {p: as_fetched(p, data[p].get(case)) for p in order}
    by_id = {id(doc): p for p, doc in docs.items()}
    picked: dict[str, int] = {}
    original = chain._result

    def record(url, doc, *notes):
        picked["doc"] = id(doc)
        return original(url, doc, *notes)

    def fetch_of(doc):
        async def fetch(deadline):
            return doc

        return fetch

    async def run():
        stages = [Stage(p, NAMES[p], fetch_of(docs[p])) for p in order if p != "keenable"]
        reference = asyncio.get_running_loop().create_future()
        reference.set_result(docs["keenable"])
        return await run_chain(f"https://case.invalid/{case}", stages, reference, budget=1e9)

    chain._result = record
    try:
        result = asyncio.run(run())
    finally:
        chain._result = original
    return by_id.get(picked.get("doc"), ""), result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rawdata")
    ap.add_argument("grades")
    ap.add_argument("--order", default="jina,brightdata,firecrawl,keenable")
    ap.add_argument("--run", default="vorlauf")
    a = ap.parse_args()
    order = [p.strip() for p in a.order.split(",") if p.strip() and p.strip() != "keenable"] + ["keenable"]
    raw = Path(a.rawdata) / "laeufe"
    data = {p: load(raw / a.run / f"{p}.jsonl") for p in order}
    if a.run == "vorlauf" and "firecrawl" in order:
        data["firecrawl"] = load(raw / "d1" / "firecrawl.jsonl")
    with open(a.grades, encoding="utf-8") as fh:
        grades = {row["id"]: row for row in csv.DictReader(fh)}
    cases = [c for c in grades if all(grades[c].get(p) for p in order if p != "firecrawl")]
    counts, notes, sources = collections.Counter(), collections.Counter(), collections.Counter()
    for case in cases:
        source, result = replay(order, data, case)
        grade = grades[case].get(source) if source else ""
        counts[{"voll": "complete", "teil": "partial"}.get(grade, "wrong" if source else "nothing")] += 1
        sources[source or "-"] += 1
        content = result.get("content") or ""
        for name in NOTES:
            if getattr(chain, name).split("{")[0] in content:
                notes[f"{name} ({source or '-'})"] += 1
    print(f"cases {len(cases)}, order {' -> '.join(order)}")
    print("  " + ", ".join(f"{k} {counts[k]}" for k in ("complete", "partial", "wrong", "nothing")))
    print("  source: " + ", ".join(f"{k} {v}" for k, v in sources.most_common()))
    print("  notes: " + (", ".join(f"{k} {v}" for k, v in sorted(notes.items())) or "-"))


if __name__ == "__main__":
    main()
