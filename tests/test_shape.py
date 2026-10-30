"""V16: link addresses and images in the returned text (V16a Jina, V16b Markdown, D40-D42)."""

import time

import pytest

from sift import shape as shape_module
from sift.shape import LINK_TEXT_MAX, LINK_TEXT_MIN, LINKS_MAX, clean_links, insert_links, markdown, shape

U = "https://a.example/x"
H = "https://h.example/"
H1, H2, H3 = "https://h.example/1", "https://h.example/2", "https://h.example/3"


def pair(text, url=H):
    return [text, url]


# --- V16a clean_links: filters, in this order --------------------------------------------------------------


def test_constants():  # V16a: the bounds of D42
    assert (LINK_TEXT_MIN, LINK_TEXT_MAX, LINKS_MAX) == (4, 200, 500)


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("abc", False),  # 3 characters
        ("abcd", True),  # 4 characters
        ("a\n\t b", False),  # whitespace runs collapse to one space first: "a b" is 3 characters
        ("ab\n\t c", True),  # "ab c" is 4 characters
        ("a      b", False),
        ("", False),
    ],
)
def test_clean_links_text_length_after_collapse(text, kept):  # V16a: shorter than LINK_TEXT_MIN is dropped
    assert bool(clean_links([[text, H]], U)) is kept


def test_clean_links_collapses_whitespace_in_the_kept_text():  # V16a
    assert clean_links([["ab\n\t c", H]], U) == [("ab c", H)]


@pytest.mark.parametrize(
    ("href", "kept"),
    [
        ("http://h.example/", True),
        ("https://h.example/", True),
        ("ftp://h.example/", False),
        ("mailto:a@h.example", False),
        ("/relative/path", False),
        ("//h.example/x", False),
        ("https://h.example/a b", False),
        ("https://h.example/a\tb", False),
        ("https://h.example/a\nb", False),
        ("https://h.example/<a", False),
        ("https://h.example/a>", False),
        ("https://h.example/a?b=1&c=(2)", True),
    ],
)
def test_clean_links_url_filter(href, kept):  # V16a
    assert bool(clean_links([["Link text", href]], U)) is kept


def test_clean_links_self_link_is_an_exact_match():  # V16a: the requested URL as an exact string
    assert clean_links([["Link text", U]], U) == []
    assert clean_links([["Link text", U + "/"]], U) == [("Link text", U + "/")]
    assert clean_links([["Link text", U + "#top"]], U) == [("Link text", U + "#top")]
    assert clean_links([["Link text", "https://A.example/x"]], U) == [("Link text", "https://A.example/x")]


def test_clean_links_duplicate_url_keeps_the_first():  # V16a
    out = clean_links([["First text", H], ["Second text", H], ["Third text", H + "b"]], U)
    assert out == [("First text", H), ("Third text", H + "b")]


def test_clean_links_duplicate_only_after_a_kept_link():  # V16a: a dropped link does not block its URL
    assert clean_links([["abc", H], ["Longer text", H]], U) == [("Longer text", H)]  # the short one is dropped
    assert clean_links([["Link text", "ftp://h.example/"], ["Link text", H]], U) == [("Link text", H)]
    assert clean_links([["Link text", U], ["Other text", U]], U) == []  # self-links are dropped, never kept


@pytest.mark.parametrize(("length", "cut"), [(199, 199), (200, 200), (201, 200), (250, 200)])
def test_clean_links_text_cut_to_200(length, cut):  # V16a
    assert clean_links([["a" * length, H]], U) == [("a" * cut, H)]


@pytest.mark.parametrize(("count", "kept"), [(499, 499), (500, 500), (501, 500), (700, 500)])
def test_clean_links_at_most_500(count, kept):  # V16a, D42: the first 500 kept links
    links = [[f"Link {i:04d}", f"https://h.example/{i}"] for i in range(count)]
    assert clean_links(links, U) == [(t, u) for t, u in links[:kept]]


