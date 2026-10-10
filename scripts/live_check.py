"""T3: live check through Hermes' real web_extract path, without an LLM.

Run with the Python interpreter of a Hermes installation (isolated mode), e.g. Hermes Desktop on Windows:

    <hermes python> -I scripts/live_check.py URLS_JSON OUTDIR PROFILE [PACE_S]

URLS_JSON  list of {"id", "url", ...}; entries with the same "group" value are sent in one web_extract call.
PROFILE    Hermes profile with the plugin installed, web.extract_backend: extract-chain and
           web.keyless_rescue: false. Its .env provides the keys.
PACE_S     wait after each call, per URL of the call (default 7.5 s: below 8 URLs/min per provider).

Hermes is found under %LOCALAPPDATA%/hermes, i.e. Hermes Desktop on Windows (override with HERMES_ROOT).
Writes OUTDIR/results.jsonl with the tool output as the model sees it (article texts: keep it outside git) and
prints a summary without texts.
"""

import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = os.environ.get("HERMES_ROOT") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes")
KEENABLE_NOTE = "[extract-chain] Copy from Keenable's index"


def hermes_env(profile):
    """Load Hermes for one profile; keys only from the profile's .env, not from the shell."""
    home = os.path.join(ROOT, "profiles", profile)
    os.environ["HERMES_HOME"] = home
    for k in [k for k in os.environ if k.endswith("_API_KEY")]:
        os.environ.pop(k)
    sys.path.insert(0, os.path.join(ROOT, "hermes-agent"))
    sys._hermes_pin_default_home = True
    import hermes_bootstrap  # noqa: F401
    from hermes_cli.env_loader import load_hermes_dotenv

    load_hermes_dotenv(hermes_home=home)


class Collect(logging.Handler):
    """Collects the plugin's L1 lines (with timestamps) of the current call."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        if record.getMessage().startswith("extract-chain "):
            self.lines.append((round(record.created, 1), record.getMessage()))


def calls(cases):
    groups = defaultdict(list)
    for case in cases:
        groups[case.get("group") or case["id"]].append(case)
    return list(groups.values())


def main():
    cases_file, out = sys.argv[1], sys.argv[2]
    profile = sys.argv[3]
    pace = float(sys.argv[4]) if len(sys.argv) > 4 else 7.5
    sys.stdout.reconfigure(encoding="utf-8")
    hermes_env(profile)
    from agent.web_search_registry import get_provider
    from tools.web_tools import _ensure_web_plugins_loaded, _get_extract_backend, web_extract_tool

    _ensure_web_plugins_loaded()
    assert _get_extract_backend() == "extract-chain", f"extract backend is {_get_extract_backend()!r}"
    assert get_provider("extract-chain"), "plugin not loaded (plugins.enabled?)"

    collect = Collect()
    logging.getLogger().addHandler(collect)
    logging.getLogger().setLevel(min(logging.getLogger().level or logging.INFO, logging.INFO))

    os.makedirs(out, exist_ok=True)
    problems, rows = [], []
    with open(os.path.join(out, "results.jsonl"), "a", encoding="utf-8") as fh:
        for group in calls(json.loads(Path(cases_file).read_text(encoding="utf-8"))):
            urls = [c["url"] for c in group]
            collect.lines = []
            start = time.time()
            raw = asyncio.run(web_extract_tool(urls, "markdown"))
            duration = round(time.time() - start, 1)
            try:
                results = json.loads(raw).get("results") or []
            except (ValueError, AttributeError):
                results = []
            row = {"ids": [c["id"] for c in group], "urls": urls, "start": round(start, 1), "duration_s": duration,
                   "log": collect.lines, "raw": raw}  # fmt: skip
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            rows.append(row)

            if duration >= 120:
                problems.append(f"{row['ids']}: {duration} s")
            if [r.get("url") for r in results] != urls:
                problems.append(f"{row['ids']}: order/count {[r.get('url') for r in results]}")
            by_host = {line.split(" ", 2)[1].rstrip(":"): line for _, line in collect.lines}
            for case, res in zip(group, results, strict=False):
                line = by_host.get(urlsplit(case["url"]).hostname or "", "")
                content = res.get("content") or ""
                if ("keenable=ok" in line or "keenable=paywall" in line) and not content.startswith(KEENABLE_NOTE):
                    problems.append(f"{case['id']}: Keenable result without note")
                first = content.split("\n", 1)[0] if content.startswith("[extract-chain]") else ""
                print(f"{case['id']:<16} {duration:>5} s  {line.split(': ', 1)[-1]:<45} "
                      f"len={len(content):>6}  {first[16:70]}{(res.get('error') or '')[:70]}", flush=True)  # fmt: skip
            time.sleep(pace * len(urls))

    # Rate per provider: most L1 lines naming a provider within any 60 s window.
    stamps = defaultdict(list)
    for row in rows:
        for ts, line in row["log"]:
            for provider in ("tinyfish", "firecrawl", "keenable"):
                if f"{provider}=" in line:
                    stamps[provider].append(ts)
    for provider, ts in stamps.items():
        ts.sort()
        peak = max(sum(1 for t in ts if s <= t < s + 60) for s in ts)
        print(f"rate {provider}: {len(ts)} URLs, max {peak} in 60 s")
        if peak > 8:
            problems.append(f"rate {provider}: {peak}/min")
    print("problems:", problems or "none")


if __name__ == "__main__":
    main()
