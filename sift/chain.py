"""Classification, checks, fallback chain and notes (design sections 5-7 and 11)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from .shape import shape, without_addresses

log = logging.getLogger(__name__)

Fetch = Callable[[float], Awaitable[dict]]  # takes the time it may use, in seconds

EMPTY_BELOW = 20  # E2: visible characters once HTML tags are removed
CHALLENGE_BELOW = 1500  # E7: bot-check markers count only in texts shorter than this (visible characters)
THIN_BELOW = 500  # E8 / N7.1: visible characters; a shorter text is a reason to ask the next stage
WALL_WINDOW = 2000  # E3: start of longer texts
WHOLE_BELOW = 4000  # E3/E4: shorter texts are checked completely
FULL_PAGE_PAYWALL_SHARE = 0.75  # E4: full pages end with footer and subscription dialogs

# N7: checks of a result that looks fine to classify(); measured in the benchmark of 2026-10-18.
PRINT_WINDOW = 5000  # N7.2: print-view markers count in the first characters only
CHECK_BELOW = 3000  # N7.3: JavaScript and bot-check hints count only in texts shorter than this
CONSENT_BELOW = 1500  # N7.4
CONSENT_MIN = 2  # N7.4: words containing a marker, not different markers
REFERENCE_FACTOR = 1.5  # N7.5: Keenable's copy at least this many times longer -> suspect
REFERENCE_WAIT = 8.0  # K3, D35: the first stage that looks fine waits at most this long for Keenable's copy
POLL = 1.0  # S8: a wait for Keenable checks the interrupt flag at least this often
SUSPECT_PRINT = ["dieser ausdruck wurde am", "ausdruck erstellt"]
SUSPECT_JS = [
    "turn on javascript", "enable javascript", r"javascript (is )?(disabled|required)", "aktivieren sie javascript",
]  # fmt: skip
SUSPECT_CHECK = [
    "just a moment", "nur einen moment", "verify you are human", "captcha", "access denied",
    "pardon our interruption", "zugriff verweigert", "sicherheitsüberprüfung", "security check",
    "checking your browser",
]  # fmt: skip
SUSPECT_CONSENT = r"[\w-]*(?:cookie|consent|zustimm|einwillig)[\w-]*"  # N7.4: a word, hyphenated ones too

# N9: time budget of one URL; a stage with less time left is skipped.
URL_BUDGET_MAX = 170.0
MIN_STAGE = 10.0
COPY_STAGES = frozenset({"tavily", "keenable"})  # N17: copies that may be older than the live page

# E6: marker lists from the chain test prototype (2026-10-09).
WALL = [
    "cookies zustimmen", "cookie-zustimmung", "(?<!cookie-)zustimmung", "einwilligung", "privacy center",
    r"pur[- ]abo", "contentpass", r"werb(ung|e-) und tracking", "mit werbung", "werbefrei", "consent",
    "alle akzeptieren", "akzeptieren und weiter", "zustimmen und weiter", "accept all", "accept cookies",
    "we value your privacy", "datenschutzeinstellungen", "cookie-einstellungen", "cookie settings", "adblock",
]  # fmt: skip
PAYWALL_DEFINITE = [
    "das war die leseprobe", "um den gesamten artikel", "mehrfachnutzung erkannt",
    "nur f(ue|ü)r abonnenten", r"registrieren und weiterlesen", "behind a login or paywall",
]  # fmt: skip
PAYWALL = [
    "jetzt weiterlesen", "weiterlesen mit", "abo abschlie(ss|ß)en", r"plus-(artikel|inhalt)",
    "artikel freischalten", "anmelden und weiterlesen", r"spiegel\+", r"(?<!\w)z\+", r"(?<!\w)f\+",
    "sz plus", r"heise\+", "weltplus", "paywall", "bezahlschranke",
]  # fmt: skip
# E7: bot-check phrases from the job-board measurement (2026-10-12); apostrophes are avoided on purpose.
CHALLENGE = [
    "not a robot", "are you a robot", r"verif(y|ying) (that )?you are human", "checking your browser",
    "checking the site connection security", "automated bot check", "just a moment",
    "enable javascript and cookies to continue", "security checkpoint", "captcha",
    "click the button below to continue shopping", "a required part of this site couldn",
    "access denied", "request blocked", "unusual traffic",
]  # fmt: skip

NOTE_LIVE = "[sift] Live fetch via {provider} ({reasons})."
NOTE_COPY = "[sift] Copy via {provider}; it may be older than the live page ({reasons})."
NOTE_LONGEST = "[sift] No source passed the checks; this is the longest result ({provider}, {n} characters; {reasons})."
NOTE_LONGEST_COPY = (
    "[sift] No source passed the checks; this is the longest result, a copy that may be older than the live "
    "page ({provider}, {n} characters; {reasons})."
)
NOTE_REDIRECT = "[sift] The site redirected to {final}; the text below is from that page."
NOTE_CHECK = (
    "[sift] This looks like a bot-check page; no other source had the page ({reasons}). "
    "The text below is what the site returned."
)
NOTE_PAYWALL = "[sift] Paywall indicators found; the text is probably only the free teaser."
NOTE_WALL = "[sift] Consent wall detected; no alternative source found ({reasons}). The text below is the consent page."
NOTE_PDF = "[sift] PDF cut to the first {shown} of {total} pages (Firecrawl page cap)."

# E2: a tag name followed by whitespace, "/" or ">", or a comment or doctype; none holds a "<". So "a < b ... c > d"
# and "i<n; ... p->next" in an article stay text, and the match stays linear.
_TAGS = re.compile(r"</?[a-z][a-z0-9-]*(?:\s[^<>]*)?/?>|<![^<>]*>", re.IGNORECASE)
_WALL_RX = [re.compile(m, re.IGNORECASE) for m in WALL]
_PAYWALL_DEFINITE_RX = [re.compile(m, re.IGNORECASE) for m in PAYWALL_DEFINITE]
_PAYWALL_RX = [re.compile(m, re.IGNORECASE) for m in PAYWALL]
_CHALLENGE_RX = [re.compile(m, re.IGNORECASE) for m in CHALLENGE]
_PRINT_RX = [re.compile(m, re.IGNORECASE) for m in SUSPECT_PRINT]
_HINT_RX = [re.compile(m, re.IGNORECASE) for m in SUSPECT_JS + SUSPECT_CHECK]
_CONSENT_RX = re.compile(SUSPECT_CONSENT, re.IGNORECASE)
_LOCALE = re.compile(r"[a-z]{2}(-[a-z]{2})?", re.IGNORECASE)  # V10: a path like /de/ or /en-us/
_KIND_TEXT = {"empty": "empty page", "wall": "consent wall", "challenge": "bot check page"}
_SUSPECT_TEXT = {
    "print": "print view",
    "check": "JavaScript or bot-check hint",
    "consent": "consent text",
    "shorter": "shorter than the reference copy",
}


@dataclass(frozen=True)
class Stage:
    """One stage of the chain. fetch is None when the stage cannot run (N3); missing then says why."""

    id: str  # brightdata, jina, firecrawl, tavily (log line, N2)
    name: str  # Bright Data, Jina, Firecrawl, Tavily (reasons and notes)
    fetch: Fetch | None
    full_page: bool = True  # E4: all live providers and Tavily return the whole page
    missing: str = "no API key"


def _hits(patterns: list[re.Pattern[str]], text: str) -> int:
    """Number of different markers found in text."""
    return sum(1 for p in patterns if p.search(text))


def _visible(doc: dict) -> str:
    return _TAGS.sub("", doc.get("content") or "").strip()


def _length(doc: dict) -> int:
    """E2: length of the visible text; for Jina from where the page text starts, without the header lines (D37)."""
    content = doc.get("content") or ""
    at = doc.get("text_at")
    if isinstance(at, int) and 0 < at <= len(content):
        content = content[at:]
    return len(_TAGS.sub("", content).strip())


def _plain_length(doc: dict) -> int:
    """C5, D43: visible length without image references and link addresses, so that Markdown and Jina's plain text
    compare fairly."""
    content = doc.get("content") or ""
    at = doc.get("text_at")
    if isinstance(at, int) and 0 < at <= len(content):
        content = content[at:]
    return len(_TAGS.sub("", without_addresses(content)).strip())


def classify(doc: dict, full_page: bool = False) -> str:
    """E1-E8: 'error', 'empty', 'challenge', 'wall', 'paywall', 'thin' or 'ok'. full_page: whole page."""
    if doc.get("error"):
        return "error"
    text = doc.get("content") or ""
    visible = _visible(doc)  # markers: the whole text; lengths: _length (D37)
    n = _length(doc)
    if n < EMPTY_BELOW:
        return "empty"
    if n < CHALLENGE_BELOW and _hits(_CHALLENGE_RX, visible):
        return "challenge"
    short = len(text) < WHOLE_BELOW
    if _hits(_WALL_RX, text if short else text[:WALL_WINDOW]) >= 2:
        return "wall"
    area = text if short or not full_page else text[: int(len(text) * FULL_PAGE_PAYWALL_SHARE)]
    if _hits(_PAYWALL_DEFINITE_RX, area) or _hits(_PAYWALL_RX, area) >= 2:
        return "paywall"
    return "thin" if n < THIN_BELOW else "ok"


def suspect(doc: dict, reference_len: int | None) -> str | None:
    """N7: why a result that classify() calls ok or thin is not taken yet, or None. The first rule that applies
    wins. reference_len: visible length of Keenable's copy, None without one (and for Keenable itself)."""
    visible = _visible(doc)  # markers: the whole text; lengths: _length (D37)
    n = _length(doc)
    if n < THIN_BELOW:
        return "thin"
    if _hits(_PRINT_RX, visible[:PRINT_WINDOW]):
        return "print"
    if n < CHECK_BELOW and _hits(_HINT_RX, visible):
        return "check"
    if n < CONSENT_BELOW and len(_CONSENT_RX.findall(visible)) >= CONSENT_MIN:
        return "consent"
    if reference_len is not None and reference_len >= REFERENCE_FACTOR * max(1, _plain_length(doc)):
        return "shorter"
    return None


