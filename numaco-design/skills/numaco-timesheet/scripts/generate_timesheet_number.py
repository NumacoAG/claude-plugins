#!/usr/bin/env python3
"""Generate the next unused Numaco timesheet / Arbeitsrapport number.

A timesheet takes its OWN number from the shared `YYDDDN` series. It is never
the accompanying SOW's number with a suffix bolted on, and never that number
reused. Historic tenant precedent: `Timesheet 253507`, `Timesheet 260039`,
`Arbeitsrapport 252319`, all bare six-digit numbers of their own.

Thin CLI shim over `shared/numbering/document_number.py`, which is the single
home of the numbering rules.

When one sitting produces a SOW and its timesheet, allocate both in ONE call.
The collision scan reads filenames on disk, so two separate calls made before
either file is written hand back the same number twice:

    python3 generate_timesheet_number.py --data-dir "..." --count 2
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
