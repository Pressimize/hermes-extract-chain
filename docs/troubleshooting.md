# Troubleshooting

How failures show up, what the log line means, typical problems with their fixes, and the edge cases the plugin handles on purpose. Requirement IDs refer to [design.md](design.md). This file describes 0.3.0; for the TinyFish chain of v0.1–v0.2 see the file at tag `v0.2.6`.

## Where to look

| Place | What you find |
|---|---|
| The tool result the model sees | Per URL either content (possibly with `[extract-chain]` notes at the top) or an `error` listing the reason of every stage, e.g. `Jina: target HTTP 403; Bright Data: target HTTP 403; Firecrawl: target HTTP 403; Keenable: Gateway timeout` |
| `logs/agent.log` in the Hermes home (INFO) | One line per URL: `extract-chain <host>: jina=… brightdata=… firecrawl=… keenable=…` (L1; `tavily=…` appears only if Tavily is in the order) |
| `logs/errors.log` (WARNING) | Plugin load failures, the website-policy import warning, the plugin's `chain failed` warning, the start of a pause (`… paused for <seconds> s`), an invalid `EXTRACT_CHAIN_ORDER`, a `web.extract_timeout` below 180 s, Hermes' extract timeouts |
| `hermes plugins list` | Whether `extract-chain` is enabled and loaded, or why it failed to load |

Count how often each stage was needed and how it ended, e.g. to watch credits:

```bash
grep -oE "(jina|brightdata|firecrawl|tavily|keenable)=[a-z_0-9]*" logs/agent.log | sort | uniq -c
```

## How failures surface

