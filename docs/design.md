# Design: `extract-chain`, a fallback chain for Hermes' `web_extract`

Requirements carry IDs (`S`, `K`, `C`, `E`, `V`, `A`, `Z`, `I`, `L`, `T`, decisions `D`). Tests, reviews and [validation.md](validation.md) refer to them. Rules that changed in 0.3.0 also name the item of the 0.3.0 specification (`N1`–`N25`) they implement, in parentheses; the code comments cite those items.

## 1. Purpose

Hermes Agent uses exactly one provider for `web_extract` (`web.extract_backend`). When that provider fails for a URL, Hermes does not try a second configured provider. The only built-in fallback is the *keyless rescue*: it runs only when **every** URL of a call fails, and then tries anonymous free tiers (Exa first), without telling the model.

This plugin registers its own extract provider that chains four services per URL (default order, K1), and a fifth on request:

1. **Jina Reader**: live, works without a key (rate-limited, 20 requests per minute) or with a key.
2. **Bright Data Web Unlocker**: live, gets past most bot protection; 5,000 requests/month free.
3. **Firecrawl**: live, with a browser and proxies; 1 credit per page.
4. **Keenable**: a copy from Keenable's index; gets past cookie/consent walls; 100,000 requests/month free. It is asked for every URL at the start, in parallel, and its copy is also the reference that the other results are checked against (K3, C5).

