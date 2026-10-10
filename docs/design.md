# Design: `extract-chain`, a fallback chain for Hermes' `web_extract`

Requirements carry IDs (`S`, `K`, `E`, `V`, `A`, `Z`, `I`, `L`, `T`, decisions `D`). Tests, reviews and [validation.md](validation.md) refer to them.

## 1. Purpose

Hermes Agent uses exactly one provider for `web_extract` (`web.extract_backend`). When that provider fails for a URL, Hermes does not try a second configured provider. The only built-in fallback is the *keyless rescue*: it runs only when **every** URL of a call fails, and then tries anonymous free tiers (Exa first), without telling the model.

This plugin registers its own extract provider that chains three services per URL:

1. **TinyFish Fetch**: live, free for 1,000 successful URLs/day, returns the main content, reports failures with clear codes.
2. **Firecrawl**: live, gets past most bot protection that stops TinyFish; 1 credit per page.
3. **Keenable**: a copy from Keenable's index; gets past cookie/consent walls; 100,000 requests/month free.

**Why these three, in this order.** The choice comes from tests on 2026-10-09 comparing six providers (TinyFish, Firecrawl, Keenable, Parallel, Exa, Tavily): 15 pages with questions answered by three LLMs, and 23 German news articles with consent walls and paywalls. Full tables and data: [evaluation.md](evaluation.md).

- TinyFish and Firecrawl were the only ones that never returned stale or wrong content.
- Keenable solved the consent walls that defeat both live fetchers.
- The chain reached 13 of 14 free articles, as many as all six providers together.
- Parallel, Exa and Tavily brought no extra coverage (reasons and data: [evaluation.md](evaluation.md)).

## 2. Non-goals

- Paywalls are not bypassed. A detected paywall gets a note, and no further provider is asked (D4).
- Teasers of paywalled articles that carry no marker at all (seen at FAZ, SZ, Welt, Handelsblatt, Tagesspiegel) are not detected (D5).
- No web search. `web.search_backend` is untouched.
- No configuration of its own, no retries, no cache of its own (Hermes caches results). The only state the plugin keeps is the pause after a used-up quota (K7), in memory.

## 3. Environment

- Hermes Agent ≥ 0.21, tested with v0.21.6 (Docker image and Hermes Desktop). Hermes runs Python 3.14; the code supports Python ≥ 3.11, and CI tests 3.11 and 3.14.
- Uses only the standard library and `httpx`, which Hermes ships as a core dependency (`httpx==0.28.1`). No vendor SDKs.

## 4. Interface to Hermes

- **S1** The plugin directory contains `plugin.yaml` and `__init__.py`.
  - `plugin.yaml` declares `name: extract-chain`, `kind: backend`, `requires_hermes: ">=0.21"`, `provides_web_providers: [extract-chain]` and `requires_env` with `TINYFISH_API_KEY`, `FIRECRAWL_API_KEY` and `KEENABLE_API_KEY` (each `secret: true`).
  - `register(ctx)` calls `ctx.register_web_search_provider(...)` once.
- **S2** The provider subclasses `agent.web_search_provider.WebSearchProvider`. Its `name` is `extract-chain`; `supports_search()` returns False and `supports_extract()` True. `is_available()` is true iff `TINYFISH_API_KEY` is set, and checks without network access.
- **S3** Keys are read only via `agent.web_search_provider.get_provider_env(...)`, so per-profile `.env` files work.
  - If reading a key raises (e.g. `UnscopedSecretError`), the key counts as missing.
  - Keys never appear in logs, error texts or notes.
- **S4** `async def extract(urls, **kwargs)`. kwargs such as `format` are ignored; Markdown is always requested.
- **S5** One entry per input URL, in input order, duplicates included (each as an object of its own).
  - Keys: `url` (the input URL), `title`, `content`, `error` (`None` or text), and `metadata` with `sourceURL` (the input URL) and, when known, `finalURL`.
  - `raw_content` is deliberately absent: Hermes uses `raw_content or content`, and the notes are in `content`.
