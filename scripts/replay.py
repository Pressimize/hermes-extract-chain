"""T2: replay the chain on stored raw results of the chain test of 2026-10-09 (no network, no Hermes).

    uv run python scripts/replay.py RAW_JSONL PROTOTYPE CLOSING

RAW_JSONL  raw results of the chain test (not published, contains article texts): one JSON line per article with
           "id" and "docs" = {"tinyfish"|"firecrawl"|"keenable": {"url", "title", "content", "error"}}.
PROTOTYPE  "path/to/file.py:function" of the earlier chain prototype, called as function(tinyfish_doc,
           firecrawl_fetch, keenable_fetch) -> (doc, source, calls, reason); used for comparison.
CLOSING    "path/to/file.py:NAME" of a dict {article id: [closing sentence, optional "ALT:" older variant]}
           for the free articles, read without executing the file.

Prints per article the source chosen by the prototype and by the plugin, the plugin's notes and whether a free
article is complete (closing sentence present). Prints no article text. The data set is not published.
"""

import ast
import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract_chain.chain import NOTE_FIRECRAWL, NOTE_KEENABLE, NOTE_WALL, run_chain  # noqa: E402


def tinyfish_doc(d):
    err = d.get("error")
    if not err:
        return {"title": d.get("title") or "", "content": d.get("content") or ""}
    code = err if re.fullmatch(r"[a-z_]+", err) else None
    return {"error": f"TinyFish: {err}"[:210], **({"code": code} if code else {})}


def other_doc(provider, d):
    err = d.get("error")
    if not err:
        return {"title": d.get("title") or "", "content": d.get("content") or ""}
    detail = err.split(" failed: ", 1)[-1]
    try:  # Keenable's JSON body as stored by Hermes' provider
        body = json.loads(detail)
        detail = body.get("message") or body.get("error") or detail
    except ValueError:
        pass
    return {"error": f"{provider}: {detail}"[:210]}


def load_function(spec):
    path, name = spec.rsplit(":", 1)
    module_spec = importlib.util.spec_from_file_location("prototype", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return getattr(module, name)


def load_dict(spec):
    path, name = spec.rsplit(":", 1)
    for node in ast.parse(Path(path).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == name:
            return ast.literal_eval(node.value)
    raise SystemExit(f"{name} not found in {path}")


def norm(s):
    s = (s or "").replace("\\", "").replace("\xad", "").replace("*", "").replace("_", "")
    return re.sub(r"\s+", " ", s).lower()


def complete(content, sentences):
    c = norm(content)
    if norm(sentences[0]) in c:
        return "yes"
    return "old" if len(sentences) > 1 and norm(sentences[1].removeprefix("ALT:")) in c else "no"


def source(out):
    first = out["content"].split("\n", 1)[0]
    for name, note in (("firecrawl", NOTE_FIRECRAWL), ("keenable", NOTE_KEENABLE), ("none", NOTE_WALL)):
        if first.startswith(note.split("(", 1)[0]):
            return name
    return "none" if out["error"] else "tinyfish"


def fixed(doc):
    async def fetch():
        return doc

    return fetch


def main():
    raw, prototype, closing = Path(sys.argv[1]), load_function(sys.argv[2]), load_dict(sys.argv[3])
    totals = {"prototype": 0, "plugin": 0}
    print(f"{'id':<13} {'prototype':<10} {'plugin':<10} {'complete p/p':<13} notes")
    for line in raw.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        tf, fc, ke = (row["docs"][n] for n in ("tinyfish", "firecrawl", "keenable"))
        proto_doc, proto_src, _, _ = prototype(tf, lambda fc=fc: fc, lambda ke=ke: ke)
        out = asyncio.run(
            run_chain(tf["url"], tinyfish_doc(tf), fixed(other_doc("Firecrawl", fc)), fixed(other_doc("Keenable", ke)))
        )
        notes = [ln[16:60] for ln in out["content"].splitlines() if ln.startswith("[extract-chain]")]
        if out["error"]:
            notes.append("error: " + out["error"][:80])
        done = ""
        if row["id"] in closing:
            p, n = complete(proto_doc.get("content"), closing[row["id"]]), complete(out["content"], closing[row["id"]])
            totals["prototype"] += p == "yes"
            totals["plugin"] += n == "yes"
            done = f"{p}/{n}"
        print(f"{row['id']:<13} {proto_src:<10} {source(out):<10} {done:<13} {' | '.join(notes)}")
    print(f"\nfree articles complete ({len(closing)}): prototype {totals['prototype']}, plugin {totals['plugin']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
