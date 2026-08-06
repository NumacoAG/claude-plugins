#!/usr/bin/env python3
"""Canonical Numaco document numbering.

ONE series for every commercial document Numaco issues. Format `YYDDDN`:

    YY   two-digit year
    DDD  day of year (001-366)
    N    collision-avoidance digit, smallest unused for that day

Examples from the live tenant: `IN262090` is 28 July 2026, `Arbeitsrapport
243662` is 31 December 2024 (2024 was a leap year, so day 366 exists),
`Timesheet 253507` is 16 December 2025.

Two rules that are easy to get wrong:

1. **Quotation, order confirmation, delivery note and invoice for the SAME
   transaction share ONE number**, distinguished only by the letter prefix:
   `QU261938`, `OC261938`, `DN261938`, `IN261938`. The number identifies the
   transaction, not the sheet of paper.

2. **Every OTHER document takes its own number from the same series.** A
   Statement of Work, a timesheet, an Arbeitsrapport: each is allocated
   separately. NEVER derive one document's number by suffixing another's
   (`262180-07` is not a Numaco number), and never reuse a SOW number for the
   timesheet that accompanies it.

The collision scan reads filenames on disk, so allocating two numbers in two
separate calls before writing either file hands back the same number twice.
Use `next_numbers(count=N)` when a single sitting produces several documents.

Resolution order for the data dir: explicit argument, then the NUMACO_DATA_DIR
environment variable, then empty (no collision scan, N starts at 0).

Usage:
    python3 document_number.py --data-dir "/path/to/Sales - Documents"
    python3 document_number.py --data-dir "..." --count 2
    python3 document_number.py --date 2026-04-23
"""
import argparse
import os
import re
from datetime import date, datetime

# Configurable, never assumed to exist. Prefer the env var; else no scan.
DEFAULT_DATA_DIR = os.environ.get("NUMACO_DATA_DIR", "")


def compute_prefix(d: date) -> str:
    """The `YYDDD` stem shared by every document issued on day `d`."""
    yy = d.strftime("%y")
    ddd = f"{d.timetuple().tm_yday:03d}"
    return f"{yy}{ddd}"


def find_used_digits(prefix: str, data_dir: str) -> set:
    """Walk data_dir and find all filenames containing '<prefix><digit>' as a token."""
    used = set()
    if not data_dir or not os.path.isdir(data_dir):
        return used
    pat = re.compile(rf"(?<!\d){re.escape(prefix)}(\d)(?!\d)")
    for root, _dirs, files in os.walk(data_dir):
        for name in files:
            for m in pat.finditer(name):
                used.add(int(m.group(1)))
    return used


def next_numbers(data_dir: str = DEFAULT_DATA_DIR, when: date = None, count: int = 1) -> list:
    """Allocate `count` distinct numbers for `when`, in ascending order.

    The disk is scanned once, so numbers handed out in the same call never
    collide with each other. This is the call to use when one sitting produces
    a SOW and its timesheet: the files do not exist yet, so N separate calls
    would all return the same number.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    when = when or date.today()
    prefix = compute_prefix(when)
    used = find_used_digits(prefix, data_dir)
    out = []
    for d in range(10):
        if d not in used:
            out.append(f"{prefix}{d}")
            if len(out) == count:
                return out
    # All ten single digits taken; continue with a second digit.
    for d in range(10, 100):
        candidate = f"{prefix}{d}"
        if not find_used_digits(candidate, data_dir):
            out.append(candidate)
            if len(out) == count:
                return out
    raise RuntimeError(f"Could not allocate {count} document numbers for prefix {prefix}")


def next_number(data_dir: str = DEFAULT_DATA_DIR, when: date = None) -> str:
    """The single next unused number. Thin wrapper over `next_numbers`."""
    return next_numbers(data_dir, when, 1)[0]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    p.add_argument("--date", help="ISO date, e.g. 2026-04-23")
    p.add_argument("--count", type=int, default=1,
                   help="allocate N distinct numbers in one scan (SOW + timesheet = 2)")
    args = p.parse_args()
    when = date.today()
    if args.date:
        when = datetime.strptime(args.date, "%Y-%m-%d").date()
    for n in next_numbers(args.data_dir, when, args.count):
        print(n)


if __name__ == "__main__":
    main()
