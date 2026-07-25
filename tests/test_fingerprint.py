"""Tests for fingerprint() / SIGNATURES -- family classification.

Every body below is invented for this test; none of it is real dashboard
HTML copied from ysfprobe_cache/ (that directory holds third-party bodies
whose redistribution is prohibited, and real amateur callsigns besides).
Where a fixture needs to mirror something the real sample showed -- e.g.
the plain-xlxd dashboard's stock `<meta name="keywords">` tag mentioning
"XReflector" -- the wording below is reinvented to have the same *shape*
(the incidental keyword sitting in an unrelated meta tag) without
reproducing any real host's actual tag content. Hostnames use the RFC 2606
reserved .test/.invalid suffixes so nothing here resolves.
"""

from ysfprobe import SIGNATURES, fingerprint

# ---------------------------------------------------------------------------
# xlxd: identified by title shape alone, regardless of which visual
# template a sysop has installed. The real sample showed at least three
# different script/stylesheet bundles under this one title convention, so
# the fixtures below deliberately vary unrelated body content (different
# invented script tags, presence/absence of a stray "XReflector" mention)
# while keeping only the title shape constant.
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
# resolve to "xlxd" (via the title), never "ycs" -- the regression this
# issue fixes.
XLXD_WITH_INCIDENTAL_XREFLECTOR_KEYWORD = """
<!DOCTYPE html>
<html><head>
<meta name="keywords" content="Amateur Radio, XReflector, Digital Voice, YSF, DMR" />
<title>XLX501 Reflector Dashboard</title>
</head><body>Connected modules</body></html>
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
    # marker is anchored to the <title> tag on purpose.
    body = (
        "<html><head><title>N0CALL Hotspot Status</title></head>"
        "<body><table><tr><td>Linked: XLX010</td></tr></table></body></html>"
    )
    assert fingerprint(body)[0] is None


# ---------------------------------------------------------------------------
# ycs: identified by a literal, case-varying "YCS" token that is genuinely
# the software's own name -- never by the "XReflector" keyword above, which
# only ever belonged to xlxd's template.
# ---------------------------------------------------------------------------

YCS_UPPERCASE_IN_TITLE = "<html><head><title>YCS Dashboard</title></head><body></body></html>"

# The real sample showed the token rendered lower-case in a URL on one
# genuine YCS install and upper-case in on-page button text on another --
# the original pattern was case-sensitive and missed the lower-case form.
YCS_LOWERCASE_IN_URL = """
<html><head><title>Example Reflector</title></head>
<body><a href="http://ycs777.example.test/status">status</a></body></html>
"""


def test_uppercase_ycs_token_in_title_classifies_as_ycs():
    assert fingerprint(YCS_UPPERCASE_IN_TITLE)[0] == "ycs"


def test_lowercase_ycs_token_in_a_url_classifies_as_ycs():
    assert fingerprint(YCS_LOWERCASE_IN_URL)[0] == "ycs"


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
# The four newly-covered families -- each was reachable in the first live
# sample but came back unidentified because SIGNATURES had nothing for it.
# ---------------------------------------------------------------------------

HUB_MONITOR_BODY = "<html><head><title>HUB Monitor</title></head><body></body></html>"
FUSION_DASHBOARD_BODY = "<html><head><title>Fusion Dashboard</title></head><body></body></html>"
CUMBRIACQ_BACKUP_BODY = (
    "<html><head><title>CumbriaCQ Backup Server</title></head><body></body></html>"
)
MARRAS_BODY = (
    "<html><head><title>MARRAS C4FM Multi Streams Reflector</title></head><body></body></html>"
)


def test_hub_monitor_title_classifies_as_hub_monitor():
    assert fingerprint(HUB_MONITOR_BODY)[0] == "hub-monitor"


def test_fusion_dashboard_title_classifies_as_fusion_dashboard():
    assert fingerprint(FUSION_DASHBOARD_BODY)[0] == "fusion-dashboard"


def test_cumbriacq_backup_server_title_classifies_as_cumbriacq_backup():
    assert fingerprint(CUMBRIACQ_BACKUP_BODY)[0] == "cumbriacq-backup"


def test_marras_title_classifies_as_marras():
    assert fingerprint(MARRAS_BODY)[0] == "marras"


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
# Ordering: SIGNATURES is first-match-wins, so a signature that used to be
# (or could again be) shadowed by a broader pattern must sit above it. A
# later `SIGNATURES.append(...)` must not be able to silently undo this.
# ---------------------------------------------------------------------------


def _index_of(family: str) -> int:
    return next(i for i, sig in enumerate(SIGNATURES) if sig.family == family)


def test_narrow_title_signatures_sit_above_ycs_and_xlxd():
    # hub-monitor, fusion-dashboard, cumbriacq-backup and marras must all be
    # checked before ycs and xlxd -- fusion-dashboard in particular used to
    # be shadowed by ycs's old (now-removed) `xreflector` pattern, and
    # nothing should be able to silently reintroduce that by appending a
    # broader pattern to ycs/xlxd instead of inserting above these.
    ycs_index = _index_of("ycs")
    xlxd_index = _index_of("xlxd")
    for family in ("hub-monitor", "fusion-dashboard", "cumbriacq-backup", "marras"):
        assert _index_of(family) < ycs_index
        assert _index_of(family) < xlxd_index


def test_ysfdash2_shaymez_fork_still_sits_above_its_generic_ancestor():
    # Pre-existing fork relationship, guarded here so a later append can't
    # silently shadow it either: "YSFReflector-Dashboard2" bodies also
    # satisfy ysfdash-dg9vh's plain "YSFReflector-Dashboard" pattern, so the
    # fork must be checked first.
    assert _index_of("ysfdash2-shaymez") < _index_of("ysfdash-dg9vh")
