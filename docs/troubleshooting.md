# Troubleshooting

How failures show up, what the log line means, typical problems with their fixes, and the edge cases the plugin handles on purpose. Requirement IDs refer to [design.md](design.md).

## Where to look

| Place | What you find |
|---|---|
| The tool result the model sees | Per URL either content (possibly with `[extract-chain]` notes at the top) or an `error` such as `TinyFish: bot_blocked; Firecrawl: target HTTP 403; Keenable: Gateway timeout` |
| `logs/agent.log` in the Hermes home (INFO) | One line per URL: `extract-chain <host>: tinyfish=… firecrawl=… keenable=…` |
| `logs/errors.log` (WARNING) | Plugin load failures, the website-policy import warning, the plugin's `chain failed` warning, the start of a pause (`… paused for <seconds> s`), Hermes' extract timeouts |
| `hermes plugins list` | Whether `extract-chain` is enabled and loaded, or why it failed to load |

Count how often each stage was needed, e.g. to watch Firecrawl credits:

```bash
grep -c "extract-chain .*firecrawl=" logs/agent.log
grep -o "firecrawl=[a-z_0-9]*" logs/agent.log | sort | uniq -c
```

## How failures surface

| Level | Failure | What the model sees | Log |
|---|---|---|---|
| Plugin not available | not in `plugins.enabled`, import error, `requires_hermes` mismatch, directory without `plugin.yaml`/`__init__.py` | Every `web_extract` call fails: *web is configured to use 'extract-chain' (set via hermes tools), but no registered web extract provider has that name.* | `errors.log`: `Failed to load plugin 'extract-chain': …` or `Plugin 'extract-chain' skipped: requires hermes >=0.21, running …`; `hermes plugins list` says *not enabled in config* |
| Whole call | Hermes' `web.extract_timeout` reached | `Extract timed out after <n>s via extract-chain` for every URL of the call, including URLs that had already finished | `errors.log`: `web_extract provider 'extract-chain' timed out …` |
| Whole call | Hermes' policy module cannot be imported (incompatible Hermes version) | `Blocked by website policy: extract-chain cannot load Hermes' website blocklist …` for every URL; nothing is fetched, and the keyless rescue does not step in | `errors.log`: `extract-chain: tools.website_policy not importable; every URL refused` |
| Whole call | Bug in the plugin raises | `Error extracting content: …`. With `web.keyless_rescue` on, Hermes instead tries anonymous providers, and you see content without notes | traceback in `errors.log` |
| One URL | Bug in the plugin raises while handling that URL | `error`: `extract-chain: <exception class>`; the other URLs of the call keep their results | `errors.log`: `extract-chain <host>: chain failed: <exception class>` |
| One URL | Policy block | `error` with Hermes' block message plus a `blocked_by_policy` field | none; Hermes' policy logs |
| One URL | All stages failed | `error` listing every stage's reason | the L1 line shows each stage's code |
| One URL | A later stage delivered | content with a note naming the source and why the earlier stages failed | the L1 line |

Problems with a single URL never raise and never fail other URLs of the same call (S6).

## Log line codes (L1)

Each stage that ran appears as `<stage>=<outcome>`. Success outcomes are the classes `ok`, `paywall`, `wall`, `empty`. Errors show a short code.

| Code | Stage | Meaning | Chain continues? |
|---|---|---|---|
| `bot_blocked` | TinyFish | Bot protection (Cloudflare, DataDome …) | yes → Firecrawl |
| `target_http_error` | TinyFish | Site answered non-2xx (not 404/410); seen at faz.net and another news site | yes → Firecrawl |
| `timeout`, `target_unreachable`, `proxy_error`, `empty_content` | TinyFish | Fetch problems on TinyFish's side | yes → Firecrawl |
| `page_not_found`, `login_required`, `invalid_url`, `invalid_redirect_url`, `content_too_large` | TinyFish | Final: another provider would not do better | no, the error is returned |
| `http_401` / `http_402` / `http_429` / `http_5xx` | TinyFish, Keenable | API problem: bad key / quota or credits used up / rate limit / provider outage | yes, to the next stage |
| `api_401` / `api_402` / `api_408` / `api_429` / `api_5xx` | Firecrawl | Same for Firecrawl's API | yes → Keenable |
| `target_403`, `target_404`, … | Firecrawl | Firecrawl reached the site, the site refused | yes → Keenable |
| `http_4xx` / `http_5xx` with a message | Keenable | Keenable could not provide the page; the error text carries its message, e.g. *The page is behind a login or paywall* (`Unprocessable entity`), *The page was reached but content could not be extracted*, *The target page took too long to respond* (`Gateway timeout`), *The target server denied access to this URL* (`Upstream forbidden`) | last stage |
| `timeout` | any | The plugin's own deadline (40/40/25 s), an httpx timeout or the provider's timeout | yes |
| `ConnectError`, `ProxyError`, … | any | Network: DNS, firewall, proxy refused the connection, TLS | yes |
| `no_result` | TinyFish | TinyFish's reply did not mention the URL (see *Edge cases*, redirects) | yes → Firecrawl |
| `no_key` | any | Key not set in the profile | stage skipped |
| `paused` | any | The provider's API answered HTTP 402 earlier (quota or credits used up); no request is sent until the pause ends (K7) | stage skipped |
| `interrupted` | Firecrawl, Keenable | The user stopped the turn | stage skipped |
| `exception` | Firecrawl, Keenable | Unexpected error inside the stage (bug); details in the error text | yes |

## Typical problems

**Every call fails with "no registered web extract provider has that name".**
The plugin is not loaded. Check, in this order:

1. `extract-chain` is listed under `plugins.enabled` in the profile's `config.yaml`. User plugins are opt-in.
2. The directory `plugins/extract-chain/` contains `plugin.yaml` and `__init__.py`, not a nested `extract_chain/` folder.
3. `hermes plugins list` and `errors.log` show the reason: an import error or a Hermes version below 0.21.
4. Hermes or the gateway was restarted after installing.

**`tinyfish=http_401` on every URL.**
The TinyFish key is wrong or missing in the profile's `.env`. Hermes reads keys per profile; a key exported in the shell may not reach a gateway or a container. While this lasts, every URL goes to Firecrawl and costs credits.

**`tinyfish=http_402`.**
The free daily allowance is used up: 1,000 successful URLs per day, reset at 00:00 UTC, and the TinyFish wallet is empty. Wait for the reset or top up. In the meantime Firecrawl takes over and its credits drain quickly. After the 402 the plugin skips TinyFish until 00:05 UTC (`tinyfish=paused`).

**`tinyfish=http_429` / `firecrawl=api_429`.**
Rate limits: TinyFish allows 150 URLs/min per key, Firecrawl's free plan 10 scrapes/min. Agents and profiles that share a key share the limit.

**`firecrawl=api_402`.**
Firecrawl credits are exhausted (1,000/month on the free plan). URLs that TinyFish cannot fetch now end up at Keenable, as index copies or not at all. Top up or wait for the monthly reset. After the 402 the plugin skips Firecrawl for 24 hours (`firecrawl=paused`); the same holds for Keenable.

**`…=paused` although the credits are back.**
A pause does not notice a top-up. It ends by itself (TinyFish at 00:05 UTC, the others after 24 hours); to use the stage at once, restart Hermes or the gateway. `errors.log` shows when a pause began: `extract-chain: Firecrawl paused for 86400 s (api_402)`.

**`firecrawl=timeout` only in calls with several URLs.**
Firecrawl's free plan scrapes 2 pages at a time and queues the rest. Queue time counts against the 30 s timeout. The URL moves on to Keenable; this is expected (K6).

**`keenable=http_401` / `http_403`.**
The Keenable key is invalid or disabled. Consent walls (e.g. golem.de, derstandard.at) then stay unresolved and come back with the note *Consent wall detected …*.

**All stages fail with `ConnectError` or `ProxyError`.**
The host cannot reach the APIs. Allow HTTPS to `api.fetch.tinyfish.ai`, `api.firecrawl.dev` and `api.keenable.ai`.

- The plugin honours `HTTPS_PROXY` and `NO_PROXY`.
- `ProxyError` means the proxy refused the connection, typically a missing allowlist entry.

**TLS errors (`ConnectError` mentioning certificates).**
Hermes trusts the operating system's certificate store and installs this process-wide at start-up; the plugin inherits it. Behind TLS inspection, install the inspecting CA in the OS store of the host or container, or point `SSL_CERT_FILE` at a bundle that contains it.

**Failed URLs come back with content but without any note.**
The keyless rescue is on. When every URL of a call fails, Hermes silently retries with anonymous providers. Set `web.keyless_rescue: false`.

**`Extract timed out after <n>s via extract-chain`.**
`web.extract_timeout` is below the chain's worst case (105 s). Set it to at least 110; the default is 120.

**A normal article gets a paywall or consent-wall note.**
A false alarm of the keyword rules, e.g. in an article *about* paywalls or cookie banners. Nothing to configure. Please report the URL.

- A false wall sends the URL to Keenable. The text is then Keenable's copy, with its note.
- A false paywall only adds the note; the text is complete.

**The same wrong or stale result keeps coming back.**
Hermes caches successful results, notes included, for `web.cache_ttl_minutes` (default 20). This includes a consent page returned with the wall note. Wait, or lower the TTL.

**Every URL fails with `Blocked by website policy: extract-chain cannot load Hermes' website blocklist …`.**
A Hermes update moved the policy module, and the plugin fetches nothing without the blocklist (S7). `errors.log` shows `extract-chain: tools.website_policy not importable; every URL refused` for each call. Update the plugin; until then, set `web.extract_backend` to another provider.

