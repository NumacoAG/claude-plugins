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
    "project_title": "Chromatogram report archival service",
    "client_legal_name": "Acme Labs AG",
    "client_address": ["Industriestrasse 12", "CH-8600 Duebendorf", "Switzerland"],
    "client_contacts": [
        {"name": "Petra Meier", "email": "petra.meier@acmelabs.ch", "role": "Head of IT"},
        {"name": "Jonas Frei", "email": "jonas.frei@acmelabs.ch", "role": "QA Lead"},
    ],
    "context": (
        "Acme Labs AG runs a legacy chromatography data system and must retain a "
        "faithful visual record of every result report for audit. Today the "
        "archive stores only raw CDS export files, which auditors cannot read "
        "without the original software.\n\n"
        "This SOW covers a service that captures each export and renders a "
        "faithful PDF alongside it, so the archive becomes human readable "
        "and audit ready without changing the laboratory workflow."
    ),
    "deliverables": [
        {"summary": "Native PDF report writer",
         "body": "Numaco delivers a service that captures the CDS export stream and renders a faithful PDF of each report inline, preserving the original report layout."},
        {"summary": "Archive integration",
         "body": "The rendered PDFs are written to the existing archive store next to the source export, keyed by the same job identifier."},
        {"summary": "Operator runbook",
         "body": "A short runbook covers deployment, health checks, and how to reprocess a batch."},
    ],
    "exclusions": [
        {"summary": "CDS configuration changes",
         "body": "No changes are made to the chromatography data system configuration or its export formats."},
        {"summary": "Historical backfill",
         "body": "Re-rendering the existing historical export archive is out of scope for the base engagement."},
    ],
    "assumptions": [
        {"summary": "Access to a representative report set",
         "body": "Acme provides a representative set of production export files covering all active report templates."},
        {"summary": "Stable export format",
         "body": "The current export format and delivery path remain unchanged for the duration of the engagement."},
    ],
    "workstreams": [
        {"name": "Scope, analysis, and sample capture", "days": 3},
        {"name": "PDF rendering engine and report layout", "days": 6},
        {"name": "Archive integration and job keying", "days": 3.5},
        {"name": "Testing, runbook, and handover", "days": 2.5},
    ],
    "day_rate_chf": 100,
    "payment_days": 60,
    "optional_addons": [
        {"number": 1, "title": "Historical archive backfill",
         "days": 4,
         "body": "Auditors increasingly ask for readable records of reports produced before go live. This add-on re-renders the existing export archive into PDF in controlled batches, so the whole historical record becomes audit ready in one pass rather than staying a blind spot."},
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