def test_clean_links_500_counts_kept_links_not_input():  # V16a: dropped links do not use the limit
    links = [["x", f"https://h.example/short{i}"] for i in range(100)]
    links += [[f"Link {i:04d}", f"https://h.example/{i}"] for i in range(600)]
    out = clean_links(links, U)
    assert len(out) == 500 and out[-1] == ("Link 0499", "https://h.example/499")


def test_clean_links_skips_what_is_no_pair_of_strings():  # robustness: shape must not trust the list
    items = [None, "ab", ["only one"], ["a", "b", "c"], [1, H], ["Link text", None], pair("Fine text")]
    assert clean_links(items, U) == [("Fine text", H)]
    assert clean_links(None, U) == [] and clean_links("text", U) == [] and clean_links({"a": 1}, U) == []


# --- V16a insert_links ----------------------------------------------------------------------------------


def test_insert_format_is_space_and_angle_url_right_after_the_match():  # V16a
    assert insert_links("Click Apply now please.", [("Apply now", H)]) == f"Click Apply now <{H}> please."


def test_insert_candidates_whole_text_first():  # V16a
    text = "see Apply now and Apply now please later"
    assert insert_links(text, [("Apply now please", H)]) == f"see Apply now and Apply now please <{H}> later"


def test_insert_candidate_first_five_words():  # V16a
    out = insert_links("xx one two three four five seven", [("one two three four five six", H)])
    assert out == f"xx one two three four five <{H}> seven"


def test_insert_candidate_first_three_words():  # V16a
    out = insert_links("xx alpha beta gamma only", [("alpha beta gamma delta epsilon zeta", H)])
    assert out == f"xx alpha beta gamma <{H}> only"


def test_insert_longer_candidate_wins_over_shorter_one():  # V16a: the first candidate found wins
    text = "alpha beta gamma only. alpha beta gamma delta epsilon zeta."
    out = insert_links(text, [("alpha beta gamma delta epsilon zeta", H)])
    assert out == f"alpha beta gamma only. alpha beta gamma delta epsilon zeta <{H}>."  # not the early 3 words
    text = "alpha beta gamma only. alpha beta gamma delta epsilon."
    out = insert_links(text, [("alpha beta gamma delta epsilon zeta", H)])
    assert out == f"alpha beta gamma only. alpha beta gamma delta epsilon <{H}>."  # the 5 words, not the 3


def test_insert_candidate_shorter_than_4_is_not_searched():  # V16a: also directly, without clean_links
    assert insert_links("a b c", [("a b", H)]) == "a b c"
    assert insert_links("abc abcd", [("abc", H)]) == "abc abcd"
    assert insert_links("abc abcd", [("abcd", H)]) == f"abc abcd <{H}>"


def test_insert_a_candidate_equal_to_an_earlier_one_is_searched_once():  # V16a: three words are one candidate
    out = insert_links("Apply now today and Apply now today", [("Apply now today", H)])
    assert out == f"Apply now today <{H}> and Apply now today"


@pytest.mark.parametrize("page", ["Jetzt bewerben", "Jetztbewerben", "Jetzt\n  bewerben", "Jetzt\u00a0bewerben"])
def test_insert_any_whitespace_or_none_between_words(page):  # V16a: Jina joins the words of adjacent elements
    assert insert_links(f"x {page} y", [("Jetzt bewerben", H)]) == f"x {page} <{H}> y"


def test_insert_is_case_sensitive():  # V16a
    assert insert_links("Apply Now", [("apply now", H)]) == "Apply Now"
    assert insert_links("apply now", [("apply now", H)]) == f"apply now <{H}>"


def test_insert_search_starts_after_the_previous_insertion():  # V16a
    text = "beta text. alpha text. beta text."
    out = insert_links(text, [("alpha text", H1), ("beta text", H2)])
    assert out == f"beta text. alpha text <{H1}>. beta text <{H2}>."