- **S6** Problems with single URLs or providers never raise; they become the entry's `error`. An unexpected exception while handling one URL fails only that URL (`extract-chain: <exception class>`, with a warning in the log); the other URLs of the call keep their results. An entry of `urls` that is not a string gets `extract-chain: not a URL` and reaches no provider (Hermes itself passes strings only).
- **S7** Website policy: Hermes applies its website blocklist inside each provider, not centrally (`tools.website_policy.check_website_access`). The plugin therefore:
  - checks every input URL before any request; a blocked URL gets Hermes' error entry (`error`, `blocked_by_policy`) and is sent to no provider. A block result of an unexpected shape still blocks, with a generic message;
  - checks the final URL reported by TinyFish, Firecrawl or Keenable after the chain; a redirect to a blocked site replaces the result with the blocked entry;
  - blocks a URL whose check raises (e.g. a final URL that cannot be parsed) and logs a warning: a result whose blocklist status is unknown is withheld, as Hermes' own providers do. Errors in the policy file itself are handled inside Hermes, which then allows (D19);
  - fetches nothing if the policy module cannot be imported (an incompatible Hermes version): every URL of every call gets an error that names the cause, and each call logs a warning. The error starts with `Blocked by website policy`; Hermes' keyless rescue leaves such entries alone, so it cannot fetch the URLs without the blocklist either (D15);
  - does not repeat Hermes' SSRF check on final URLs: the pages are fetched by the external services, not from the Hermes host, and Hermes checks every input URL before the provider runs.
- **S8** Interrupts, best effort as in Hermes' built-in providers: the plugin checks `tools.interrupt.is_interrupted()`. If set before the first request, the call returns `Interrupted` for all URLs (policy-blocked URLs keep their block entry). Between stages, the remaining stages are skipped without a request (`<Provider>: interrupted`). A request already in flight is not cancelled; its deadline (A0) still applies. The flag is thread-scoped in Hermes, so a run on another thread may not see it.

## 5. Chain (per URL)

