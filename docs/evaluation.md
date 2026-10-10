# Evaluation: how the providers were chosen

The chain TinyFish → Firecrawl → Keenable is the result of three tests run on 2026-10-09 with Hermes Agent 0.21.6:

1. **Extraction test**: six providers, 15 pages, a question per page answered by three LLMs. It shows which providers deliver correct and current content.
2. **Chain test**: the same six providers on 23 German news articles, without an LLM. It shows who gets past consent walls and paywalls, and what a chain can reach.
3. **Live check of the plugin**: 54 URLs through Hermes' real `web_extract` path, in [validation.md](validation.md).

The URL lists and per-URL results are in [`data/`](../data); article texts are not published.

## Test 1 – Extraction test with questions

**Setup**

- Hermes Desktop 0.21.6, one throwaway profile per provider, extraction pinned to that provider, keyless fallback and rescue off, `web.extract_char_limit` 30,000.
- Providers:
  - **TinyFish** via TinyFish's own Hermes plugin (v0.2.1);
  - **Tavily, Exa, Parallel, Firecrawl, Keenable** via Hermes' built-in providers, all with API keys.
- **Cases:** 15 URLs, each with a question and an answer verified beforehand ([cases](../data/extraction-test/cases.csv)).
  - Kinds: a JavaScript page, an AJAX shop, a PDF, a table, a long page, freshness, anti-bot, a consent wall.
  - Four traps: a login page, HTTP 403, HTTP 404, an empty page.
  - Each of three models answered five URLs: GLM 5.3, Mistral Large 4, DeepSeek V4.1 Flash.
- **Runs:**
  - **Run 1:** only the `web` toolset; on long pages the model sees head and tail (30,000 characters).
  - **Run 2:** additionally `file` and `terminal` (sandboxed), so the model can search the full text that Hermes stores.
  - Two repetitions per cell; all 360 answers rated by hand.

**Result** (run 2; run 1 in parentheses where different)

✓ correct · ○ failure reported openly (error, empty, "not on the page") · ✗ wrong without any notice · – no answer (turn limit)

| Case (model) | TinyFish | Tavily | Exa | Parallel | Firecrawl | Keenable |
|---|---|---|---|---|---|---|
| JavaScript page, Brave pricing (GLM) | ✓ | ✓ | ○ empty scaffold | ○ empty scaffold | ✓ | ✓ |
| PDF, table in the middle (GLM) | ✓ | ✓ | ✓ | ✓ (○ cut) | ✓ (○ cut) | ✓ |
| HTML table, PostgreSQL versions (GLM) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Long page, fact in the middle (Large 4) | ✓ (–/○) | ✓ (○) | ✓ (○) | ✓ (○) | ✓ (○) | ○/– own 50,000-char cut |
| Documentation with navigation (Large 4) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Freshness: Hacker News front page (Large 4) | ✓ | ✗ old copy | ✗ old copy | ✓ | ✓ | ✓ |
| Freshness: GitHub release list (DeepSeek) | ✓ | ✗ previous release | ✓ | ✓ | ✓ | ✗ previous release |
| JavaScript shop, data via AJAX (DeepSeek) | ✓ | ○ error | ○ JS notice | ○ JS notice | ✓ | ○ JS notice |
| Anti-bot: Cloudflare challenge (Large 4) | ○ `bot_blocked` | ○ error | ○ error | ✓ | ✓ | ○ forbidden |
| Anti-bot: Stack Overflow (DeepSeek) | ✓ | ✓ | ✓ | ✗ old title | ✓ | ✓ |
| Consent wall: Golem (DeepSeek) | ○ consent page | ○ consent page | ✓ | ✓ | ○ consent page | ✓ |
| Traps: login, 403, 404, empty page | ○ | ○ | ○ | ○ | ○ | ○ |
| **Correct of 22 (run 1 → run 2)** | 16 → **18** | 10 → 12 | 12 → 14 | 12 → 16 | 16 → **20** | 14 → 14 |
| **Wrong without notice** | **0** | 4 | 2 | 2 | **0** | 2 |

The 22 are the 11 answerable cases times two repetitions. On the four traps, every provider and model reported "no content" correctly in both runs.

**Failure patterns**

- **TinyFish:** reads JavaScript and AJAX pages; current in both freshness cases.
  - Error code per URL: `login_required`, `page_not_found`, `bot_blocked`, `target_unreachable` for 403 and the empty page.
  - Fails on the Cloudflare challenge and the Golem consent page, and reports both.
  - No wrong result.
  - In a later run over 626 URLs it returned `bot_blocked` for all 34 pages of the Stack Exchange network.
