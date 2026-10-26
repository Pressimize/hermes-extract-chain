"""V16: link addresses and images in the returned text (design section 7, D40-D42).

Only the text the chain returns is shaped; classification and checks see the provider's text (D41).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

LINK_TEXT_MIN = 4  # V16a, V16b: shorter link texts get no address (D42)
PLACE_SECONDS = 1.0  # V16a: time for placing the addresses of one page (D42)
LINK_TEXT_MAX = 200  # V16a: link text cut to this length
LINKS_MAX = 500  # V16a: at most this many links are placed (D42)

_BAD_URL = re.compile(r"[\s<>]")
_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")  # V16b: a backslash before ASCII punctuation
_FENCE = re.compile(r"[ \t]*```")

# V16b, D42: bounded parts keep the work linear on pages of several megabytes.
_TEXT = r"((?:\\.|[^\[\]\\]){0,500})"  # link or alt text: escapes, no unescaped "[" (each search ends there, D42)
_URL = r"(https?://(?:[^()\s<>]|\([^()\s<>]{0,200}\)){1,2000})"  # one level of balanced parentheses
_SRC = r"(?:[^()\s]|\([^()\s]{0,200}\)){0,20000}"
_TITLE = r"""(?:\s{1,20}(?:"[^"]{0,300}"|'[^']{0,300}'))?\s{0,20}"""
_IMAGE = re.compile(r"!\[" + _TEXT + r"\]\(" + _SRC + _TITLE + r"\)")
_LINK = re.compile(r"\[" + _TEXT + r"\]\(" + _URL + _TITLE + r"\)")


def clean_links(links: object, url: str) -> list[tuple[str, str]]:
    """V16a: the links that may get an address, in list order: text of 4 or more characters, an http(s) URL without
    whitespace, "<" or ">", not the requested URL, no URL twice; text cut to 200 characters; at most 500."""
    kept: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in links if isinstance(links, list) else ():
        if not (isinstance(item, list | tuple) and len(item) == 2 and all(isinstance(v, str) for v in item)):
            continue
        text, href = " ".join(item[0].split()), item[1]
        if len(text) < LINK_TEXT_MIN or not href.startswith(("http://", "https://")) or _BAD_URL.search(href):
            continue
        if href == url or href in seen:
            continue
        seen.add(href)
        kept.append((text[:LINK_TEXT_MAX], href))
        if len(kept) == LINKS_MAX:
            break
    return kept


def insert_links(
    text: str, links: list[tuple[str, str]], start: int = 0, clock: Callable[[], float] = time.monotonic
) -> str:
    """V16a: put " <url>" after each link text found in text[start:]. Candidates: the whole link text, its first five
    words, its first three words (each of 4 or more characters); any or no whitespace between the words; searched
    from the previous insertion, then from start; an end position gets one address only. After PLACE_SECONDS the
    remaining links get no address (D42)."""
    placed: dict[int, str] = {}
    pos = start
    stop_at = clock() + PLACE_SECONDS
    for link_text, url in links:
        if clock() > stop_at:
            break
        words = link_text.split()
        for candidate in dict.fromkeys((" ".join(words), " ".join(words[:5]), " ".join(words[:3]))):  # no repeats
            if len(candidate) < LINK_TEXT_MIN:
                continue
            pattern = re.compile(r"\s*".join(re.escape(w) for w in candidate.split()))
            starts = (pos, start) if pos > start else (start,)  # the second pass only when it covers more text
            found = next((m for s in starts for m in pattern.finditer(text, s) if m.end() not in placed), None)
            if found:
                placed[found.end()] = url
                pos = found.end()
                break
    parts, last = [], 0
    for end in sorted(placed):
        parts += [text[last:end], f" <{placed[end]}>"]
        last = end
    parts.append(text[last:])
    return "".join(parts)


def _link(match: re.Match[str]) -> str:
    text = " ".join(_ESCAPE.sub(r"\1", match.group(1)).split())
    return f"{text} <{match.group(2)}>" if len(text) >= LINK_TEXT_MIN else text


def _rewrite(text: str) -> str:
    return _LINK.sub(_link, _IMAGE.sub("", text))


def without_addresses(text: str) -> str:
    """C5, D43: the text without image references and with links reduced to their text (no fences, no bounds
    beyond V16b's patterns); used only to compare lengths."""
    return _LINK.sub(lambda m: m.group(1), _IMAGE.sub("", text))


def markdown(text: str) -> str:
    """V16b: outside fenced code blocks, images removed and inline links as "text <url>". A block runs from a line
    starting with three backticks (after spaces or tabs) to the next such line, or to the end of the text."""
    out: list[str] = []
    outside: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            if not fenced:
                out.append(_rewrite("\n".join(outside)) if outside else None)
                outside = []
            fenced = not fenced
            out.append(line)
        elif fenced:
            out.append(line)
        else:
            outside.append(line)
    if outside or not out:
        out.append(_rewrite("\n".join(outside)))
    return "\n".join(part for part in out if part is not None)


def shape(url: str, doc: dict) -> str:
    """V16: the text of a returned result. A result with a link list (Jina) gets the addresses after the link texts,
    any other result is treated as Markdown. Never raises: on an unexpected failure the text stays as it is."""
    content = doc.get("content") or ""
    try:
        if "links" in doc:
            at = doc.get("text_at")
            at = at if isinstance(at, int) and not isinstance(at, bool) and 0 <= at <= len(content) else 0
            return insert_links(content, clean_links(doc["links"], url), at)
        return markdown(content)
    except Exception:
        return content
