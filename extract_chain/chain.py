"""Classification, fallback chain and notes (design sections 5-7 and 11)."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

Fetch = Callable[[], Awaitable[dict]]

EMPTY_BELOW = 20  # E2: visible characters once HTML tags are removed
WALL_WINDOW = 2000  # E3: start of longer texts
WHOLE_BELOW = 4000  # E3/E4: shorter texts are checked completely
FULL_PAGE_PAYWALL_SHARE = 0.75  # E4: full pages (Firecrawl) end with footer and subscription dialogs
FINAL_TINYFISH_CODES = frozenset(
    {"page_not_found", "login_required", "invalid_url", "invalid_redirect_url", "content_too_large"}
)

# E6: marker lists from the chain test prototype (2026-10-09).
WALL = [
    "cookies zustimmen", "cookie-zustimmung", "zustimmung", "einwilligung", "privacy center",
    r"pur[- ]abo", "contentpass", r"werb(ung|e-) und tracking", "mit werbung", "werbefrei", "consent",
    "alle akzeptieren", "akzeptieren und weiter", "zustimmen und weiter", "accept all", "accept cookies",
    "we value your privacy", "datenschutzeinstellungen", "cookie-einstellungen", "cookie settings", "adblock",
]  # fmt: skip
PAYWALL_DEFINITE = [
    "das war die leseprobe", "um den gesamten artikel", "bezahlschranke", "mehrfachnutzung erkannt",
    "nur f(ue|ü)r abonnenten", r"registrieren und weiterlesen", "behind a login or paywall",
]  # fmt: skip
PAYWALL = [
    "jetzt weiterlesen", "weiterlesen mit", "abo abschlie(ss|ß)en", "nur f(ue|ü)r abonnenten",
    r"plus-(artikel|inhalt)", r"registrieren und weiterlesen",
    "artikel freischalten", "anmelden und weiterlesen", r"spiegel\+", r"(?<!\w)z\+", r"(?<!\w)f\+",
    "sz plus", r"heise\+", "weltplus", "paywall",
]  # fmt: skip

NOTE_FIRECRAWL = "[extract-chain] Live fetch via Firecrawl ({reason})."
NOTE_PAYWALL = "[extract-chain] Paywall indicators found; the text is probably only the free teaser."
NOTE_KEENABLE = (
    "[extract-chain] Copy from Keenable's index; it may be older than the live page (live fetch: {reasons})."
)
NOTE_WALL = (
    "[extract-chain] Consent wall detected; no alternative source found ({reasons}). "
    "The text below is the consent page."
)
NOTE_PDF = "[extract-chain] PDF cut to the first {shown} of {total} pages (Firecrawl page cap)."

_TAGS = re.compile(r"<[^>]*>")
_WALL_RX = [re.compile(m, re.IGNORECASE) for m in WALL]
_PAYWALL_DEFINITE_RX = [re.compile(m, re.IGNORECASE) for m in PAYWALL_DEFINITE]
_PAYWALL_RX = [re.compile(m, re.IGNORECASE) for m in PAYWALL]
_KIND_TEXT = {"empty": "empty page", "wall": "consent wall"}


def _hits(patterns: list[re.Pattern[str]], text: str) -> int:
    """Number of different markers found in text."""
    return sum(1 for p in patterns if p.search(text))


def classify(doc: dict, full_page: bool = False) -> str:
    """E1-E5: 'error', 'empty', 'wall', 'paywall' or 'ok'. full_page: text is a whole page (Firecrawl)."""
    if doc.get("error"):
        return "error"
    text = doc.get("content") or ""
    if len(_TAGS.sub("", text).strip()) < EMPTY_BELOW:
        return "empty"
    short = len(text) < WHOLE_BELOW
    if _hits(_WALL_RX, text if short else text[:WALL_WINDOW]) >= 2:
        return "wall"
    area = text if short or not full_page else text[: int(len(text) * FULL_PAGE_PAYWALL_SHARE)]
    if _hits(_PAYWALL_DEFINITE_RX, area) or _hits(_PAYWALL_RX, area) >= 2:
        return "paywall"
    return "ok"


def _result(url: str, doc: dict, *notes: str) -> dict:
    if pages := doc.get("pdf_pages"):
        notes = (*notes, NOTE_PDF.format(shown=pages[0], total=pages[1]))
    content = doc.get("content") or ""
    if notes:
        content = "\n".join(notes) + "\n\n" + content
    metadata = {"sourceURL": url}
    if isinstance(doc.get("final_url"), str):
        metadata["finalURL"] = doc["final_url"]  # the provider re-checks the website policy on it (S7)
    return {"url": url, "title": doc.get("title") or "", "content": content, "error": None, "metadata": metadata}


def _failure(url: str, error: str) -> dict:
    return {"url": url, "title": "", "content": "", "error": error, "metadata": {"sourceURL": url}}


def _host(url: str) -> str:
    """Host for the log line; never the full URL (query strings may carry tokens) and never raises."""
    try:
        return urlsplit(url).hostname or "<no host>"
    except ValueError:
        return "<invalid url>"


def _reason(provider: str, doc: dict, kind: str) -> str:
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
            return _failure(url, tinyfish["error"])

        reasons = [_reason("TinyFish", tinyfish, kind)]
        wall_page = tinyfish if kind == "wall" else None
        if wall_page is None:
            page = await _call("Firecrawl", firecrawl)
            kind = step("firecrawl", page)
            if kind in ("ok", "paywall"):
                notes = [NOTE_FIRECRAWL.format(reason=reasons[0])]
                return _result(url, page, *notes, *([NOTE_PAYWALL] if kind == "paywall" else []))
            reasons.append(_reason("Firecrawl", page, kind))
            if kind == "wall":
                wall_page = page

        page = await _call("Keenable", keenable)
        kind = step("keenable", page)
        if kind in ("ok", "paywall"):
            notes = [NOTE_KEENABLE.format(reasons="; ".join(reasons))]
            return _result(url, page, *notes, *([NOTE_PAYWALL] if kind == "paywall" else []))
        reasons.append(_reason("Keenable", page, kind))
        if wall_page is not None:
            return _result(url, wall_page, NOTE_WALL.format(reasons="; ".join(reasons)))
        return _failure(url, "; ".join(reasons))
    finally:
        log.info("extract-chain %s: %s", _host(url), " ".join(steps))
