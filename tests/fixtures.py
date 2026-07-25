"""Synthetic registry-export fixtures for ysfprobe tests.

Every record below is invented -- no slice of a real RefCheck.Radio export.
IPs are drawn from the RFC 5737 documentation ranges (192.0.2.0/24,
198.51.100.0/24, 203.0.113.0/24) and hostnames use the RFC 2606 reserved
``.test``/``.invalid`` suffixes, so nothing here resolves or is reachable
even by accident.
"""

# Semicolon-delimited export: ID;Name;Description;Address;Port;UserCount;
# The real file is 7 fields with a trailing separator -- despite the
# publisher's landing page calling this "tab-delimited", there is not a
# single tab in the real export, so this fixture has none either.
SYNTHETIC_TEXT_EXPORT = (
    "90001;Synthetic Net One;Weekly practice net;relay-one.example.test;42001;4;\n"
    "90002;Synthetic Net Two;A quiet room;198.51.100.7;42002;0;\n"
    "\n"
    "# a comment line, silently skipped\n"
    "this-line-has-no-semicolons-at-all\n"
)

# One truly malformed record above (too few fields to be a real one) --
# used to exercise the unparsed-line collector.
SYNTHETIC_TEXT_UNPARSED_LINE = "this-line-has-no-semicolons-at-all"

# JSON export: {"_refcheck_metadata": {...}, "reflectors": [...]}
SYNTHETIC_JSON_EXPORT = """
{
    "_refcheck_metadata": {"generated": "synthetic-fixture"},
    "reflectors": [
        {
            "designator": "90101",
            "name": "Synthetic Dashboard Reflector",
            "description": "Has a declared dashboard url",
            "dns": "dash.example.test",
            "ipv4": "203.0.113.11",
            "port": 42101,
            "url": "https://dash.example.test/status"
        },
        {
            "designator": "90102",
            "name": "Synthetic Hostname-Only Reflector",
            "description": "Hostname known, no declared url",
            "dns": "reflector.example.test",
            "ipv4": "203.0.113.12",
            "port": 42102,
            "url": ""
        },
        {
            "designator": "90103",
            "name": "Synthetic IP-Only Reflector",
            "description": "Bare IP only -- unmeasurable",
            "dns": "",
            "ipv4": "203.0.113.13",
            "port": 42103,
            "url": null
        },
        "not-a-record-object",
        {
            "designator": "",
            "name": "Missing designator and host",
            "dns": "",
            "ipv4": "",
            "port": 42104
        }
    ]
}
"""