| Level | Failure | What the model sees | Log |
|---|---|---|---|
| Plugin not available | not in `plugins.enabled`, import error, `requires_hermes` mismatch, directory without `plugin.yaml`/`__init__.py` | Every `web_extract` call fails: *web is configured to use 'extract-chain' (set via hermes tools), but no registered web extract provider has that name.* | `errors.log`: `Failed to load plugin 'extract-chain': …` or `Plugin 'extract-chain' skipped: requires hermes >=0.21, running …`; `hermes plugins list` says *not enabled in config* |
| Whole call | Hermes' `web.extract_timeout` reached | `Extract timed out after <n>s via extract-chain` for every URL of the call, including URLs that had already finished | `errors.log`: `web_extract provider 'extract-chain' timed out …` |
| Whole call | Hermes' policy module cannot be imported (incompatible Hermes version) | `Blocked by website policy: extract-chain cannot load Hermes' website blocklist …` for every URL; nothing is fetched, and the keyless rescue does not step in | `errors.log`: `extract-chain: tools.website_policy not importable; every URL refused` |
| Whole call | Bug in the plugin raises | `Error extracting content: …`. With `web.keyless_rescue` on, Hermes instead tries anonymous providers, and you see content without notes | traceback in `errors.log` |
| One URL | Bug in the plugin raises while handling that URL | `error`: `extract-chain: <exception class>`; the other URLs of the call keep their results | `errors.log`: `extract-chain <host>: chain failed: <exception class>` |
| One URL | Hermes' policy check raises for the URL or its final URL | `error`: `Blocked by website policy: the check failed for this URL (<exception class>)`; the content is withheld | `errors.log`: `extract-chain: website policy check failed for a URL (blocked): <exception class>` |
| One URL | Policy block | `error` with Hermes' block message plus a `blocked_by_policy` field | none; Hermes' policy logs |
| One URL | No stage delivered | the longest suspect result, a consent-wall or bot-check page with a note, or an `error` listing every stage's reason (K8) | the L1 line shows each stage's outcome |
| One URL | A later stage delivered | content with a note naming the source and why the earlier stages were passed over | the L1 line |

Problems with a single URL never raise and never fail other URLs of the same call (S6).

## Log line codes (L1)

Each stage appears as `<stage>=<outcome>`, in order, Keenable last. The outcomes are the classes `ok`, `thin`, `paywall`, `wall`, `empty` and `challenge` (bot-check page), a check, or a short error code.

**Checks** (any stage; the stage was passed over and its result kept for the fallback, K4, K8):

| Code | Meaning |
|---|---|
| `suspect_thin` | Under 500 visible characters (C1) |
| `suspect_print` | A print view (C2) |
| `suspect_check` | Under 3,000 characters with a JavaScript or bot-check hint (C3) |
| `suspect_consent` | Under 1,500 characters with repeated consent text (C4) |
| `suspect_shorter` | Keenable's copy is at least 1.5 times as long (C5) |

**Per stage:**

| Code | Stage | Meaning | Chain continues? |
|---|---|---|---|
| `api_401` | Jina, Bright Data, Firecrawl, Tavily | Key wrong or disabled | yes |
| `api_400` | Bright Data | Zone unknown (text `zone "…" not found`), or the URL was refused as invalid; no pause | yes |
| `api_402` | Jina, Bright Data, Firecrawl, Tavily | Quota or credits used up; the stage pauses for 24 h (K7) | yes |
| `api_432`, `api_433` | Tavily (only if enabled) | Plan limit or pay-as-you-go limit reached; pause (K7) | yes |
| `api_429` | Jina, Firecrawl, Tavily | Rate limit; no pause. Jina without a key allows 20 requests per minute | yes |
| `api_422` | Jina | Seen in tests; meaning not documented | yes |
| `api_200` | Firecrawl | Firecrawl answered 200 without `success: true` | yes |
| `api_5xx` | Jina, Bright Data, Firecrawl, Tavily | Provider outage | yes |
| `brd_<code>` | Bright Data | Unlocker error with Bright Data's code (A1), e.g. `brd_proxy_error` (host not resolvable; also seen for a blocked government site), `brd_client_10110` or `brd_sr_rate_limit` (rate limits, no pause); `brd_client_10020`, `brd_client_10100`, `brd_client_10002` pause the stage (account suspended, zone limit, zone disabled). Read from Bright Data's reply headers, also with an outer error status, and from the JSON field `headers` only when the page body is empty (D38) | yes |
| `pdf` | Bright Data | Bright Data returned the raw PDF file instead of text (D39); Jina and Firecrawl read PDFs | yes |
| `brd_unlocker` | Bright Data | Unlocker error without a readable code | yes |
| `target_<status>` | Jina, Bright Data, Firecrawl | The service reached the site, the site answered with this status (404/410 included since 0.3.1, D36) | yes |
| `failed` | Tavily (only if enabled) | Tavily listed the URL in `failed_results`; its text is in the error the model sees | yes |
| `no_result` | Tavily (only if enabled) | Tavily's reply named no result | yes |
| `http_<status>` | Keenable | Keenable could not provide the page; the error text carries its message, e.g. *The page is behind a login or paywall* (`Unprocessable entity`), *The target page took too long to respond* (`Gateway timeout`), *The target server denied access to this URL* (`Upstream forbidden`). `http_402` pauses Keenable (K7) | last stage |
| `malformed` | any | The API answered 2xx with something that is no JSON object, or with an empty one | yes |
| `timeout` | any | The stage's deadline (A0), an httpx timeout or the provider's own timeout | yes |
| `ConnectError`, `ProxyError`, … | any | Network: DNS, firewall, proxy refused the connection, TLS | yes |
| `exception` | any | Unexpected error inside the stage (bug); details in the error text | yes |
| `no_key` | any | Key not set; for Bright Data also a missing zone (`Bright Data: no zone`) | stage skipped |
| `no_time` | any | Less than 10 s of the URL's budget left (Z1); for Keenable: its copy was not ready in the time left | stage skipped |
| `paused` | any | The provider's API reported a used-up quota earlier; no request until the pause ends (K7) | stage skipped |
| `interrupted` | any | The user stopped the turn (S8); for Keenable only when its copy had not arrived yet | stage skipped |

**Keenable only, when the URL ended before its turn (K3):**

| Code | Meaning |
|---|---|
| `ref_<outcome>` | Its reference copy had arrived; the outcome is its class or error code, e.g. `ref_ok`, `ref_http_422` |
| `pending` | Its request was still running and was cancelled |

## Typical problems

**Every call fails with "no registered web extract provider has that name".**
The plugin is not loaded. Check, in this order:

1. `extract-chain` is listed under `plugins.enabled` in the profile's `config.yaml`. User plugins are opt-in.
2. The directory `plugins/extract-chain/` contains `plugin.yaml` and `__init__.py`, not a nested `extract_chain/` folder.
3. `hermes plugins list` and `errors.log` show the reason: an import error or a Hermes version below 0.21.
4. Hermes or the gateway was restarted after installing.

**`brightdata=no_key` although the key is set.**
`BRIGHTDATA_UNLOCKER_ZONE` is missing; the error the model sees says `Bright Data: no zone`. Put the name of your Web Unlocker zone into the profile's `.env`. A zone name that Bright Data does not know gives `api_400` (*zone … not found*) instead, a disabled zone `brd_client_10002` and a pause.

**`…=api_401` on every URL.**
The key is wrong or missing in the profile's `.env`. Hermes reads keys per profile; a key exported in the shell may not reach a gateway or a container. While this lasts, every URL goes on to the next stage and costs its quota.

**`jina=api_429`.**
Jina's limit without a key is 20 requests per minute, counted per IP. Several agents behind one address share it. Set `JINA_API_KEY`; no pause is started, the chain goes on to Bright Data (Jina is the first stage by default, so a 429 shows up often when several agents share one address).

**`brightdata=brd_proxy_error` on government or other public-sector sites.**
Without KYC, Bright Data refuses government sites and some other categories, and honours robots.txt. Expected; the other stages fetch these pages (D33).

**`…=no_time`.**
The URL's budget (Z1) was used up, mostly by a slow Bright Data request (up to 90 s) after a failed Jina request, and further stages. The fallback (K8) then returns what was kept. If it happens often, check `web.extract_timeout`: with less than 180 the budget is smaller than 170 s.

**`Extract timed out after <n>s via extract-chain`, or the warning `web.extract_timeout is <n> s; 180 s are recommended`.**
`web.extract_timeout` is too small for the chain. Set it to 180 (I2). The plugin keeps each URL 10 s below the setting, but Hermes discards the whole call when the setting is reached.

**`…=paused` although the credits are back.**
A pause does not notice a top-up. It ends after 24 hours (K7); to use the stage at once, restart Hermes or the gateway. `errors.log` shows when a pause began: `extract-chain: Firecrawl paused for 86400 s (api_402)`.

**Warning `EXTRACT_CHAIN_ORDER has unknown or repeated names`.**
A name in the list is misspelt or repeated. The warning names the order used. Valid names: `jina`, `brightdata`, `firecrawl`, `tavily`, `keenable`. Tavily is not in the default order; it runs only if you name it.

**`keenable=http_401` / `http_403`.**
The Keenable key is invalid or disabled. Without a reference copy, check C5 is off, consent walls stay unresolved and come back with the note *Consent wall detected …*.

**All stages fail with `ConnectError` or `ProxyError`.**
The host cannot reach the APIs. Allow HTTPS to `r.jina.ai`, `api.brightdata.com`, `api.firecrawl.dev` and `api.keenable.ai`, and to `api.tavily.com` if Tavily is in your order (I4).

- The plugin honours `HTTPS_PROXY` and `NO_PROXY`.
- `ProxyError` means the proxy refused the connection, typically a missing allowlist entry.

**TLS errors (`ConnectError` mentioning certificates).**
Hermes trusts the operating system's certificate store and installs this process-wide at start-up; the plugin inherits it. Behind TLS inspection, install the inspecting CA in the OS store of the host or container, or point `SSL_CERT_FILE` at a bundle that contains it.

**Failed URLs come back with content but without any note.**
The keyless rescue is on. When every URL of a call fails, Hermes silently retries with anonymous providers. Set `web.keyless_rescue: false`.

**A normal article gets a paywall or consent-wall note.**
A false alarm of the keyword rules, e.g. in an article *about* paywalls or cookie banners. Nothing to configure. Please report the URL.

- A false wall sends the URL to the next stage.
- A false paywall only adds the note; the text is complete.

**Many URLs go past the first stage (`suspect_shorter`).**
Check C5 fires when Keenable's copy is much longer, also on complete pages where the copy carries more around the article. It costs a request, not a result (D29).

**The same wrong or stale result keeps coming back.**
Hermes caches successful results, notes included, for `web.cache_ttl_minutes` (default 20). This includes a consent page returned with the wall note. Jina and Firecrawl may also serve copies up to an hour old (A7, D7). Wait, or lower the TTL.

**Every URL fails with `Blocked by website policy: extract-chain cannot load Hermes' website blocklist …`.**
A Hermes update moved the policy module, and the plugin fetches nothing without the blocklist (S7). `errors.log` shows `extract-chain: tools.website_policy not importable; every URL refused` for each call. Update the plugin; until then, set `web.extract_backend` to another provider.