- **Firecrawl:** reads JavaScript, AJAX and the Cloudflare challenge; current in both freshness cases.
  - Fails on the Golem consent page.
  - Returns 403/404 pages as empty content without an error field.
  - Longest texts (whole pages).
  - No wrong result.
- **Keenable:** reads the JavaScript page, not the AJAX shop.
  - **Outdated copy without notice** (GitHub releases).
  - Cuts pages at 50,000 characters.
  - Distinct error texts (forbidden, not found, unprocessable).
- **Tavily:** reads the JavaScript page, not the AJAX shop. **Outdated copies without notice** (Hacker News, GitHub releases).
- **Exa:** empty scaffold on JavaScript pages; **outdated Hacker News copy**; reads Golem behind the consent wall.
  - Failed URLs are simply missing from the result; Hermes then reports *Content was inaccessible or not found*.
- **Parallel:** empty scaffold on JavaScript pages; passes the Cloudflare challenge; reads Golem; **old Stack Overflow title**.

The most dangerous failure is the outdated copy: the model cannot recognise it and presents it as current. It occurred at Tavily, Exa, Parallel and Keenable. TinyFish and Firecrawl, which fetch live, never returned one.

**Speed** (run 1, duration of `web_extract`)

| | TinyFish | Tavily | Exa | Parallel | Firecrawl | Keenable |
|---|---|---|---|---|---|---|
| Median, all 15 cases | 2.4 s | 0.6 s | 0.5 s | 0.9 s | 1.2 s | 0.5 s |
| Median, successful fetches | 1.9 s | 0.6 s | 0.5 s | 0.8 s | 1.5 s | 0.5 s |
| Slowest fetch | 7.1 s (login) | 9.1 s (long page) | 10.4 s (403) | 25.9 s (AJAX shop) | 9.4 s (anti-bot) | 16.1 s (anti-bot) |

Index-based providers answer in 0.5–0.9 s; these were also the ones with outdated content. The live fetchers need 1–6 s. In context: the models took 3.6–4.7 s (median) just to make the tool call.

## Test 2 – Chain test: consent walls and paywalls

**Setup**

- 23 articles from 14 German-language news publishers, published 8–9 October 2026 ([articles](../data/chain-test/articles.csv)):
  - 14 free, 8 paywalled (evidence per article), 1 live blog (not rated);
  - among them 3 from a news site with a metered "plus" subscription (URLs and titles withheld in the data).
- Each provider fetched each URL once, at most 8 requests per minute per provider, without an LLM.
- **Rating:**
  - free articles: complete if the article's closing sentence (chosen by hand) is in the text;
  - paywalled articles: whether any article text beyond the teaser came back.
- Per-provider results: [results](../data/chain-test/results.csv).

✓ complete · T teaser · W consent wall · E error · empty = empty HTML · old = earlier version of the article

| Article(s) | TinyFish | Firecrawl | Keenable | Parallel | Exa | Tavily | **Chain** |
|---|---|---|---|---|---|---|---|
| Golem (2 free) | W | W | ✓ | ✓ | ✓ | W | ✓ via Keenable |
| derStandard | T + wall text at the end | W | ✓ | ✓ | ✓ | W | ✓ via Keenable |
| Spiegel, SZ | ✓ | ✓ | ✓ | only the first 600 chars, no error | ✓ | ✓ | ✓ |
| FAZ | ✓ | ✓ | E | only the first 600 chars, no error | ✓ | ✓ | ✓ |
| heise, t-online, netzpolitik | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| tagesschau | ✓ | ✓ | ✓ | ✓ | last paragraph missing | ✓ | ✓ |
| n-tv | ✓ | ✓ | old | old | old | ✓ | ✓ |
| stern | E `bot_blocked` | ✓ | E | E | missing | E | ✓ via Firecrawl |
| Metered news site (free) | E `target_http_error` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ via Firecrawl |
| Zeit | E | empty | E | E | missing | E | error with all reasons |
| **Free articles complete (of 14)** | **8** | **10** | **10** (+1 old) | **8** (+1 old) | **10** (+1 old) | **9** | **13** |
| **Paywalled: text beyond the teaser (of 8)** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

**Findings**

- **Consent walls:** Keenable, Exa and Parallel get past them, because they serve stored copies. The two live fetchers and Tavily do not.
- **Paywalls:** no provider gets past any of them. The chain can only label them.
  - Paywall note on SPIEGEL+ and heise+, and on one of the two plus articles of the metered news site; the other comes back with the consent-wall note and Keenable's paywall message.
  - FAZ+, WELTplus, SZ Plus and Golem+ teasers carry no marker and pass unlabelled.
