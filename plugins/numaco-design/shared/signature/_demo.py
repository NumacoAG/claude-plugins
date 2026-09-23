#!/usr/bin/env python3
"""Data-driven smoke test for signature.py.

Builds a document from entirely made-up content (Weeklab GmbH cold-chain rollout,
not the Acme sample the design was tuned on): a two-section proposal with
a parties block, a small effort table plus optional add-on, a callout, a terms list,
a note, a signature block and an appendix. Renders it via numaco_render and runs the
CoreGraphics fidelity check, proving the builders drive any data.
"""
import os
from pathlib import Path

os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")

import signature as S  # noqa: E402

HERE = Path(__file__).resolve().parent
RATE = 100

cov = S.cover(
    "Service Proposal",
    "PRP-401",
    "Cold Chain Monitoring Rollout",
    "A wireless temperature-logging network for the Weeklab cold rooms, with one "
    "dashboard and automated deviation alerts across all four sites.",
    [
        ("Prepared for", "Weeklab GmbH", "DE-79539 Loerrach"),
        ("Prepared by", "Numaco AG", "CH-8905 Islisberg"),
        ("Issued", "August 2026", "Valid 45 days"),
        ("Reference", "PRP-401", "Rev B"),
    ],
    "Numaco AG &middot; CH-8905 Islisberg",
)

parties = S.block_eyebrow("Contracting parties") + S.parties(
    {
        "role": "Client",
        "name": "Weeklab GmbH",
        "address": ["Am Marktplatz 4", "DE-79539 Loerrach", "Germany"],
        "contacts": [
            {"name": "Dr. Lena Brandt", "role": "Lab Director", "email": "lena.brandt@weeklab.de"},
            {"name": "Tomas Iten", "role": "Facilities", "email": "tomas.iten@weeklab.de"},
        ],
    },
    {
        "role": "Supplier",
        "name": "Numaco AG",
        "address": ["Haldenstrasse 3c", "CH-8905 Islisberg", "Switzerland"],
        "contacts_label": "Contacts &middot; VAT CHE-107.980.861 MWST",
        "contacts": [
            {"name": "Aria Fenn", "role": "Project lead", "email": ""},
            {"name": "Numaco AG", "role": "", "email": "numaco.ch"},
        ],
    },
)

sec1 = S.section(
    "01",
    "Objective",
    "Scope &middot; outcome",
    S.lead(
        "Weeklab operates four cold rooms with manual chart logging. This proposal "
        "replaces the paper charts with a wireless sensor network that logs every "
        "reading and alerts on deviation, without interrupting normal cold-room use."
    )
    + S.para(
        "Each room reports to a small site gateway; the gateways feed one shared "
        "dashboard so a deviation in Loerrach is seen the same way as one in Basel."
    )
    + S.subhead("Deliverables")
    + S.items(
        S.scope_item("D1", "Sensor mesh install", "Battery temperature sensors in every cold room, reporting to a local site gateway."),
        S.scope_item("D2", "Dashboard and alerts", "One dashboard for all four sites, with SMS and email deviation alerts."),
        S.scope_item("D3", "Validation pack", "IQ and OQ documents plus a calibration certificate per sensor.", tag="Optional"),
    )
    + S.subhead("Exclusions")
    + S.items(
        S.scope_item("N1", "Cold-room hardware", "No changes are made to the cold-room compressors or door interlocks.", excl=True),
    )
    + S.subhead("What we solve")
    + S.spec_list(
        [
            "<b>Blind spots.</b> Manual charts are read twice a day; a night excursion can pass unseen until morning.",
            "<b>Audit effort.</b> Paper charts must be transcribed for review, which is slow and error prone.",
        ]
    ),
    first=True,
)

effort = S.effort_table(
    [("Ref", False, "10mm"), ("Workstream", False, None), ("Days", True, None), ("Amount CHF", True, None)],
    [
        [("W1", "ref"), ("Site survey and sensor plan", "ws"), ("2.0", "num"), (S.num(2 * RATE), "num")],
        [("W2", "ref"), ("Install and gateway setup", "ws"), ("4.0", "num"), (S.num(4 * RATE), "num")],
        [("W3", "ref"), ("Dashboard, alerts and handover", "ws"), ("3.0", "num"), (S.num(3 * RATE), "num")],
    ],
    total_row=[("", ""), ("Base engagement total", "ws"), ("9.0", "num"), (S.num(9 * RATE), "num amt")],
    addon_rows=[
        [("O1", "ref"), ('Validation pack <span class="otag">Optional</span>', "ws"), ("3.0", "num"), (S.num(3 * RATE), "num")]
    ],
)

sec2 = S.section(
    "02",
    "Commercials",
    "Rates &middot; terms &middot; example order",
    S.para("The estimate below covers the base rollout for all four sites at a fixed day rate.")
    + effort
    + S.callout(
        "Billing basis",
        "Billing is for time actually worked. The optional validation pack is "
        "<em>excluded</em> from the base total and is activated by a separate order.",
    )
    + S.subhead("Commercial terms")
    + S.term_list(
        [
            ("Day rate", '<span class="big">' + S.chf(RATE) + "</span> per engineer day, excl. VAT"),
            ("Payment terms", 'Net <span class="big">30 days</span> from invoice date'),
            ("Validity", "This proposal is valid for 45 days from issue"),
        ]
    )
    + S.subhead("Illustrative order")
    + S.line_items_table(
        [
            ("Gateway appliance, per site", 4, 900),
            ("Temperature sensor, per unit", 24, 145),
            ("Dashboard licence, annual", 1, 3600),
        ],
        subtotal=4 * 900 + 24 * 145 + 3600,
        vat=(4 * 900 + 24 * 145 + 3600) * 0.081,
        total=(4 * 900 + 24 * 145 + 3600) * 1.081,
    )
    + S.note(
        "Planning note",
        "Sensor counts are indicative and confirmed after the site survey; final quantities "
        "may move at the margin.",
    )
    + S.signature_block([("For the client", "Weeklab GmbH"), ("For the supplier", "Numaco AG")]),
)

apx = S.appendix(
    "Appendix: Standard terms",
    [
        ("&sect;1", "Scope of service", "Numaco installs and configures the monitoring system, produces the documentation, and trains the client's staff on its use."),
        ("&sect;5", "Payment", "Charges follow the rates quoted in this proposal and exclude travel and subsistence unless pre-agreed."),
        ("&sect;11", "Governing law", "This proposal is governed by the laws of Switzerland, and any dispute is brought before a competent Swiss court."),
    ],
)

body = cov + S.main_body(parties, sec1, sec2, apx)

pdf = HERE / "_demo.pdf"
eng, n = S.render_pdf("Numaco Signature demo", body, str(pdf), "Service Proposal", "PRP-401")
print(f"rendered {pdf} via {eng}, {n} pages")
S.R.pdfcheck(str(pdf), "signature_demo", pages=f"1,2,{n}")