def test_insert_falls_back_to_the_start():  # V16a: not found after the previous insertion: search from text_at
    out = insert_links("alpha text. beta text.", [("beta text", H2), ("alpha text", H1)])
    assert out == f"alpha text <{H1}>. beta text <{H2}>."


def test_insert_fallback_starts_at_text_at_not_at_zero():  # V16a, A7
    text = "Title: alpha text\n\nbeta text, alpha text."
    out = insert_links(text, [("beta text", H2), ("alpha text", H1)], text.index("beta"))
    assert out == f"Title: alpha text\n\nbeta text <{H2}>, alpha text <{H1}>."


def test_insert_a_used_match_end_goes_on_to_the_next_occurrence():  # V16a
    text = "Read more x Read more. Later text here."
    out = insert_links(text, [("Read more", H1), ("Later text here", H2), ("Read more", H3)])
    # link 3 is not found after "here"; from the start, the first "Read more" has its address, so the second gets it
    assert out == f"Read more <{H1}> x Read more <{H3}>. Later text here <{H2}>."


def test_insert_a_used_match_end_with_no_occurrence_left_gives_no_address():  # V16a
    text = "Read more. Later text here."
    out = insert_links(text, [("Later text here", H2), ("Read more", H1), ("Read more", H3)])
    assert out == f"Read more <{H1}>. Later text here <{H2}>."


def test_insert_never_searches_the_title_line():  # V16a, A7
    content = "Title: Apply now\n\nBody text only."
    assert insert_links(content, [("Apply now", H)], content.index("Body")) == content
    content = "Title: Apply now\n\nBody: Apply now here."
    out = insert_links(content, [("Apply now", H)], content.index("Body"))
    assert out == f"Title: Apply now\n\nBody: Apply now <{H}> here."


def test_insert_empty_page_text_stays_empty():  # V16a
    assert insert_links("", [("Apply now", H)]) == ""
    head = "Title: Apply now\n\n"
    assert insert_links(head, [("Apply now", H)], len(head)) == head


def test_insert_link_not_found_gets_no_address():  # V16a
    assert insert_links("Nothing here at all.", [("Apply now", H)]) == "Nothing here at all."


def test_insert_without_links_returns_the_text():  # V16a
    assert insert_links("Some text", []) == "Some text"


# --- shape(): V16a or V16b ----------------------------------------------------------------------------------

LINKED = "[Apply now](https://x.example/a) text"


def test_shape_with_links_key_is_v16a_even_for_markdown():  # V16: the key decides, not the look of the content
    doc = {"content": LINKED, "links": [pair("Apply now", "https://x.example/a")]}
    assert shape(U, doc) == "[Apply now <https://x.example/a>](https://x.example/a) text"  # no Markdown rewriting


def test_shape_with_an_empty_links_list_is_still_v16a():  # V16a: the fetcher always sets the list, an empty one too
    assert shape(U, {"content": LINKED, "links": []}) == LINKED


def test_shape_without_links_is_v16b():  # V16
    assert shape(U, {"content": LINKED}) == "Apply now <https://x.example/a> text"


def test_shape_filters_the_requested_url():  # V16a: a link to the page itself gets no address
    assert shape(U, {"content": "Apply now please", "links": [pair("Apply now", U)]}) == "Apply now please"


def test_shape_text_at_skips_the_title_line():  # V16a, A7
    content = "Title: Apply now\n\nApply now later"
    doc = {"content": content, "links": [pair("Apply now")], "text_at": content.index("Apply now later")}
    assert shape(U, doc) == f"Title: Apply now\n\nApply now <{H}> later"


@pytest.mark.parametrize("at", [-1, 99, True, "5", 2.0, None])
def test_shape_invalid_text_at_counts_as_zero(at):  # V16a: out of range, bool and non-int are 0
    doc = {"content": "Apply now X", "links": [pair("Apply now")], "text_at": at}
    assert shape(U, doc) == f"Apply now <{H}> X"


