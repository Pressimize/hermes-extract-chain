# Validation

Results for T1–T4 in [design.md](design.md); T5 (lint, CI) is what CI itself runs. No page texts are stored here; the raw data stays outside the repository. URL lists and per-URL results of v0.1–v0.2: [`data/`](../data). How the providers were chosen: [evaluation.md](evaluation.md).

Sections marked *history* tested the TinyFish chain of v0.1–v0.2. Their rule IDs (K1–K7, V2, V4, V8–V9, A1) are those of design.md at tag `v0.2.6`, not of the current design.

Which check ran against which version. What each version changed: [CHANGELOG.md](../CHANGELOG.md).

- **v0.1.0:** T2 and T3, on 2026-10-09.
- **v0.2.0:** unit tests, replay and a live smoke test (*Edge-case review*).
- **v0.2.1, v0.2.2:** unit tests and replay (output identical to v0.2.0); no new live check. The pause (K7, v0.2.1) was checked with unit tests and a test clock only, because no real 402 was available.
- **v0.2.3:** unit tests and replay (output identical to v0.2.0); the one marker change (E6) alters no classification of the 727 stored texts of the chain test, the live check and the search test. v0.2.0 and v0.2.3 were run side by side on the same simulated provider replies (fetchers, provider, chain), and the tests of v0.2.0 were run against v0.2.3; every difference is an entry of the changelog.
- **v0.2.4:** unit tests, replay (output identical to v0.2.0) and the same side-by-side run of v0.2.3 and v0.2.4.
- **v0.2.5:** unit tests and stored data (section *v0.2.5: stored data*). Unlike the releases before, the classification changes results.
- **v0.2.6:** unit tests; replay identical to v0.2.5 (13 of 14 free articles complete); the new tag rule (N01) changes the class of none of the 626 stored TinyFish pages of the search test, in either mode; a mutation run with mutmut 3.3.1 (137 of 1,327 mutants survived; 95 are now killed by new or tightened tests, the rest are equivalent or outside the spec); and v0.2.5 and v0.2.6 run side by side on 14,092 simulated replies: requests differ only where N01 changes a class, and every difference is an entry of the changelog.
- **v0.3.0:** unit tests; replay on the data of web benchmark v2 (section *v0.3.0*); live check pending.

## T1 – Unit tests

`uv run pytest`: all tests pass without network access, locally (Python 3.14) and in CI (Python 3.11 and 3.14).

## v0.3.0

### T2 – Replay on the web benchmark v2 data

