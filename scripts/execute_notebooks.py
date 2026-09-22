#!/usr/bin/env python3
"""Execute every notebook in the myst.yml table of contents.

The published book renders whatever outputs happen to be committed, so a
notebook can rot for years -- an API gets removed upstream and the stored
output still looks fine -- without anything failing. This script actually runs
them, and is wired into CI so that rot is caught at PR time instead of by a
student on day one.

Usage:  python scripts/execute_notebooks.py [--timeout SECONDS] [paths...]
"""
import argparse
import pathlib
import re
import sys
import time
import warnings

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parent.parent


def known_failures():
    """Map of notebook path -> reason, from scripts/known_failures.txt."""
    path = ROOT / "scripts" / "known_failures.txt"
    if not path.exists():
        return {}
    skips = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        nb, _, reason = line.partition("#")
        skips[nb.strip()] = reason.strip()
    return skips


def toc_notebooks():
    text = (ROOT / "myst.yml").read_text()
    return [ROOT / p for p in re.findall(r"file:\s*(\S+\.ipynb)", text)]


def run(path, timeout):
    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(
        nb,
        timeout=timeout,
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
    )
    start = time.monotonic()
    try:
        client.execute()
        return True, "", time.monotonic() - start
    except CellExecutionError as exc:
        # last line of the traceback is the actual exception
        last = [ln for ln in str(exc).strip().splitlines() if ln.strip()][-1]
        return False, last.strip(), time.monotonic() - start
    except Exception as exc:  # timeout, dead kernel, unreadable notebook
        return False, f"{type(exc).__name__}: {exc}", time.monotonic() - start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="notebooks to run (default: all in myst.yml)")
    ap.add_argument("--timeout", type=int, default=600, help="per-cell timeout in seconds")
    args = ap.parse_args()

    explicit = bool(args.paths)
    notebooks = [pathlib.Path(p).resolve() for p in args.paths] or toc_notebooks()
    skips = {} if explicit else known_failures()
    failures, skipped = [], []

    for path in notebooks:
        rel = path.relative_to(ROOT)
        if str(rel) in skips:
            print(f"SKIP  {rel}", flush=True)
            skipped.append((rel, skips[str(rel)]))
            continue
        ok, err, secs = run(path, args.timeout)
        print(f"{'PASS' if ok else 'FAIL'}  {rel}  ({secs:.0f}s)", flush=True)
        if not ok:
            print(f"        {err}", flush=True)
            failures.append((rel, err))

    ran = len(notebooks) - len(skipped)
    print(f"\n{ran - len(failures)}/{ran} notebooks executed cleanly"
          + (f" ({len(skipped)} skipped)" if skipped else ""))
    if skipped:
        print("\nSkipped (see scripts/known_failures.txt):")
        for rel, reason in skipped:
            print(f"  {rel}\n      {reason}")
    if failures:
        print("\nFailures:")
        for rel, err in failures:
            print(f"  {rel}\n      {err}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