def test_shape_text_at_at_the_end_is_valid_and_empty():  # V16a: text_at == len(content) is an empty page
    content = "Title: Apply now\n\n"
    doc = {"content": content, "links": [pair("Apply now")], "text_at": len(content)}
    assert shape(U, doc) == content


def test_shape_missing_content_is_empty():
    assert shape(U, {}) == "" and shape(U, {"content": None, "links": []}) == ""


@pytest.mark.parametrize(("name", "doc"), [("insert_links", {"links": []}), ("markdown", {})])
def test_shape_never_raises(monkeypatch, name, doc):  # V16, S6: on an unexpected failure the text stays as it is
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(shape_module, name, boom)
    assert shape(U, {"content": LINKED, **doc}) == LINKED


def test_shape_never_raises_on_odd_links():  # V16, S6
    assert shape(U, {"content": "Apply now", "links": 5}) == "Apply now"
    assert shape(U, {"content": "Apply now", "links": [None, 3, ["a"]]}) == "Apply now"


# --- V16b markdown: images ---------------------------------------------------------------------------------


def test_markdown_image_is_removed_and_spaces_stay():  # V16b
    assert markdown("Before ![alt](a.png) after") == "Before  after"
    assert markdown("![alt](https://i.example/a.png)") == ""
    assert markdown("a\n\n![alt](a.png)\n\nb") == "a\n\n\n\nb"  # blank lines around stay


@pytest.mark.parametrize("title", ['"Title"', "'Title'"])
def test_markdown_image_with_title_is_removed(title):  # V16b
    assert markdown(f"x ![alt](a.png {title}) y") == "x  y"


def test_markdown_image_without_alt_is_removed():  # V16b
    assert markdown("x ![](a.png) y") == "x  y"


# --- V16b markdown: links --------------------------------------------------------------------------------


def test_markdown_link_becomes_text_and_address():  # V16b
    assert markdown("see [Apply now](https://x.example/a) now") == "see Apply now <https://x.example/a> now"
    assert markdown("[Apply now](http://x.example/a)") == "Apply now <http://x.example/a>"


@pytest.mark.parametrize("title", ['"Title"', "'Title'"])
def test_markdown_link_with_title(title):  # V16b
    assert markdown(f"[Apply now](https://x.example/a {title})") == "Apply now <https://x.example/a>"


def test_markdown_self_link_and_repeated_url_are_handled():  # V16b: no filter on either, unlike V16a
    text = "[Apply now](https://x.example/a) [Apply now](https://x.example/a)"
    assert markdown(text) == "Apply now <https://x.example/a> Apply now <https://x.example/a>"


def test_markdown_escaped_brackets_are_unescaped():  # V16b: `\[1\]` becomes `[1]`, 3 characters: no address
    assert markdown(r"x [\[1\]](https://x.example/n) y") == "x [1] y"


def test_markdown_backslash_before_a_letter_stays():  # V16b: only before ASCII punctuation
    assert markdown(r"[C:\dir](https://x.example/p)") == r"C:\dir <https://x.example/p>"


def test_markdown_length_is_measured_after_unescaping():  # V16b
    assert markdown(r"[\[12\]](https://x.example/n)") == "[12] <https://x.example/n>"


@pytest.mark.parametrize(("text", "out"), [("abc", "abc"), ("abcd", "abcd <https://x.example/n>")])
def test_markdown_short_link_text_gets_no_address(text, out):  # V16b: 3 characters no, 4 yes
    assert markdown(f"[{text}](https://x.example/n)") == out


def test_markdown_link_text_whitespace_is_collapsed():  # V16b
    assert markdown("[Apply\n   now\t](https://x.example/a)") == "Apply now <https://x.example/a>"
    assert markdown("[a \n b](https://x.example/a)") == "a b"  # 3 characters after the collapse


