#!/usr/bin/env python3
"""Generate the next unused Numaco SOW number.

Thin CLI shim. The numbering rules live in ONE place, the shared module at
`shared/numbering/document_number.py`, because SOWs, timesheets and
Arbeitsrapporte all draw from the same `YYDDDN` series. Read that module's
docstring before changing anything about numbering.

Usage:
    python3 generate_sow_number.py --data-dir "/path/to/Sales - Documents"
    python3 generate_sow_number.py --data-dir "..." --count 2   # SOW + timesheet
    python3 generate_sow_number.py --date 2026-04-23
"""
import sys
from pathlib import Path

ND = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ND / "shared" / "numbering"))

from document_number import (  # noqa: E402  (path set above)
    DEFAULT_DATA_DIR,
    compute_prefix,
    find_used_digits,
    main,
    next_number,
    next_numbers,
)

if __name__ == "__main__":
    main()
