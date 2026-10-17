"""Classification, fallback chain and notes (design sections 5-7 and 11)."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

Fetch = Callable[[], Awaitable[dict]]

EMPTY_BELOW = 20  # E2: visible characters once HTML tags are removed
CHALLENGE_BELOW = 1500  # E7: bot-check markers count only in texts shorter than this (visible characters)
THIN_BELOW = 500  # E8: visible characters; a shorter text asks for a second opinion
WALL_WINDOW = 2000  # E3: start of longer texts
WHOLE_BELOW = 4000  # E3/E4: shorter texts are checked completely
FULL_PAGE_PAYWALL_SHARE = 0.75  # E4: full pages (Firecrawl) end with footer and subscription dialogs
FINAL_TINYFISH_CODES = frozenset(
    {"page_not_found", "login_required", "invalid_url", "invalid_redirect_url", "content_too_large"}
)

# E6: marker lists from the chain test prototype (2026-10-09).
WALL = [
    "cookies zustimmen", "cookie-zustimmung", "(?<!cookie-)zustimmung", "einwilligung", "privacy center",
    r"pur[- ]abo", "contentpass", r"werb(ung|e-) und tracking", "mit werbung", "werbefrei", "consent",
    "alle akzeptieren", "akzeptieren und weiter", "zustimmen und weiter", "accept all", "accept cookies",
    "we value your privacy", "datenschutzeinstellungen", "cookie-einstellungen", "cookie settings", "adblock",
]  # fmt: skip
PAYWALL_DEFINITE = [
    "das war die leseprobe", "um den gesamten artikel", "bezahlschranke", "mehrfachnutzung erkannt",
    "nur f(ue|ü)r abonnenten", r"registrieren und weiterlesen", "behind a login or paywall",
]  # fmt: skip
PAYWALL = [
    "jetzt weiterlesen", "weiterlesen mit", "abo abschlie(ss|ß)en", r"plus-(artikel|inhalt)",
    "artikel freischalten", "anmelden und weiterlesen", r"spiegel\+", r"(?<!\w)z\+", r"(?<!\w)f\+",
    "sz plus", r"heise\+", "weltplus", "paywall",
]  # fmt: skip

NOTE_FIRECRAWL = "[extract-chain] Live fetch via Firecrawl ({reason})."
NOTE_THIN_BOTH = "[extract-chain] Very short page ({n} characters); a second live fetch (Firecrawl) was short as well."
NOTE_THIN = "[extract-chain] Very short page ({n} characters)."
NOTE_THIN_ALONE = "[extract-chain] Very short page ({n} characters); no second opinion ({reason})."
NOTE_REDIRECT = "[extract-chain] The site redirected to {final}; the text below is from that page."
NOTE_CHECK = (
    "[extract-chain] This looks like a bot-check page; no other source had the page ({reasons}). "
    "The text below is what the site returned."
)
NOTE_PAYWALL = "[extract-chain] Paywall indicators found; the text is probably only the free teaser."
NOTE_KEENABLE = (
    "[extract-chain] Copy from Keenable's index; it may be older than the live page (live fetch: {reasons})."
)
NOTE_WALL = (
    "[extract-chain] Consent wall detected; no alternative source found ({reasons}). "
    "The text below is the consent page."
)
NOTE_PDF = "[extract-chain] PDF cut to the first {shown} of {total} pages (Firecrawl page cap)."
# E7: bot-check phrases from the job-board measurement (2026-10-12); apostrophes are avoided on purpose.
CHALLENGE = [
    "not a robot", "are you a robot", r"verif(y|ying) (that )?you are human", "checking your browser",
    "checking the site connection security", "automated bot check", "just a moment",
    "enable javascript and cookies to continue", "security checkpoint", "captcha",
    "click the button below to continue shopping", "a required part of this site couldn",
    "access denied", "request blocked", "unusual traffic",
]  # fmt: skip

# A tag starts with a letter, "/" or "!" and holds no "<": "a < b ... c > d" is text, and the match stays linear.
_TAGS = re.compile(r"</?[a-z!][^<>]*>", re.IGNORECASE)
_WALL_RX = [re.compile(m, re.IGNORECASE) for m in WALL]
_PAYWALL_DEFINITE_RX = [re.compile(m, re.IGNORECASE) for m in PAYWALL_DEFINITE]
_PAYWALL_RX = [re.compile(m, re.IGNORECASE) for m in PAYWALL]
_CHALLENGE_RX = [re.compile(m, re.IGNORECASE) for m in CHALLENGE]
_LOCALE = re.compile(r"[a-z]{2}(-[a-z]{2})?", re.IGNORECASE)  # V10: a path like /de/ or /en-us/
_KIND_TEXT = {"empty": "empty page", "wall": "consent wall", "challenge": "bot check page"}


def _hits(patterns: list[re.Pattern[str]], text: str) -> int:
    """Number of different markers found in text."""
    return sum(1 for p in patterns if p.search(text))


def _visible(doc: dict) -> str:
    return _TAGS.sub("", doc.get("content") or "").strip()


def classify(doc: dict, full_page: bool = False) -> str:
    """E1-E8: 'error', 'empty', 'challenge', 'wall', 'paywall', 'thin' or 'ok'. full_page: whole page (Firecrawl)."""
    if doc.get("error"):
        return "error"
    text = doc.get("content") or ""
    visible = _visible(doc)
    if len(visible) < EMPTY_BELOW:
        return "empty"
    if len(visible) < CHALLENGE_BELOW and _hits(_CHALLENGE_RX, visible):
        return "challenge"
    short = len(text) < WHOLE_BELOW
    if _hits(_WALL_RX, text if short else text[:WALL_WINDOW]) >= 2:
        return "wall"
    area = text if short or not full_page else text[: int(len(text) * FULL_PAGE_PAYWALL_SHARE)]
    if _hits(_PAYWALL_DEFINITE_RX, area) or _hits(_PAYWALL_RX, area) >= 2:
        return "paywall"
    return "thin" if len(visible) < THIN_BELOW else "ok"


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
    content = doc.get("content") or ""
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
    if kind == "thin":
        return f"{provider}: very short page ({len(_visible(doc))} characters)"
    return doc["error"] if kind == "error" else f"{provider}: {_KIND_TEXT[kind]}"


async def _call(provider: str, fetch: Fetch | None) -> dict:
    if fetch is None:
        return {"error": f"{provider}: no API key", "code": "no_key"}
    try:
        return await fetch()
    except Exception as exc:  # S6: an unexpected failure only fails this stage
        return {"error": f"{provider}: {type(exc).__name__}", "code": "exception"}


async def run_chain(url: str, tinyfish: dict, firecrawl: Fetch | None, keenable: Fetch | None) -> dict:
    """K2-K5 for one URL, starting from TinyFish's result. Returns the Hermes result entry."""
    steps: list[str] = []

    def step(name: str, doc: dict) -> str:
        kind = classify(doc, full_page=name == "firecrawl")
        steps.append(f"{name}={doc.get('code') or kind}")
        return kind

    try:
        kind = step("tinyfish", tinyfish)
        if kind == "ok":
            return _result(url, tinyfish)
        if kind == "paywall":
            return _result(url, tinyfish, NOTE_PAYWALL)
        if kind == "error" and tinyfish.get("code") in FINAL_TINYFISH_CODES:
            return failure(url, tinyfish["error"])

        reasons = [_reason("TinyFish", tinyfish, kind)]
        wall_page = tinyfish if kind == "wall" else None
        short = tinyfish if kind == "thin" else None  # E8/K2: the short page so far
        check = (tinyfish, []) if kind == "challenge" else None  # E7/V11: the bot-check page so far, with its notes
        if wall_page is None:
            page = await _call("Firecrawl", firecrawl)
            kind = step("firecrawl", page)
            if kind in ("ok", "paywall"):
                notes = [NOTE_FIRECRAWL.format(reason=reasons[0])]
                return _result(url, page, *notes, *([NOTE_PAYWALL] if kind == "paywall" else []))
            reasons.append(_reason("Firecrawl", page, kind))
            if kind == "thin":  # K3: two short live pages end the chain; Keenable is not asked (D23)
                source = NOTE_FIRECRAWL.format(reason=reasons[0])
                if short is None:
                    return _result(url, page, source, NOTE_THIN.format(n=len(_visible(page))))
                if len(_visible(page)) > len(_visible(short)):
                    return _result(url, page, source, NOTE_THIN_BOTH.format(n=len(_visible(page))))
                return _result(url, short, NOTE_THIN_BOTH.format(n=len(_visible(short))))
            if short is not None:  # K3: Firecrawl gave no page; a short live page is never dropped (D23)
                return _result(url, short, NOTE_THIN_ALONE.format(n=len(_visible(short)), reason=reasons[1]))
            if kind == "wall":
                wall_page = page
            if kind == "challenge" and check is None:
                check = (page, [NOTE_FIRECRAWL.format(reason=reasons[0])])

        page = await _call("Keenable", keenable)
        kind = step("keenable", page)
        if kind in ("ok", "paywall", "thin"):  # K4: a short index copy is still the best there is
            notes = [NOTE_KEENABLE.format(reasons="; ".join(reasons))]
            return _result(url, page, *notes, *([NOTE_PAYWALL] if kind == "paywall" else []))
        reasons.append(_reason("Keenable", page, kind))
        if wall_page is not None:
            return _result(url, wall_page, NOTE_WALL.format(reasons="; ".join(reasons)))
        if check is not None:  # V11: no stage had better; a real short page can match a marker
            return _result(url, check[0], *check[1], NOTE_CHECK.format(reasons="; ".join(reasons)))
        return failure(url, "; ".join(reasons))
    except Exception as exc:  # S6: an unexpected failure only fails this URL, not the whole call
        log.warning("extract-chain %s: chain failed: %s", _host(url), type(exc).__name__)
        return failure(url, f"extract-chain: {type(exc).__name__}")
    finally:
        log.info("extract-chain %s: %s", _host(url), " ".join(steps))
