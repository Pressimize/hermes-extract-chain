# Validation

Results for T1–T5 in [design.md](design.md). No article texts are stored here; the raw data stays outside the repository. URL lists and per-URL results: [`data/`](../data). How the providers were chosen: [evaluation.md](evaluation.md).

Versions:

- **v0.1.0:** T2 and T3 ran against this version, on 2026-10-09.
- **v0.2.0:** It added the website-policy and interrupt handling (S7, S8), the Firecrawl PDF cap (A2, V7), TinyFish batch splitting and the error codes in the log line (L1). The classification and the chain are unchanged. v0.2.0 was checked with the unit tests, the replay and a live smoke test (section *Edge-case review*).

## T1 – Unit tests

`uv run pytest`: all tests pass without network access, locally (Python 3.14) and in CI (Python 3.11 and 3.14). `ruff check` and `ruff format --check` are clean.

## T2 – Replay on the chain-test data

### Data set

The chain test of 2026-10-09 fetched 23 German news articles from 14 publishers once with each of TinyFish, Firecrawl and Keenable. It added Parallel, Exa and Tavily as a cross-check.

- **Articles:** 14 free, 8 paywalled, 1 live blog (not rated).
- **Completeness:** "complete" means the article's closing sentence, determined by hand, appears in the text.
- **Results across all six providers:**

| Provider | Free articles complete (of 14) | Notes |
|---|---|---|
| TinyFish | 8 | blocked by consent walls, `bot_blocked` on stern.de |
| Firecrawl | 10 | whole pages including navigation and footer |
| Keenable | 10 (+1 outdated) | solves consent walls; index copies can be older |
| Parallel | 8 (+1 outdated) | first 600 characters only on three sites |
| Exa | 10 (+1 outdated) | omits failed URLs silently |
| Tavily | 9 | fails on consent walls |
| **All six together** | **13** | |
| **This chain** | **13** | |

No provider got past any paywall.

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

## T3 – Live check (v0.1.0)

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

- "Path" is the plugin's log line. The live run used v0.1.0, which logged Firecrawl and Keenable errors as `error`; v0.2.0 shows codes (L1).
- "Chars" is the length of the content as the model sees it, notes included. The test profile had `web.extract_char_limit: 30000`; Hermes' default is 15,000.
- "s" is the duration of the `web_extract` call. `(g1)` and `(g2)` are the two 3-URL calls.
- "?" means unclear, "–" not applicable.

