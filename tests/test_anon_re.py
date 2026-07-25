"""Tests for ANON_RE -- what counts as a genuinely redacted callsign, not
merely "the page contains ordinary HTML".

Every body below is invented for this test; none of it is real dashboard
HTML copied from ysfprobe_cache/ (that directory holds third-party bodies
whose redistribution is prohibited). The ordinary-markup snippets mirror
the *shape* of what the first live sample of 43 real dashboards showed as
false-positive sources -- Bootstrap's "hidden" utility class/attribute, a
"/**" CSS/JSDoc comment opener, and the crossorigin="anonymous" attribute
common on CDN-hosted <script>/<link> tags -- without reproducing any
actual dashboard's markup.
"""

import pytest

from ysfprobe import ANON_RE

# Ordinary markup that appears on nearly every Bootstrap-based dashboard
# and has nothing to do with redacting a callsign. Each of these used to
# trip the old ANON_RE.
ORDINARY_MARKUP = [
    '<input type="hidden" name="do" value="SetFilter" />',
    'class="hidden"',
    'class="d-none hidden"',
    (
        "/**\n"
        " * Popover component definition, adapted from a UI framework.\n"
        " * @see https://example.test/docs\n"
        " */\n"
        ".popover { position: absolute; }"
    ),
    # Not called out in the issue, but the same class of bug: a bare
    # "anonymous" inside a CDN Subresource Integrity attribute, common on
    # every <script>/<link> tag pulling Bootstrap from a CDN.
    '<link rel="stylesheet" href="bootstrap.min.css" '
    'integrity="sha384-abc123" crossorigin="anonymous">',
]


@pytest.mark.parametrize("body", ORDINARY_MARKUP)
def test_ordinary_markup_never_matches(body):
    assert ANON_RE.search(body) is None


def test_markdown_style_bold_asterisks_do_not_match():
    # Two bare asterisks around a word (Markdown/JS-string emphasis, not a
    # callsign) must not trip the flag -- the same reasoning that excludes
    # "/**": two stars alone is not enough evidence of redaction.
    assert ANON_RE.search("This net is **very** active tonight.") is None


# Genuine redaction renderings, confirmed against the real 43-host sample:
# a callsign-shaped prefix followed by asterisks, a fully starred entry
# with nothing callsign-shaped in front of it, and an explicit placeholder.
GENUINE_REDACTIONS = [
    "<td nowrap>AB1***</td>",   # partially starred callsign
    "<td nowrap>W7C***</td>",   # partially starred callsign (real shape)
    "<td nowrap>******</td>",   # fully starred entry, callsign fully masked
    "Last heard: ANON",         # explicit anonymised placeholder
    "Caller: XXXXX1",           # X-masked placeholder with trailing digit
]


@pytest.mark.parametrize("body", GENUINE_REDACTIONS)
def test_genuine_redaction_renderings_match(body):
    assert ANON_RE.search(body) is not None


def test_two_bare_asterisks_alone_do_not_match():
    # Fewer than 4 bare asterisks, with no callsign-shaped prefix, is
    # indistinguishable from decorative punctuation -- must not match.
    assert ANON_RE.search("Status: OK **") is None


def test_short_star_run_is_not_enough_without_a_callsign_shaped_prefix():
    # 3 asterisks alone isn't a redacted callsign either -- the minimum
    # bare-run length exists specifically so a "/**"-style comment opener
    # (2 stars) can never qualify, without hand-carving comment syntax.
    assert ANON_RE.search("loading***") is None
