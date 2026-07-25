"""Tests for fingerprint() / SIGNATURES -- family classification.

Every body below is invented for this test; none of it is real dashboard
HTML copied from ysfprobe_cache/ (that directory holds third-party bodies
whose redistribution is prohibited). Fixtures that mirror something the
real sample showed -- the plain-xlxd dashboard's stock meta tags, the YCS
credit-block shape, the shared-navbar hub page CQ-UK/CQ-WORLD render -- are
reinvented to have the same *structural shape* using invented wording,
without reproducing any real host's actual markup. Hostnames use the RFC
2606 reserved .test suffix so nothing here resolves.
"""

from ysfprobe import SIGNATURES, fingerprint

# ---------------------------------------------------------------------------
# xlxd: identified by title shape, regardless of which visual template a
# sysop has installed -- the real sample showed at least three different
# script/stylesheet bundles under this one title convention -- and,
# separately, by xlxd's stock <meta name="description"> tag for the one
# host that has replaced its title with the sysop's own callsign.
# ---------------------------------------------------------------------------

XLXD_NUMBERED_DESIGNATOR = """
<!DOCTYPE html>
<html><head><title>XLX999 Reflector Dashboard</title>
<script src="./js/jquery-1.12.4.min.js"></script>
<link rel="stylesheet" href="./css/layout.css" />
</head><body>Modules: A B C</body></html>
"""

XLXD_LETTER_DESIGNATOR_NO_SUFFIX = """
<!DOCTYPE html>
<html><head><title>XLXTEST</title>
<script src="https://cdn.example.test/jquery-3.7.1.min.js"></script>
</head><body>Modules table here</body></html>
"""

# Same title shape, a completely different template (invented bootstrap-ish
# bundle) -- must still land in the same family as the two above.
XLXD_DIFFERENT_TEMPLATE = """
<!DOCTYPE html>
<html><head><title>XLXQRZ Reflector Dashboard</title>
<script src="https://cdn.example.test/bootstrap.min.js"></script>
<link rel="stylesheet" href="css/dashboard.css" />
</head><body>Modules list</body></html>
"""

# Carries the stock xlxd "keywords" meta tag mentioning "XReflector" -- the
# exact incidental match that used to misclassify this host as "ycs". Must
# resolve to "xlxd" (via the title), never "ycs" -- the regression the first
# review cycle of this issue fixed.
XLXD_WITH_INCIDENTAL_XREFLECTOR_KEYWORD = """
<!DOCTYPE html>
<html><head>
<meta name="keywords" content="Amateur Radio, XReflector, Digital Voice, YSF, DMR" />
<title>XLX501 Reflector Dashboard</title>
</head><body>Connected modules</body></html>
"""

# A host running the same xlxd software but with its title replaced by the
# sysop's own callsign -- the title anchor above cannot see this one, so it
# has to be caught by xlxd's stock description tag instead.
XLXD_RETITLED_WITH_CALLSIGN_TITLE = """
<!DOCTYPE html>
<html><head>
<meta name="description" content="XLX is a D-Star Reflector System for Ham Radio Operators.">
<title>N0CALL</title>
</head><body>Modules table here</body></html>
"""


def test_numbered_designator_classifies_as_xlxd():
    assert fingerprint(XLXD_NUMBERED_DESIGNATOR)[0] == "xlxd"


def test_letter_designator_without_reflector_dashboard_suffix_still_classifies_as_xlxd():
    # The real sample had a host whose title was the bare designator with no
    # "Reflector Dashboard" suffix at all -- the marker can't depend on that
    # suffix being present.
    assert fingerprint(XLXD_LETTER_DESIGNATOR_NO_SUFFIX)[0] == "xlxd"


def test_different_visual_template_with_same_title_shape_still_classifies_as_xlxd():
    assert fingerprint(XLXD_DIFFERENT_TEMPLATE)[0] == "xlxd"


def test_incidental_xreflector_keyword_no_longer_misclassifies_as_ycs():
    family, _ = fingerprint(XLXD_WITH_INCIDENTAL_XREFLECTOR_KEYWORD)
    assert family == "xlxd"
    assert family != "ycs"


def test_xlx_mentioned_outside_the_title_does_not_trigger_xlxd():
    # A dashboard that merely lists XLX-numbered reflectors it bridges to
    # (e.g. a linked-reflectors table) must not be mistaken for one -- the
    # title pattern is anchored to the <title> tag on purpose.
    body = (
        "<html><head><title>N0CALL Hotspot Status</title></head>"
        "<body><table><tr><td>Linked: XLX010</td></tr></table></body></html>"
    )
    assert fingerprint(body)[0] is None


def test_retitled_host_still_classifies_as_xlxd_via_the_stock_description_tag():
    assert fingerprint(XLXD_RETITLED_WITH_CALLSIGN_TITLE)[0] == "xlxd"