| ID | Host | Paywall | Path (L1) | Chars | s | Assessment |
|---|---|---|---|---|---|---|
| golem1 | golem.de | no | `tinyfish=wall keenable=ok` | 3761 | 5.6 | complete (closing sentence) |
| golem-alt | golem.de | no | `tinyfish=wall keenable=ok` | 3818 | 2.7 | complete (closing sentence) |
| golemplus1 | golem.de | yes | `tinyfish=wall keenable=ok` | 647 | 3.3 | teaser (index copy), no paywall note |
| heise1 | heise.de | no | `tinyfish=ok` | 3117 | 2.2 | complete (closing sentence) |
| spiegel1 | spiegel.de | no | `tinyfish=ok` | 3163 | 4.4 | complete (closing sentence) |
| zeit1 | zeit.de | no | `tinyfish=target_http_error firecrawl=error keenable=error` | 0 | 11.6 | error: all three refused access |
| faz1 | faz.net | no | `tinyfish=target_http_error firecrawl=ok` | 28381 | 16.1 | complete (closing sentence) |
| sz1 | sueddeutsche.de | no | `tinyfish=ok` | 2229 | 1.4 | complete (closing sentence) |
| tonline1 | t-online.de | no | `tinyfish=ok` | 5718 | 1.6 | complete (closing sentence) |
| welt1 | welt.de | no | `tinyfish=ok` | 5221 | 4.9 | live blog, not rated (as in the chain test) |
| ntv1 | n-tv.de | no | `tinyfish=ok` | 3206 | 1.2 | complete (closing sentence) |
| stern1 | stern.de | no | `tinyfish=bot_blocked firecrawl=ok` | 19416 | 2.9 | complete (closing sentence) |
| standard1 | derstandard.at | no | `tinyfish=wall keenable=ok` | 2197 | 2.4 | complete (closing sentence) |
| tagesschau1 | tagesschau.de | no | `tinyfish=ok` | 3720 | 2.9 | complete (closing sentence) |
| netzpolitik1 | netzpolitik.org | no | `tinyfish=ok` | 8120 | 2.9 | complete (closing sentence) |
| spiegelplus1 | spiegel.de | yes | `tinyfish=paywall` | 1203 | 2.4 | teaser with paywall note |
| fazplus1 | faz.net | yes | `tinyfish=ok` | 1953 | 12.6 | teaser, no note (D5) |
| weltplus1 | welt.de | yes | `tinyfish=ok` | 268 | 1.7 | teaser, no note (D5) |
| sz-plus1 | sueddeutsche.de | yes | `tinyfish=ok` | 1094 | 2.8 | teaser, no note (D5) |
| heiseplus1 | heise.de | yes | `tinyfish=paywall` | 828 | 2.2 | teaser with paywall note |
| metered1 | metered news site | yes | `tinyfish=wall keenable=error` | 2827 | 14.7 | teaser with wall note and Keenable paywall message |
| metered2 | metered news site | yes | `tinyfish=wall keenable=error` | 2827 | 17.4 | teaser with wall note and Keenable paywall message |
| metered3 | metered news site | no | `tinyfish=ok` | 5573 | 11.9 | complete (closing sentence) |
| n-spiegel1 (g1) | spiegel.de | no | `tinyfish=ok` | 2066 | 19.9 | complete (end of text inspected) |
| n-faz3 (g1) | faz.net | no | `tinyfish=target_http_error firecrawl=ok` | 30341 | 19.9 | complete (end of text inspected); end lies in the untruncated head |
| n-sz3 (g1) | sueddeutsche.de | no | `tinyfish=ok` | 2695 | 19.9 | complete (closing sentence) |
| n-spiegel2 | spiegel.de | yes | `tinyfish=paywall` | 1116 | 2.3 | teaser with paywall note |
| n-spiegel3 | spiegel.de | yes | `tinyfish=paywall` | 1234 | 1.7 | teaser with paywall note |
| n-faz1 | faz.net | yes | `tinyfish=target_http_error firecrawl=ok` | 28251 | 13.0 | teaser, no note (D5) |
| n-faz2 | faz.net | yes | `tinyfish=ok` | 2906 | 14.5 | teaser, no note (D5) |
| n-sz1 | sueddeutsche.de | yes | `tinyfish=ok` | 859 | 2.8 | teaser, no note (D5) |
| n-sz2 | sueddeutsche.de | yes | `tinyfish=ok` | 975 | 17.9 | teaser, no note (D5) |
| n-tsp1 | tagesspiegel.de | yes | `tinyfish=ok` | 714 | 1.7 | teaser, no note (D5) |
| n-hb1 | handelsblatt.com | yes | `tinyfish=ok` | 1204 | 4.7 | teaser, no note (D5) |
| n-hb2 | handelsblatt.com | yes | `tinyfish=ok` | 1506 | 3.3 | teaser, no note (D5) |
| n-hb3 (g2) | handelsblatt.com | no | `tinyfish=ok` | 1354 | 4.5 | complete (closing sentence) |
| n-ntv1 (g2) | n-tv.de | no | `tinyfish=ok` | 2350 | 4.5 | complete (end of text inspected) |
| n-tagesschau1 (g2) | tagesschau.de | no | `tinyfish=ok` | 7209 | 4.5 | complete (end of text inspected) |
| n-zeit1 | zeit.de | ? | `tinyfish=target_http_error firecrawl=error keenable=ok` | 1725 | 9.1 | index copy, probably a Z+ teaser |
| n-zeit2 | zeit.de | ? | `tinyfish=target_http_error firecrawl=error keenable=ok` | 1649 | 9.3 | index copy, probably a Z+ teaser |
| n-ntv2 | n-tv.de | no | `tinyfish=ok` | 5701 | 1.4 | complete (closing sentence) |
| n-zdf1 | zdfheute.de | no | `tinyfish=ok` | 4876 | 2.6 | complete (closing sentence) |
| n-zdf2 | zdfheute.de | no | `tinyfish=ok` | 6375 | 4.1 | complete (closing sentence) |
| n-netz1 | netzpolitik.org | no | `tinyfish=ok` | 9415 | 2.5 | complete (end of text inspected) |
| n-netz2 | netzpolitik.org | no | `tinyfish=ok` | 7905 | 2.8 | complete (end of text inspected) |
| n-std1 | derstandard.at | no | `tinyfish=wall keenable=ok` | 7226 | 2.2 | complete (end of text inspected) |
| n-golem1 | golem.de | no | `tinyfish=wall keenable=ok` | 3640 | 2.6 | complete (end of text inspected) |
| n-golem2 | golem.de | no | `tinyfish=wall keenable=ok` | 3919 | 4.0 | complete (end of text inspected) |
| n-heise1 | heise.de | no | `tinyfish=ok` | 2035 | 2.0 | complete (closing sentence), with code formatting |
| n-br1 | br.de | no | `tinyfish=ok` | 5233 | 2.3 | complete (end of text inspected); collected closing sentence absent (likely from the audio teaser) |
| n-welt1 | welt.de | ? | `tinyfish=ok` | 7069 | 1.6 | complete (end of text inspected) |
| n-so1 | stackoverflow.com | – | `tinyfish=bot_blocked firecrawl=ok` | 30186 | 5.3 | question and answers (whole page, truncated by Hermes) |
| n-notfound1 | tagesschau.de | – | `tinyfish=page_not_found` | 0 | 1.9 | correct: `page_not_found`, no fallback |
| n-docs1 | docs.python.org | – | `tinyfish=ok` | 30382 | 2.6 | complete (truncated by Hermes) |