**Credits drain faster than expected.**
Jina and Keenable are asked for every URL (default order); the later stages only when earlier ones fail or are suspect. Common causes for Firecrawl:

- sites that block Jina and Bright Data;
- PDFs, which cost 1 credit per page (capped at 30, A2);
- target 403/404 pages, which Firecrawl bills when it returns a document.

The counts per stage in the log show which sites cause it.

## Edge cases (behaviour by design)

| Situation | Behaviour |
|---|---|
| Duplicate URLs in one call | Fetched once, returned at every position as an entry of its own (S5). |
| Redirect | Jina, Bright Data and Tavily (if enabled) follow redirects themselves and report no final URL: no note, and the blocklist sees only the input URL. Firecrawl and Keenable report the final URL: note V10 where it points to another page, and the blocklist is checked on it (S7). |
| Redirect to a blocked site | The result is replaced by Hermes' policy block entry (S7). |
| Website blocklist | Checked before any request; blocked URLs reach no provider. |
| Consent wall everywhere | The first consent page comes back with the wall note listing all reasons, unless a suspect result was kept (K8). Hermes caches it like any success. |
| Page gone (404/410) | An error like any other: the chain asks the remaining stages, Keenable included, and a copy comes back with the copy note, whose reasons name the 404s (D36). |
| Firecrawl returns an empty `<body></body>` | Treated as empty; moves on. |
| Long PDF via Firecrawl | Firecrawl reads the first 30 pages; the note says *PDF cut to the first 30 of N pages*. Jina, Bright Data and Tavily (if enabled) read PDFs without a cap. |
| Page that loads with status 200 but shows "Access denied" or a challenge text | Recognised as a bot-check page if it is shorter than 1,500 visible characters and contains a phrase of the list (E7), or as suspect below 3,000 characters (C3); the chain moves on. If no stage has the page, it comes back with the note V11. |
| URL with a fragment (`#…`) | Jina does not receive the fragment; pages that route by fragment may come back as the start page. |
| No key at all | The provider reports itself unavailable, and Hermes hides `web_extract` unless another web backend is available. Jina alone does not make it available (S2). |
| Missing key of one stage | That stage is skipped (`no_key`). |
| User stops the turn | No further requests; remaining stages report `interrupted`, and a wait for Keenable ends within a second. A Keenable copy that has already arrived is still used (S8). |
| Hermes timeout | All URLs of the call fail, also those that had finished (Hermes discards the whole call). |

Paywalls (detected or not, English ones), the Hermes cache and privacy: [design.md, section 13](design.md#13-known-limitations).

## Cost and quota safety

Free allowances, billing and hard caps: [README, Costs and quotas](../README.md#costs-and-quotas). An exhausted quota pauses that stage for 24 hours (K7); the chain continues with the others.

## Reporting a problem

Include:

- the L1 log line(s);
- the error or note the model saw;
- the Hermes version and the plugin version (`plugin.yaml`);
- the URL, if it can be shared.

Never include API keys or `.env` contents.