- **K1** Stage 1, TinyFish. All URLs of a call go out as batch requests of at most 10 URLs (TinyFish's limit; Hermes passes at most 5). Stage 2 starts for a URL only when its batch has answered, so one slow URL can hold back the others by up to TinyFish's deadline (A0); Z1 includes that. Without `TINYFISH_API_KEY`, stage 1 fails for all URLs with `TinyFish: no API key`. Hermes offers `web_extract` at all only while some web backend reports itself available; if it does, it calls `extract` even then, because it does not check `is_available()` for an explicitly configured extract backend (see troubleshooting.md, *Missing TinyFish key*).
- **K2** Depending on the class (section 6) of TinyFish's result:
  - `ok`: done, no note.
  - `paywall`: done, with the paywall note (V3).
  - `wall`: go to stage 3. Firecrawl is skipped, because in tests it hit the same wall.
  - `error` with a final code (`page_not_found`, `login_required`, `invalid_url`, `invalid_redirect_url`, `content_too_large`): done; the error passes through unchanged.
  - Any other error (including `no result`, `no API key`, a pause (K7), HTTP and transport errors) or `empty`: go to stage 2.
- **K3** Stage 2, Firecrawl. Without `FIRECRAWL_API_KEY` the stage is skipped with the reason `no API key`.
  - `ok`: done, with the source note (V2).
  - `paywall`: done, with the source and paywall notes.
  - `wall`: go to stage 3; the Firecrawl page is the best result so far.
  - `error` or `empty`: go to stage 3.
- **K4** Stage 3, Keenable. Without `KEENABLE_API_KEY` the stage is skipped with the reason `no API key`.
  - `ok`: done, with the index note (V4).
  - `paywall`: done, with the index and paywall notes.
  - Anything else: if a wall page exists from an earlier stage, it is returned with the wall note (V5) naming all reasons. Otherwise the result is an `error` listing the reasons of all stages, e.g. `TinyFish: bot_blocked; Firecrawl: target HTTP 403; Keenable: Gateway timeout`.
- **K5** Each provider is asked at most once per URL and call. No retries.
- **K6** Stages 2 and 3 run concurrently across the URLs of a call; within one URL the stages run in order. There is no concurrency limit of its own. Firecrawl's free plan allows 2 concurrent scrapes and queues the rest; queue time counts against its 30 s timeout, so an overflowing URL usually times out and moves on to stage 3.
- **K7** Pauses. When a provider's API answers HTTP 402 (quota or credits used up), that stage is skipped without a request for a while, so that a used-up quota does not cost one failing request per URL:

  | Provider | Pause | Reason |
  |---|---|---|
  | TinyFish | until the next 00:05 UTC, at most 24 hours | its daily allowance renews at 00:00 UTC; a longer pause would send every URL to Firecrawl although TinyFish is free again. The five minutes cover clock differences, so that a 402 just after midnight does not cost a whole day |
  | Firecrawl, Keenable | 24 hours | monthly quotas; the stage is asked again once a day |

  - A paused stage counts as failed. Its reason repeats the reply that started the pause and adds the remaining time, e.g. `Firecrawl: API 402: Insufficient credits (paused for another 17 h)`; below one hour it is given in minutes. The chain continues as after any other error (K2–K4).
  - Only an HTTP 402 of the provider's own API starts a pause. A rate limit (429), an error for a single URL and the status of the target page do not.
  - A pause belongs to the pair of provider and key, so profiles with different keys in one process do not pause each other, and a corrected key is used at once. The pause table stores a digest of the key, not the key.
  - Pauses live in memory only. A new process starts without pauses, and a pause that is no longer justified (credits topped up) ends by itself or with a restart.
  - After the pause, the stage is asked again on the next call. Nothing needs to be reset when a quota renews.
  - A pause never has more than 24 hours left. If it has, the system clock was set back; the pause is dropped and the stage is asked again.
  - Several URLs of one call can each receive the 402 before the pause exists; the pause is set and announced once (L2). Calls running on other threads at that moment may announce it again.

## 6. Classification

Checks run in this order; the first match wins. The rules come from the chain-test prototype (2026-10-09) with these changes:

- the wall window (E3) and the paywall area of whole pages (E4);
- a paywall ends the chain (K2, K3, D4); the prototype still asked Keenable afterwards;
- the prototype's rule "drop a shorter Keenable copy" is gone; it only applied to paywalls, which are no longer passed on;
- the kind named in the note without alternative is no longer derived from Keenable's error text; the reasons of all stages are listed instead (V5, K4).

Rules:

- **E1** `error`: the result has an error text.
- **E2** `empty`: fewer than 20 characters remain after removing HTML tags and stripping whitespace. Firecrawl's empty `<body></body>` counts as empty.
- **E3** `wall`: at least 2 different wall markers occur in the check area. The check area is the raw `content` (Markdown or HTML, uncleaned): the whole text below 4,000 characters, otherwise the first 2,000 characters.
  - A real consent wall replaces the content: it stands at the beginning, or the page is short (derStandard via TinyFish: 992 characters, wall text at the end).
  - The prototype also checked the last 2,000 characters. On whole pages (Firecrawl) that caused false alarms from consent texts in the footer (Welt, n-tv).
- **E4** `paywall`: one definite paywall marker, or at least 2 different general paywall markers, occur in the check area.
  - **Check area:** for TinyFish and Keenable, which return the main content, the whole text. For Firecrawl, which returns the whole page, the whole text below 4,000 characters, otherwise the first 75 %.
  - **Whole page:** Firecrawl is asked for the main content only (`onlyMainContent: true`, A2). On the tested news sites its Markdown still carries navigation, teasers of other articles, the footer and subscription boxes, so these rules treat it as a whole page. The false notes on stern.de were seen with exactly this request body.
  - **Why:** whole pages end with footer and subscription dialogs. On stern.de, "Artikel freischalten", "PUR-Abo abschließen" and "STERN PLUS-Inhalte" sit at 81–95 % of the page; Spiegel and Welt are similar. Since TinyFish is always blocked on stern.de, every stern article would otherwise get a false paywall note.
  - Real paywall notices sit right after the teaser (Firecrawl in the chain test: at 13–45 % of the page). For main-content providers the notice is at the very end (Exa on heise+: 96 %), so the cut applies to Firecrawl only (D12).
- **E5** `ok`: otherwise.
- **E6** The marker lists `WALL`, `PAYWALL_DEFINITE` and `PAYWALL` come from the prototype; v0.2.0 dropped one marker that matched a single site only (no change in the replay). Each marker is in one list only; two that the prototype also listed as general markers are definite only, which changes no result. No marker lies completely inside another marker of its list, so `zustimmung` does not count within `Cookie-Zustimmung` (since v0.2.3; no stored test text is classified differently). Markers that only overlap still count as two, e.g. "Alle akzeptieren und weiter" or "mit Werbung und Tracking": that is the wording of consent buttons. Matching is case-insensitive. They target German news sites plus common English consent phrases.

## 7. Notes for the model

- **V1** A note is a line at the start of `content` beginning with `[extract-chain]`. Several notes are one line each, followed by a blank line and the content. Notes are in English (D6). Hermes truncates long content as 75 % head plus 25 % tail, so the start, and with it the notes, always reaches the model.
- **V2** Source Firecrawl: `[extract-chain] Live fetch via Firecrawl (TinyFish: <reason>).`
- **V3** Paywall: `[extract-chain] Paywall indicators found; the text is probably only the free teaser.`
- **V4** Source Keenable: `[extract-chain] Copy from Keenable's index; it may be older than the live page (live fetch: <reasons>).`
- **V5** Wall without alternative: `[extract-chain] Consent wall detected; no alternative source found (<reasons>). The text below is the consent page.`
- **V6** A direct TinyFish success gets no note.
- **V7** Firecrawl PDF cut short (A2): `[extract-chain] PDF cut to the first <n> of <total> pages (Firecrawl page cap).`

## 8. Provider calls (direct REST)

- **A0** Every request has a hard total deadline via `asyncio.timeout(...)`; the httpx timeout alone only bounds single phases. Deadlines: TinyFish 40 s, Firecrawl 40 s, Keenable 25 s.
- **A1** TinyFish:
  - `POST https://api.fetch.tinyfish.ai`, headers `X-API-Key` and `Accept: application/json`; body `{"urls": [...], "format": "markdown", "per_url_timeout_ms": 30000, "ttl": 3600}`; at most 10 URLs per request, more are split and sent concurrently. TinyFish processes the URLs of a request in parallel (its documentation: request latency ≈ the slowest URL), so the deadline (A0) covers a whole batch.
  - `results[]` and `errors[]` are matched to the input by `url`: the exact URL first, otherwise ignoring a trailing `/`. Two input URLs that differ only in the trailing `/` each get the entry that names them exactly; if the reply names only one of them, both get that entry. Where the reply lists a URL twice, the later entry counts (`errors[]` after `results[]`). The final URL is `final_url`, else the `url` of the entry.
  - `errors[].error` is the error code. The error text keeps TinyFish's wording (A4). The code is that text in lowercase if it consists of at most 40 letters, digits and `_`; any other text gives the code `fetch_failed`, because it might quote the URL or the page and only a code may reach the log line (L1). K2 compares this code with the final codes.
  - If a single-URL request gets exactly one entry with a different URL (e.g. after a redirect), that entry counts for the URL.
  - A URL in neither list gets `TinyFish: no result`. An entry of `results[]` or `errors[]` that is no object is skipped, so only its URL is left without a result; a `results` or `errors` that is no list counts as empty. A non-2xx reply, a reply that is no JSON object or an empty one (`TinyFish: malformed reply`) or a transport error fails all URLs of the request: `TinyFish: HTTP <status>` or `TinyFish: <exception class>`.
- **A2** Firecrawl:
  - `POST https://api.firecrawl.dev/v2/scrape` with `Authorization: Bearer <key>`; body `{"url", "formats": ["markdown"], "onlyMainContent": true, "maxAge": 3600000, "timeout": 30000, "parsers": [{"type": "pdf", "maxPages": 30}]}`.
  - Success means `success: true`; the text is `data.markdown` (a missing or empty one counts as an empty page, E2), the title comes from `data.metadata.title`, the final URL from `data.metadata.url`.
  - A target status (`data.metadata.statusCode`) outside 200–299 and not 304 becomes `target HTTP <status>`. Firecrawl otherwise returns such pages without an error field, and still bills them.
  - An API error becomes `API <status>: <error>`.
  - PDFs are capped at 30 pages, because Firecrawl bills one credit per PDF page. If `metadata.totalPages` exceeds `metadata.numPages`, the result gets note V7.
- **A3** Keenable:
  - `GET https://api.keenable.ai/v1/fetch?url=...` with `Authorization: Bearer <key>` and `X-Keenable-Title: hermes-extract-chain`.
  - No `live` parameter: its price is undocumented, and the index copy is what solves consent walls.
  - A 2xx reply that is no JSON object, or an empty one, is `Keenable: malformed reply`. On non-2xx, the error is the JSON field `message` (else `error`), else the response text, else `HTTP <status>`, e.g. `{"error": "Unprocessable entity", "message": "The page is behind a login or paywall"}`.
- **A4** Provider error texts are reduced to one line (runs of whitespace, line breaks included, become one space, so that a note stays one line, V1), cut to 200 characters and prefixed with the provider name. The remaining time of a pause (K7) is added after the cut. A key echoed in them is replaced by `[key]` (S3), as sent or percent-encoded and in any case. Each error also carries a short code for the log (L1), and a failed reply of the provider's API carries its HTTP status, which K7 reads.
- **A5** One `httpx.AsyncClient` per `extract` call (`async with`), closed on cancellation too. It honours `HTTP(S)_PROXY`/`NO_PROXY`. It does not follow redirects, so a key never travels to another host; a redirect from a provider's API counts as an error (`http_3xx`, `api_3xx`). TLS uses Hermes' process-wide OS trust store, which Hermes installs at start-up.

## 9. Time budget

- **Z1** Worst case per URL: 40 + 40 + 25 = 105 s (hard deadlines, A0). That is below Hermes' `web.extract_timeout` (default 120 s), which bounds the whole call. Measured maxima on 2026-10-09: TinyFish 16.9 s, Firecrawl 22.9 s, Keenable 20.7 s.
- **Z2** Because `extract` is async, Hermes' timeout cancels running requests cleanly; no threads keep running.

## 10. Installation and configuration

- **I1** Install the directory `extract_chain/` as the plugin `extract-chain`, either:
  - with `hermes plugins install <owner>/hermes-extract-chain#extract_chain --enable` (sparse clone of the subdirectory), or
  - by copying it to `$HERMES_HOME/plugins/extract-chain/` and adding `extract-chain` to `plugins.enabled`.

  The keys go into the profile's `.env`.
- **I2** Configuration:
  - `web.extract_backend: extract-chain`.
  - `web.keyless_rescue: false`. Otherwise, when all URLs of a call fail, Hermes silently replaces the results with anonymous free tiers, without notes.
  - `web.extract_timeout` not below 110.
- **I3** The plugin directory contains no `pyproject.toml` and no dependencies. It is therefore not a member of Hermes' package manager and needs no environment changes. The manual copy (I1) avoids running the package manager at all, which matters in containers built from the official image.
- **I4** Egress: the host must reach `api.fetch.tinyfish.ai`, `api.firecrawl.dev` and `api.keenable.ai` (HTTPS), directly or through the configured proxy.

## 11. Logging

- **L1** Logger `logging.getLogger(__name__)`. For each URL that reaches the chain, one INFO line: `extract-chain <host>: tinyfish=<outcome> [firecrawl=<outcome>] [keenable=<outcome>]`.
  - The outcome is the class from section 6, or for errors a short code:
    - TinyFish's own code (e.g. `bot_blocked`), or `fetch_failed` when TinyFish sent no code or a text instead of a code (A1);
    - `http_<status>` (API status of TinyFish/Keenable);
    - `api_<status>` (Firecrawl API);
    - `target_<status>` (target page via Firecrawl);
    - `timeout` or an exception class name;
    - `no_key`, `no_result`, `malformed` (a reply that is no JSON object, or an empty one), `paused` (K7), `interrupted`, `exception`.
  - A URL that ends before the chain has no such line: a policy block, the refusal without the policy module, an interrupt before the first request, an entry that is no string, a client that cannot be created. Its reason is the entry's `error`; the refusal, a failing policy check and the client failure also log a warning.
  - Each stage that ran is listed. No content, no keys, no full URL: without a host the line says `<no host>`, for an invalid URL `<invalid url>`.
  - Hermes writes INFO to `logs/agent.log` and WARNING to `logs/errors.log` in the Hermes home. Troubleshooting by log line: [troubleshooting.md](troubleshooting.md).
- **L2** When a pause starts (K7), one WARNING line: `extract-chain: <Provider> paused for <seconds> s (<code>)`, e.g. `extract-chain: Firecrawl paused for 86400 s (api_402)`.

## 12. Tests and acceptance

- **T1** Unit tests (pytest, no network, `httpx.MockTransport`):
  - every rule E1–E5 with boundaries; no marker in two lists (E6);
  - every branch K2–K4 with missing keys (K1, K3, K4);
  - at most one call per provider and URL (K5); concurrency across URLs (K6); pauses with a test clock (K7);
  - order, count and duplicates (S5); ignored kwargs (S4); exceptions become errors (S6);
  - website policy before and after redirects and with the policy module missing (S7); interrupts (S8);
  - mapping of provider replies (A1–A3) including Firecrawl `statusCode`, the PDF cap, batch splitting and transport errors; notes V1–V7;
  - `register(ctx)` and `plugin.yaml` (S1), with the same version as `pyproject.toml`; properties and `is_available` (S2); keys absent from results and logs (S3); log line format and codes (L1).
- **T2** Replay of the chain on the stored raw results of the chain test (23 articles, all three providers per URL; data not published): at least 13 of 14 free articles complete; no paywall note on a free article from TinyFish text; every difference to the prototype explained.
- **T3** Live check through Hermes' real `web_extract` path, without an LLM, in a throwaway profile:
  - **Scope:** the 23 known articles, at least 20 new German news articles from other days and publishers (at least 5 paywalled), and special cases (a Stack Overflow question, a 404 page, a documentation page).
  - **Rate:** at most 8 URLs/min per provider.
  - **Acceptance:**
    - every free article is complete or its failure explained;
    - where the chain deviates from TinyFish, its result is at least as good;
    - every Keenable result carries V4;
    - every call stays under 120 s;
    - multi-URL calls keep order and count;
    - false alarms are counted.
- **T4** A review checks the result against this document.
- **T5** `ruff check` and `ruff format --check` are clean; CI (GitHub Actions: ruff, pytest on Python 3.11 and 3.14) is green.

## 13. Known limitations

See also [troubleshooting.md](troubleshooting.md), section *Edge cases*.

- Paywalls are not bypassed; teasers without markers stay undetected.
- Keenable copies may be older than the live page. The note says so; the age itself is unknown.
- Marker rules are keyword rules tuned on German news sites. An article *about* paywalls or cookie consent can trigger a note.
- Firecrawl free plan: 10 scrapes/min, 2 concurrent, 1,000 credits/month. It bills target 403/404 pages that come back as documents, and one credit per PDF page (capped at 30).
- TinyFish: 1,000 successful URLs/day free, 150 URLs/min.
- A pause (K7) does not notice a top-up. After adding credits, the stage is used again when the pause ends or Hermes is restarted. The pauses rest on the providers' documentation; no real HTTP 402 was available for a test. Should a provider answer 402 for another reason than a used-up quota, the stage is paused all the same: for example for one request that costs more than the credits left (a long PDF) although cheaper requests would still work, or by passing on the status of a target page (neither seen nor documented).
- Hermes caches successful results with their notes for `web.cache_ttl_minutes` (default 20), including a consent page returned with V5.
- Every URL is sent to TinyFish, and possibly to Firecrawl and Keenable (privacy).
- Providers and their order are fixed; see the README FAQ.
- The plugin imports two modules from inside Hermes, `agent.web_search_provider` and `tools.website_policy`. If a Hermes update moves either, `web_extract` fails with a clear error until the plugin is updated: without the first the plugin does not load, without the second it refuses every URL (S7).

## 14. Decisions

| ID | Decision | Reason |
|---|---|---|
| D1 | Firecrawl and Keenable via direct REST, not via Hermes' built-in providers | Hermes' Firecrawl provider needs `firecrawl-py`, an optional extra that Hermes installs on first use. In container deployments that runtime install can disturb the image's package set. Direct calls also make timeouts and parameters controllable and avoid Hermes internals. |
| D2 | TinyFish via direct REST, not via TinyFish's own Hermes plugin | No third-party code dependency. No `tinyfish_agent` tool that spends credits, no interactive key prompt at install time. |
| D3 | `async def extract` | Hermes' timeout cancels cleanly; URLs run concurrently without a thread pool. |
| D4 | Paywall: note only, no further provider | In tests no provider got past a teaser; another call would only cost quota. |
| D5 | Teasers without markers not handled in v1 | No reliable signal in the text; a per-site list would need constant upkeep. |
| D6 | Notes in English | Matches Hermes' own messages and the provider error texts. |
| D7 | Freshness: TinyFish `ttl` 3600 s, Firecrawl `maxAge` 1 h | Defaults accept cached copies of any age (TinyFish) or up to 2 days (Firecrawl). Agents should read versions and dates from the page; for news the current state matters. Same price, slightly more latency. |
| D8 | Wall window: start, whole text if short (E3) | Avoids false alarms from consent texts in footers of whole pages. |
| D9 | Check Firecrawl's target `statusCode` | Firecrawl returns 403/404 pages empty and without an error field. |
| D10 | Constants instead of configuration | As little code as needed; changes come with releases. |
| D11 | MIT license | Same as Hermes Agent. |
| D12 | Paywall check on Firecrawl pages without the last quarter (E4) | The live smoke test showed stern.de getting false paywall notes via Firecrawl. On the stored data of all six providers, this removes the three Firecrawl false alarms (Spiegel, Welt, stern) and keeps every paywall hit of TinyFish, Firecrawl and Keenable. |
| D13 | Enforce Hermes' website policy and interrupts in the plugin (S7, S8); cap Firecrawl PDFs at 30 pages (A2) | Found in the edge-case review (2026-10-10): Hermes leaves the blocklist and interrupt checks to each provider, and an uncapped PDF can cost hundreds of Firecrawl credits in one call. |
| D14 | Pause a stage after HTTP 402 (K7): 24 hours, TinyFish until 00:05 UTC | A used-up quota answers every request with 402 until it renews. TinyFish documents the renewal of its daily allowance at 00:00 UTC; pausing beyond it would spend Firecrawl credits on pages TinyFish fetches for free. |
| D15 | Refuse every URL when Hermes' policy module cannot be imported (S7) | A blocklist that silently stops working is the worse failure; a refusal shows in the first call. Up to v0.2.0 the plugin went on without the blocklist and logged one warning. `is_available()` stays true in that state: otherwise Hermes would stop offering the tool, and the model would see a missing tool instead of the reason. |
| D16 | No concurrency limit of its own (K6) | Proposed in several reviews. A local limit puts waiting time in front of a stage's deadline (A0): with five URLs up to 185 s, beyond Hermes' `web.extract_timeout`, and Hermes then drops every result of the call. Hermes passes at most five URLs, and Firecrawl queues by itself. |
| D17 | One client per call, not one kept across calls (A5) | Hermes runs tool calls on several event loops and, when called from inside a running loop, closes the loop after the call. A client kept across calls would be bound to a closed loop. The saving would be one TLS handshake per provider and call. |
| D18 | No retry (K5) and no cap on the text that is classified (E3, E4) | The next stage is the retry; waiting for `Retry-After` does not fit into Z1. Classifying costs about 13 ms per 100,000 characters (measured), and main-content providers put the paywall notice at the very end, where a cap would lose it. |
| D19 | Block a URL whose policy check raises (S7) | Up to v0.2.2 such a URL was allowed, on the assumption that Hermes does the same. Hermes allows only when the policy file is faulty; its own providers return an error when the check of a final URL raises. A result whose blocklist status is unknown should not reach the model. |