def test_markdown_empty_link_text_leaves_nothing():  # V16b
    assert markdown("x[](https://x.example/a)y") == "xy"
    assert markdown("x[ \n ](https://x.example/a)y") == "xy"


def test_markdown_image_inside_link_text_is_gone_first():  # V16b
    assert markdown("[![logo](l.png)](https://x.example/)") == ""
    assert markdown("[Home ![logo](l.png) page](https://x.example/)") == "Home page <https://x.example/>"


def test_markdown_url_with_one_level_of_parentheses():  # V16b: Wikipedia
    out = markdown("[Wiki page](https://en.example/wiki/Foo_(bar)) x")
    assert out == "Wiki page <https://en.example/wiki/Foo_(bar)> x"
    url = "https://en.example/wiki/Foo_(bar)_(baz)"
    assert markdown(f"[Wiki page]({url})") == f"Wiki page <{url}>"


def test_markdown_two_levels_of_parentheses_stay():  # V16b: only one level
    text = "[Wiki page](https://en.example/w/Foo_(a_(b)))"
    assert markdown(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "[mail me](mailto:a@x.example)",
        "[local page](/docs/x)",
        "[ftp site](ftp://x.example/)",
        "[Apply now](https://x.example/<a)",
        "[Apply now](https://x.example/a>)",
        "[Apply now](https://x.example/a b)",
        "[Apply now](<https://x.example/a>)",
        "[Apply now][1]\n\n[1]: https://x.example/a",
        "[Apply now][]",
        "<https://x.example/a>",
        '<a href="https://x.example/a">Apply now</a>',
        "[Apply now] (https://x.example/a)",
        "[Apply now](https://x.example/a",
    ],
)
def test_markdown_unchanged(text):  # V16b: non-http links, bad URLs, reference style, autolinks, HTML
    assert markdown(text) == text


def test_markdown_nested_brackets_stay():  # V16b
    text = "[outer [inner] text](https://x.example/a)"
    assert markdown(text) == text


def test_markdown_nested_link_inner_is_a_link_of_its_own():  # V16b: no unescaped "[" in a link text; inner link only
    assert markdown("[outer [inner link](https://x.example/a)]") == "[outer inner link <https://x.example/a>]"


# --- V16b markdown: fenced blocks ---------------------------------------------------------------------------

IN = "[Apply now](https://x.example/a) ![i](p.png)"
OUT = "Apply now <https://x.example/a> "


def test_markdown_fenced_block_is_untouched():  # V16b
    text = f"```\n{IN}\n```"
    assert markdown(text) == text


@pytest.mark.parametrize("fence", ["  ```", "\t```", " \t ```python", "```js"])
def test_markdown_fence_may_be_indented_and_have_an_info_string(fence):  # V16b: after spaces or tabs
    text = f"{fence}\n{IN}\n```"
    assert markdown(text) == text


def test_markdown_unclosed_fence_runs_to_the_end():  # V16b
    text = f"before [Apply now](https://x.example/b)\n```\n{IN}\n\nmore {IN}"
    assert markdown(text) == f"before Apply now <https://x.example/b>\n```\n{IN}\n\nmore {IN}"


def test_markdown_text_outside_the_fence_is_rewritten():  # V16b
    text = f"{IN}\n```\n{IN}\n```\n{IN}"
    assert markdown(text) == f"{OUT}\n```\n{IN}\n```\n{OUT}"


def test_markdown_two_blocks():  # V16b
    text = f"```\n{IN}\n```\n{IN}\n```\n{IN}\n```\nend"
    assert markdown(text) == f"```\n{IN}\n```\n{OUT}\n```\n{IN}\n```\nend"


def test_markdown_any_line_of_three_backticks_closes():  # V16b: the closing line needs no matching info string
    text = f"```python\n{IN}\n```not a language\n{IN}"
    assert markdown(text) == f"```python\n{IN}\n```not a language\n{OUT}"


