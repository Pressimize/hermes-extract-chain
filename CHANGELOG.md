# Changelog

## 0.3.0 – unreleased

A new chain of four services, Jina → Bright Data → Firecrawl → Keenable, with checks of every result against Keenable's copy. Tavily Extract is optional: it runs only if `EXTRACT_CHAIN_ORDER` names it. From web benchmark v2 (2026-10-17/18) and a second, harder set; results on their stored data in `docs/validation.md`.

**Breaking changes**

- TinyFish is removed, with its key, its batch requests, its final error codes and its pause until 00:05 UTC. `TINYFISH_API_KEY` is no longer read and can be deleted.
- New keys in the profile's `.env`: `BRIGHTDATA_API_KEY` and `BRIGHTDATA_UNLOCKER_ZONE` (name of a Web Unlocker zone); optionally `JINA_API_KEY` and, only for the optional Tavily stage, `TAVILY_API_KEY`. `FIRECRAWL_API_KEY` and `KEENABLE_API_KEY` stay.
- `web.extract_timeout` must be 180 (was: at least 110). The chain now takes up to 170 s per URL; a lower setting shrinks that budget, and below 120 s the plugin logs a warning.
- Egress: allow `r.jina.ai` and `api.brightdata.com` (and `api.tavily.com` if you enable Tavily); `api.fetch.tinyfish.ai` is no longer used.
- The notes changed: `Live fetch via <Provider> (…)` and `Copy via <Provider>; it may be older than the live page (…)` replace the Firecrawl and Keenable source notes, the three short-page notes are gone, and two notes are new (longest result, page gone). The log line lists the new stages, and Keenable always.

**Chain**

- Keenable's copy is requested for every URL at the start, in parallel, and serves as the reference for the checks and as the last stage.
- A result that looks fine is checked: very short, print view, short with a JavaScript or bot-check hint, short with repeated consent text, or much shorter than Keenable's copy. A suspect result is kept and the next stage is asked; before, a short live page ended the chain (D23, superseded).
- When no stage passes, the longest kept result is returned with a note.
- No error ends the chain any more, except two 404/410 answers of live stages before Firecrawl was asked; Keenable's copy is then returned with a note, if it has one.
- `EXTRACT_CHAIN_ORDER` sets the order of the stages; Keenable always stays last. The default is `jina,brightdata,firecrawl,keenable`. Tavily is not part of it; to use it, name it, e.g. `jina,brightdata,firecrawl,tavily` (D34). Jina first gave more complete results than Bright Data first on the second, harder benchmark set (170 against 160 of 197 pages); Tavily changed no result in either set.
- A time budget per URL from `web.extract_timeout`; a stage with less than 10 s left is skipped (`no_time`).
- Pauses only on quota codes of a provider's API, now also Bright Data's account and zone codes and Tavily's 432/433; a target page with status 402 never pauses a stage.
- The paywall check skips the last quarter of every full page (Bright Data, Jina, Firecrawl, Tavily), not only of Firecrawl's.

**Docs:** design rewritten for 0.3.0 (rules K1–K9, C1–C5, V12–V15, A1, A6–A8, decisions D26–D34; D2, D10, D23, D24 superseded); README with configuration, costs per provider and privacy; troubleshooting with the new log codes; validation and evaluation keep the v0.1–v0.2 tests as history.

## 0.2.6 – 2026-10-17

Fixes from the overnight review (`docs/reviews/2026-10-16.md`) and from a mutation run, and alignment with hermes-search-chain. No change to the interface, the notes or the order of providers.

- A `<` in the text (`x < 10`, `>>> 1 < 2`, `i<n; i++`) no longer swallows everything up to the next `>` when the visible length is measured. A programming article could be classified as `empty` or `thin` before and was replaced by Firecrawl or Keenable. Markdown autolinks such as `<https://example.com/>` now count as visible text as well. The tag pattern is also linear now; a page with many `<` and no `>` took seconds of CPU before (N01).
- A Firecrawl reply whose `data` or `metadata` is no object gives `Firecrawl: malformed reply` (code `malformed`) instead of `Firecrawl: AttributeError`, as TinyFish and Keenable already do (N02).
- Aligned with hermes-search-chain: control and other non-printable characters in a provider's error text become spaces; a key is masked only from 8 characters on; the remaining time of a pause is given as the nearest hour from one hour on (3,600 s read `60 min` before and now `1 h`; 3,601 s read `2 h` and now `1 h`; below one hour minutes are still rounded up).
- Docs: the troubleshooting table now says that bot-check pages are recognised (E7, since 0.2.5) (N03).
- Developer scripts: `scripts/replay.py` no longer stops on a stored error detail that is JSON but no object (N04); `scripts/live_check.py` checks URLs of the same host together instead of matching log lines by host only (N05). New tests in `tests/test_scripts.py`.

## 0.2.5 – 2026-10-12

Bot-check pages and very short pages no longer pass as good results, and a redirect is noted. From a measurement on job-board pages.

- New class `challenge` (E7): a text under 1,500 visible characters with a bot-check phrase ("not a robot", "checking the site connection security", "captcha", …) is a failure at every stage and moves the chain on. Before, only errors and empty pages did.
  - Keenable results that are bot-check pages are no longer accepted, and Firecrawl results that are bot-check pages lead on to Keenable.
  - If no stage has anything better, the first bot-check page is returned with the note V11, not as an error, because the phrase list can match a real short page. A consent wall still wins over it. Without any page, the error lists all reasons as before.
