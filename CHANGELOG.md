# Changelog

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