def test_markdown_tilde_fences_and_code_spans_are_not_protected():  # V16b
    assert markdown(f"~~~\n{IN}\n~~~") == f"~~~\n{OUT}\n~~~"
    assert markdown("`[Apply now](https://x.example/a)`") == "`Apply now <https://x.example/a>`"


def test_markdown_backticks_in_the_middle_of_a_line_open_no_block():  # V16b: the line must start with them
    text = f"text ``` {IN}\n{IN}"
    assert markdown(text) == f"text ``` {OUT}\n{OUT}"


def test_markdown_keeps_line_structure():  # V16b: lines, trailing newline, empty text
    assert markdown("") == "" and markdown("\n") == "\n" and markdown("a\n\nb\n") == "a\n\nb\n"
    assert markdown("```\n") == "```\n"
    assert markdown("```\ncode\n```\n") == "```\ncode\n```\n"


def test_markdown_link_text_may_span_lines_but_not_a_fence():  # V16b
    assert markdown("[Apply\nnow](https://x.example/a)") == "Apply now <https://x.example/a>"
    text = "[Apply\n```\nnow](https://x.example/a)\n```"
    assert markdown(text) == text


# --- V16b bounds ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("length", "converted"), [(500, True), (501, False)])
def test_markdown_link_text_bound_500(length, converted):  # V16b, D42
    text = f"[{'a' * length}](https://x.example/a)"
    assert (markdown(text) != text) is converted
    if converted:
        assert markdown(text) == f"{'a' * length} <https://x.example/a>"


@pytest.mark.parametrize(("length", "converted"), [(2000, True), (2001, False)])
def test_markdown_link_url_bound_2000(length, converted):  # V16b, D42: at most 2,000 characters after "https://"
    url = "https://" + "x.example/" + "a" * (length - len("x.example/"))
    assert len(url) == length + len("https://")
    text = f"[Apply now]({url})"
    assert (markdown(text) != text) is converted


@pytest.mark.parametrize(("length", "removed"), [(20000, True), (20001, False)])
def test_markdown_image_source_bound_20000(length, removed):  # V16b, D42
    text = f"x ![alt]({'a' * length}) y"
    assert (markdown(text) == "x  y") is removed
    if not removed:
        assert markdown(text) == text


@pytest.mark.parametrize(("length", "removed"), [(500, True), (501, False)])
def test_markdown_image_alt_bound_500(length, removed):  # V16b, D42
    text = f"x ![{'a' * length}](p.png) y"
    assert (markdown(text) == "x  y") is removed


@pytest.mark.parametrize("quote", ['"', "'"])
@pytest.mark.parametrize(("length", "converted"), [(300, True), (301, False)])
def test_markdown_title_bound_300(quote, length, converted):  # V16b, D42
    title = quote + "t" * length + quote
    link = f"[Apply now](https://x.example/a {title})"
    assert (markdown(link) == "Apply now <https://x.example/a>") is converted
    assert (markdown(f"![alt](p.png {title})") == "") is converted
    if not converted:
        assert markdown(link) == link


# --- performance guard (D42): timing tests with a generous limit; a failure means the work is no longer linear ---


def test_performance_guard_markdown_3mb_with_unclosed_brackets():  # D42, timing: under 2 s
    text = "![x [ab ![ [word " * 180_000 + "a [real link](https://x.example/a) and ![img](p.png)"
    assert len(text) > 3_000_000
    start = time.perf_counter()
    out = markdown(text)
    assert time.perf_counter() - start < 2
    assert out.endswith("a real link <https://x.example/a> and ")


def test_performance_guard_markdown_unclosed_bracket_runs():  # D42, timing: under 2 s
    text = "[" * 300_000 + "![" * 150_000 + "[some words in a long unclosed link text " * 10_000  # about 1 MB
    start = time.perf_counter()
    assert markdown(text) == text
    assert time.perf_counter() - start < 2


