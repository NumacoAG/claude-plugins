#!/usr/bin/env python3
"""Generate the next unused Numaco SOW number.

Format: YYDDDN
  YY  = two-digit year
  DDD = day of year (001-366)
  N   = collision-avoidance digit (0-9), smallest unused

Scans a data directory recursively for filenames that contain any 6-digit
sequence starting with the computed YYDDD prefix, then picks the smallest unused
trailing digit. The data directory is configurable and never assumed to exist:
if it is missing or empty the scan returns no collisions and N starts at 0.

Resolution order for the data dir: --data-dir flag, then the NUMACO_DATA_DIR
environment variable, then empty (no collision scan).

Usage:
    python3 generate_sow_number.py
    python3 generate_sow_number.py --data-dir "/path/to/1. Data"
    python3 generate_sow_number.py --date 2026-04-23
    NUMACO_DATA_DIR="/path/to/1. Data" python3 generate_sow_number.py
"""
import argparse
import os
import re
from datetime import date, datetime

# Configurable, never assumed to exist. Prefer the env var; else no scan.
DEFAULT_DATA_DIR = os.environ.get("NUMACO_DATA_DIR", "")


def compute_prefix(d: date) -> str:
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


def next_number(data_dir: str = DEFAULT_DATA_DIR, when: date = None) -> str:
    when = when or date.today()
    prefix = compute_prefix(when)
    used = find_used_digits(prefix, data_dir)
    for d in range(10):
        if d not in used:
            return f"{prefix}{d}"
    # All ten taken; pad with a second digit.
    for d in range(10, 100):
        candidate = f"{prefix}{d}"
        if not find_used_digits(candidate, data_dir):
            return candidate
    raise RuntimeError(f"Could not allocate an SOW number for prefix {prefix}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    p.add_argument("--date", help="ISO date, e.g. 2026-04-23")
    args = p.parse_args()
    when = date.today()
    if args.date:
        when = datetime.strptime(args.date, "%Y-%m-%d").date()
    print(next_number(args.data_dir, when))


if __name__ == "__main__":
    main()