# ---------------------------------------------------------------------------
# ycs: identified by what a dashboard says about ITSELF -- a title
# beginning "YCS", or the software crediting itself by name in a bare
# credit-list line -- never by a YCS token that only appears because the
# page links out to a sibling install (that was the second, subtler version
# of the original xreflector mistake: classifying by what a page links to
# rather than what it is).
# ---------------------------------------------------------------------------

YCS_GENUINE_TITLE = "<html><head><title>YCS Dashboard</title></head><body></body></html>"

# The real sample's one genuine YCS install credits the software by name
# ahead of its authors' calls, each on its own line, as plain text rather
# than inside any URL or button label.
YCS_GENUINE_CREDIT_BLOCK = """
<html><head><title>Example Reflector</title></head>
<body>
&nbsp;&nbsp;YCS<br/>
&nbsp;&nbsp;N0CALL<br/>
</body></html>
"""

# The real CQ-UK/CQ-WORLD shape: a hub page with a row of outbound navbar
# buttons to sibling systems, one of which happens to point at a YCS
# install (button text glued to a version number, href pointing at a
# ycsNNN.<domain> sibling host) sitting beside unrelated buttons for other
# bridged protocols. Nothing here asserts that THIS page is YCS software.
YCS_HUB_PAGE_LINKING_TO_SIBLING_YCS_INSTALL = """
<html><head><title>Example Hub</title></head>
<body>
<div id="navbarToggleExternalContent">
  <a href="./blocked.php">Callsigns blocked in time</a>
</div>
<span class="navbar-text">
  <a href="http://ycs444.example.test/ycs"><button>YCS444</button></a>
</span>
<span class="navbar-text">
  <a href="http://ycs444.example.test/dcs"><button>DCS010</button></a>
</span>
<span class="navbar-text">
  <a href="http://m17.example.test"><button>M17</button></a>
</span>
</body></html>
"""


def test_genuine_ycs_title_classifies_as_ycs():
    assert fingerprint(YCS_GENUINE_TITLE)[0] == "ycs"


def test_genuine_ycs_credit_block_classifies_as_ycs_even_with_a_different_title():
    assert fingerprint(YCS_GENUINE_CREDIT_BLOCK)[0] == "ycs"


def test_ycs_token_glued_to_a_version_number_does_not_alone_classify_as_ycs():
    # "YCS444", not bare "YCS" -- must not satisfy either ycs pattern on its
    # own (no title match, and the credit-block pattern requires YCS not be
    # immediately followed by a word character).
    body = "<html><head><title>Example</title></head><body>YCS444<br/></body></html>"
    assert fingerprint(body)[0] != "ycs"


def test_navbar_link_to_a_sibling_ycs_install_does_not_classify_as_ycs():
    # The regression this review cycle exists to fix: a page whose only YCS
    # token is an outbound navbar button linking to a sibling ycsNNN host
    # must not be treated as a YCS dashboard just because the word appears
    # -- that is the xreflector mistake in a different shape.
    assert fingerprint(YCS_HUB_PAGE_LINKING_TO_SIBLING_YCS_INSTALL)[0] != "ycs"


def test_navbar_link_hub_page_with_the_shared_keywords_marker_classifies_as_pysfreflector3():
    # The real CQ-UK/CQ-WORLD pages are this exact hub-page shape plus the
    # dashboard software's own keywords marker -- that combination is what
    # correctly resolves them to pysfreflector3 (see MARRAS/CQ-UK/CQ-WORLD
    # below), not ycs.
    body = YCS_HUB_PAGE_LINKING_TO_SIBLING_YCS_INSTALL.replace(
        "<title>Example Hub</title>",
        '<meta name="keywords" content="c4fm, reflector, ysf protocol, yaesu, example" />'
        "<title>Example Hub</title>",
    )
    assert fingerprint(body)[0] == "pysfreflector3"


def test_incidental_xreflector_keyword_alone_no_longer_classifies_as_ycs():
    # A body with the stock xlxd keywords tag but no XLX-shaped title and no
    # genuine YCS token: must come back unidentified, not "ycs". This is the
    # direct regression test for the removed `xreflector` pattern.
    body = (
        '<html><head><meta name="keywords" '
        'content="Amateur Radio, XReflector, Digital Voice" />'
        "<title>Some Reflector</title></head><body></body></html>"
    )
    assert fingerprint(body)[0] is None


# ---------------------------------------------------------------------------
# pysfreflector3: extended, not replaced. MARRAS and CQ-UK/CQ-WORLD (the
# latter two evicted from "ycs" above) are this same dashboard software --
# confirmed structurally against the real bodies (identical
# navbarToggleExternalContent nav, identical blocked.php menu entry,
# identical author meta shape) and by a shared keywords-tag prefix, present
# verbatim on all four real hosts with only the trailing site-specific word
# differing.
# ---------------------------------------------------------------------------

PYSF3_ORIGINAL_MARKER_BODY = (
    "<html><head><title>pYSF3 Multi Streams Reflector</title></head><body></body></html>"
)