def test_performance_guard_jina_10000_links_in_200000_characters():  # D42, timing: under 2 s
    text = " ".join(f"word{i:05d}" for i in range(20_000))[:200_000]
    links = [[f"word{i:05d} word{i + 1:05d}", f"https://h.example/f{i}"] for i in range(0, 1_200, 3)]  # 400 found
    links += [[f"missing link text {i}", f"https://h.example/m{i}"] for i in range(9_600)]  # never found
    assert len(links) == 10_000 and len(text) <= 200_000
    start = time.perf_counter()
    out = shape(U, {"content": text, "links": links})
    assert time.perf_counter() - start < 2
    assert out.count(" <https://h.example/f") == 400 and " <https://h.example/m" not in out


def test_performance_guard_jina_500_links_that_are_not_found():  # D42, timing: under 2 s (worst case: full scans)
    text = ("lorem ipsum dolor sit amet " * 8_000)[:200_000]
    links = [[f"zz{i} yy{i} xx{i} ww{i} vv{i}", f"https://h.example/{i}"] for i in range(600)]
    start = time.perf_counter()
    assert shape(U, {"content": text, "links": links}) == text
    assert time.perf_counter() - start < 2


# --- Gaps found by the mutation run of the final review ---------------------------------------------------


def test_insert_link_text_with_regex_metacharacters():  # V16a: the link text is searched literally
    assert insert_links("Jobs C++ (m/w/d) ok", [("C++ (m/w/d)", H)]) == f"Jobs C++ (m/w/d) <{H}> ok"
    assert insert_links("x a.b*c? y", [("a.b*c?", H)]) == f"x a.b*c? <{H}> y"
    assert insert_links("x aXbbc y", [("a.b*c?", H)]) == "x aXbbc y"  # "." and "*" are no wildcards


def test_markdown_upper_case_scheme_stays():  # V16b: http:// or https:// in lower case only
    text = "[Foo bar](HTTPS://x.example/)"
    assert markdown(text) == text


def test_markdown_fence_after_no_break_space_is_no_fence():  # V16b: only spaces or tabs before the backticks
    text = " ```\n[Apply now](https://x.example/a)"
    assert markdown(text) == " ```\nApply now <https://x.example/a>"


@pytest.mark.parametrize(("spaces", "converted"), [(20, True), (21, False)])
def test_markdown_title_whitespace_bounds(spaces, converted):  # V16b, D42: whitespace around the title
    before = f'[Apply now](https://x.example/a{" " * spaces}"t")'
    after = f'[Apply now](https://x.example/a "t"{" " * spaces})'
    for text in (before, after):
        assert (markdown(text) == "Apply now <https://x.example/a>") is converted


@pytest.mark.parametrize(("length", "converted"), [(200, True), (201, False)])
def test_markdown_parenthesis_group_bound_200(length, converted):  # V16b, D42: a group of up to 200 characters
    url = f"https://x.example/w_({'a' * length})"
    assert (markdown(f"[Apply now]({url})") == f"Apply now <{url}>") is converted


def test_insert_links_stops_after_the_time_limit():  # V16a, D42: links after PLACE_SECONDS get no address
    ticks = iter([0.0, 0.0, shape_module.PLACE_SECONDS + 0.1])
    out = insert_links("Apply one. Apply two.", [("Apply one", H1), ("Apply two", H2)], clock=lambda: next(ticks))
    assert out == f"Apply one <{H1}>. Apply two."


def test_performance_guard_repeated_words_near_misses():  # D42, timing: 3 MB of one word, 500 near-miss links
    text = "aaaa " * 600_000
    links = [(f"aaaa aaaa aaaa aaaa aaaa zz{i}", f"https://h.example/{i}") for i in range(500)]
    t0 = time.perf_counter()
    insert_links(text, links)
    assert time.perf_counter() - t0 < 3.0  # stops after PLACE_SECONDS (1 s) plus the link in hand