## T4 – Review against the design

An independent review checked code, tests and this file against every requirement ID and found no blocker. Fixed:

- **Log line (L1, S6):** an invalid URL made `urlsplit` raise inside `finally`, which would have failed the whole call. Without a host, the full URL including its query appeared in the log. Now `<invalid url>` or `<no host>`.
- **TinyFish matching (A1):** a single-URL reply that names another URL (redirect) still counts for the input URL; before, it cost an unnecessary Firecrawl call.
- **Key protection (S3):** a key echoed in a provider's error text is replaced by `[key]`.
- **T3:** per-URL table and the note on the test profile's character limit.

Left open on purpose:

- A non-dict item in TinyFish's `results` fails the whole batch (it then goes to Firecrawl); harmless.
- Duplicates share one `metadata` object; Hermes drops `metadata` anyway.
- No concurrency limit for Firecrawl (K6).

## Edge-case review (v0.2.0, 2026-10-10)

The review covered failure modes and costs: Hermes' extract path, plugin loading and installation, and the providers' documented failure behaviour. Findings and changes:

- **Website blocklist (S7):** Hermes leaves `check_website_access` to each provider; only its built-in Firecrawl provider calls it. v0.1.0 therefore bypassed the blocklist. v0.2.0 checks every input URL before any request and the final URL after redirects.
- **Interrupts (S8):** v0.1.0 kept fetching after the user stopped the turn. v0.2.0 checks `is_interrupted()` before TinyFish and before each further stage.
- **PDF credits (A2, V7):** Firecrawl bills one credit per PDF page, so one long PDF that TinyFish cannot fetch could cost hundreds of credits. v0.2.0 sends `parsers: [{"type": "pdf", "maxPages": 30}]` and adds a note when the PDF was cut.
  - Verified live once: an arXiv PDF with `maxPages: 2` returned `numPages: 2`, `totalPages: 15` and `creditsUsed: 2`.
- **Batches over 10 URLs (A1):** TinyFish rejects more than 10 URLs per request. Hermes' tool passes at most 5, but other callers might pass more; v0.2.0 splits them.
- **Diagnosis (L1):** error codes per stage (`http_402`, `api_402`, `target_403`, …) instead of a bare `error`. Quota and key problems are thus visible in `agent.log`; see [troubleshooting.md](troubleshooting.md).
- **Rules on non-news pages:** the 554 TinyFish texts of an earlier search test (software documentation, forums and Q&A sites, mostly English) produce no wall or paywall classification.
- **Remaining by design:** see [troubleshooting.md](troubleshooting.md), *Edge cases*. Keyword rules can fire on articles *about* paywalls or cookie consent; teasers without markers stay undetected.

## T5 – CI

GitHub Actions (`ci.yml`) runs `ruff check`, `ruff format --check` and `pytest` on Python 3.11 and 3.14 for every push. The first green run was on 2026-10-09.