# A different title entirely (mirrors MARRAS/CQ-WORLD, each named after
# their own reflector rather than the software) -- must still resolve to
# pysfreflector3 via the shared keywords marker alone.
SHARED_KEYWORDS_ONLY_BODY = (
    '<html><head><meta name="keywords" '
    'content="c4fm, reflector, ysf protocol, yaesu, example net" />'
    "<title>EXAMPLENET Multi Streams Reflector</title></head><body></body></html>"
)


def test_original_pysf_marker_still_classifies_as_pysfreflector3():
    assert fingerprint(PYSF3_ORIGINAL_MARKER_BODY)[0] == "pysfreflector3"


def test_shared_keywords_marker_alone_classifies_as_pysfreflector3():
    assert fingerprint(SHARED_KEYWORDS_ONLY_BODY)[0] == "pysfreflector3"


# ---------------------------------------------------------------------------
# fusion-dashboard: unaffected by this cycle's ycs changes, still needs to
# win over ycs given the same stock xlxd keywords tag beside it.
# ---------------------------------------------------------------------------

FUSION_DASHBOARD_BODY = "<html><head><title>Fusion Dashboard</title></head><body></body></html>"


def test_fusion_dashboard_title_classifies_as_fusion_dashboard():
    assert fingerprint(FUSION_DASHBOARD_BODY)[0] == "fusion-dashboard"


def test_fusion_dashboard_with_incidental_xreflector_keyword_still_classifies_as_fusion_dashboard():
    # In the first live sample, two "Fusion Dashboard"-titled hosts were
    # misclassified as "ycs" through the same incidental meta tag as the
    # xlxd hosts, while two template-identical siblings were left
    # unidentified. fusion-dashboard must win regardless of that tag being
    # present.
    body = (
        '<html><head><meta name="keywords" '
        'content="Amateur Radio, XReflector, Digital Voice" />'
        "<title>Fusion Dashboard</title></head><body></body></html>"
    )
    assert fingerprint(body)[0] == "fusion-dashboard"


# ---------------------------------------------------------------------------
# Deliberately unsigned: "HUB Monitor" and "CumbriaCQ Backup Server" are
# genuinely not YSF dashboards (a Joomla/AllStar page and a bare four-link
# landing page, respectively) -- see the block comment above SIGNATURES for
# the politeness-contract and gate-accuracy reasoning. This pins that
# decision so it isn't quietly "fixed" by adding signatures back.
# ---------------------------------------------------------------------------


def test_hub_monitor_and_cumbriacq_backup_titles_stay_deliberately_unidentified():
    hub_monitor = "<html><head><title>HUB Monitor</title></head><body></body></html>"
    cumbriacq_backup = (
        "<html><head><title>CumbriaCQ Backup Server</title></head><body></body></html>"
    )
    assert fingerprint(hub_monitor)[0] is None
    assert fingerprint(cumbriacq_backup)[0] is None


# ---------------------------------------------------------------------------
# Ordering: SIGNATURES is first-match-wins, so a signature that used to be
# (or could again be) shadowed by a broader pattern must sit above it. A
# later `SIGNATURES.append(...)` must not be able to silently undo this.
# ---------------------------------------------------------------------------


def _index_of(family: str) -> int:
    return next(i for i, sig in enumerate(SIGNATURES) if sig.family == family)


def test_narrow_families_sit_above_ycs_and_xlxd():
    # fusion-dashboard and pysfreflector3 must both be checked before ycs
    # and xlxd -- fusion-dashboard was previously shadowed by ycs's old
    # (now-removed) `xreflector` pattern, and pysfreflector3 now carries the
    # CQ-UK/CQ-WORLD hosts evicted from ycs in this cycle. Nothing should be
    # able to silently reintroduce either shadowing by appending a broader
    # pattern to ycs/xlxd instead of inserting above these.
    ycs_index = _index_of("ycs")
    xlxd_index = _index_of("xlxd")
    for family in ("fusion-dashboard", "pysfreflector3"):
        assert _index_of(family) < ycs_index
        assert _index_of(family) < xlxd_index


def test_ysfdash2_shaymez_fork_still_sits_above_its_generic_ancestor():
    # Pre-existing fork relationship, guarded here so a later append can't
    # silently shadow it either: "YSFReflector-Dashboard2" bodies also
    # satisfy ysfdash-dg9vh's plain "YSFReflector-Dashboard" pattern, so the
    # fork must be checked first.
    assert _index_of("ysfdash2-shaymez") < _index_of("ysfdash-dg9vh")


def test_xlxd_sits_above_ysfdash_dg9vh():
    # xlxd matches on a title *prefix* ("XLX..."), while dg9vh-style titles
    # are "<sysop name> - YSFReflector-Dashboard". Not observed colliding in
    # the sample, but the full registry has 223 records starting with "XLX"
    # -- a future dg9vh-titled host whose sysop name happens to start that
    # way would need xlxd's narrower-looking-but-unrelated pattern checked
    # in a predictable position. Pinned here rather than reordered: no
    # observed collision to fix, just an ordering worth not losing by
    # accident.
    assert _index_of("xlxd") < _index_of("ysfdash-dg9vh")