**Data.** Web benchmark v2 (2026-10-17/18, [evaluation.md](evaluation.md#web-benchmark-v2-2026-10-1718)) fetched each page once with each provider and graded every single result against a ground truth: complete, partial, failure the chain can see, or silent failure. The replay uses the 132 pages graded for the chain's providers.

**Method.** `scripts/replay.py` turns each stored result into what the plugin's fetcher returns (target status from the error code or Jina's warning line, no final URL for Bright Data, Jina and Tavily), sends the results through the real `run_chain` with Keenable's stored result as the reference (K3), and grades the returned text with the grade of the provider it came from. No network, no time limit; timings are not part of the replay.

**Result** (acceptance T2: at least 116 complete, at most 6 wrong):

| Order | Complete | Partial | Wrong | No result |
|---|---|---|---|---|
| default: Bright Data → Jina → Firecrawl → Tavily → Keenable | **118** | 9 | 5 | 0 |
| `EXTRACT_CHAIN_ORDER=jina,brightdata,firecrawl,tavily` | 117 | 8 | 7 | 0 |

- **T2 accepted** for the default order.
- **Source of the returned result** (default order): Bright Data 97, Jina 19, Firecrawl 8, Keenable 7, Tavily 1.
- **Notes** (default order): the paywall note (V3) 5 times, all on Bright Data results; the bot-check fallback (V11) once. No result needed the longest-result fallback (V15), the wall fallback (V5) or the page-gone copy (V14).
- **Against the benchmark model** (the rules computed on the same grades, 118 complete and 4 wrong): two cases differ, neither changes the number of complete results. On one page every stage failed; the plugin returns the bot-check page of the first stage with its note (fallback), which the replay counts as wrong and the model counted as no result. On another page the plugin reads the error status in Jina's header block (A7) and takes Firecrawl's result instead of Jina's; both are partial.

### T3 – Live check

Pending: 20 pages from the benchmark through Hermes' real `web_extract` path in a throwaway profile with `web.extract_timeout: 180` (design T3).

## T2 – Replay on the chain-test data (history)

### Data set

The chain test of 2026-10-09 fetched 23 German news articles from 14 publishers once with each of TinyFish, Firecrawl and Keenable. It added Parallel, Exa and Tavily as a cross-check.

- **Articles:** 14 free, 8 paywalled, 1 live blog (not rated).
- **Completeness:** "complete" means the article's closing sentence, determined by hand, appears in the text.
- **Results per provider:** [evaluation.md, Test 2](evaluation.md#test-2--chain-test-consent-walls-and-paywalls). The chain reached 13 of 14 free articles, as many as all six providers together. No provider got past any paywall.

### Replay

`scripts/replay.py` runs `run_chain` on the stored results and compares the outcome with the prototype.

- **Free articles complete:** plugin 13 of 14, prototype 13 of 14.
  - Missing is zeit.de: TinyFish `target_http_error`, Firecrawl empty HTML, Keenable gateway timeout. The plugin returns an error listing all three reasons.
- **Paywall notes on free articles:** none.
- **Differences to the prototype,** all explained by D4 (a paywall ends the chain):
  - `spiegelplus1`, `heiseplus1`: the prototype asked Keenable after TinyFish's teaser and kept the teaser. The plugin returns the teaser at once with the paywall note; the content is the same, one Keenable call less.
  - `metered2`: the prototype asked Keenable after Firecrawl's teaser. The plugin returns Firecrawl's teaser at once, with source and paywall notes.
- **Effect of the rule changes,** measured on all six providers' stored texts:
  - The wall window (E3) removes the false wall alarm on n-tv via Firecrawl.
  - The whole-page paywall area (E4) removes the false paywall alarms on Spiegel, Welt and stern via Firecrawl.
  - No paywall hit of a chain provider is lost. One Exa hit is lost; Exa is not part of the chain.
  - Still wrong: `metered3` via Parallel and Tavily (registration and subscription texts). Neither provider is in the chain.

## T3 – Live check (v0.1.0, history)

### Smoke test

3 URLs in a throwaway Hermes Desktop profile (v0.21.6).

- The plugin loads, and `web.extract_backend: extract-chain` takes effect.
- All three paths work: heise `tinyfish=ok`; stern `tinyfish=bot_blocked`, then Firecrawl; golem `tinyfish=wall keenable=ok`.
- Firecrawl and Keenable accept Bearer auth.
- The notes arrive in the tool result.
- **Finding:** stern got a false paywall note via Firecrawl. This led to rule change E4 (D12).

### Main run

**Setup**

- 2026-10-09, throwaway profile, Hermes' real `web_extract_tool`, no LLM, Hermes cache off.
- 54 URLs:
  - the 23 chain-test articles;
  - 28 new articles from 15 publishers, dated 4–7 October (one BR article first published in 2024 and republished). Of these, 16 free, 9 paywalled (evidence: `isAccessibleForFree: false` in the JSON-LD), 3 unclear (2 Zeit, 1 Welt);
  - 3 special cases: Stack Overflow, a 404 page, Python documentation.
- Two calls with 3 URLs each; all other calls single-URL.

**Automatic checks (`live_check.py`)**, all passed:

- Order and count correct in every call, including the two with 3 URLs.
- Longest call 19.9 s (FAZ via Firecrawl, inside a 3-URL call); median about 3 s.
- Every `keenable=ok` result starts with the index note.
- Rate per provider in any 60 s window: TinyFish at most 7, Keenable 3, Firecrawl 2.

**Paths taken**

| Path | Count | Cases |
|---|---|---|
| TinyFish directly | 32 | |
| TinyFish with paywall note | 4 | SPIEGEL+ (3), heise+ |
| TinyFish error → Firecrawl | 5 | FAZ 3 × `target_http_error`; stern, Stack Overflow `bot_blocked` |
| Consent wall → Keenable | 7 | Golem 5, derStandard 2 |
| TinyFish and Firecrawl error → Keenable | 2 | Zeit (new) 2 × |
| Wall, Keenable fails → wall page with note | 2 | metered news site, plus articles 2 ×; Keenable: *The page is behind a login or paywall* |
| Everything failed | 1 | Zeit (old): TinyFish `target_http_error`, Firecrawl `target HTTP 403`, Keenable *The target server denied access* |
| Final TinyFish error | 1 | 404 page: `page_not_found` |

**Free articles complete: 29 of 30**; TinyFish alone would have had 20.

- **Method:** closing sentence where known (14 old, 9 new articles); otherwise inspection of the end of the text.
- **Old articles:** 13 of 14, as in the chain test; zeit.de refused every access.
- **New articles:** 16 of 16.
  - heise: the closing sentence is present, with code formatting.
  - BR: the text ends with the republication note. The closing sentence collected beforehand is absent; it most likely came from the audio teaser.
  - FAZ (via Firecrawl, 35,758 characters): Hermes truncates to 30,000 characters (head 75 % + tail 25 %). The article ends at about 21,100 characters, inside the untruncated head.

**False alarms:** no paywall or wall note on any free article.

**Paywalled articles** (17, old and new):

- Paywall note on 4: SPIEGEL+ 3, heise+ 1.
- Metered news site, plus articles (2): wall note with Keenable's paywall message; the text contains the teaser and the subscription notice.
- Not recognised (no marker, D5): FAZ 3, SZ 3, Welt 1, Handelsblatt 2, Tagesspiegel 1, Golem+ 1. For Golem+ the Keenable copy is only the teaser.
  - Tagesspiegel shows `showPaywall: true` in the text, but only one general marker (`paywall`) matches.

**Zeit (new, unclear):** TinyFish and Firecrawl get 403. Keenable returns a copy of about 1,700 characters with *Diese Fragen beantwortet der Artikel*, probably a Z+ teaser; the index note is present.

**TinyFish and FAZ:** TinyFish failed on 3 of 5 FAZ pages with `target_http_error`; in the chain test FAZ worked. Possibly `ttl: 3600` (D7) forces more live fetches, which FAZ refuses. Firecrawl covers it at one credit per page. To be watched.

**Usage:** TinyFish 54 URLs (free), Firecrawl 8 credits, Keenable 12 requests.

**T3 accepted.**

### Results per URL

[`data/live-check/results.csv`](../data/live-check/results.csv) has one row per URL: paywall status, the plugin's log line (the live run used v0.1.0, which logged Firecrawl and Keenable errors as `error`; v0.2.0 shows codes, L1), the length of the content as the model sees it, the duration and the assessment. The test profile had `web.extract_char_limit: 30000`; Hermes' default is 15,000.

## T4 – Review against the design (v0.1.0, history)

An independent review checked code, tests and this file against every requirement ID and found no blocker. Fixed:

- **Log line (L1, S6):** an invalid URL made `urlsplit` raise inside `finally`, which would have failed the whole call. Without a host, the full URL including its query appeared in the log. Now `<invalid url>` or `<no host>`.
- **TinyFish matching (A1):** a single-URL reply that names another URL (redirect) still counts for the input URL; before, it cost an unnecessary Firecrawl call.
- **Key protection (S3):** a key echoed in a provider's error text is replaced by `[key]`.
- **T3:** per-URL table and the note on the test profile's character limit.

Left open on purpose: no concurrency limit for Firecrawl (K6, D16).

## Edge-case review (v0.2.0, 2026-10-10, history)

The review covered failure modes and costs: Hermes' extract path, plugin loading and installation, and the providers' documented failure behaviour. Findings, fixed in v0.2.0 (D13, [CHANGELOG.md](../CHANGELOG.md)):

- v0.1.0 bypassed the website blocklist (S7) and kept fetching after the user stopped the turn (S8).
- One long PDF that TinyFish cannot fetch could cost hundreds of Firecrawl credits (A2, V7). Verified live once: an arXiv PDF with `maxPages: 2` returned `numPages: 2`, `totalPages: 15` and `creditsUsed: 2`.
- Rules on non-news pages: the 554 TinyFish texts of an earlier search test (software documentation, forums and Q&A sites, mostly English) produce no wall or paywall classification.
- Remaining by design: [design.md, section 13](design.md#13-known-limitations).

## v0.2.5: stored data (history)

Three checks of v0.2.4 against v0.2.5 on stored data. Texts are never quoted; hosts, ids, lengths, classes and counts only.

### Replay of the chain test

`scripts/replay.py` on the 23 articles of the chain test, once with the v0.2.4 sources and once with v0.2.5.

- Free articles complete: 13 of 14 in both versions. No free article gets a paywall note.
- One line differs: `weltplus1` (paywalled). TinyFish's text has 268 visible characters, so it is `thin` now (E8); before, it was returned as `ok`. Firecrawl is asked and returns 12,863 characters, which carry the source note (V2) and the paywall note (V3).
- Every other line is identical.

### Classes of the 554 TinyFish texts of the search test

Each text classified as a TinyFish document with v0.2.4 and v0.2.5.

| Class | v0.2.4 | v0.2.5 |
|---|---|---|
| ok | 554 | 534 |
| thin | – | 16 |
| challenge | – | 4 |

The 20 texts that changed class (visible length in characters):

- `challenge`: addons.mozilla.org 209, pypi.org 209, www.amazon.com 142, www.techpowerup.com 267.
- `thin`: caddy.community 460, caddy.current-version.com 66, caddyserver.com 489 (twice), community.bitdefender.com 260, dannyda.com 344, docs.docker.com 383, forum.opnsense.org 474, hatchbox.io 291, ollama.com 339, openrouter.ai 298, vaultwarden.discourse.group 284, www.youtube.com 164 (four times).

No text changed in any other way. About half of the 20 are real short pages (a version page, forum and docs pages); in the chain each costs one Firecrawl request, which is 3.6 % of the pages.

### Job-board measurement

Provider outputs for job-board pages (two runs), variants TinyFish markdown and Firecrawl main content. A line with an error is an error document. Class under v0.2.5; `redirect` is the condition of V10:

| Page | TinyFish | Firecrawl |
|---|---|---|
| isaca | challenge (41 characters) | error in run 1; challenge (98 characters) in run 2 |
| stepstone-liste | thin (410) | ok (40,524) |
| euremote-a2 (run 2) | not measured | challenge (189) |
| monster | ok (1,339), redirect true | ok (3,178), redirect true |
| meinestadt | error | ok |
| all other lines | ok | ok |

Under v0.2.4 every line without an error was `ok`. The expectations of the specification are met: isaca is a challenge on both providers (Firecrawl in run 2), the StepStone list via TinyFish is `thin`, euremote-a2 via Firecrawl is a challenge, monster via TinyFish is `ok` with the redirect condition true. No other line has the redirect condition true.