- New class `thin` (E8): a text under 500 visible characters is no longer `ok`. A short TinyFish page triggers a second opinion from Firecrawl; the longer short page wins, and a short page without second opinion (any Firecrawl outcome but ok, paywall or thin, a consent wall included) is returned with a note (V8, V8a, V9). Keenable is not asked after a short live result (D23).
- New note V10: the site redirected to another host, or to the home page or a locale root. A note only; the class and the order of stages do not change.
- The log line shows `challenge` and `thin` as outcomes.
- Behaviour change: a text of 20 to 499 visible characters was `ok` before. Of the 554 stored TinyFish texts of the search test, 16 become `thin` and 4 `challenge`. In the replay of the chain test one article differs (a TinyFish text of 268 characters, now answered by Firecrawl).
- Design: rules E7, E8, V8–V11, changes to K2–K4 and decisions D20–D25; results on stored data in `docs/validation.md`.

## 0.2.4 – 2026-10-10

From a sixth and a seventh external code review.

- A TinyFish reply entry that is no object is skipped, so only its URL is left without a result. Before, it failed every URL of the request, and each of them went on to Firecrawl.
- A 2xx reply of TinyFish or Keenable that is no JSON object, or an empty one, gives the code `malformed` (`<Provider>: malformed reply`) instead of `AttributeError` or `JSONDecodeError`.
- The pause table is keyed by a digest of the API key, so the plugin keeps no key of its own in memory.
- A key echoed in an error text is replaced in any case and also in its percent-encoded form. A TinyFish error that repeats the key in another case can no longer become the code in the log.
- Without Hermes' policy module, an entry of `urls` that is no string keeps the error `extract-chain: not a URL`.
- The CI job times out after 10 minutes.
- Design: the log line (L1) is written for every URL that reaches the chain; the text now says which URLs have none.
- Metadata: Claude is named as an author next to Pressimize (README, `plugin.yaml`, `pyproject.toml`).

## 0.2.3 – 2026-10-10

Hardening from a fourth and a fifth external code review.

- A URL whose website-policy check raises is blocked. Before, it was allowed. Hermes' own providers withhold such a result as well.
- A TinyFish error that is not a plain code is logged as `fetch_failed`. Before, the first 40 characters of its text went to the log in reduced form, which could include part of a URL. A code in another case (`PAGE_NOT_FOUND`) counts as that code, also where the chain ends on it.
- `zustimmung` no longer counts as a second wall marker inside `Cookie-Zustimmung`. No stored test text is classified differently.
- An entry of `urls` that is not a string gets an error of its own. Before, it failed the other URLs of the call or made `extract()` raise. Hermes itself passes strings only.
- The HTTP client is told explicitly not to follow redirects (it never did), so that a key cannot travel to another host.
- Input URLs that share one TinyFish entry each get a copy of it.
- Design: decisions D16–D18 record three proposals that reviews keep raising, and why they were not adopted.

## 0.2.2 – 2026-10-10

Two fixes from a third external code review.

- Two URLs of one call that differ only in the trailing `/` each get the TinyFish result that names them. Before, both got the text of one of them.
- A website-policy block whose result has an unexpected shape still blocks, with a generic message. Before, `extract()` raised.
- Documentation: Firecrawl is asked for the main content only, yet returns much of the page around the article; the design now says so where it speaks of whole pages.

## 0.2.1 – 2026-10-10

A pause after a used-up quota, and hardening after two external code reviews. The classification is unchanged.

- After an HTTP 402 from a provider's API, that stage is skipped without a request: TinyFish until five minutes after its daily reset at 00:00 UTC, Firecrawl and Keenable for 24 hours. The log shows `paused`, and a warning marks the start of a pause.
- Provider error texts are reduced to one line before they appear in a note or an error.
- If Hermes' website blocklist module cannot be imported (an incompatible Hermes version), every URL is refused with a clear error. Before, the plugin went on without the blocklist and logged one warning.
- An unexpected error while handling one URL fails only that URL; the other URLs of the call keep their results.
- Duplicate URLs of one call get result entries that share no data.
- TinyFish error codes are reduced to lowercase letters, digits and `_` (at most 40 characters) before they reach the log line, and a key echoed in a TinyFish error is replaced by `[key]`, as for the other providers.
- A TinyFish result without `final_url` takes the URL its entry names as final URL. When that URL differs from the requested one, the website blocklist is checked on it.
- Removed two paywall markers that were listed both as definite and as general markers; no result changes.

## 0.2.0 – 2026-10-10

- Apply Hermes' website blocklist to every input URL and to the final URL after redirects (Hermes leaves this to each provider).
- Stop between stages when the user interrupts the turn.
- Never raise from `extract()`: an unexpected failure becomes a per-URL error.
- Cap Firecrawl PDFs at 30 pages (one credit per page) and add a note when a PDF was cut.
- Split TinyFish requests into batches of at most 10 URLs.
- Dropped a paywall marker that matched a single site only.
- Log line shows an error code per stage (`http_402`, `api_402`, `target_403`, `no_key`, …).
- Documentation in English: design, validation, troubleshooting, evaluation (provider choice and test scenarios); test data as CSV in `data/`; MIT license.

## 0.1.0 – 2026-10-09

- First version: `extract-chain` provider for `web_extract` with the chain TinyFish → Firecrawl → Keenable, notes for the model, validated on 54 URLs.
