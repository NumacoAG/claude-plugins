#!/usr/bin/env python3
"""Build a sample Numaco SOW to prove the numaco-sow HTML pipeline end to end."""
import sys
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SAMPLE_DIR.parent / "scripts"))
import build_sow  # noqa: E402

PAYLOAD = {
    "sow_number": "261912",
    "issue_date": "July 2026",
    "project_title": "ZPL to PDF label archival service",
    "client_legal_name": "Acme Labs AG",
    "client_address": ["Industriestrasse 12", "CH-8600 Duebendorf", "Switzerland"],
    "client_contacts": [
        {"name": "Petra Meier", "email": "petra.meier@acmelabs.ch", "role": "Head of IT"},
        {"name": "Jonas Frei", "email": "jonas.frei@acmelabs.ch", "role": "QA Lead"},
    ],
    "context": (
        "Acme Labs AG prints GxP relevant labels from a legacy label management "
        "stack and must retain a faithful visual record of every printed label "
        "for audit. Today the archive stores only raw ZPL, which auditors cannot "
        "read without a printer.\n\n"
        "This SOW covers a service that captures each print stream and renders a "
        "pixel faithful PDF alongside it, so the archive becomes human readable "
        "and audit ready without changing the printing workflow."
    ),
    "deliverables": [
        {"summary": "Native PDF label writer",
         "body": "Numaco delivers a service that captures the ZPL print stream and renders a faithful PDF of each label inline, with correct label geometry rather than an A4 page."},
        {"summary": "Archive integration",
         "body": "The rendered PDFs are written to the existing archive store next to the source ZPL, keyed by the same job identifier."},
        {"summary": "Operator runbook",
         "body": "A short runbook covers deployment, health checks, and how to reprocess a batch."},
    ],
    "exclusions": [
        {"summary": "Printer firmware changes",
         "body": "No changes are made to printer firmware or driver configuration."},
        {"summary": "Historical backfill",
         "body": "Re-rendering the existing historical ZPL archive is out of scope for the base engagement."},
    ],
    "assumptions": [
        {"summary": "Access to a representative label set",
         "body": "Acme provides a representative set of production ZPL samples covering all active label templates."},
        {"summary": "Stable print protocol",
         "body": "The current print protocol and port remain unchanged for the duration of the engagement."},
    ],
    "workstreams": [
        {"name": "Scope, analysis, and sample capture", "days": 3},
        {"name": "PDF rendering engine and label geometry", "days": 6},
        {"name": "Archive integration and job keying", "days": 3.5},
        {"name": "Testing, runbook, and handover", "days": 2.5},
    ],
    "day_rate_chf": 1000,
    "payment_days": 60,
    "optional_addons": [
        {"number": 1, "title": "Historical archive backfill",
         "days": 4,
         "body": "Auditors increasingly ask for readable records of labels printed before go live. This add-on re-renders the existing ZPL archive into PDF in controlled batches, so the whole historical record becomes audit ready in one pass rather than staying a blind spot."},
    ],
    "output_path": str(SAMPLE_DIR / "sample_sow.pdf"),
}


def main():
    html_path, pdf_path = build_sow.render(PAYLOAD, PAYLOAD["output_path"])
    print("HTML:", html_path)
    print("PDF: ", pdf_path)
    import os
    os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")
    n = build_sow.R.pdf_page_count(pdf_path)
    last = str(n)
    build_sow.R.pdfcheck(pdf_path, "sample_sow", pages=f"1,2,3,{last}")
    print("PAGE_COUNT:", n)


if __name__ == "__main__":
    main()
