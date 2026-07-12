#!/usr/bin/env python3
"""Build a sample Numaco timesheet to prove the numaco-timesheet pipeline end to end.

The payload in sample_payload.json is entirely fictional (client Acme Labs AG,
project and entries invented) and hours-only: no day rate, so no amounts appear.
"""
import json
import sys
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SAMPLE_DIR.parent / "scripts"))
import build_timesheet  # noqa: E402


def main():
    payload = json.loads((SAMPLE_DIR / "sample_payload.json").read_text(encoding="utf-8"))
    pdf_path = str(SAMPLE_DIR / "sample_timesheet.pdf")
    html_path, pdf_path = build_timesheet.render(payload, pdf_path)
    print("HTML:", html_path)
    print("PDF: ", pdf_path)
    n = build_timesheet.R.pdf_page_count(pdf_path)
    pages = ",".join(str(p) for p in range(1, n + 1)) if n <= 4 else f"1,2,3,{n}"
    build_timesheet.R.pdfcheck(pdf_path, "sample_timesheet", pages=pages)
    print("PAGE_COUNT:", n)


if __name__ == "__main__":
    main()