def _redirect(url: str, final: object) -> bool:
    """V10: the final URL is another page than the requested one. Never raises."""
    try:
        if not isinstance(final, str):
            return False
        a, b = urlsplit(url), urlsplit(final)
        host_a, host_b = (a.hostname or "").removeprefix("www."), (b.hostname or "").removeprefix("www.")
        if not host_a or not host_b:
            return False
        if host_a != host_b:
            return True
        path_a, path_b = [p.lower() for p in a.path.split("/") if p], [p.lower() for p in b.path.split("/") if p]
        locale_root = not path_b or (len(path_b) == 1 and _LOCALE.fullmatch(path_b[0]))
        return bool(path_a and path_a != path_b and locale_root)
    except Exception:
        return False


def _result(url: str, doc: dict, *notes: str) -> dict:
    if pages := doc.get("pdf_pages"):
        notes = (*notes, NOTE_PDF.format(shown=pages[0], total=pages[1]))
    if _redirect(url, doc.get("final_url")):
        final = " ".join(doc["final_url"].split())[:200]  # one line (V1), cut to 200 characters (V10)
        notes = (*notes, NOTE_REDIRECT.format(final=final))
    content = shape(url, doc)  # V16: link addresses and images; notes are added after it (V1)
    if notes:
        content = "\n".join(notes) + "\n\n" + content
    metadata = {"sourceURL": url}
    if isinstance(doc.get("final_url"), str):
        metadata["finalURL"] = doc["final_url"]  # the provider re-checks the website policy on it (S7)
    return {"url": url, "title": doc.get("title") or "", "content": content, "error": None, "metadata": metadata}