**Firecrawl credits drain faster than expected.**
Firecrawl is only used when TinyFish fails. Common causes:

- sites that block TinyFish (`bot_blocked`: stern.de, Stack Overflow and the whole Stack Exchange network in our tests; `target_http_error`: faz.net);
- PDFs, which cost 1 credit per page, capped at 30;
- target 403/404 pages, which Firecrawl bills when it returns a document.

The `firecrawl=` counts in the log show which sites cause it.

## Edge cases (behaviour by design)

| Situation | Behaviour |
|---|---|
| Duplicate URLs in one call | Fetched once, returned at every position as an entry of its own (S5). |
| More than 10 URLs | Split into TinyFish batches of 10, sent concurrently. Hermes' `web_extract` passes at most 5. |
| Redirect, single URL | TinyFish's entry is used even if it names the final URL. |
| Redirect inside a multi-URL batch | If TinyFish reports only the final URL, the input URL gets `no_result` and goes to Firecrawl (one credit). Not observed in tests. |
| Redirect to a blocked site | The result is replaced by Hermes' policy block entry (S7). |
| Website blocklist | Checked before any request; blocked URLs reach no provider. |
| Consent wall, Keenable fails | The consent page comes back with the wall note listing all reasons. Hermes caches it like any success. |
| Paywall detected | Teaser plus paywall note; no further provider is asked (D4). |
| Paywall without markers (FAZ, SZ, Welt, Handelsblatt, Tagesspiegel) | Returned as normal content; the teaser is not recognised (D5). |
| Firecrawl returns an empty `<body></body>` | Treated as empty; moves on to Keenable. |
| Target 403/404 via Firecrawl | Error `target HTTP <status>`; Firecrawl still bills one credit. |
| Long PDF where TinyFish fails | Firecrawl reads the first 30 pages; the note says *PDF cut to the first 30 of N pages*. |
| `content_too_large`, `login_required`, `page_not_found` | Final; no other provider is asked. |
| Page that loads with status 200 but shows "Access denied" or a challenge text | Not recognised as a failure if TinyFish returns it as content (rare; TinyFish normally reports `bot_blocked`). |
| English-language paywalls | Markers are mostly German. An English teaser is usually not detected (D5 applies). |
| Missing TinyFish key | The provider reports itself unavailable, and Hermes hides `web_extract` unless another web backend is available. If the tool is still offered, stage 1 fails with `no_key` for all URLs and the chain continues with Firecrawl. |
| Missing Firecrawl or Keenable key | That stage is skipped (`no_key`). |
| User stops the turn | No further requests; remaining stages report `interrupted` (S8). |
| Hermes timeout | All URLs of the call fail, also those that had finished (Hermes discards the whole call). |
| Hermes cache | Successful results, notes included, are reused for 20 minutes without running the chain. |
| Privacy | Every URL goes to TinyFish, and possibly to Firecrawl and Keenable. Hermes refuses URLs that contain secrets before any provider sees them. |

## Cost and quota safety

| Provider | Free tier | When exhausted | Hard cap |
|---|---|---|---|
| TinyFish | 1,000 successful URLs/day, 150 URLs/min | HTTP 402, unless the wallet has balance | Keep wallet auto-reload off; balance via `GET /v1/wallet` |
| Firecrawl | 1,000 credits/month, 10 scrapes/min, 2 concurrent | HTTP 402 until the monthly reset | Keep auto-recharge off (dashboard, paid plans); PDFs are capped at 30 pages |
| Keenable | 100,000 requests/month, 10 requests/s | HTTP 402 | Keep auto top-up off (console) |

## Reporting a problem

Include:

- the L1 log line(s);
- the error or note the model saw;
- the Hermes version and the plugin version (`plugin.yaml`);
- the URL, if it can be shared.

Never include API keys or `.env` contents.
