"""Tests for ANON_RE -- what counts as a genuinely redacted callsign, not
merely "the page contains ordinary HTML".

Every body below is invented for this test; none of it is real dashboard
HTML copied from ysfprobe_cache/ (that directory holds third-party bodies
whose redistribution is prohibited). The ordinary-markup snippets mirror
the *shape* of what the first live sample of 43 real dashboards showed as
false-positive sources -- Bootstrap's "hidden" utility class/attribute, a
"/**" CSS/JSDoc comment opener, and the crossorigin="anonymous" attribute
common on CDN-hosted <script>/<link> tags -- without reproducing any
actual dashboard's markup. Likewise the genuine-redaction fixtures below
use invented callsign prefixes (AB1, KX9, ...) rather than any of the real
partially-masked callsigns observed in the cache.
"""

import pytest

from ysfprobe import ANON_RE

# Ordinary markup that appears on nearly every Bootstrap-based dashboard
# and has nothing to do with redacting a callsign. Each of these used to
# trip the old ANON_RE.
ORDINARY_MARKUP = [
    '<input type="hidden" name="csrf_token" value="deadbeef" />',
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
    # A decorative banner-style comment: opener AND closer both carry more
    # than one asterisk. The bare-run branch's lookaround excludes a match
    # immediately adjacent to '/' or '*' on either side, not just the
    # two-star "/**" opener.
    "/*** big banner title ***/",
    # The closer on its own, detached from any opener in this snippet --
    # still must not match.
    "css minified here ******/ more rules follow",
]


@pytest.mark.parametrize("body", ORDINARY_MARKUP)
def test_ordinary_markup_never_matches(body):
    assert ANON_RE.search(body) is None


def test_markdown_style_bold_asterisks_do_not_match():
    # Two bare asterisks around a word (Markdown/JS-string emphasis, not a
    # callsign) must not trip the flag -- the same reasoning that excludes
    # "/**": two stars alone is not enough evidence of redaction.
    assert ANON_RE.search("This net is **very** active tonight.") is None


@pytest.mark.parametrize("body", ["x2**3", "n0**2"])
def test_exponentiation_with_a_callsign_shaped_variable_name_does_not_match(body):
    # "**" is also the JS/Python exponentiation operator. A variable name
    # that happens to be callsign-shaped (letter(s) + digit) immediately
    # followed by "**digit" must not be mistaken for a partially-starred
    # callsign. Not observed in the 43-host sample, but a live risk over
    # the full ~1,700-host registry.
    assert ANON_RE.search(body) is None


# Genuine redaction renderings. The first two shapes were confirmed
# against the real 43-host sample; the entity-zero shape ("&Oslash;" is
# the ham convention for a slashed zero, undecoded because probe() reads
# raw r.text) is real too -- it accounts for half the redacted cells on
# one of the two hosts that actually redact -- but the fixture below uses
# an invented prefix rather than any of the observed callsigns.
GENUINE_REDACTIONS = [
    "<td nowrap>AB1***</td>",           # partially starred callsign
    "<td nowrap>KX9***</td>",           # partially starred callsign, table context
    "<td nowrap>KX&Oslash;Z***</td>",   # entity-encoded zero, no ASCII digit in the prefix
    "<td nowrap>******</td>",           # fully starred entry, callsign fully masked
    "Last heard: ANON",                 # explicit anonymised placeholder
    "Caller: XXXXX1",                   # X-masked placeholder with trailing digit
]


@pytest.mark.parametrize("body", GENUINE_REDACTIONS)
def test_genuine_redaction_renderings_match(body):
    assert ANON_RE.search(body) is not None


def test_two_bare_asterisks_alone_do_not_match():
    # Fewer than 3 bare asterisks, with no callsign-shaped prefix, is
    # indistinguishable from decorative punctuation -- must not match.
    assert ANON_RE.search("Status: OK **") is None


def test_three_bare_asterisks_match_even_without_a_callsign_shaped_prefix():
    # Deliberately broad: the bare-run branch does NOT require anything
    # callsign-shaped in front of it, specifically so entity-encoded
    # prefixes like "KX&Oslash;Z" above (which have no ASCII digit for the
    # prefix branch to anchor on) are still caught. The cost is that any
    # unrelated 3+ run of asterisks -- not just a redacted callsign -- also
    # matches; that tradeoff was chosen deliberately after finding it
    # missed 18 of 126 genuinely redacted cells in the real sample when the
    # threshold was 4 instead of 3.
    assert ANON_RE.search("loading***") is not None