- **All six providers together** reach 13 of 14 free articles; no provider got zeit.de. The chain TinyFish → Firecrawl → Keenable already reaches this maximum, so another last stage would add nothing.
- **Calls in chain mode** (replay with the plugin's rules): Firecrawl was needed for 4 of 23 URLs, Keenable for 6.
- **The classification rules were tuned on these 23 articles,** so this result is optimistic. The live check on new articles ([validation.md](validation.md)) is the independent test.

## Test 3 – Live check of the plugin

54 URLs through Hermes' real `web_extract` path:

- 23 chain-test articles;
- 28 new articles from 15 publishers;
- Stack Overflow, a 404 page and Python documentation.

Results: 29 of 30 free articles complete (TinyFish alone: 20), no false paywall or wall note, longest call 19.9 s. Details and per-URL table: [validation.md](validation.md), data: [live-check results](../data/live-check/results.csv).

## Free tiers and costs (vendor pages, 2026-10-09)

| Provider | Free tier | Extraction cost | Free tier covers about |
|---|---|---|---|
| TinyFish | Fetch free up to 1,000 URLs/day and 150 URLs/min; failed URLs not counted | 0 | 1,000 pages/day |
| Keenable | 100,000 requests/month (search and fetch combined) | 1 credit per fetch | 100,000 pages/month |
| Firecrawl | 1,000 credits/month, 10 scrapes/min | 1 credit per page (also from cache), 1 per PDF page | under 1,000 pages/month |
| Exa | $10/month | $1 per 1,000 pages and content type | 10,000 pages/month, shared with search |
| Tavily | 1,000 credits/month | 1 credit per 5 successful URLs (basic) | 5,000 pages/month, shared with search |
| Parallel | 5,000 requests and $5 credit per month | $1 per 1,000 URLs | up to 5,000 pages/month, shared with search |

## Decision

**TinyFish first.**

- Free for 1,000 URLs a day, live and current, and returns the main content, which keeps notes and token use small.
- It never returned wrong content.
- Its per-URL error codes tell whether another provider can help: `bot_blocked` yes, `page_not_found` no.
- Weak spots are bot protection (Cloudflare challenge, stern.de, the Stack Exchange network) and consent walls.

**Firecrawl second.**

- Live and current; it passes most of the bot protection that stops TinyFish (Cloudflare challenge, stern.de, the metered news site, Stack Overflow).
- It never returned wrong content.
- It costs one credit per page and returns whole pages, so it is only a fallback.
- It fails on the same consent walls as TinyFish, which is why the chain skips it when TinyFish hits a wall.

**Keenable last.**

- Index copies get past consent walls; Keenable has the largest free tier (100,000 requests/month).
- It reports paywalls explicitly (*The page is behind a login or paywall*).
- Its copies can be outdated (GitHub releases, n-tv), so it is the last resort, and its results always carry the note *it may be older than the live page*.

**Not used:**

- **Exa:** solves consent walls like Keenable, but bills per page, drops failed URLs silently, returned empty scaffolds for JavaScript pages and an outdated copy.
- **Parallel:** cut three news sites to the first 600 characters without an error, returned empty scaffolds for JavaScript pages and an old Stack Overflow title; bills per URL.
- **Tavily:** returned outdated copies and fails on consent walls.

**Why the providers are fixed.** The rules depend on these roles:

- the final error codes are TinyFish's;
- the paywall check skips the footer of Firecrawl's whole pages;
- a consent wall skips Firecrawl;
- only Keenable results carry the "may be older" note.

Swapping a provider would need an adapter that declares its role, plus a re-validation of the rules (README, FAQ).

## Limits of this evaluation

- One fetch per provider and URL, at one point in time, from one location. Bot-protection outcomes and cache ages depend on IP and time; for example, TinyFish read Stack Overflow in test 1 and was blocked on it two hours later.
- German news sites dominate tests 2 and 3; the paywall and consent markers are German plus common English consent phrases.
- Test 1 has 15 URLs and no clean model comparison, since each model had its own URLs. Ratings were made by hand.
- The chain rules were tuned on test 2; test 3 checks them on new articles.

## Data files

| File | Content |
|---|---|
| [`data/extraction-test/cases.csv`](../data/extraction-test/cases.csv) | Test 1: URL, kind, model, question, expected answer |
| [`data/chain-test/articles.csv`](../data/chain-test/articles.csv) | Test 2: article, publisher, date, paywall status with evidence, and the plugin's result (source, notes, complete) from replaying the stored provider results |
| [`data/chain-test/results.csv`](../data/chain-test/results.csv) | Test 2: per article and provider: characters, seconds, error, class under the plugin's rules, closing sentence found |
| [`data/live-check/results.csv`](../data/live-check/results.csv) | Test 3: URL, paywall status with evidence, the plugin's path (log line), characters, seconds, assessment |