def failure(url: str, error: str) -> dict:
    return {"url": url, "title": "", "content": "", "error": error, "metadata": {"sourceURL": url}}


def _host(url: str) -> str:
    """Host for the log line; never the full URL (query strings may carry tokens) and never raises."""
    try:
        return urlsplit(url).hostname or "<no host>"
    except Exception:  # ValueError for a malformed URL, other classes for a value that is no string
        return "<invalid url>"


def _reason(provider: str, doc: dict, kind: str) -> str:
    """Why a stage was passed over: its error, its class (E2-E8) or the check that applied (N7, N17)."""
    if kind == "thin":
        return f"{provider}: very short page ({_length(doc)} characters)"
    if kind in _SUSPECT_TEXT:
        return f"{provider}: {_SUSPECT_TEXT[kind]}"
    return doc["error"] if kind == "error" else f"{provider}: {_KIND_TEXT[kind]}"


async def _call(provider: str, fetch: Fetch, deadline: float) -> dict:
    try:
        return await fetch(deadline)
    except Exception as exc:  # S6: an unexpected failure only fails this stage
        return {"error": f"{provider}: {type(exc).__name__}", "code": "exception"}


def _source(stage_id: str, provider: str, reasons: list[str]) -> tuple[str, ...]:
    """N17: where the text comes from, when an earlier stage was passed over."""
    if not reasons:
        return ()
    note = NOTE_COPY if stage_id in COPY_STAGES else NOTE_LIVE
    return (note.format(provider=provider, reasons="; ".join(reasons)),)