**Tavily Extract** (a copy from Tavily's service) is not in the default order. It runs, before Keenable, only if `EXTRACT_CHAIN_ORDER` names it (K1, D34).

The aim is as many complete results as possible; saving credits comes second. Escalating once too often costs requests, escalating once too rarely costs a result (D29).

**Why these four, in this order:** web benchmark v2 on 2026-10-17/18 ([evaluation.md](evaluation.md#web-benchmark-v2-2026-10-1718)), a second, harder benchmark set, and the decisions D26–D34. The choice of the v0.1–v0.2 chain (TinyFish → Firecrawl → Keenable) is in the same file.

## 2. Non-goals

- Paywalls are not bypassed. A detected paywall gets a note, and no further provider is asked (D4).
- Teasers of paywalled articles that carry no marker at all (seen at FAZ, SZ, Welt, Handelsblatt, Tagesspiegel) are not detected (D5).
- No web search. `web.search_backend` is untouched.
- No browser of its own. All stages are external services.
- One setting of its own only, the stage order `EXTRACT_CHAIN_ORDER` (K1, D27). No retries, no cache of its own (Hermes caches results). The only state the plugin keeps is the pause after a used-up quota (K7), in memory.

## 3. Environment

- Hermes Agent ≥ 0.21, tested with v0.21.6 (Docker image and Hermes Desktop). Hermes runs Python 3.14; the code supports Python ≥ 3.11, and CI tests 3.11 and 3.14.
- Uses only the standard library and `httpx`, which Hermes ships as a core dependency (`httpx==0.28.1`). No vendor SDKs.

## 4. Interface to Hermes

- **S1** The plugin directory contains `plugin.yaml` and `__init__.py` (N4).
  - `plugin.yaml` declares `name: extract-chain`, `kind: backend`, `requires_hermes: ">=0.21"`, `provides_web_providers: [extract-chain]`, `requires_env` with `BRIGHTDATA_API_KEY`, `BRIGHTDATA_UNLOCKER_ZONE`, `FIRECRAWL_API_KEY`, `KEENABLE_API_KEY`, and `optional_env` with `TAVILY_API_KEY` (used only if the order names Tavily), `JINA_API_KEY` and `EXTRACT_CHAIN_ORDER`. The keys are `secret: true`, the zone and the order are not.
  - In Hermes 0.21.6, `requires_env` is asked for at installation and reported by the configuration check; it does not disable the plugin. Each stage checks its own key (K2).
  - `register(ctx)` calls `ctx.register_web_search_provider(...)` once.
- **S2** The provider subclasses `agent.web_search_provider.WebSearchProvider`. Its `name` is `extract-chain`; `supports_search()` returns False and `supports_extract()` True. `is_available()` is true iff at least one keyed stage of the order (N2) can run: Bright Data (key and zone), Firecrawl, Tavily or Keenable; a stage the order leaves out does not count. Jina alone does not count. It checks without network access (N3).
- **S3** Keys, the zone and the order are read only via `agent.web_search_provider.get_provider_env(...)`, so per-profile `.env` files work.
  - If reading a value raises (e.g. `UnscopedSecretError`), it counts as missing.
  - Keys of 8 or more characters never appear in logs, error texts or notes (A4); a shorter value is not taken for a key.
- **S4** `async def extract(urls, **kwargs)`. kwargs such as `format` are ignored; Markdown is always requested.
- **S5** One entry per input URL, in input order, duplicates included (each as an object of its own).
  - Keys: `url` (the input URL), `title`, `content`, `error` (`None` or text), and `metadata` with `sourceURL` (the input URL) and, when known, `finalURL`.
  - `raw_content` is deliberately absent: Hermes uses `raw_content or content`, and the notes are in `content`.
- **S6** Problems with single URLs or providers never raise; they become the entry's `error`. An unexpected exception inside a stage fails only that stage (`<Provider>: <exception class>`, code `exception`); the Keenable request runs as a task of its own with the same guard (K3). An unexpected exception while handling one URL fails only that URL (`extract-chain: <exception class>`, with a warning in the log); the other URLs of the call keep their results. An entry of `urls` that is not a string gets `extract-chain: not a URL` and reaches no provider (Hermes itself passes strings only).
- **S7** Website policy: Hermes applies its website blocklist inside each provider, not centrally (`tools.website_policy.check_website_access`). The plugin therefore:
  - checks every input URL before any request; a blocked URL gets Hermes' error entry (`error`, `blocked_by_policy`) and is sent to no provider. A block result of an unexpected shape still blocks, with a generic message;
  - checks the final URL of the returned result after the chain, whichever stage it came from; a redirect to a blocked site replaces the result with the blocked entry. Only Firecrawl and Keenable report a final URL; for results of Bright Data, Jina and Tavily only the input URL is checked (section 13);
  - blocks a URL whose check raises (e.g. a final URL that cannot be parsed) and logs a warning: a result whose blocklist status is unknown is withheld, as Hermes' own providers do. Errors in the policy file itself are handled inside Hermes, which then allows (D19);
  - fetches nothing if the policy module cannot be imported (an incompatible Hermes version): every URL of every call gets an error that names the cause, and each call logs a warning. The error starts with `Blocked by website policy`; Hermes' keyless rescue leaves such entries alone, so it cannot fetch the URLs without the blocklist either (D15);
  - does not repeat Hermes' SSRF check on final URLs: the pages are fetched by the external services, not from the Hermes host, and Hermes checks every input URL before the provider runs.
- **S8** Interrupts, best effort as in Hermes' built-in providers: the plugin checks `tools.interrupt.is_interrupted()`. If set before the first request, the call returns `Interrupted` for all URLs (policy-blocked URLs keep their block entry), and no request is sent. When a stage finds the flag set, it sends no request (`<Provider>: interrupted`); the chain then skips the remaining stages, does not wait for Keenable and cancels its request, and returns the fallback (K8) or an error with the reasons so far. A request already in flight when the flag is set is not cancelled; its deadline (A0) still applies. The flag is thread-scoped in Hermes, so a run on another thread may not see it.

## 5. Chain (per URL)

- **K1** Stages and order (N1, N2). Default order `jina,brightdata,firecrawl,keenable` (D34); Tavily is not part of it. The variable `EXTRACT_CHAIN_ORDER` (comma-separated) overrides it:
  - Names are trimmed and lowercased; valid are exactly `brightdata`, `jina`, `firecrawl`, `tavily`, `keenable`. Unknown names and repeats are dropped.
  - Keenable always goes last, wherever it stands and also when it is missing, because it is the reference (K3). A stage left out of the list is not asked; this is how Tavily is switched on (`jina,brightdata,firecrawl,tavily`) and how it stays off by default.
  - If no stage but Keenable remains, the default applies. A list with unknown or repeated names is logged once per process as a WARNING naming the order used.
- **K2** Missing keys (N3). A stage without its key is skipped with `<Provider>: no API key` (code `no_key`). Bright Data also needs `BRIGHTDATA_UNLOCKER_ZONE`; without it the stage is skipped with `Bright Data: no zone` (code `no_key`). Jina runs without a key, with a lower rate limit. Hermes offers `web_extract` at all only while some web backend reports itself available (S2); if it does, it calls `extract` even then, because it does not check `is_available()` for an explicitly configured extract backend.
- **K3** Keenable as reference (N5). Keenable's request starts for every URL at the beginning, in parallel to the first stage, as a task of its own (S6). Its result is the reference for C5 and the last stage (K4); Keenable is asked at most once per URL (K5). The first stage whose result is `ok` or `thin` waits for it, at most until its deadline (A0) and at most for the time left (Z1); if it is not ready then, failed, or is no copy (a class other than `ok` or `thin`, e.g. a consent page), C5 is off for every stage of this URL. Later stages never wait. When the URL ends before Keenable's turn (a result was taken, an interrupt, an exception), the task is cancelled if still running before the client closes (A5).
- **K4** Per stage, in order, the result is classified (section 6). Jina, Bright Data, Firecrawl and Tavily (if in the order) are full pages (E4); Keenable is not (N6):
  - `error`, `empty`, `challenge`, `wall`: next stage. The first consent-wall page and the first bot-check page are kept for the fallback (K8).
  - `paywall`: done, with the source note (V12, V13) if an earlier stage was passed over, and the paywall note (V3) (D4).
  - `ok` or `thin`: the checks C1–C5 run. No check applies: done, with the source note if an earlier stage was passed over. A check applies: the result is kept with the check that applied, and the next stage is asked (D29).
  - Keenable, the last stage: `ok` or `thin` is checked with C1–C4 (C5 does not apply to the reference itself) and taken or kept like any other stage; `paywall` as above. A Keenable wall or bot-check page is never kept; its reason is listed.
  - No error ends the chain except two 404/410 answers (K9).
- **K5** Each provider is asked at most once per URL and call. No retries.
- **K6** URLs of a call run concurrently; within one URL the stages run in order (N10). There is no concurrency limit of its own (D16). Firecrawl's free plan allows 2 concurrent scrapes and queues the rest; queue time counts against its timeout, so an overflowing URL may time out and move on. A rate limit (HTTP 429, e.g. Jina without a key) is an error of that stage and starts no pause.
- **K7** Pauses (N16). When a provider's **API** reports a used-up quota or a blocked account, that stage is skipped without a request for 24 hours, so that a used-up quota does not cost one failing request per URL. The fetcher decides and marks its error with `quota`; the status of a target page never starts a pause.

  | Provider | Starts a pause | No pause |
  |---|---|---|
  | Bright Data | API status 402; Unlocker code `client_10020` (account suspended, negative balance), `client_10100` (zone usage limit), `client_10002` (zone not found or disabled), in the reply headers or in the JSON field `headers` | `client_10110`, `sr_rate_limit` (rate limits); a target page with 402 |
  | Jina | API status 402 (credits used up) | 429 |
  | Firecrawl | API status 402 | 429; a target page with 402 |
  | Tavily | API status 402, 432 (plan limit), 433 (pay-as-you-go limit) | 429 |
  | Keenable | HTTP 402 | 429 |

  - A paused stage counts as failed (code `paused`). Its reason repeats the reply that started the pause and adds the remaining time, e.g. `Firecrawl: API 402: Insufficient credits (paused for another 17 h)`; below one hour it is given in minutes, rounded up, from one hour on as the nearest hour (as in search-chain). The chain continues as after any other error.
  - A pause belongs to the pair of provider and key, so profiles with different keys in one process do not pause each other, and a corrected key is used at once. The pause table stores a digest of the key, not the key.
  - Pauses live in memory only. A new process starts without pauses, and a pause that is no longer justified (credits topped up) ends by itself or with a restart.
  - After the pause, the stage is asked again on the next call. Nothing needs to be reset when a quota renews.
  - A pause never has more than 24 hours left. If it has, the system clock was set back; the pause is dropped and the stage is asked again.
  - Several URLs of one call can each receive the quota reply before the pause exists; the pause is set and announced once (L2). Calls running on other threads at that moment may announce it again.
- **K8** Fallback, when no stage passes the checks (N8), in this order:
  1. the kept result with the longest visible text (E2), the earlier stage on a tie, leaving out results kept for C3; with V15 (D30);
  2. otherwise the longest result kept for C3, with V11;
  3. otherwise the consent-wall page, with V5;
  4. otherwise the bot-check page, with V11;
  5. otherwise an `error` listing the reasons of all stages, e.g. `Jina: API 429: …; Bright Data: target HTTP 403; Firecrawl: target HTTP 403; Keenable: Gateway timeout`.
- **K9** Page gone (N6, D32). When two live stages (Bright Data, Jina, Firecrawl; in any order, not necessarily in a row) report a target status of 404 or 410 **and Firecrawl has not been asked yet**, no further live stage is asked. Keenable's copy, requested at the start, is awaited: if it is `ok`, `thin` or `paywall`, it is returned with V14 (and V3 for a paywall); a consent page, a bot check, an empty page or an error is no copy, and the result is an `error` listing the reasons of all stages asked. Once Firecrawl has been asked (a request went out, not skipped for a key, a pause, an interrupt or lack of time), the chain runs to its end. Tavily reports no target status.

## 6. Classification

Checks run in this order; the first match wins: E1, E2, E7, E3, E4, E8, E5. The rules come from the chain-test prototype (2026-10-09) with these changes:

- the wall window (E3) and the paywall area of whole pages (E4);
- a paywall ends the chain (K4, D4); the prototype still asked Keenable afterwards;
- the prototype's rule "drop a shorter Keenable copy" is gone; it only applied to paywalls, which are no longer passed on;
- the kind named in the note without alternative is no longer derived from Keenable's error text; the reasons of all stages are listed instead (V5, K8).

Rules:

- **E1** `error`: the result has an error text.
- **E2** `empty`: fewer than 20 characters remain after removing HTML tags and stripping whitespace. Firecrawl's empty `<body></body>` counts as empty. A tag is `<`, an optional `/`, a tag name (a letter, then letters, digits or `-`), then whitespace with attributes, `/` or directly `>`; a comment or doctype is `<!…>`. Neither contains a further `<`. So `a < b … c > d`, `i<n; … p->next`, `Map<String, Integer>` and Markdown autolinks such as `<https://example.com/>` are text, not tags. The text left this way is the *visible text*; all lengths below are its length in characters.
- **E7** `challenge`: the visible text is shorter than `CHALLENGE_BELOW` = 1,500 characters and contains at least one marker of the list `CHALLENGE` (bot-check phrases such as "not a robot", "verify you are human", "checking your browser", "captcha", "access denied"; case-insensitive). The length cap keeps real articles that mention these phrases out of the class. Providers return bot checks with status 200, so the text decides (D21). Checked after E2 and before E3.
- **E3** `wall`: at least 2 different wall markers occur in the check area. The check area is the raw `content` (Markdown or HTML, uncleaned): the whole text below 4,000 characters, otherwise the first 2,000 characters.
  - A real consent wall replaces the content: it stands at the beginning, or the page is short (derStandard: 992 characters, wall text at the end).
  - The prototype also checked the last 2,000 characters. On whole pages that caused false alarms from consent texts in the footer (Welt, n-tv).
- **E4** `paywall`: one definite paywall marker, or at least 2 different general paywall markers, occur in the check area.
  - **Check area:** for full pages (Jina, Bright Data, Firecrawl, Tavily; K4) the whole text below 4,000 characters, otherwise the first 75 %. For Keenable, which returns the main content, the whole text.
  - **Why:** whole pages end with footer and subscription dialogs. On stern.de, "Artikel freischalten", "PUR-Abo abschließen" and "STERN PLUS-Inhalte" sit at 81–95 % of the page; Spiegel and Welt are similar. Firecrawl is asked for the main content only (`onlyMainContent: true`, A2), yet its Markdown still carries navigation, teasers of other articles, the footer and subscription boxes.
  - Real paywall notices sit right after the teaser (Firecrawl in the chain test: at 13–45 % of the page). For main-content providers the notice is at the very end (Exa on heise+: 96 %), so the cut does not apply to them (D12).
- **E8** `thin`: not error, empty, challenge, wall or paywall, and the visible text is shorter than `THIN_BELOW` = 500 characters. A short text is no error; it is a reason to ask the next stage (C1, D20).
- **E5** `ok`: otherwise.
- **E6** The marker lists `WALL`, `PAYWALL_DEFINITE` and `PAYWALL` come from the prototype; v0.2.0 dropped one marker that matched a single site only (no change in the replay). Each marker is in one list only; two that the prototype also listed as general markers are definite only, which changes no result. No marker lies completely inside another marker of its list, so `zustimmung` does not count within `Cookie-Zustimmung` (since v0.2.3; no stored test text is classified differently). Markers that only overlap still count as two, e.g. "Alle akzeptieren und weiter" or "mit Werbung und Tracking": that is the wording of consent buttons. Matching is case-insensitive. They target German news sites plus common English consent phrases.

### Checks of results that look fine (C1–C5)

A result classified `ok` or `thin` is checked before it is taken (N7, D29). The first check that applies counts; its name appears in the log (`suspect_<name>`, L1) and in the reasons (V12, V13). Matching is case-insensitive.

- **C1** `thin`: visible text shorter than 500 characters (E8) (N7.1).
- **C2** `print`: a marker of `SUSPECT_PRINT` (`dieser ausdruck wurde am`, `ausdruck erstellt`) in the first 5,000 characters of the visible text: a print view, usually cut short (N7.2).
- **C3** `check`: visible text shorter than 3,000 characters with a marker of `SUSPECT_JS` (`turn on javascript`, `enable javascript`, `javascript (is )?(disabled|required)`, `aktivieren sie javascript`) or `SUSPECT_CHECK` (`just a moment`, `nur einen moment`, `verify you are human`, `captcha`, `access denied`, `pardon our interruption`, `zugriff verweigert`, `sicherheitsüberprüfung`, `security check`, `checking your browser`) (N7.3). A result kept for C3 is the last candidate of the fallback (K8).
- **C4** `consent`: visible text shorter than 1,500 characters with at least 2 occurrences of `cookie|consent|zustimm|einwillig` (occurrences, not different markers) (N7.4).
- **C5** `shorter`: Keenable's reference copy (K3) has no error and its visible text is at least `REFERENCE_FACTOR` = 1.5 times as long. Not for Keenable itself; without a reference the check is off (N7.5).

No title comparison: it made no difference in the benchmark.

## 7. Notes for the model

- **V1** A note is a line at the start of `content` beginning with `[extract-chain]`. Several notes are one line each, followed by a blank line and the content. Notes are in English (D6). Hermes truncates long content as 75 % head plus 25 % tail, so the start, and with it the notes, always reaches the model. Order: source (V12, V13), gone (V14) or fallback (V5, V11, V15); then V3; then V7; then V10.
- **V3** Paywall: `[extract-chain] Paywall indicators found; the text is probably only the free teaser.`
- **V5** Wall without alternative: `[extract-chain] Consent wall detected; no alternative source found (<reasons>). The text below is the consent page.`
- **V6** A result of the first stage in the order gets no source note.
- **V7** Firecrawl PDF cut short (A2): `[extract-chain] PDF cut to the first <n> of <total> pages (Firecrawl page cap).`
- **V10** Redirect: `[extract-chain] The site redirected to <final_url>; the text below is from that page.` The URL is reduced to one line and cut to 200 characters. It is added for the returned page of any stage, after the other notes, when the provider reports a `final_url` that points to another page than the requested URL:
  - the host differs after lowercasing and removing one leading `www.`, or
  - the requested path has at least one non-empty segment and the final path has none or only a locale-like single segment (`^[a-z]{2}(-[a-z]{2})?$`, case-insensitive, e.g. `/de/`, `/en-us/`).
  - No note for differences in scheme, trailing slash, query, fragment or letter case, for the same path, or when `final_url` is missing or not a string. V10 is a note only; it never changes the class or the stage order (D22). Only Firecrawl and Keenable report a final URL.
- **V11** Bot-check page without alternative: `[extract-chain] This looks like a bot-check page; no other source had the page (<reasons>). The text below is what the site returned.` The reasons of all stages, joined with `; ` as in V5. The result is no error.
- **V12** Source, live stage (Bright Data, Jina, Firecrawl), when an earlier stage was passed over (N17): `[extract-chain] Live fetch via <Provider> (<reasons>).`
- **V13** Source, copy (Keenable; Tavily if in the order), when an earlier stage was passed over (N17): `[extract-chain] Copy via <Provider>; it may be older than the live page (<reasons>).`
- **V14** Page gone (K9, N17a): `[extract-chain] The live page returned HTTP <status>; this is an older copy from Keenable's index.`
- **V15** Longest result (K8, N18): `[extract-chain] No source passed the checks; this is the longest result (<Provider>, <n> characters; <reasons>).` n is the visible length of the returned text.
- `<reasons>` lists the stages passed over, joined with `; `: their error text (A4), their class (`Jina: consent wall`, `Bright Data: bot check page`, `Firecrawl: empty page`) or the check that applied (`Bright Data: shorter than the reference copy`, `Jina: very short page (312 characters)`, `Firecrawl: print view`, `Tavily: JavaScript or bot-check hint`, `Bright Data: consent text`).
- Removed in 0.3.0: V2 and V4 (replaced by V12, V13), V8, V8a and V9 (a short page is now check C1, the fallback V15).

## 8. Provider calls (direct REST)

- **A0** Every request has a hard total deadline via `asyncio.timeout(...)`; the httpx timeout alone only bounds single phases. Deadlines: Bright Data 90 s, Jina 35 s, Firecrawl 40 s, Tavily 30 s, Keenable 25 s (in parallel, K3). Each stage gets at most the time left of the URL (Z1). Where a provider takes a timeout of its own, it gets 5 s less, so that it answers before the deadline.
- **A1** Bright Data Web Unlocker (N11):
  - `POST https://api.brightdata.com/request` with `Authorization: Bearer <key>`; body `{"zone", "url", "format": "json", "data_format": "markdown"}`.
  - A reply outside 2xx is an error of the API: `Bright Data: API <status>: <text>` (code `api_<status>`). Bright Data documents 401 (key) and 400 (unknown zone, invalid URL) as outer statuses.
  - Unlocker errors arrive with an outer 200 and the headers `x-brd-error` (text) and `x-brd-error-code`, either as reply headers or, with `format: json`, inside the JSON field `headers`; `body` is then empty. Codes passed on from the proxy network arrive as `x-brd-err-code` (text `x-brd-err-msg`) and are read the same way. They become `Bright Data: <code> <text>` (code `brd_<code>`, taking `x-brd-error-code` before `x-brd-err-code`; `brd_unlocker` when neither is a plain code) and carry no target status. Seen: `proxy_error` for a blocked government site.
  - Otherwise `status_code` is the status of the target page. From 400 on it is `Bright Data: target HTTP <status>` (code `target_<status>`); the page text is dropped, and the status is a target status, not an API status (K7, K9). A 2xx reply that is no JSON object or an empty one is `Bright Data: malformed reply`.
  - The text is `body`. Bright Data follows redirects itself and reports no final URL.
  - Without KYC, Bright Data honours robots.txt and refuses government sites and some other categories; such pages go on to the next stage (D33).
- **A2** Firecrawl:
  - `POST https://api.firecrawl.dev/v2/scrape` with `Authorization: Bearer <key>`; body `{"url", "formats": ["markdown"], "onlyMainContent": true, "maxAge": 3600000, "timeout": <ms>, "parsers": [{"type": "pdf", "maxPages": 30}]}`. `timeout` is the stage's time (A0) minus 5 s.
  - Success means `success: true`; the text is `data.markdown` (a missing or empty one counts as an empty page, E2), the title comes from `data.metadata.title`, the final URL from `data.metadata.url`, else from `data.metadata.sourceURL`.
  - A target status (`data.metadata.statusCode`) outside 200–299 and not 304 becomes `target HTTP <status>`. Firecrawl otherwise returns such pages without an error field, and still bills them (D9).
  - An API error, or a reply without `success: true`, becomes `API <status>: <error>`. A successful reply whose `data` or `data.metadata` is present but no JSON object is `Firecrawl: malformed reply` (code `malformed`); an empty or missing one counts as `{}`.
  - PDFs are capped at 30 pages, because Firecrawl bills one credit per PDF page. If `metadata.totalPages` exceeds `metadata.numPages`, the result gets note V7.
- **A3** Keenable:
  - `GET https://api.keenable.ai/v1/fetch?url=...` with `Authorization: Bearer <key>` and `X-Keenable-Title: hermes-extract-chain`.
  - No `live` parameter: its price is undocumented, and the index copy is what solves consent walls.
  - The final URL is the reply's `url`. A 2xx reply that is no JSON object, or an empty one, is `Keenable: malformed reply`. On non-2xx (code `http_<status>`), the error is the JSON field `message` (else `error`), else the response text, else `HTTP <status>`, e.g. `{"error": "Unprocessable entity", "message": "The page is behind a login or paywall"}`.
- **A4** Provider error texts are reduced to one line (runs of whitespace, line breaks included, become one space, so that a note stays one line, V1), cut to 200 characters and prefixed with the provider name; control and other non-printable characters in the cut text become spaces as well. The remaining time of a pause (K7) is added after the cut. A key of 8 or more characters echoed in them is replaced by `[key]` (S3), as sent or percent-encoded and in any case; a shorter value is not masked, as in search-chain. Error texts of Bright Data and Jina can quote the target page; they reach the reasons cut like any other. Each error also carries a short code for the log (L1).
- **A5** One `httpx.AsyncClient` per `extract` call (`async with`), closed on cancellation too. It honours `HTTP(S)_PROXY`/`NO_PROXY`. It does not follow redirects, so a key never travels to another host; a redirect from a provider's API counts as an error (`http_3xx`, `api_3xx`). TLS uses Hermes' process-wide OS trust store, which Hermes installs at start-up.
- **A6** The requests of Bright Data, Jina and Tavily are those of the benchmark of 2026-10-18, without cache parameters (D7). PDFs are not capped there: those providers bill per request, not per page, and Hermes truncates the content anyway.
- **A7** Jina Reader (N12):
  - `GET https://r.jina.ai/<url>` with `Accept: text/plain`, `X-Return-Format: markdown` and, with a key, `Authorization: Bearer <key>`. The URL is appended as it is, query string included; Jina does not receive a fragment (`#…`).
  - The text is the whole reply, header lines included. Only the header block before `Markdown Content:` (within its first 4,000 characters) is read: `Title:` gives the title, and `Warning: Target URL returned error <status>` with a status from 400 on gives `Jina: target HTTP <status>` (code `target_<status>`). The same lines inside the page text never count. `URL Source:` is the requested URL, not a final URL.
  - An API reply outside 2xx is `Jina: API <status>: <text>` (code `api_<status>`); 429 is its rate limit without a key.
  - Jina caches pages by default (documented as 5 minutes to 1 hour); the plugin does not switch that off.
- **A8** Tavily Extract (N13):
  - `POST https://api.tavily.com/extract` with `Authorization: Bearer <key>`; body `{"urls": [url], "extract_depth": "advanced", "format": "markdown", "timeout": <s>}`. `timeout` is the stage's time minus 5 s; with the stage deadline of 30 s that is at most 25 s (Tavily accepts 1–60 s; 30 s is its default for `advanced`; the slowest Tavily fetch measured took 18 s).
  - The text is `results[0].raw_content`; `results[0].url` is the source URL, not a final URL. An entry in `failed_results` is `Tavily: <Tavily's text>` (code `failed`; Tavily does not document these texts), no entry at all `Tavily: no result`. An API reply outside 2xx is `Tavily: API <status>: <text>`.

## 9. Time budget

- **Z1** Each URL has a budget of `web.extract_timeout` minus 10 s, at most 170 s (N9, D31). The setting is read as Hermes reads it (`tools.web_tools._load_web_config()`); 0 or below means "no limit" in Hermes and gives 170 s; if the setting cannot be read, 110 s (Hermes' default of 120 s minus 10 s). Below 120 s the plugin logs one WARNING per process. Each stage gets at most the time left (monotonic clock from the start of the URL, A0); with less than 10 s left it is skipped (`<Provider>: no time left`, code `no_time`), and the fallback (K8) applies. Keenable runs in parallel and takes no time of its own. URLs of a call run concurrently, so a call takes as long as its slowest URL.
- **Z2** Because `extract` is async, Hermes' timeout cancels running requests cleanly; no threads keep running.

## 10. Installation and configuration

- **I1** Install the directory `extract_chain/` as the plugin `extract-chain`, either:
  - with `hermes plugins install <owner>/hermes-extract-chain#extract_chain --enable` (sparse clone of the subdirectory), or
  - by copying it to `$HERMES_HOME/plugins/extract-chain/` and adding `extract-chain` to `plugins.enabled`.

  The keys, the zone and the optional order go into the profile's `.env`; `TAVILY_API_KEY` is needed only if the order names Tavily.
- **I2** Configuration:
  - `web.extract_backend: extract-chain`.
  - `web.keyless_rescue: false`. Otherwise, when all URLs of a call fail, Hermes silently replaces the results with anonymous free tiers, without notes.
  - `web.extract_timeout: 180`. Hermes discards every result of a call that exceeds it; 180 s leave 10 s above the budget of 170 s (Z1).
- **I3** The plugin directory contains no `pyproject.toml` and no dependencies. It is therefore not a member of Hermes' package manager and needs no environment changes. The manual copy (I1) avoids running the package manager at all, which matters in containers built from the official image.
- **I4** Egress: the host must reach `r.jina.ai`, `api.brightdata.com`, `api.firecrawl.dev` and `api.keenable.ai` (HTTPS), directly or through the configured proxy. `api.tavily.com` is needed only if the order names Tavily.

## 11. Logging

- **L1** Logger `logging.getLogger(__name__)`. For each URL that reaches the chain, one INFO line (N20): `extract-chain <host>: <stage>=<outcome> … keenable=<outcome>`, e.g. `extract-chain www.example.com: jina=suspect_shorter brightdata=ok keenable=ref_ok`.
  - Every stage that was asked or skipped is listed in order; Keenable is always listed, last.
  - The outcome is the class from section 6 (`ok`, `paywall`, `wall`, `empty`, `challenge`; a `thin` result always shows as `suspect_thin`, because C1 applies to it), a check (`suspect_thin`, `suspect_print`, `suspect_check`, `suspect_consent`, `suspect_shorter`), or for errors a short code:
    - `api_<status>` (API of Bright Data, Jina, Firecrawl, Tavily), `http_<status>` (Keenable);
    - `brd_<code>` (Bright Data Unlocker error, A1);
    - `target_<status>` (target page via Bright Data, Jina or Firecrawl);
    - `failed`, `no_result` (Tavily); `malformed` (a reply that is no JSON object, or an empty one);
    - `timeout` or an exception class name; `exception` (unexpected error inside a stage, S6);
    - `no_key`, `no_time`, `paused` (K7), `interrupted`.
  - Keenable's entry when the URL ended before its turn: `ref_<outcome>` (its reference copy had arrived, with its class or code), `pending` (still running; the request is cancelled, K3) or `no_key`. After K9 it is `gone_copy` when its copy is returned.
  - A URL that ends before the chain has no such line: a policy block, the refusal without the policy module, an interrupt before the first request, an entry that is no string, a client that cannot be created. Its reason is the entry's `error`; the refusal, a failing policy check and the client failure also log a warning.
  - No content, no keys, no full URL: without a host the line says `<no host>`, for an invalid URL `<invalid url>`.
  - Hermes writes INFO to `logs/agent.log` and WARNING to `logs/errors.log` in the Hermes home. Troubleshooting by log line: [troubleshooting.md](troubleshooting.md).
- **L2** When a pause starts (K7), one WARNING line: `extract-chain: <Provider> paused for <seconds> s (<code>)`, e.g. `extract-chain: Firecrawl paused for 86400 s (api_402)`.
- **L3** Once per process, a WARNING for an invalid `EXTRACT_CHAIN_ORDER` (K1) and for `web.extract_timeout` below 120 s (Z1).

## 12. Tests and acceptance

- **T1** Unit tests (pytest, `httpx.MockTransport`, no network). Every rule S, K, C, E, V, A and Z has at least one test, boundaries included (500, 1,500, 3,000 and 5,000 characters, factor 1.5 just below and above, 10 s left).
- **T2** Replay on the stored single-provider results of web benchmark v2 (data not published): `scripts/replay.py` sends them through the real chain. Two page sets: set 1 (132 pages) and the harder set 2 (197 pages, 71 of them job pages). Acceptance with the default order: set 1 at least 116 complete, set 2 at least 168 complete, together at most 30 wrong; fallbacks (K8) and paywall notes per stage listed separately. Results: [validation.md](validation.md).
- **T3** Live check through Hermes' real `web_extract` path, without an LLM, in a throwaway profile with `web.extract_timeout: 180`: 20 pages from the benchmark, every call under 180 s, notes plausible, no keys in the log. Results: [validation.md](validation.md).
- **T4** A review checks the result against this document.
- **T5** `ruff check` and `ruff format --check` are clean; CI (GitHub Actions: ruff, pytest on Python 3.11 and 3.14) is green.

## 13. Known limitations

See also [troubleshooting.md](troubleshooting.md), section *Edge cases*.

- Paywalls are not bypassed; teasers without markers stay undetected.
- The checks (E7, E8, C1–C5) are heuristics. A bot check in other words passes; a real short page goes on to the next stages and comes back only if nothing better is found (K8). The reference check C5 also fires on complete results when Keenable's copy carries more around the article, which costs a request, not a result. Partial results of the first stage that pass every check end the chain.
- Jina, Bright Data and Tavily (if enabled) report no final URL. For their results, redirects are not noted (V10), and the website blocklist sees only the input URL (S7).
- Without KYC, Bright Data refuses government sites and paths blocked by robots.txt (D33); the other stages fetch them.
- Keenable sees every URL: it is asked for each one at the start (K3).
- Copies (Keenable, and Tavily if enabled) may be older than the live page. The note says so; the age itself is unknown. A copy longer than a live page wins in the fallback (K8, D30). Jina caches pages for up to an hour (A7), Firecrawl accepts copies of up to an hour (D7).
- Marker rules are keyword rules tuned on German news sites. An article *about* paywalls or cookie consent can trigger a note, and English-language paywalls are mostly not detected.
- A pause (K7) does not notice a top-up. After adding credits, the stage is used again when the pause ends or Hermes is restarted. The pauses rest on the providers' documentation; no real quota reply was available for a test. What Bright Data answers when its free monthly allowance is used up without a payment method is not documented; if it is no code of K7, every URL costs one failing Bright Data request until the month renews.
- Hermes caches successful results with their notes for `web.cache_ttl_minutes` (default 20), including a consent page returned with V5.
- Privacy: every URL is sent to Keenable and to the first stage of the order (Jina by default), and, depending on the outcome, to the later stages (Tavily only if the order names it). Hermes refuses URLs that contain secrets before any provider sees them.
- The plugin imports two modules from inside Hermes, `agent.web_search_provider` and `tools.website_policy`, and reads `web.extract_timeout` via `tools.web_tools`. If a Hermes update moves the first, the plugin does not load; without the second it refuses every URL (S7); without the third the budget falls back to 110 s (Z1).

## 14. Decisions

| ID | Decision | Reason |
|---|---|---|
| D1 | All providers via direct REST, not via Hermes' built-in providers or vendor SDKs | Hermes' Firecrawl provider needs `firecrawl-py`, an optional extra that Hermes installs on first use. In container deployments that runtime install can disturb the image's package set. Direct calls also make timeouts and parameters controllable and avoid Hermes internals. |
| D2 | TinyFish via direct REST, not via TinyFish's own Hermes plugin. **Superseded in 0.3.0** (D26) | No third-party code dependency. No `tinyfish_agent` tool that spends credits, no interactive key prompt at install time. |
| D3 | `async def extract` | Hermes' timeout cancels cleanly; URLs run concurrently without a thread pool. |
| D4 | Paywall: note only, no further provider | In tests no provider got past a teaser; another call would only cost quota. |
| D5 | Teasers without markers not handled | No reliable signal in the text; a per-site list would need constant upkeep. |
| D6 | Notes in English | Matches Hermes' own messages and the provider error texts. |
| D7 | Freshness: Firecrawl `maxAge` 1 h; Bright Data, Jina and Tavily as measured, without cache parameters (changed in 0.3.0; TinyFish had `ttl` 3600 s) | Firecrawl's default accepts copies up to 2 days old. Agents should read versions and dates from the page; for news the current state matters. Jina's default cache (up to an hour) was part of the measurement and stays. |
| D8 | Wall window: start, whole text if short (E3) | Avoids false alarms from consent texts in footers of whole pages. |
| D9 | Check Firecrawl's target `statusCode` | Firecrawl returns 403/404 pages empty and without an error field. |
| D10 | Constants instead of configuration. **Superseded in 0.3.0** (D27): the stage order is configurable; all else stays constant | As little code as needed; changes come with releases. |
| D11 | MIT license | Same as Hermes Agent. |
| D12 | Paywall check on full pages without the last quarter (E4); since 0.3.0 for every stage but Keenable | The live smoke test showed stern.de getting false paywall notes via Firecrawl. On the stored data of all six providers of the 2026-10-09 tests, this removed the three Firecrawl false alarms (Spiegel, Welt, stern) and kept every paywall hit. |
| D13 | Enforce Hermes' website policy and interrupts in the plugin (S7, S8); cap Firecrawl PDFs at 30 pages (A2) | Found in the edge-case review (2026-10-10): Hermes leaves the blocklist and interrupt checks to each provider, and an uncapped PDF can cost hundreds of Firecrawl credits in one call. |
| D14 | Pause a stage after a used-up quota (K7) for 24 hours. Changed in 0.3.0 (D33): no TinyFish pause until 00:05 UTC any more | A used-up quota answers every request with an error until it renews. |
| D15 | Refuse every URL when Hermes' policy module cannot be imported (S7) | A blocklist that silently stops working is the worse failure; a refusal shows in the first call. Up to v0.2.0 the plugin went on without the blocklist and logged one warning. `is_available()` stays true in that state: otherwise Hermes would stop offering the tool, and the model would see a missing tool instead of the reason. |
| D16 | No concurrency limit of its own (K6) | Proposed in several reviews. A local limit puts waiting time in front of a stage's deadline (A0) and can push a call beyond Hermes' `web.extract_timeout`, and Hermes then drops every result of the call. Hermes passes at most five URLs, and Firecrawl queues by itself. |
| D17 | One client per call, not one kept across calls (A5) | Hermes runs tool calls on several event loops and, when called from inside a running loop, closes the loop after the call. A client kept across calls would be bound to a closed loop. The saving would be one TLS handshake per provider and call. |
| D18 | No retry (K5) and no cap on the text that is classified (E3, E4) | The next stage is the retry; waiting for `Retry-After` does not fit into Z1. Classifying costs about 13 ms per 100,000 characters (measured), and main-content providers put the paywall notice at the very end, where a cap would lose it. |
| D19 | Block a URL whose policy check raises (S7) | Up to v0.2.2 such a URL was allowed, on the assumption that Hermes does the same. Hermes allows only when the policy file is faulty; its own providers return an error when the check of a final URL raises. A result whose blocklist status is unknown should not reach the model. |
| D20 | A short text is not an error (E8); since 0.3.0 it is check C1 | 20 of 554 TinyFish texts of the search test were below 500 characters, and about half of them were real pages. A short page is a reason to ask the next stage, and it still comes back when nothing better is found (K8). |
| D21 | Bot-check pages are recognised by a short phrase list plus a length cap (E7), not by length alone and not by HTTP status | Providers return bot checks with status 200; length alone would turn real short pages into failures. |
| D22 | A redirect is noted, not treated as a failure (V10) | Many redirects are harmless; the model can judge with the note. |
| D23 | No Keenable request after two short live results, or after a short TinyFish page and a failed Firecrawl. **Superseded in 0.3.0** (D29, D30) | An older index copy must not replace a live page only because that page is short. |
| D24 | No switch for the provider order in v0.2.5. **Superseded in 0.3.0** (D27) | Asked for job listings, where TinyFish returns no links; decided to wait and see what E7 and E8 already fix. |
| D25 | A bot-check page without alternative is returned with a note, like a consent wall (V5), not as an error | The marker list can match a real short page. |
| D26 | TinyFish removed (0.3.0) | In web benchmark v2 (132 pages) no chain gained from TinyFish at any position; as first stage it ended the chain on failures it did not report. It fails on most pages with bot protection, and returning only the main content makes it look short against any reference. |
| D27 | Stage order configurable via `EXTRACT_CHAIN_ORDER`; Keenable always last (K1) | Bright Data first and Jina first were close in the benchmark model (118 and 117 complete), Jina first being faster; a further measurement decides, and a setting avoids a release for it. The further measurement came in D34: Jina first is the default. Keenable reports its failures worst of all providers and is the reference (K3), so nothing comes after it. |
| D28 | Keenable asked for every URL at the start, in parallel, as reference (K3) | The length comparison (C5) carries most of the gain of the checks; the text patterns alone added little on the benchmark pages. Running in parallel costs no time; it costs one Keenable request per URL from a large free allowance. |
| D29 | A result that fails a check (C1–C5) moves the chain on instead of ending it (K4) | The goal is the most complete results; a false alarm costs requests, not a result. Measured false alarms on complete results: Bright Data 6 %, Jina 1 %, Firecrawl 8 %, Tavily 1 %. A short live page now yields to a longer later result, Keenable's copy included (supersedes D23); the source note says the copy may be older. |
| D30 | When no stage passes, the longest kept result, the earlier on a tie; results with a bot-check hint last (K8) | Asking every stage and picking the longest result measured worse than stopping at the first result that passes the checks; the order is the better filter, the length only the fallback. A bot-check hint is a stronger sign of a wrong page than shortness. |
| D31 | Time budget from `web.extract_timeout` (at most 170 s per URL), stage deadlines Bright Data 90 s, Jina 35 s, Firecrawl 40 s, Tavily 30 s, Keenable 25 s (Z1, A0) | The slow pages are the hard ones that only Bright Data fetched; a shorter Bright Data limit cost complete results, and every Bright Data fetch over 90 s failed. The other limits sit at or above the slowest fetch measured for each provider. A single total budget instead of a sum of deadlines keeps the call under Hermes' limit; I2 raises that limit to 180 s. |
| D32 | Two 404/410 answers of live stages end the live stages only before Firecrawl was asked (K9) | A page that two services report gone is rarely fetched by a third; skipping the rest saves quota. Once Firecrawl has been asked, the remaining stages cost little compared to the chance of an older copy that still holds the content. Keenable's copy, already requested, is returned with a note. |
| D33 | Pauses only on quota codes of a provider's API, set by the fetcher (K7); no Bright Data KYC | Bright Data reports account and zone errors with an outer 200; target pages answered 402 several times in the benchmark and must not pause a stage. KYC requires a company; government sites and robots.txt-blocked paths are left to the other stages. |
| D34 | Default order Jina → Bright Data → Firecrawl → Keenable; Tavily optional, only via `EXTRACT_CHAIN_ORDER` (K1) | A second, harder benchmark set (197 pages, 71 of them job pages) replayed with the real chain: Jina first 170 complete and 19 wrong, Bright Data first 160 and 30 (paired sign test, p = 0.04); on the first set (132 pages) 116 / 8 against 118 / 5. Bright Data stays second: several agents share Jina's keyless limit of 20 requests per minute, a 429 then moves on to Bright Data, and a second live stage ahead of Firecrawl spares Firecrawl credits. Tavily changed no result in either set and reported only 38 % of its failures recognisably in the second set, so it is optional. Settles the default order that D27 left open; Tavily's fetcher (A8) stays. |