async def run_chain(
    url: str,
    stages: list[Stage],
    reference: asyncio.Task | None,
    *,
    budget: float,
    clock: Callable[[], float] = time.monotonic,
    is_interrupted: Callable[[], bool] = lambda: False,
) -> dict:
    """N5-N9 for one URL. stages: the live stages and Tavily in order; reference: the running Keenable request, which
    is the reference for N7.5 and the last stage; is_interrupted: Hermes' interrupt flag (S8). Returns the Hermes
    result entry. Never raises (S6)."""
    start = clock()
    steps: list[str] = []
    reasons: list[str] = []
    kept: list[tuple[bool, int, int, str, str, dict]] = []  # (no check hint, length, -position, id, name, doc)
    wall: dict | None = None
    check: dict | None = None
    reference_len: int | None = None
    waited = False
    interrupted = False

    def left() -> float:
        return budget - (clock() - start)

    def stop() -> bool:
        try:
            return bool(is_interrupted())
        except Exception:  # S6: a failing flag check counts as no interrupt
            return False

    async def keenable_doc(wait: float) -> dict | None:
        """The Keenable result, waiting at most wait seconds and ending the wait on an interrupt (S8); None without a
        request or when it is not ready."""
        if reference is None:
            return None
        loop = asyncio.get_running_loop()
        end = loop.time() + wait
        while not reference.done():  # a copy that has arrived is used even when the flag is set (S8)
            rest = end - loop.time()
            if rest <= 0 or stop():
                break
            await asyncio.wait({reference}, timeout=min(POLL, rest))
        if not reference.done() or reference.cancelled():
            return None
        try:
            return reference.result()
        except Exception as exc:  # S6
            return {"error": f"Keenable: {type(exc).__name__}", "code": "exception"}

    try:
        for position, stage in enumerate(stages):
            if stage.fetch is None:
                doc = {"error": f"{stage.name}: {stage.missing}", "code": "no_key"}
            elif (remaining := left()) < MIN_STAGE:
                doc = {"error": f"{stage.name}: no time left", "code": "no_time"}
            else:
                doc = await _call(stage.name, stage.fetch, remaining)
            if doc.get("code") == "interrupted":  # S8, N5: skip the rest; Keenable only if its copy has arrived
                steps.append(f"{stage.id}=interrupted")
                reasons.append(doc["error"])
                interrupted = True
                break
            kind = classify(doc, full_page=stage.full_page)
            if kind == "paywall":
                steps.append(f"{stage.id}=paywall")
                return _result(url, doc, *_source(stage.id, stage.name, reasons), NOTE_PAYWALL)
            if kind in ("error", "empty", "challenge", "wall"):
                steps.append(f"{stage.id}={doc.get('code') or kind}")
                reasons.append(_reason(stage.name, doc, kind))
                if kind == "wall" and wall is None:
                    wall = doc
                if kind == "challenge" and check is None:
                    check = doc
                continue  # no error ends the chain (K4; K9 removed in 0.3.1, D36)
            if not waited:  # N9: the reference is needed now; later stages do not wait again
                waited = True
                ref = await keenable_doc(min(REFERENCE_WAIT, left()))  # K3, D35
                # only a real copy is a reference; a consent page or bot check of Keenable is none (second opinion)
                usable = ref is not None and classify(ref) in ("ok", "thin")
                reference_len = _plain_length(ref) if usable else None  # C5, D43
            rule = suspect(doc, reference_len)
            if rule is None:
                steps.append(f"{stage.id}={kind}")
                return _result(url, doc, *_source(stage.id, stage.name, reasons))
            steps.append(f"{stage.id}=suspect_{rule}")
            kept.append((rule != "check", _length(doc), -position, stage.id, stage.name, doc))
            reasons.append(_reason(stage.name, doc, rule))

        # N5: Keenable is the last stage; its request has been running since the start.
        if reference is None:
            doc = {"error": "Keenable: no API key", "code": "no_key"}
        else:  # after an interrupt only a copy that has arrived; the provider cancels the request otherwise (S8)
            doc = await keenable_doc(0 if interrupted else left())
            if doc is None and (interrupted or stop()):
                doc = {"error": "Keenable: interrupted", "code": "interrupted"}
            elif doc is None:
                doc = {"error": "Keenable: no time left", "code": "no_time"}
        kind = classify(doc)
        if kind == "paywall":
            steps.append("keenable=paywall")
            return _result(url, doc, *_source("keenable", "Keenable", reasons), NOTE_PAYWALL)
        if kind in ("ok", "thin"):
            rule = suspect(doc, None)
            if rule is None:
                steps.append(f"keenable={kind}")
                return _result(url, doc, *_source("keenable", "Keenable", reasons))
            steps.append(f"keenable=suspect_{rule}")
            kept.append((rule != "check", _length(doc), -len(stages), "keenable", "Keenable", doc))
            reasons.append(_reason("Keenable", doc, rule))
        else:  # a Keenable wall or bot-check page is never kept, as before (K4)
            steps.append(f"keenable={doc.get('code') or kind}")
            reasons.append(_reason("Keenable", doc, kind))

        # N8: no stage passed the checks
        plain = [k for k in kept if k[0]]
        if plain:
            _, n, _, sid, name, doc = max(plain, key=lambda k: (k[1], k[2]))
            note = NOTE_LONGEST_COPY if sid in COPY_STAGES else NOTE_LONGEST  # V15: a copy may be older
            return _result(url, doc, note.format(provider=name, n=n, reasons="; ".join(reasons)))
        if kept:  # only results with a bot-check or JavaScript hint
            doc = max(kept, key=lambda k: (k[1], k[2]))[5]
            return _result(url, doc, NOTE_CHECK.format(reasons="; ".join(reasons)))
        if wall is not None:
            return _result(url, wall, NOTE_WALL.format(reasons="; ".join(reasons)))
        if check is not None:
            return _result(url, check, NOTE_CHECK.format(reasons="; ".join(reasons)))
        return failure(url, "; ".join(reasons))
    except Exception as exc:  # S6: an unexpected failure only fails this URL, not the whole call
        log.warning("sift %s: chain failed: %s", _host(url), type(exc).__name__)
        return failure(url, f"sift: {type(exc).__name__}")
    finally:
        try:  # S6: the log line must never fail the URL or the call
            if not any(s.startswith("keenable=") for s in steps):  # N20: Keenable is always listed
                if reference is None:
                    steps.append("keenable=no_key")
                elif reference.done() and not reference.cancelled() and reference.exception() is None:
                    ref = reference.result()
                    steps.append(f"keenable=ref_{ref.get('code') or classify(ref)}")
                else:
                    steps.append("keenable=pending")
        except Exception:
            steps.append("keenable=exception")
        log.info("sift %s: %s", _host(url), " ".join(steps))
